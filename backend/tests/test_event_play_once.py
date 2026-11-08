"""Event « joue une fois » — le serveur le DIT au player et ne sert plus un event échu.

Constat d'Ed (2026-08-11) sur la prod et le VPS : un event configuré pour jouer une
vidéo une fois toutes les 30 min « recommence à la fin pour s'arrêter quelques
secondes après avoir redémarré ».

Chaîne mesurée, deux défauts distincts :

  ① Le payload ne portait AUCUNE notion de « joue une fois ». Le moteur, lui, la
     connaît (`event_worker` : `duration_ms` renseigné = play-once, `duration_ms`
     vide = boucle jusqu'à la fin de la fenêtre) — mais le player rebouclait
     toujours en fin de liste, donc il relançait la vidéo.

  ② La requête d'événement actif filtrait sur `status == 'active'` SANS regarder
     `expires_at`. Or c'est le beat `expire_events` (30 s) qui bascule un event
     échu : pendant 30 s au plus, la base le dit encore actif. Une synchro
     demandée juste après la fin se voyait donc RESERVIR le même event — ce qui
     rendait le correctif côté player inopérant à lui seul.

Ces deux tests figent l'un et l'autre. Le second est le plus important : sans lui,
le player demanderait une synchro fraîche et recevrait… le même event.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import CmsEvent
from app.models.media import CmsMedia
from app.models.organization import CmsOrganization, CmsOrgAuthSettings
from app.models.player import CmsPlayer

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="PlayOnceOrg", org_slug=f"po-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


async def _fixture(
    db: AsyncSession,
    org: CmsOrganization,
    *,
    duration_ms,
    expires_in_s,
    lan_sync: bool = False,
    activated_s_ago: int = 1,
):
    """Un player + un média + un event actif le ciblant. Renvoie (player, event)."""
    player = CmsPlayer(
        id_org=org.id_org,
        player_name=f"PlayOnce {uuid.uuid4().hex[:6]}",
        player_os="linux-x64",
        status="online",
        display_config={"lan_sync_enabled": True} if lan_sync else None,
    )
    media = CmsMedia(
        id_org=org.id_org,
        media_name="clip.mp4",
        media_type="video",
        mime_type="video/mp4",
        storage_key=f"m/{uuid.uuid4().hex}.mp4",
        file_size_bytes=1024,
        checksum_sha256=uuid.uuid4().hex * 2,
        duration_ms=369058,
        transcode_status="done",
    )
    db.add_all([player, media])
    await db.commit()
    await db.refresh(player)
    await db.refresh(media)

    now = datetime.now(UTC)
    event = CmsEvent(
        id_org=org.id_org,
        event_name="Spot",
        event_type="scheduled",
        event_kind="content",
        status="active",
        priority=70,
        id_media=media.id_media,
        duration_ms=duration_ms,
        is_recurring=True,
        is_preemptive=True,
        revert_on_end=True,
        activated_at=now - timedelta(seconds=activated_s_ago),
        expires_at=now + timedelta(seconds=expires_in_s),
        target_config={"target_type": "player", "target_ids": [player.id_player]},
        trigger_config={},
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return player, event


async def test_payload_dit_au_player_que_l_event_joue_une_fois(
    db_session: AsyncSession, org: CmsOrganization
) -> None:
    """`duration_ms` renseigné ⇒ `play_once: True` dans le payload.

    Sans ce drapeau le player reboucle : il avance sur un minuteur réglé sur
    `item.duration_ms` et relance donc la vidéo à la seconde même où l'event expire.
    """
    from app.api.v1.endpoints.ws import _build_sync_payload

    player, event = await _fixture(db_session, org, duration_ms=369000, expires_in_s=300)

    payload = await _build_sync_payload(db_session, player.id_player)
    assert payload["id_event"] == event.id_event
    assert payload["play_once"] is True, "le payload doit dire que l'event joue une fois"


async def test_un_event_qui_boucle_ne_porte_pas_le_drapeau(
    db_session: AsyncSession, org: CmsOrganization
) -> None:
    """`duration_ms` vide = mode BOUCLE (jusqu'à la fin de la fenêtre) : pas de play_once.

    Témoin indispensable : un drapeau posé inconditionnellement passerait le test
    précédent tout en cassant les events qui doivent, eux, tourner en boucle.
    """
    from app.api.v1.endpoints.ws import _build_sync_payload

    player, _ = await _fixture(db_session, org, duration_ms=None, expires_in_s=300)

    payload = await _build_sync_payload(db_session, player.id_player)
    assert payload["play_once"] is False


async def test_un_event_echu_n_est_plus_servi_meme_s_il_est_encore_actif_en_base(
    db_session: AsyncSession, org: CmsOrganization
) -> None:
    """`expires_at` dépassé ⇒ l'event n'est plus servi, sans attendre le beat 30 s.

    C'est la moitié serveur du correctif : le player qui demande une synchro fraîche
    à la fin d'un event play-once doit recevoir la programmation normale. Sans cette
    garde il recevrait le MÊME event (le beat ne l'a pas encore basculé) et
    relancerait la vidéo — le défaut resterait entier.
    """
    from app.api.v1.endpoints.ws import _build_sync_payload

    player, event = await _fixture(db_session, org, duration_ms=369000, expires_in_s=-5)
    assert event.status == "active", "la base le dit encore actif — c'est tout le sujet"

    payload = await _build_sync_payload(db_session, player.id_player)
    assert payload.get("id_event") is None, "un event échu ne doit plus être servi"
    assert payload["items"] == []


# ── Rejoindre un event « joue une fois » EN COURS DE DIFFUSION ────────────────────
#
# Question d'Ed (2026-08-11) : « un player hors groupe sync LAN démarre du début du
# contenu quelle que soit l'heure de démarrage pendant la fenêtre de l'event et est
# coupé à l'heure fixée au départ. Techniquement est-il possible de le faire commencer
# à l'endroit où il devrait être ? »
#
# Le calcul du décalage existait, mais il était réservé aux groupes de synchro LAN. Or
# un event play-once se termine à un instant FIXE décidé par le serveur : un écran qui
# repart du début ne verra qu'un fragment. La raison d'être du décalage n'est donc plus
# « aligner des écrans entre eux » mais « se placer sur une horloge que le serveur va
# arrêter » — ça vaut pour tout écran.
#
# ⚠️ Ces quatre tests forment un tout : sans le troisième (boucle hors LAN), on ne
# saurait pas si le décalage a été étendu à bon escient ou posé partout.

_TOLERANCE_MS = 5000  # le test lui-même consomme quelques ms


async def test_hors_groupe_lan_un_play_once_demarre_a_la_bonne_position(
    db_session: AsyncSession, org: CmsOrganization
) -> None:
    """Écran SANS synchro LAN qui rejoint 120 s après l'activation ⇒ décalage ≈ 120 s.

    C'est le cas d'Ed : redémarrage, coupure réseau ou écran rallumé en cours de
    diffusion. Avant, le décalage valait 0 et l'écran repartait du début pour se faire
    couper à l'échéance — il ne voyait qu'un fragment, d'autant plus court qu'il
    arrivait tard.
    """
    from app.api.v1.endpoints.ws import _build_sync_payload

    player, _ = await _fixture(
        db_session, org, duration_ms=369000, expires_in_s=240,
        lan_sync=False, activated_s_ago=120,
    )

    payload = await _build_sync_payload(db_session, player.id_player)
    off = payload["start_offset_ms"]
    assert off is not None
    assert abs(off - 120_000) < _TOLERANCE_MS, f"décalage attendu ~120 s, obtenu {off} ms"


async def test_hors_groupe_lan_un_event_en_BOUCLE_demarre_toujours_au_debut(
    db_session: AsyncSession, org: CmsOrganization
) -> None:
    """⛔ LA FRONTIÈRE, et elle est délibérée : en boucle, hors LAN, on ne décale PAS.

    Un event en boucle tourne jusqu'à la fermeture de sa fenêtre : il n'existe aucune
    « position où l'on devrait être », et démarrer à zéro laisse voir le contenu ENTIER.
    Étendre le décalage à ce cas changerait le comportement de tout le parc sans rien
    faire gagner à personne.

    Sans ce test, un décalage posé inconditionnellement passerait le test précédent.
    """
    from app.api.v1.endpoints.ws import _build_sync_payload

    player, _ = await _fixture(
        db_session, org, duration_ms=None, expires_in_s=240,
        lan_sync=False, activated_s_ago=120,
    )

    payload = await _build_sync_payload(db_session, player.id_player)
    assert payload["start_offset_ms"] == 0


async def test_le_groupe_lan_garde_son_alignement_en_mode_boucle(
    db_session: AsyncSession, org: CmsOrganization
) -> None:
    """Non-régression : un groupe LAN reste aligné, y compris pour un event en boucle.

    C'est la raison d'origine du mécanisme (des écrans côte à côte doivent afficher la
    même image). Le nouveau motif s'AJOUTE, il ne remplace rien.
    """
    from app.api.v1.endpoints.ws import _build_sync_payload

    player, _ = await _fixture(
        db_session, org, duration_ms=None, expires_in_s=240,
        lan_sync=True, activated_s_ago=120,
    )

    payload = await _build_sync_payload(db_session, player.id_player)
    off = payload["start_offset_ms"]
    assert abs(off - 120_000) < _TOLERANCE_MS, f"décalage attendu ~120 s, obtenu {off} ms"


async def test_le_decalage_reste_dans_les_bornes_du_media(
    db_session: AsyncSession, org: CmsOrganization
) -> None:
    """Le décalage servi ne peut jamais dépasser la durée du média.

    Un décalage hors bornes produirait un seek tronqué — donc un écran figé, le
    symptôme même qu'on cherche à supprimer.
    """
    from app.api.v1.endpoints.ws import _build_sync_payload

    player, _ = await _fixture(
        db_session, org, duration_ms=369000, expires_in_s=240,
        lan_sync=False, activated_s_ago=360,
    )

    payload = await _build_sync_payload(db_session, player.id_player)
    off = payload["start_offset_ms"]
    assert 0 <= off < 369_058, f"décalage hors des bornes du média : {off} ms"
