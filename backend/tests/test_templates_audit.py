"""Audit du menu Templates (2026-07-28) — suppression franche, traçabilité, périmètre.

Décisions d'Ed :
  · « quand on efface, on efface » — la suppression logique laissait des lignes fantômes,
    ni visibles, ni listées, ni restaurables (6 en production), et **sans aucune trace**
    d'audit pour dire qui les avait supprimées ;
  · consolider les fuites de périmètre trouvées par les sondes.

Défauts couverts, tous MESURÉS sur la production avant correctif :
  · un template d'un nœud frère (absent de la liste, 404 au détail) apparaissait par son
    NOM dans la recherche globale ;
  · on pouvait lier ce même template invisible à une playlist (201) ;
  · supprimer un template utilisé passait en 204, sans avertissement, et la playlist
    basculait silencieusement du multi-zones au plein écran ;
  · `updated_at` ne bougeait jamais.
"""

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.models.audit_log import CmsAuditLog
from app.models.governance import CmsGovernanceNode, CmsGovernanceNodeAdmin
from app.models.organization import CmsOrganization, CmsOrgAuthSettings
from app.models.playlist import CmsPlaylist
from app.models.role import (
    CmsPermission,
    CmsRole,
    CmsRolePermission,
    CmsUserRoleAssignment,
)
from app.models.template import CmsTemplate
from app.models.user import CmsUser

_LAYOUT = {"layout_type": "custom", "zones": [
    {"index": 0, "x": 0, "y": 0, "w": 960, "h": 1080, "label": "G"},
    {"index": 1, "x": 960, "y": 0, "w": 960, "h": 1080, "label": "D"},
]}
_PERMS = [("templates", "read"), ("templates", "create"), ("templates", "edit"),
          ("templates", "delete"), ("playlists", "create"), ("playlists", "edit"),
          ("playlists", "read"), ("media", "read"), ("governance", "read")]


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="Tpl", org_slug=f"tpl-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


async def _mk_user(db: AsyncSession, org, *, scoped: bool = False,
                   org_admin: bool = False) -> CmsUser:
    uid = uuid.uuid4().hex[:8]
    user = CmsUser(id_org=org.id_org, email=f"t-{uid}@test.com",
                   password_hash=hash_password("Password1!"), is_active=True)
    db.add(user)
    await db.flush()
    # `scoped` : rôle de gouvernance (G4) — le non-gouverné lui devient invisible.
    key = "CMS_GOVERNANCE_EDITOR" if scoped else f"CMS_T_{uid}"
    await db.execute(
        pg_insert(CmsRole).values(id_org=org.id_org, role_key=key, label="T", is_system=scoped)
        .on_conflict_do_nothing(index_elements=["role_key"])
    )
    await db.flush()
    role = (await db.execute(select(CmsRole).where(CmsRole.role_key == key))).scalar_one()
    for module, operation in _PERMS:
        await db.execute(
            pg_insert(CmsPermission)
            .values(module=module, operation=operation, label=f"{module}.{operation}")
            .on_conflict_do_nothing(constraint="uq_cms_permissions_module_operation")
        )
        await db.flush()
        perm = (await db.execute(select(CmsPermission).where(
            CmsPermission.module == module, CmsPermission.operation == operation
        ))).scalar_one()
        await db.execute(
            pg_insert(CmsRolePermission)
            .values(id_role=role.id_role, id_permission=perm.id_permission)
            .on_conflict_do_nothing()
        )
    await db.flush()
    db.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    if org_admin:
        # Témoin non filtré : sans le bypass org-admin, `content_visibility` s'applique
        # AUSSI à lui (aucun nœud administré ⇒ il ne voit que le non-gouverné), et le test
        # « l'admin, lui, le voit » ne prouverait rien.
        await db.execute(
            pg_insert(CmsRole)
            .values(id_org=org.id_org, role_key="CMS_ORG_ADMIN", label="Org Admin", is_system=True)
            .on_conflict_do_nothing(index_elements=["role_key"])
        )
        await db.flush()
        oa = (await db.execute(select(CmsRole).where(
            CmsRole.role_key == "CMS_ORG_ADMIN"))).scalar_one()
        db.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=oa.id_role))
    await db.commit()
    await db.refresh(user)
    return user


def _h(user: CmsUser) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.id_user)}"}


@pytest_asyncio.fixture
async def scene(db_session: AsyncSession, org):
    """National → Site-A et Site-B. `local` administre Site-A seulement."""
    nat = CmsGovernanceNode(id_org=org.id_org, node_name="National", node_level=0,
                            node_type="national", requires_approval=False, path="")
    db_session.add(nat)
    await db_session.flush()
    nat.path = str(nat.id_node)
    made = {}
    for name in ("A", "B"):
        n = CmsGovernanceNode(id_org=org.id_org, parent_id=nat.id_node, node_name=f"Site-{name}",
                              node_level=1, node_type="store", requires_approval=False, path="")
        db_session.add(n)
        await db_session.flush()
        n.path = f"{nat.id_node}.{n.id_node}"
        made[name] = n
    local = await _mk_user(db_session, org, scoped=True)
    admin = await _mk_user(db_session, org, org_admin=True)
    db_session.add(CmsGovernanceNodeAdmin(id_node=made["A"].id_node, id_user=local.id_user))
    # Template du nœud FRÈRE : hors périmètre de `local`, ni ancêtre ni descendant.
    sibling = CmsTemplate(id_org=org.id_org, template_name="Maquette Site-B",
                          layout=_LAYOUT, id_governance_node=made["B"].id_node)
    db_session.add(sibling)
    await db_session.commit()
    await db_session.refresh(sibling)
    return {"nat": nat, "a": made["A"], "b": made["B"],
            "local": local, "admin": admin, "sibling": sibling}


# ── Périmètre ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_global_search_hides_templates_out_of_scope(client: AsyncClient, scene) -> None:
    """La barre globale ne doit pas révéler par leur NOM ce que la liste refuse.

    Mesuré en production : liste 0, détail 404… et le nom bien présent dans la recherche.
    """
    async def _hits(user) -> list[str]:
        r = await client.get("/api/v1/search", params={"q": "Maquette"}, headers=_h(user))
        assert r.status_code == 200, r.text
        return [i["label"] for g in r.json()["groups"] if g["kind"] == "template"
                for i in g["items"]]

    assert await _hits(scene["local"]) == []            # hors périmètre : rien
    assert "Maquette Site-B" in await _hits(scene["admin"])


@pytest.mark.asyncio
async def test_cannot_attach_an_invisible_template_to_a_playlist(
    client: AsyncClient, scene
) -> None:
    """Le filtre de visibilité n'existait que dans le sélecteur, donc côté client."""
    tid = scene["sibling"].id_template
    # Il ne le voit pas…
    assert (await client.get(f"/api/v1/templates/{tid}",
                             headers=_h(scene["local"]))).status_code == 404
    # …il ne doit donc pas pouvoir le lier en devinant l'identifiant.
    r = await client.post("/api/v1/playlists",
                          json={"playlist_name": "Pirate", "id_template": tid,
                                "id_governance_node": scene["a"].id_node},
                          headers=_h(scene["local"]))
    assert r.status_code == 404, r.text


# ── « Quand on efface, on efface » ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_really_removes_the_row_and_is_traced(
    client: AsyncClient, db_session: AsyncSession, org, scene
) -> None:
    """Plus de ligne fantôme : la ligne DISPARAÎT, et le journal, lui, RESTE."""
    admin = scene["admin"]
    tid = (await client.post("/api/v1/templates",
                             json={"template_name": "A supprimer", "layout": _LAYOUT},
                             headers=_h(admin))).json()["id_template"]

    assert (await client.delete(f"/api/v1/templates/{tid}",
                                headers=_h(admin))).status_code == 204
    # Effacé POUR DE BON — avant, la ligne restait avec is_deleted = True.
    assert (await db_session.execute(select(CmsTemplate).where(
        CmsTemplate.id_template == tid))).scalar_one_or_none() is None

    # …mais on sait qui, quand et quoi : c'est ce qui manquait pour répondre à
    # « qui a supprimé ce template ? » (0 ligne d'audit mesurée en production).
    rows = list((await db_session.execute(select(CmsAuditLog).where(
        CmsAuditLog.resource_type == "template",
        CmsAuditLog.resource_id == str(tid)))).scalars().all())
    actions = {r.action for r in rows}
    assert actions == {"create", "delete"}
    deleted = next(r for r in rows if r.action == "delete")
    assert deleted.detail["template_name"] == "A supprimer"
    assert deleted.id_user == admin.id_user


@pytest.mark.asyncio
async def test_delete_refuses_a_template_in_use_then_accepts_with_force(
    client: AsyncClient, db_session: AsyncSession, org, scene
) -> None:
    """Une playlist pointant sur un template disparu bascule SILENCIEUSEMENT en plein
    écran mono-zone. On refuse donc, en nommant la playlist, plutôt que de dégrader."""
    admin = scene["admin"]
    tid = (await client.post("/api/v1/templates",
                             json={"template_name": "Deux zones", "layout": _LAYOUT},
                             headers=_h(admin))).json()["id_template"]
    pl = CmsPlaylist(id_org=org.id_org, playlist_name="Vitrine", id_template=tid)
    db_session.add(pl)
    await db_session.commit()
    await db_session.refresh(pl)

    r = await client.delete(f"/api/v1/templates/{tid}", headers=_h(admin))
    assert r.status_code == 409, r.text
    assert "Vitrine" in r.json()["detail"]        # la playlist est NOMMÉE
    # Rien n'a bougé.
    assert (await db_session.execute(select(CmsTemplate).where(
        CmsTemplate.id_template == tid))).scalar_one_or_none() is not None

    # L'impact est consultable AVANT de confirmer.
    imp = (await client.get(f"/api/v1/templates/{tid}/deletion-impact",
                            headers=_h(admin))).json()
    assert imp["summary"] == {"playlists": 1, "zones": 2}

    # Confirmation explicite : la playlist est DÉTACHÉE, puis le template supprimé.
    assert (await client.delete(f"/api/v1/templates/{tid}?force=true",
                                headers=_h(admin))).status_code == 204
    await db_session.refresh(pl)
    assert pl.id_template is None
    assert (await db_session.execute(select(CmsTemplate).where(
        CmsTemplate.id_template == tid))).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_update_touches_the_modification_date(client: AsyncClient, scene) -> None:
    """`updated_at` ne bougeait JAMAIS — 0 template sur 8 en production."""
    admin = scene["admin"]
    created = (await client.post("/api/v1/templates",
                                 json={"template_name": "Avant", "layout": _LAYOUT},
                                 headers=_h(admin))).json()
    updated = (await client.put(f"/api/v1/templates/{created['id_template']}",
                                json={"template_name": "Après"}, headers=_h(admin))).json()
    assert updated["template_name"] == "Après"
    assert updated["updated_at"] > created["updated_at"]


# ── Les 2 derniers points, tranchés par Ed ───────────────────────────────────

@pytest.mark.asyncio
async def test_readonly_flag_is_served_by_list_and_detail(client: AsyncClient, scene) -> None:
    """« Si lecture, alors lecture » — l'écran doit le SAVOIR avant le clic.

    L'éditeur s'ouvrait en écriture sur une maquette qu'on ne peut pas modifier, et le
    refus n'arrivait qu'au clic « Enregistrer » (403). Le drapeau doit venir des DEUX
    surfaces : ne le calculer que dans la liste laisse le lien direct mentir — c'est le
    défaut corrigé pour les médias le matin même.
    """
    local, admin = scene["local"], scene["admin"]
    # Une maquette de SON nœud : modifiable.
    mine = (await client.post("/api/v1/templates",
                              json={"template_name": "Ma maquette", "layout": _LAYOUT,
                                    "id_governance_node": scene["a"].id_node},
                              headers=_h(local))).json()
    assert mine["governed_readonly"] is False
    # Une maquette NATIONALE : visible par héritage (D6), mais en lecture seule.
    nat = (await client.post("/api/v1/templates",
                             json={"template_name": "Maquette nationale", "layout": _LAYOUT,
                                   "id_governance_node": scene["nat"].id_node},
                             headers=_h(admin))).json()

    detail = (await client.get(f"/api/v1/templates/{nat['id_template']}",
                               headers=_h(local))).json()
    assert detail["governed_readonly"] is True          # le DÉTAIL le dit…
    listed = (await client.get("/api/v1/templates", headers=_h(local))).json()
    row = next(r for r in listed if r["id_template"] == nat["id_template"])
    assert row["governed_readonly"] is True             # …et la LISTE aussi.

    # Et le drapeau ne ment pas : l'écriture est bien refusée.
    r = await client.put(f"/api/v1/templates/{nat['id_template']}",
                         json={"template_name": "Piraté"}, headers=_h(local))
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_templates_publish_permission_is_gone() -> None:
    """`templates:publish` était seedée et vérifiée NULLE PART.

    Une permission cochable dans l'éditeur de rôles qui n'accorde rien est une promesse
    fausse faite à l'administrateur. Ed : « soit on la retire soit on implémente, la
    première me semble plus adéquate ». On vérifie les DEUX bouts — la migration la
    supprime, et le code ne la réclame nulle part (sinon on l'aurait cassée).
    """
    import pathlib
    import re

    migr = pathlib.Path("alembic/versions/0115_drop_templates_publish.py").read_text(encoding="utf-8")
    assert "DELETE FROM cms_permissions WHERE module = 'templates' AND operation = 'publish'" in migr

    used = set()
    for f in pathlib.Path("app").rglob("*.py"):
        used |= set(re.findall(r'"templates"\s*,\s*"(\w+)"', f.read_text(encoding="utf-8")))
    assert "publish" not in used, f"templates:publish est encore exigé quelque part : {used}"


@pytest.mark.asyncio
async def test_campaign_placement_round_trips_through_the_api(
    client: AsyncClient, db_session: AsyncSession, org, scene
) -> None:
    """P3.6 — le mode d'affichage des spots doit VOYAGER, sinon le réglage est décoratif.

    Un champ ajouté au modèle et au schéma mais oublié dans l'endpoint se lit parfaitement
    en base et ne change jamais rien : c'est le motif « garde inerte » que ce projet
    rencontre régulièrement. On exerce donc les trois maillons — création, lecture, mise à
    jour — par l'API réelle.
    """
    admin = scene["admin"]

    # Défaut = plein écran : c'est le seul mode cohérent avec la tarification au SOV,
    # et il doit s'appliquer sans que personne n'ait à le demander.
    created = (await client.post("/api/v1/templates",
                                 json={"template_name": "Vitrine", "layout": _LAYOUT},
                                 headers=_h(admin))).json()
    assert created["campaign_placement"] == "fullscreen"

    # Le menu board choisit l'autre mode.
    tid = (await client.post("/api/v1/templates",
                             json={"template_name": "Menu board", "layout": _LAYOUT,
                                   "campaign_placement": "zone"},
                             headers=_h(admin))).json()["id_template"]
    row = (await db_session.execute(select(CmsTemplate).where(
        CmsTemplate.id_template == tid))).scalar_one()
    assert row.campaign_placement == "zone"          # réellement PERSISTÉ

    # Et il peut changer d'avis.
    r = await client.put(f"/api/v1/templates/{tid}",
                         json={"campaign_placement": "fullscreen"}, headers=_h(admin))
    assert r.status_code == 200
    assert r.json()["campaign_placement"] == "fullscreen"

    # Une valeur inconnue est REFUSÉE : l'accepter ferait diffuser autre chose que ce qui
    # a été vendu, en silence.
    bad = await client.put(f"/api/v1/templates/{tid}",
                           json={"campaign_placement": "plein_ecran"}, headers=_h(admin))
    assert bad.status_code == 422
