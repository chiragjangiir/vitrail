"""Retours utilisateurs (feedback) + triage IA (§ retours UI).

Couvre : soumission (auto-contexte, sévérité bug-only), liste/filtre/maj/suppression super-admin,
parsing du triage IA. Le triage LLM est mocké (pas de dépendance LiteLLM en test).
"""


from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.security import create_access_token, hash_password
from app.models.feedback import CmsFeedback
from app.models.organization import CmsOrganization
from app.models.role import CmsRole, CmsUserRoleAssignment
from app.models.user import CmsUser

_SEQ = [0]


def _uid() -> int:
    _SEQ[0] += 1
    return _SEQ[0]


async def _org(db) -> CmsOrganization:
    o = CmsOrganization(org_name=f"FbOrg{_uid()}", org_slug=f"fb-{_uid()}")
    db.add(o)
    await db.flush()
    return o


async def _user(db, org, roles=None) -> CmsUser:
    u = CmsUser(id_org=org.id_org, email=f"fb-{_uid()}@t.com",
                password_hash=hash_password("Password1!"), is_active=True)
    db.add(u)
    await db.flush()
    for rk in roles or []:
        await db.execute(
            pg_insert(CmsRole).values(role_key=rk, label=rk, is_system=True)
            .on_conflict_do_nothing(constraint="uq_cms_roles_role_key")
        )
        await db.flush()
        role = (await db.execute(select(CmsRole).where(CmsRole.role_key == rk))).scalar_one()
        db.add(CmsUserRoleAssignment(id_user=u.id_user, id_role=role.id_role))
    await db.flush()
    return u


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── Soumission ───────────────────────────────────────────────────────────────────

async def test_submit_feedback_captures_context(client, db_session, monkeypatch):
    # Neutralise l'enqueue du triage (pas de broker dépendance en test).
    from app.workers import feedback_worker
    monkeypatch.setattr(feedback_worker.triage_feedback, "delay", lambda *a, **k: None)

    org = await _org(db_session)
    user = await _user(db_session, org)
    await db_session.commit()
    token = create_access_token(user.id_user, extra={"org": org.id_org, "roles": []})

    resp = await client.post("/api/v1/feedback", headers=_h(token), json={
        "feedback_type": "bug",
        "description": "La playlist ne se sauvegarde pas.",
        "page_url": "https://app/x", "route": "/playlists/1",
        "user_agent": "UA/1.0", "app_version": "0.1.0",
        "console_errors": ["TypeError: x is undefined"],
        "severity": 3,
    })
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["feedback_type"] == "bug" and body["severity"] == 3
    assert body["status"] == "new" and body["route"] == "/playlists/1"
    assert body["console_errors"] == ["TypeError: x is undefined"]

    # Sévérité ignorée si ce n'est pas un bug.
    resp2 = await client.post("/api/v1/feedback", headers=_h(token), json={
        "feedback_type": "suggestion", "description": "Ajouter un mode sombre.", "severity": 2,
    })
    assert resp2.status_code == 201
    assert resp2.json()["severity"] is None


async def test_submit_feedback_filters_foreign_screenshot_keys(client, db_session, monkeypatch):
    """create_feedback ne garde que les captures préfixées par l'org (anti-référence
    d'une clé MinIO arbitraire d'une autre org / d'un autre média)."""
    from app.workers import feedback_worker
    monkeypatch.setattr(feedback_worker.triage_feedback, "delay", lambda *a, **k: None)

    org = await _org(db_session)
    user = await _user(db_session, org)
    await db_session.commit()
    token = create_access_token(user.id_user, extra={"org": org.id_org, "roles": []})

    mine = f"feedback/{org.id_org}/abc.png"
    resp = await client.post("/api/v1/feedback", headers=_h(token), json={
        "feedback_type": "bug", "description": "Capture jointe.",
        "screenshot_keys": [mine, "feedback/999999/evil.png", "12/some-media.mp4"],
    })
    assert resp.status_code == 201, resp.text
    assert resp.json()["screenshot_keys"] == [mine]


async def test_upload_screenshot_rejects_non_image(client, db_session):
    org = await _org(db_session)
    user = await _user(db_session, org)
    await db_session.commit()
    token = create_access_token(user.id_user, extra={"org": org.id_org, "roles": []})
    resp = await client.post(
        "/api/v1/feedback/screenshot", headers=_h(token),
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert resp.status_code == 400, resp.text


# ── Tri super-admin ────────────────────────────────────────────────────────────────

async def test_admin_list_update_delete(client, db_session, monkeypatch):
    org = await _org(db_session)
    user = await _user(db_session, org)
    su = await _user(db_session, org, roles=["CMS_SUPER_ADMIN"])
    fb = CmsFeedback(id_org=org.id_org, id_user=user.id_user, feedback_type="ux",
                     description="Bouton peu visible.")
    db_session.add(fb)
    await db_session.flush()
    await db_session.commit()
    su_token = create_access_token(
        su.id_user, extra={"org": org.id_org, "roles": ["CMS_SUPER_ADMIN"]}
    )

    listing = await client.get("/api/v1/admin/feedback", headers=_h(su_token))
    assert listing.status_code == 200, listing.text
    rows = {r["id_feedback"]: r for r in listing.json()}
    assert fb.id_feedback in rows
    assert rows[fb.id_feedback]["org_name"] == org.org_name
    assert rows[fb.id_feedback]["author_email"] == user.email

    # filtre par statut
    none = await client.get("/api/v1/admin/feedback?status_filter=done", headers=_h(su_token))
    assert all(r["id_feedback"] != fb.id_feedback for r in none.json())

    upd = await client.patch(f"/api/v1/admin/feedback/{fb.id_feedback}", headers=_h(su_token),
                             json={"status": "planned", "admin_note": "v2"})
    assert upd.status_code == 200 and upd.json()["status"] == "planned"

    dele = await client.delete(f"/api/v1/admin/feedback/{fb.id_feedback}", headers=_h(su_token))
    assert dele.status_code == 204
    gone = (await db_session.execute(
        select(CmsFeedback).where(CmsFeedback.id_feedback == fb.id_feedback))).scalar_one_or_none()
    assert gone is None


async def test_admin_requires_super_admin(client, db_session):
    org = await _org(db_session)
    user = await _user(db_session, org)
    await db_session.commit()
    token = create_access_token(user.id_user, extra={"org": org.id_org, "roles": []})
    resp = await client.get("/api/v1/admin/feedback", headers=_h(token))
    assert resp.status_code == 403


# ── Triage IA (parsing) ─────────────────────────────────────────────────────────────

def test_triage_parse_json_with_fences():
    from app.services.feedback_ai import _parse
    p = _parse('```json\n{"category":"bug","severity":3,"summary":"x"}\n```')
    assert p == {"category": "bug", "severity": 3, "summary": "x"}
    assert _parse("pas de json ici") is None
