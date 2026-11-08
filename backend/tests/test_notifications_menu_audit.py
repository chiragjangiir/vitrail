"""Audit menu ⑬ Notifications & alertes (2026-07-31) — dernier menu de la série.

Le module est court et son cloisonnement tient (org-admin partout, filtres `id_org` sur les
canaux comme sur les règles). Deux angles restent :

  · 🔴 **SSRF** — l'URL d'un canal webhook n'était validée que sur son SCHÉMA. Le serveur
    accepte donc de POSTer vers `127.0.0.1`, `192.168.x.x` ou l'adresse de métadonnées
    d'un cloud, et le **code HTTP est renvoyé à l'appelant** (« HTTP 200 » vs erreur de
    connexion) : de quoi cartographier un réseau interne depuis l'extérieur. Le corps de la
    réponse, lui, n'est PAS exposé — c'est un SSRF **aveugle**, pas une exfiltration.
    🔑 Le projet a déjà `app.core.ssrf.url_is_safe`, utilisé à **5 autres endroits**
    (import de campagne, médias, promo, import de bundle) : ce canal était l'oublié.
    ⚠️ Le geste demande un compte org-admin — mais le modèle intégrateur vise justement des
    serveurs partagés entre organisations, et un compte compromis reste un compte compromis.
  · **traçabilité** : 0 ligne, comme IAM. Créer un canal e-mail, c'est décider où partent les
    alertes du réseau ; le rediriger silencieusement est un geste qui doit se voir.

Mesuré en production avant correctif : 0 canal, 0 règle, 0 ligne d'audit — le module n'est pas
encore utilisé, donc rien n'a été exploité et le correctif est sans risque de régression.
"""

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.models.audit_log import CmsAuditLog
from app.models.notification import CmsAlertRule, CmsNotificationChannel
from app.models.organization import CmsOrganization, CmsOrgAuthSettings
from app.models.role import CmsRole, CmsUserRoleAssignment
from app.models.user import CmsUser


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="NotifAudit", org_slug=f"na-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


@pytest_asyncio.fixture
async def admin(db_session: AsyncSession, org) -> CmsUser:
    user = CmsUser(
        id_org=org.id_org, email=f"na-{uuid.uuid4().hex[:8]}@test.com",
        password_hash=hash_password("Password1!"), is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.execute(
        pg_insert(CmsRole)
        .values(id_org=org.id_org, role_key="CMS_ORG_ADMIN", label="Org Admin", is_system=True)
        .on_conflict_do_nothing(index_elements=["role_key"])
    )
    await db_session.flush()
    role = (await db_session.execute(
        select(CmsRole).where(CmsRole.role_key == "CMS_ORG_ADMIN")
    )).scalar_one()
    db_session.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    await db_session.commit()
    await db_session.refresh(user)
    return user


def _h(user: CmsUser) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.id_user)}"}


async def _audit_count(db: AsyncSession, org, resource_type: str) -> int:
    return (await db.execute(
        select(func.count()).select_from(CmsAuditLog).where(
            CmsAuditLog.id_org == org.id_org,
            CmsAuditLog.resource_type == resource_type)
    )).scalar_one()


# ── SSRF sur le canal webhook ────────────────────────────────────────────────

# Cibles internes classiques : la boucle locale (l'API elle-même), le réseau privé du
# client, et l'adresse de métadonnées des fournisseurs cloud (jetons d'instance).
_INTERNAL = [
    "http://127.0.0.1:8010/api/v1/meta",
    "http://localhost:8010/health",
    "http://192.168.1.10:9000/",
    "http://169.254.169.254/latest/meta-data/",
    "http://[::1]:8010/",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("url", _INTERNAL)
async def test_webhook_channel_refuses_internal_targets(
    client: AsyncClient, admin, url: str
) -> None:
    r = await client.post("/api/v1/notifications/channels", headers=_h(admin), json={
        "channel_type": "webhook", "name": "Sonde", "config": {"url": url},
    })
    assert r.status_code == 400, f"{url} accepté : {r.text}"


@pytest.mark.asyncio
async def test_webhook_channel_accepts_public_target(client: AsyncClient, admin) -> None:
    """⚠️ Le garde ne doit pas fermer l'usage NORMAL : un webhook public reste accepté."""
    r = await client.post("/api/v1/notifications/channels", headers=_h(admin), json={
        "channel_type": "webhook", "name": "Slack",
        "config": {"url": "https://hooks.slack.com/services/T000/B000/xxx"},
    })
    assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_webhook_update_refuses_internal_target(
    client: AsyncClient, db_session: AsyncSession, org, admin
) -> None:
    """🔑 La MISE À JOUR doit porter la même garde que la création : sinon on crée un canal
    public puis on le repointe vers l'intérieur en deux appels — le patron d'asymétrie
    déjà rencontré sur les cibles de programmes et de campagnes."""
    row = CmsNotificationChannel(
        id_org=org.id_org, name="Public", channel_type="webhook",
        config={"url": "https://example.com/hook"}, enabled=True)
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    r = await client.put(f"/api/v1/notifications/channels/{row.id_channel}",
                         headers=_h(admin),
                         json={"config": {"url": "http://127.0.0.1:8010/health"}})
    assert r.status_code == 400, r.text
    await db_session.refresh(row)
    assert row.config["url"] == "https://example.com/hook"


# ── Traçabilité ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_channel_mutations_are_audited(
    client: AsyncClient, db_session: AsyncSession, org, admin
) -> None:
    """Créer un canal e-mail, c'est décider OÙ PARTENT les alertes du réseau ; le rediriger
    en silence est exactement le geste qu'un journal doit rattraper."""
    r = await client.post("/api/v1/notifications/channels", headers=_h(admin), json={
        "channel_type": "email", "name": "Astreinte",
        "config": {"recipients": ["ops@retail.fr"]},
    })
    assert r.status_code == 201, r.text
    cid = r.json()["id_channel"]
    await client.put(f"/api/v1/notifications/channels/{cid}", headers=_h(admin),
                     json={"config": {"recipients": ["ailleurs@externe.com"]}})
    await client.delete(f"/api/v1/notifications/channels/{cid}", headers=_h(admin))
    n = await _audit_count(db_session, org, "notification_channel")
    assert n >= 3, f"{n} ligne(s) pour création + modification + suppression"


@pytest.mark.asyncio
async def test_rule_mutations_are_audited(
    client: AsyncClient, db_session: AsyncSession, org, admin
) -> None:
    """Désactiver une règle, c'est éteindre une alerte : le silence qui suit doit avoir
    une explication dans le journal."""
    ch = CmsNotificationChannel(
        id_org=org.id_org, name="Ops", channel_type="email",
        config={"recipients": ["ops@retail.fr"]}, enabled=True)
    db_session.add(ch)
    await db_session.commit()
    await db_session.refresh(ch)
    r = await client.post("/api/v1/notifications/rules", headers=_h(admin), json={
        "event_type": "player_offline", "id_channel": ch.id_channel,
    })
    assert r.status_code == 201, r.text
    rid = r.json()["id_rule"]
    await client.delete(f"/api/v1/notifications/rules/{rid}", headers=_h(admin))
    n = await _audit_count(db_session, org, "alert_rule")
    assert n >= 2, f"{n} ligne(s) pour création + suppression de règle"


# ── Cloisonnement (doit déjà tenir) ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_channel_of_another_org_is_404(
    client: AsyncClient, db_session: AsyncSession, admin
) -> None:
    other = CmsOrganization(org_name="Autre", org_slug=f"other-{uuid.uuid4().hex[:8]}")
    db_session.add(other)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=other.id_org))
    ch = CmsNotificationChannel(
        id_org=other.id_org, name="Chez le voisin", channel_type="email",
        config={"recipients": ["voisin@x.com"]}, enabled=True)
    db_session.add(ch)
    await db_session.commit()
    await db_session.refresh(ch)
    r = await client.put(f"/api/v1/notifications/channels/{ch.id_channel}",
                         headers=_h(admin), json={"enabled": False})
    assert r.status_code == 404, r.text
