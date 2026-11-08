"""Chartes de marque (P3.4, migr 0128) — service pur, résolution, rendu, endpoints.

Ce que ces tests figent, et pourquoi :

- **une charte ne remplace QUE ce qu'elle déclare** — sans ça, poser une seule couleur de marque
  effacerait en silence les autres couleurs du template ;
- **l'ordre de précédence** thème du template < charte < saisie de l'opérateur — c'est la décision
  « la charte pré-remplit, elle ne verrouille pas » ; si elle s'inverse, l'opérateur ne peut plus
  déroger et le produit ment sur ce qu'il promet ;
- **la police du thème atteint le rendu** — défaut latent trouvé en mesurant : les octets étaient
  embarqués, la police jamais appliquée ;
- **aucun nom de famille ne peut émettre du CSS** — il finit dans un `style="…"` où l'échappement
  HTML ne protège de rien.
"""

import uuid
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.models.brand_kit import CmsBrandKit
from app.models.campaign import CmsAdvertiser
from app.models.organization import CmsOrganization, CmsOrgAuthSettings
from app.models.role import CmsRole, CmsUserRoleAssignment
from app.models.user import CmsUser
from app.services import brand_kit as bk
from app.services.generation import prompt_assistant
from app.services.promo import fonts, render
from app.services.promo.templates import TEMPLATES, resolve_template
from tests.conftest import TEST_DATABASE_URL


# ── Fixtures ────────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="BrandOrg", org_slug=f"brand-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


@pytest_asyncio.fixture
async def other_org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="OtherOrg", org_slug=f"other-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


@pytest_asyncio.fixture
async def advertiser(db_session: AsyncSession, org: CmsOrganization) -> CmsAdvertiser:
    a = CmsAdvertiser(id_org=org.id_org, advertiser_name="Brightwell")
    db_session.add(a)
    await db_session.commit()
    await db_session.refresh(a)
    return a


async def _token(db_session: AsyncSession, org: CmsOrganization, role_key: str) -> str:
    """Jeton d'un compte réellement porteur du rôle EN BASE (`require_org_admin` lit la base :
    un jeton qui se contente de nommer le rôle n'accorde rien)."""
    user = CmsUser(id_org=org.id_org, email=f"u-{uuid.uuid4().hex[:8]}@t.com",
                   password_hash=hash_password("Password1!"), is_active=True)
    db_session.add(user)
    await db_session.flush()
    await db_session.execute(
        pg_insert(CmsRole).values(role_key=role_key, label=role_key, is_system=True)
        .on_conflict_do_nothing(constraint="uq_cms_roles_role_key")
    )
    await db_session.flush()
    role = (await db_session.execute(
        select(CmsRole).where(CmsRole.role_key == role_key))).scalar_one()
    db_session.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    await db_session.commit()
    return create_access_token(
        user.id_user, extra={"org": org.id_org, "roles": [role_key], "locale": "fr"})


@pytest_asyncio.fixture
async def admin_token(db_session: AsyncSession, org: CmsOrganization) -> str:
    return await _token(db_session, org, "CMS_ORG_ADMIN")


# ── apply_to_theme : une charte ne remplace QUE ce qu'elle déclare ───────────────

def test_kit_absente_laisse_le_theme_intact():
    """Déploiement neutre : tant qu'aucune charte n'existe, le rendu ne bouge pas d'un pixel."""
    theme = dict(TEMPLATES["fresh"]["theme"])
    assert bk.apply_to_theme(theme, None) == theme


def test_charte_partielle_ne_touche_pas_les_autres_couleurs():
    theme = dict(TEMPLATES["fresh"]["theme"])
    out = bk.apply_to_theme(theme, {"accent": "#E4002B"})
    assert out["accent"] == "#E4002B"
    # …et tout le reste est celui du template, pas un défaut inventé par la charte.
    for key in ("ink", "paper", "badge_bg", "badge_ink", "font"):
        assert out[key] == theme[key]


def test_couleur_invalide_ignoree():
    """Une valeur non hexadécimale ne doit jamais atteindre le CSS, même si elle a franchi la base
    (import, script, chemin d'écriture futur)."""
    theme = dict(TEMPLATES["fresh"]["theme"])
    out = bk.apply_to_theme(theme, {"accent": "red;background:url(http://evil)"})
    assert out["accent"] == theme["accent"]


def test_police_de_charte_absente_du_catalogue_retombe_sur_le_template():
    """Une police supprimée après l'écriture de la charte ne casse pas un rendu : il retombe sur
    celle du template (même raison que le ON DELETE SET NULL du logo)."""
    theme = dict(TEMPLATES["fresh"]["theme"])
    catalog = fonts.builtin_catalog()
    assert bk.apply_to_theme(theme, {"font_family": "Disparue"}, catalog)["font"] == theme["font"]
    assert bk.apply_to_theme(theme, {"font_family": "Oswald"}, catalog)["font"] == "Oswald"


def test_precedence_theme_puis_charte_puis_operateur():
    """LE point de la décision « pré-remplit, modifiable » : la charte l'emporte sur le template,
    et la saisie de l'opérateur l'emporte sur la charte."""
    theme = bk.apply_to_theme(dict(TEMPLATES["fresh"]["theme"]), {"ink": "#112233"})
    assert theme["ink"] == "#112233"                      # charte > template
    resolved = resolve_template(
        "fresh", "16:9", "fhd",
        {"slogan": "Promo", "style_overrides": {"slogan": {"color": "#445566"}}},
    )
    resolved["theme"] = theme
    html = render.build_html(resolved, None, None, "")
    assert "#445566" in html                              # opérateur > charte


# ── Rendu : la police du thème atteint enfin la toile ────────────────────────────

def test_la_police_du_theme_est_appliquee_a_la_toile():
    """ROUGE AVANT P3.4 : `used_font_faces` embarquait les octets de la police du thème et
    `render` posait la pile Inter en dur — la police était payée et jamais appliquée."""
    catalog = dict(fonts.builtin_catalog())
    catalog["org-brand"] = {"family": "Brand Sans", "weights": [700, 900], "source": "custom"}
    resolved = resolve_template("fresh", "16:9", "fhd",
                                {"slogan": "T", "price": "4,99"}, font_catalog=catalog)
    resolved["theme"] = {**resolved["theme"], "font": "Brand Sans"}
    html = render.build_html(resolved, None, None, "")
    stage = html.split(".stage {")[1].split("}")[0]
    assert "'Brand Sans'" in stage
    assert "Inter" in stage  # le repli reste derrière, on ne perd pas le filet


def test_font_face_et_usage_declarent_la_meme_famille():
    """Deux sanitisations divergentes donneraient une police embarquée que rien n'appelle."""
    hostile = "Bad" + chr(39) + ";color:red;x:" + chr(39)
    catalog = {"org-x": {"family": hostile, "weights": [600], "source": "custom"}}
    css = fonts.font_face_css({("org-x", 600)}, catalog, lambda *_: ("AAA", "woff2"))
    declared = css.split("font-family:'")[1].split("'")[0]
    assert declared == fonts.css_family(hostile)


# ── Aucun nom de famille ne peut émettre du CSS ──────────────────────────────────

def test_famille_hostile_ne_produit_aucune_declaration_css():
    """L'échappement Jinja transforme `'` en `&#39;`, mais dans un attribut `style="…"` l'analyseur
    HTML le redécode AVANT le CSS : seule la sanitisation du nom protège."""
    hostile = "Foo" + chr(39) + ";background-image:url(http://attacker.example/x);y:" + chr(39)
    catalog = dict(fonts.builtin_catalog())
    catalog["org-x"] = {"family": hostile, "weights": [600], "source": "custom"}
    resolved = resolve_template(
        "fresh", "16:9", "fhd",
        {"slogan": "T", "style_overrides": {"slogan": {"font": "org-x"}}}, font_catalog=catalog)
    html = render.build_html(resolved, None, None, "")
    # ⚠️ Ne PAS chercher « attacker.example » : le nom mutilé le contient encore, inerte.
    # Ce qui compte est qu'aucune DÉCLARATION ne se soit refermée.
    assert "url(http" not in html
    for family in html.split("font-family:'")[1:]:
        assert ";" not in family.split("'")[0]


def test_famille_legitime_intacte():
    """Témoin : sans lui, une sanitisation qui viderait tout passerait le test précédent."""
    assert fonts.css_family("Playfair Display") == "Playfair Display"
    assert fonts.css_family("Röboto-Condensed 2.0") == "Röboto-Condensed 2.0"
    assert fonts.is_safe_family("Playfair Display") is True
    assert fonts.is_safe_family("Foo';x:'") is False
    assert fonts.css_family("';;'") is None  # rien d'exploitable ne subsiste


# ── prompt_block : atmosphère, jamais fidélité ───────────────────────────────────

def test_prompt_block_vide_sans_charte():
    assert bk.prompt_block(None) == ""
    assert bk.prompt_block({"brand_name": "Acme"}) == ""  # ni palette ni ton → rien à dire


def test_prompt_block_donne_la_palette_et_ecarte_logo_et_mentions():
    block = bk.prompt_block({"accent": "#E4002B", "tone": "sobre et technique",
                             "brand_name": "Acme", "legal_mentions": "Voir conditions"})
    assert "#E4002B" in block
    assert "sobre et technique" in block
    # Le cœur du sujet : ces trois-là sont posés par le compositing, pas demandés au modèle.
    lowered = block.lower()
    assert "logo" in lowered and "mentions" in lowered
    # …et le nom de la marque n'est pas donné comme matière créative (il ferait peindre le produit).
    assert "Acme" not in block
    assert "Voir conditions" not in block


# ── Résolution : l'annonceur l'emporte, repli sur l'organisation ─────────────────

@pytest.mark.asyncio
async def test_resolution_annonceur_puis_org(db_session: AsyncSession, org, advertiser):
    assert await bk.resolve_brand_kit(db_session, org.id_org) is None  # rien = None

    db_session.add(CmsBrandKit(id_org=org.id_org, kit_name="Enseigne", accent="#111111"))
    await db_session.commit()
    # Sans annonceur, comme avec un annonceur qui n'a pas de charte : celle de l'org.
    assert (await bk.resolve_brand_kit(db_session, org.id_org))["accent"] == "#111111"
    resolved = await bk.resolve_brand_kit(db_session, org.id_org, advertiser.id_advertiser)
    assert resolved["accent"] == "#111111"

    db_session.add(CmsBrandKit(id_org=org.id_org, id_advertiser=advertiser.id_advertiser,
                               kit_name="Brightwell", accent="#222222"))
    await db_session.commit()
    resolved = await bk.resolve_brand_kit(db_session, org.id_org, advertiser.id_advertiser)
    assert resolved["accent"] == "#222222"                       # l'annonceur l'emporte
    assert (await bk.resolve_brand_kit(db_session, org.id_org))["accent"] == "#111111"


@pytest.mark.asyncio
async def test_resolution_cloisonnee_par_organisation(db_session: AsyncSession, org, other_org):
    db_session.add(CmsBrandKit(id_org=other_org.id_org, kit_name="Voisine", accent="#333333"))
    await db_session.commit()
    assert await bk.resolve_brand_kit(db_session, org.id_org) is None


@pytest.mark.asyncio
async def test_les_deux_chemins_de_lecture_rendent_la_meme_charte(
    db_session: AsyncSession, org, advertiser
):
    """L'API lit en ORM async, le worker de rendu en psycopg2 synchrone. Si les deux divergeaient,
    le visuel produit ne serait pas celui que l'écran a annoncé — on le mesure au lieu de le
    supposer."""
    import psycopg2

    db_session.add(CmsBrandKit(id_org=org.id_org, kit_name="Enseigne", accent="#111111"))
    db_session.add(CmsBrandKit(id_org=org.id_org, id_advertiser=advertiser.id_advertiser,
                               kit_name="Brightwell", accent="#222222", tone="technique"))
    await db_session.commit()

    dsn = TEST_DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    conn = psycopg2.connect(dsn)
    try:
        for id_adv in (None, advertiser.id_advertiser):
            async_kit = await bk.resolve_brand_kit(db_session, org.id_org, id_adv)
            sync_kit = bk.resolve_brand_kit_sync(conn, org.id_org, id_adv)
            assert async_kit == sync_kit, f"divergence des deux chemins (annonceur={id_adv})"
        # Témoin : les deux cas mesurés ne rendent pas la même chose (sinon on comparerait deux
        # fois le même résultat et l'égalité ne prouverait rien).
        assert (await bk.resolve_brand_kit(db_session, org.id_org))["accent"] != \
            bk.resolve_brand_kit_sync(conn, org.id_org, advertiser.id_advertiser)["accent"]
    finally:
        conn.close()


# ── Application au rendu : les CALQUES héritent aussi de la charte ───────────────

def test_les_calques_heritent_de_la_palette_de_la_charte():
    """La fusion se fait AVANT la résolution, pas après : les couleurs par défaut des calques
    dérivent du thème (`layers.resolve_layers`). Fusionner après aurait donné un visuel dont les
    textes portent la marque et les formes le template."""
    overrides = bk.theme_overrides({"accent": "#E4002B", "ink": "#0A0A0A"})
    resolved = resolve_template(
        "fresh", "16:9", "fhd",
        {"slogan": "T", "price": "1", "layers": [{"type": "shape", "shape": "rect"},
                                                 {"type": "text", "text": "X"}]},
        theme_overrides=overrides)
    assert resolved["theme"]["accent"] == "#E4002B"
    shape, text = resolved["layers"][0], resolved["layers"][1]
    assert shape["fill"] == "#E4002B"   # défaut de forme = accent du thème
    assert text["color"] == "#0A0A0A"   # défaut de texte = encre du thème


@pytest.mark.asyncio
async def test_la_charte_atteint_reellement_le_prompt_systeme():
    """On mesure ce que le MODÈLE reçoit, pas ce que la fonction pure renvoie : le bloc pouvait
    être construit et jamais attaché."""
    captured: dict = {}

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": '{"ready":true,"prompt":"a cat"}'}}]}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def post(self, _url, headers=None, json=None):
            captured["messages"] = json["messages"]
            return _Resp()

    with patch("app.services.generation.prompt_assistant.httpx.AsyncClient", lambda **_: _Client()):
        await prompt_assistant.assist_prompt(
            kind="image", model_id=None, reference_present=False, mode="one_shot",
            intent="un chat", brand={"accent": "#E4002B", "tone": "sobre"})
    system = captured["messages"][0]["content"]
    assert "#E4002B" in system and "sobre" in system
    assert "logo" in system.lower()

    # Témoin : sans charte, le prompt système ne parle pas de marque (sinon l'assertion ci-dessus
    # passerait sur un texte qui serait là de toute façon).
    with patch("app.services.generation.prompt_assistant.httpx.AsyncClient", lambda **_: _Client()):
        await prompt_assistant.assist_prompt(
            kind="image", model_id=None, reference_present=False, mode="one_shot",
            intent="un chat", brand=None)
    assert "Charte de marque" not in captured["messages"][0]["content"]


def test_sans_charte_le_rendu_est_strictement_inchange():
    """Déploiement neutre, mesuré sur l'arbre résolu complet."""
    inputs = {"slogan": "Promo", "price": "4,99", "original_price": "6,99"}
    assert resolve_template("fresh", "16:9", "fhd", inputs) == \
        resolve_template("fresh", "16:9", "fhd", inputs, theme_overrides=bk.theme_overrides(None))


# ── Endpoints ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_crud_charte_org(client: AsyncClient, admin_token: str):
    r = await client.put("/api/v1/promo/brand-kits/org",
                         json={"kit_name": "Enseigne", "accent": "#E4002B",
                               "tone": "chaleureux", "legal_mentions": "Offre soumise à…"},
                         headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200, r.text
    assert r.json()["accent"] == "#E4002B"

    # Idempotent : un second PUT met à jour, il ne crée pas une seconde charte.
    r = await client.put("/api/v1/promo/brand-kits/org", json={"kit_name": "Enseigne 2"},
                         headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200
    listing = await client.get("/api/v1/promo/brand-kits",
                               headers={"Authorization": f"Bearer {admin_token}"})
    assert len([k for k in listing.json() if k["id_advertiser"] is None]) == 1

    r = await client.delete("/api/v1/promo/brand-kits/org",
                            headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_couleur_invalide_refusee_a_la_saisie(client: AsyncClient, admin_token: str):
    r = await client.put("/api/v1/promo/brand-kits/org",
                         json={"kit_name": "X", "accent": "rouge"},
                         headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_police_inconnue_refusee_a_la_saisie(client: AsyncClient, admin_token: str):
    """On refuse au moment du geste plutôt que de laisser découvrir au rendu que la police n'a pas
    été appliquée."""
    r = await client.put("/api/v1/promo/brand-kits/org",
                         json={"kit_name": "X", "font_family": "Police Inexistante"},
                         headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 422
    r = await client.put("/api/v1/promo/brand-kits/org",
                         json={"kit_name": "X", "font_family": "Oswald"},
                         headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_ecriture_reservee_a_l_org_admin(client: AsyncClient, db_session: AsyncSession, org):
    """La charte décide de l'identité de marque : sa lecture est large, son écriture ne l'est pas."""
    viewer = await _token(db_session, org, "CMS_VIEWER")
    r = await client.put("/api/v1/promo/brand-kits/org", json={"kit_name": "X"},
                         headers={"Authorization": f"Bearer {viewer}"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_charte_annonceur_d_une_autre_org_refusee(
    client: AsyncClient, db_session: AsyncSession, admin_token: str, other_org
):
    """Un annonceur d'une autre organisation n'est pas une cible valide (404, jamais 403)."""
    intruder = CmsAdvertiser(id_org=other_org.id_org, advertiser_name="Ailleurs")
    db_session.add(intruder)
    await db_session.commit()
    await db_session.refresh(intruder)
    r = await client.put(f"/api/v1/promo/brand-kits/advertiser/{intruder.id_advertiser}",
                         json={"kit_name": "X"},
                         headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_charte_resolue_exposee_a_l_ui(
    client: AsyncClient, admin_token: str, advertiser: CmsAdvertiser
):
    """C'est cette réponse qui pré-remplit l'éditeur : elle doit rendre EXACTEMENT ce que le rendu
    appliquera, sinon l'aperçu ment."""
    await client.put("/api/v1/promo/brand-kits/org",
                     json={"kit_name": "Enseigne", "accent": "#111111"},
                     headers={"Authorization": f"Bearer {admin_token}"})
    await client.put(f"/api/v1/promo/brand-kits/advertiser/{advertiser.id_advertiser}",
                     json={"kit_name": "Brightwell", "accent": "#222222"},
                     headers={"Authorization": f"Bearer {admin_token}"})

    r = await client.get("/api/v1/promo/brand-kits/resolved",
                         headers={"Authorization": f"Bearer {admin_token}"})
    assert r.json()["accent"] == "#111111"
    r = await client.get(
        f"/api/v1/promo/brand-kits/resolved?advertiser_id={advertiser.id_advertiser}",
        headers={"Authorization": f"Bearer {admin_token}"})
    assert r.json()["accent"] == "#222222"
