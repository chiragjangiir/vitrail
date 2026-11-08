"""
Matrice IDOR automatisée (audit sécurité 2026-06-25).

Prouve l'isolation cross-tenant de façon SYSTÉMATIQUE plutôt qu'endpoint par endpoint :
provisionne 2 organisations jetables (A, B) + un admin chacune, crée un objet de chaque
type de ressource dans A ET dans B, puis rejoue — avec le token de A — les accès directs
aux objets de B (GET/PATCH/DELETE /{id}) et inversement. Toute réponse ≠ 404 sur un id
appartenant à l'autre tenant = fuite IDOR.

⚠️ N'a de sens que contre une instance où la RLS est ACTIVE (le backend se connecte en
`signflow_app`, non-superuser). En test pytest la RLS est inactive (session superuser) →
ce scan est un SCRIPT runtime, pas un test unitaire. Il se lance DANS le conteneur backend :

    docker compose exec backend python -m scripts.idor_scan

Non destructif sur les vraies données : il ne crée/supprime QUE ses 2 orgs jetables, qu'il
nettoie en fin de course. Les rejeux cross-tenant DOIVENT échouer (404) — donc ne modifient
rien s'ils se comportent correctement.
"""

import asyncio
import os
import sys

import httpx
from sqlalchemy import text

# Permet `python scripts/idor_scan.py` comme `python -m scripts.idor_scan`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.security import create_access_token  # noqa: E402
from app.db.session import WorkerSessionLocal  # noqa: E402

API = os.environ.get("IDOR_API_BASE", "http://localhost:8000/api/v1")

# Chaque ressource : comment la créer (POST), le champ id renvoyé, et les verbes à rejouer.
# `patch` = (méthode, corps minimal) ; la méthode diffère (PUT/PATCH) selon l'endpoint.
RESOURCES = [
    {"name": "player",
     "create": ("POST", "/players/", {"player_name": "idor", "player_os": "linux"}),
     "id_field": "id_player", "base": "/players", "edit": ("PUT", {"player_name": "x"})},
    {"name": "site", "create": ("POST", "/sites", {"site_name": "idor"}),
     "id_field": "id_site", "base": "/sites", "edit": ("PUT", {"site_name": "x"})},
    {"name": "playlist", "create": ("POST", "/playlists", {"playlist_name": "idor"}),
     "id_field": "id_playlist", "base": "/playlists", "edit": ("PUT", {"playlist_name": "x"})},
    {"name": "template", "create": ("POST", "/templates", {"template_name": "idor",
                                                           "layout": {"layout_type": "full"}}),
     "id_field": "id_template", "base": "/templates", "edit": ("PUT", {"template_name": "x"})},
    {"name": "audio_basket", "create": ("POST", "/audio-baskets",
                                        {"basket_name": "idor", "basket_type": "music"}),
     "id_field": "id_basket", "base": "/audio-baskets", "edit": ("PUT", {"basket_name": "x"})},
]


async def _provision_org(db, label: str) -> dict:
    """Crée une org jetable + son admin (CMS_ORG_ADMIN) ; renvoie {id_org, token}."""
    import uuid
    slug = f"idor-{label}-{uuid.uuid4().hex[:8]}"
    org_id = (await db.execute(text(
        "INSERT INTO cms_organizations (org_name, org_slug) VALUES (:n, :s) RETURNING id_org"
    ), {"n": f"IDOR {label}", "s": slug})).scalar_one()
    await db.execute(text("INSERT INTO cms_org_auth_settings (id_org) VALUES (:o)"), {"o": org_id})
    user_id = (await db.execute(text(
        "INSERT INTO cms_users (id_org, email, password_hash, is_active) "
        "VALUES (:o, :e, 'x', true) RETURNING id_user"
    ), {"o": org_id, "e": f"admin-{slug}@idor.test"})).scalar_one()
    role_id = (await db.execute(text(
        "INSERT INTO cms_roles (role_key, label, is_system) VALUES (:k, 'Org Admin', true) "
        "ON CONFLICT (role_key) DO UPDATE SET label = EXCLUDED.label RETURNING id_role"
    ), {"k": "CMS_ORG_ADMIN"})).scalar_one()
    await db.execute(text(
        "INSERT INTO cms_user_role_assignments (id_user, id_role) VALUES (:u, :r) "
        "ON CONFLICT DO NOTHING"
    ), {"u": user_id, "r": role_id})
    await db.commit()
    token = create_access_token(
        user_id, extra={"org": org_id, "roles": ["CMS_ORG_ADMIN"], "locale": "en"}
    )
    return {"id_org": org_id, "token": token}


async def _cleanup(db, org_ids: list[int]) -> None:
    """Supprime les 2 orgs jetables + leurs objets (ordre des FK)."""
    for tbl in ("cms_players", "cms_playlists", "cms_sites", "cms_templates", "cms_audio_baskets"):
        await db.execute(text(f"DELETE FROM {tbl} WHERE id_org = ANY(:ids)"), {"ids": org_ids})
    await db.execute(text(
        "DELETE FROM cms_user_role_assignments WHERE id_user IN "
        "(SELECT id_user FROM cms_users WHERE id_org = ANY(:ids))"
    ), {"ids": org_ids})
    p = {"ids": org_ids}
    await db.execute(text("DELETE FROM cms_users WHERE id_org = ANY(:ids)"), p)
    await db.execute(text("DELETE FROM cms_org_auth_settings WHERE id_org = ANY(:ids)"), p)
    await db.execute(text("DELETE FROM cms_organizations WHERE id_org = ANY(:ids)"), p)
    await db.commit()


async def _create_objects(client: httpx.AsyncClient, token: str) -> dict:
    """Crée un objet de chaque ressource pour un tenant ; renvoie {name: id} (ou None si échec)."""
    hdr = {"Authorization": f"Bearer {token}"}
    ids: dict = {}
    for r in RESOURCES:
        method, path, body = r["create"]
        resp = await client.request(method, f"{API}{path}", json=body, headers=hdr)
        ids[r["name"]] = resp.json().get(r["id_field"]) if resp.status_code in (200, 201) else None
        if ids[r["name"]] is None:
            print(f"  ⚠️  création {r['name']} échouée ({resp.status_code}) — ressource ignorée")
    return ids


async def _rejeu(client: httpx.AsyncClient, attacker_token: str, victim_ids: dict) -> list:
    """Rejoue GET/edit/DELETE sur les objets de la VICTIME avec le token de l'ATTAQUANT.
    Chaque tentative DOIT renvoyer 404 (cross-tenant) — sinon fuite IDOR."""
    hdr = {"Authorization": f"Bearer {attacker_token}"}
    findings = []
    for r in RESOURCES:
        vid = victim_ids.get(r["name"])
        if vid is None:
            continue
        url = f"{API}{r['base']}/{vid}"
        edit_method, edit_body = r["edit"]
        attempts = [
            ("GET", lambda: client.get(url, headers=hdr)),
            (edit_method,
             lambda: client.request(edit_method, url, json=edit_body, headers=hdr)),
            ("DELETE", lambda: client.delete(url, headers=hdr)),
        ]
        for verb, call in attempts:
            resp = await call()
            ok = resp.status_code == 404           # cross-tenant → doit être 404
            findings.append((r["name"], verb, resp.status_code, ok))
    return findings


async def main() -> int:
    async with WorkerSessionLocal() as db:
        a = await _provision_org(db, "A")
        b = await _provision_org(db, "B")
        org_ids = [a["id_org"], b["id_org"]]
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                print(f"Orgs jetables : A={a['id_org']} B={b['id_org']}")
                print("Création des objets dans A et B…")
                ids_a = await _create_objects(client, a["token"])
                ids_b = await _create_objects(client, b["token"])
                print("\nRejeu cross-tenant (A→B puis B→A) — attendu 404 partout :\n")
                findings = (await _rejeu(client, a["token"], ids_b)
                            + await _rejeu(client, b["token"], ids_a))
        finally:
            await _cleanup(db, org_ids)

    leaks = [f for f in findings if not f[3]]
    print(f"{'RESSOURCE':<16}{'VERBE':<8}{'STATUT':<8}{'RÉSULTAT'}")
    print("-" * 44)
    for name, verb, code, ok in findings:
        print(f"{name:<16}{verb:<8}{code:<8}{'✅ 404' if ok else '🔴 FUITE'}")
    print("-" * 44)
    if leaks:
        print(f"\n🔴 {len(leaks)} FUITE(S) IDOR détectée(s) sur {len(findings)} tentatives.")
        return 1
    print(f"\n✅ Aucune fuite : {len(findings)} accès cross-tenant tous bloqués (404).")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
