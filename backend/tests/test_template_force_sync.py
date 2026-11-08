"""Modifier un template doit ATTEINDRE les écrans (constat d'Ed, 2026-08-06).

En validant P3.6, Ed a basculé « Template 2 zones » de `campaign_placement=fullscreen` à
`zone` : **les players ont continué de diffuser l'ancien mode**. Il a fallu rouvrir la
playlist et la re-publier — la publication, elle, pousse `force_sync` — pour que le
changement prenne. Autrement dit le geste qui décide du rendu ne prévenait personne, et
c'est un geste voisin et sans rapport qui le faisait passer.

Ce n'est pas cosmétique : `campaign_placement` décide si un spot **FACTURÉ au SOV**
recouvre l'écran ou reste confiné dans une zone. Tant que la poussée manque, on facture une
exposition qui n'est pas celle qui est servie.

La discipline codée ici a deux faces, et les deux sont testées :
  · ce qui atteint l'écran (`layout`, `campaign_placement`) pousse ;
  · ce qui ne l'atteint pas (nom, description) **ne pousse pas** — sinon renommer une
    maquette ferait resynchroniser tout le parc.
"""

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
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

pytestmark = pytest.mark.asyncio

_LAYOUT = {"layout_type": "sidebar_r", "canvas_width": 1920, "canvas_height": 1080,
           "zones": [{"index": 0, "x": 0, "y": 0, "w": 1440, "h": 1080, "label": "Main"},
                     {"index": 1, "x": 1440, "y": 0, "w": 480, "h": 1080, "label": "Side"}]}
_PERMS = [("templates", "read"), ("templates", "edit"), ("templates", "delete")]


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="TplSync", org_slug=f"tplsync-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


@pytest_asyncio.fixture
async def user(db_session: AsyncSession, org) -> CmsUser:
    uid = uuid.uuid4().hex[:8]
    u = CmsUser(id_org=org.id_org, email=f"tsync-{uid}@test.com",
                password_hash=hash_password("Password1!"), is_active=True)
    db_session.add(u)
    await db_session.flush()
    key = f"CMS_TS_{uid}"
    await db_session.execute(
        pg_insert(CmsRole).values(id_org=org.id_org, role_key=key, label="TS")
        .on_conflict_do_nothing(index_elements=["role_key"])
    )
    await db_session.flush()
    role = (await db_session.execute(
        select(CmsRole).where(CmsRole.role_key == key))).scalar_one()
    for module, operation in _PERMS:
        await db_session.execute(
            pg_insert(CmsPermission)
            .values(module=module, operation=operation, label=f"{module}.{operation}")
            .on_conflict_do_nothing(constraint="uq_cms_permissions_module_operation")
        )
        await db_session.flush()
        perm = (await db_session.execute(select(CmsPermission).where(
            CmsPermission.module == module, CmsPermission.operation == operation
        ))).scalar_one()
        await db_session.execute(
            pg_insert(CmsRolePermission)
            .values(id_role=role.id_role, id_permission=perm.id_permission)
            .on_conflict_do_nothing()
        )
    await db_session.flush()
    db_session.add(CmsUserRoleAssignment(id_user=u.id_user, id_role=role.id_role))
    await db_session.commit()
    await db_session.refresh(u)
    return u


@pytest_asyncio.fixture
async def tmpl(db_session: AsyncSession, org) -> CmsTemplate:
    t = CmsTemplate(id_org=org.id_org, template_name="Template 2 zones",
                    layout=_LAYOUT, campaign_placement="fullscreen")
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)
    return t


def _h(u: CmsUser) -> dict:
    return {"Authorization": f"Bearer {create_access_token(u.id_user)}"}


@pytest.fixture
def pushes(monkeypatch) -> list:
    """Compte les poussées `force_sync` émises par le module templates."""
    import app.api.v1.endpoints.templates as tpl_ep
    calls: list = []

    async def _capture(db, preemptive: bool = False):
        calls.append(preemptive)

    monkeypatch.setattr(tpl_ep, "push_org_force_sync", _capture)
    return calls


async def test_placement_change_pushes_force_sync(
    client: AsyncClient, user, tmpl, pushes,
) -> None:
    """LE défaut d'Ed : basculer plein écran → zone ne prévenait aucun écran."""
    resp = await client.put(f"/api/v1/templates/{tmpl.id_template}",
                            json={"campaign_placement": "zone"}, headers=_h(user))
    assert resp.status_code == 200, resp.text
    assert resp.json()["campaign_placement"] == "zone"
    assert len(pushes) == 1, "aucune poussée : les écrans garderaient l'ancien mode"


async def test_layout_change_pushes_force_sync(
    client: AsyncClient, user, tmpl, pushes,
) -> None:
    """Déplacer/redimensionner une zone change la géométrie servie au player."""
    moved = {**_LAYOUT, "zones": [
        {"index": 0, "x": 0, "y": 0, "w": 1200, "h": 1080, "label": "Main"},
        {"index": 1, "x": 1200, "y": 0, "w": 720, "h": 1080, "label": "Side"},
    ]}
    resp = await client.put(f"/api/v1/templates/{tmpl.id_template}",
                            json={"layout": moved}, headers=_h(user))
    assert resp.status_code == 200, resp.text
    assert len(pushes) == 1


async def test_rename_does_not_push(
    client: AsyncClient, user, tmpl, pushes,
) -> None:
    """Le nom ne voyage PAS jusqu'au player : resynchroniser le parc serait du bruit pur."""
    resp = await client.put(f"/api/v1/templates/{tmpl.id_template}",
                            json={"template_name": "Maquette rebaptisée",
                                  "description": "note interne"}, headers=_h(user))
    assert resp.status_code == 200, resp.text
    assert pushes == [], "un renommage a resynchronisé tout le parc"


async def test_same_placement_does_not_push(
    client: AsyncClient, user, tmpl, pushes,
) -> None:
    """Réécrire la MÊME valeur ne change rien à l'antenne."""
    resp = await client.put(f"/api/v1/templates/{tmpl.id_template}",
                            json={"campaign_placement": "fullscreen"}, headers=_h(user))
    assert resp.status_code == 200, resp.text
    assert pushes == []


async def test_delete_detaching_playlists_pushes(
    client: AsyncClient, db_session: AsyncSession, org, user, tmpl, pushes,
) -> None:
    """Supprimer emporte les playlists du multi-zones au plein écran mono-zone."""
    db_session.add(CmsPlaylist(id_org=org.id_org, playlist_name="Kriss",
                               id_template=tmpl.id_template))
    await db_session.commit()

    resp = await client.delete(f"/api/v1/templates/{tmpl.id_template}?force=true",
                               headers=_h(user))
    assert resp.status_code == 204, resp.text
    assert len(pushes) == 1


async def test_delete_unused_does_not_push(
    client: AsyncClient, user, tmpl, pushes,
) -> None:
    """Aucune playlist ne l'utilise ⇒ rien ne change à l'antenne ⇒ on ne pousse pas."""
    resp = await client.delete(f"/api/v1/templates/{tmpl.id_template}", headers=_h(user))
    assert resp.status_code == 204, resp.text
    assert pushes == []
