"""Génère la matrice « quel rôle peut faire quoi » à partir des DONNÉES RÉELLES.

    docker compose exec -T backend python scripts/gen_role_matrix.py            # markdown
    docker compose exec -T backend python scripts/gen_role_matrix.py --json     # brut

POURQUOI CE SCRIPT PLUTÔT QU'UN TABLEAU ÉCRIT À LA MAIN
Un tableau rédigé une fois dérive dès la migration suivante, et personne ne s'en
aperçoit : un rôle documenté « peut approuver » alors que l'endpoint a changé de
garde, c'est une promesse fausse faite au client. Ici la matrice est reconstruite
à la demande depuis la base et le code.

IL FAUT CROISER DEUX SOURCES, UNE SEULE MENT
  1. la BASE  → ce qu'un rôle DÉTIENT   (cms_role_permissions)
  2. le CODE  → ce qui est VÉRIFIÉ      (require_permission / require_admin_or_permission)

Une permission détenue mais vérifiée nulle part n'accorde RIEN. C'est exactement
le piège de l'audit des rôles du 2026-07-20 : 27 permissions décoratives, dont
tout `users:*` et `groups:*` — l'administration était gatée par le booléen
`require_org_admin`, si bien qu'un rôle custom portant `users:read` n'obtenait
rien. La matrice publiée DOIT montrer cet écart plutôt que de le masquer.
"""

import asyncio
import json
import pathlib
import re
import sys

from sqlalchemy import text

sys.path.insert(0, "/app")
from app.db.session import WorkerSessionLocal  # noqa: E402

ROOT = pathlib.Path("/app/app")
# Couvre les trois factories : `require_permission`, `require_admin_or_permission`
# (qui laisse en plus passer l'org-admin) et `require_any_permission`, qui accepte
# PLUSIEURS couples équivalents — d'où la seconde expression.
#
# ⚠️ Sans la seconde, la matrice publierait les 12 permissions de la séparation additive
# (feeds/url_display/tags/generation, migr 0114) comme « détenues mais vérifiées nulle
# part », c'est-à-dire comme décoratives — exactement le mensonge que ce script existe
# pour éviter.
PAT = re.compile(r'require(?:_admin_or)?_permission\(\s*"([a-z_]+)"\s*,\s*"([a-z_]+)"')
PAT_ANY = re.compile(r'\(\s*"([a-z_]+)"\s*,\s*"([a-z_]+)"\s*\)')

#: Modules spécifiés mais pas encore développés — leurs permissions ne protègent
#: rien AUJOURD'HUI sans être pour autant une erreur (cf. §XIV moteur SPF).
PLANNED_MODULES = {"spf"}


def enforced_pairs() -> set[str]:
    """Couples `module:operation` réellement vérifiés quelque part dans le code."""
    found: set[str] = set()
    for path in ROOT.rglob("*.py"):
        src = path.read_text(encoding="utf-8")
        # `require_any_permission(("feeds","edit"), ("media","edit"))` : on relève TOUS
        # les couples de l'appel, chacun ouvrant réellement la route.
        for call in re.findall(r"require_any_permission\(([^)]*\)[^)]*)\)", src):
            for module, operation in PAT_ANY.findall(call):
                found.add(f"{module}:{operation}")
        for module, operation in PAT.findall(src):
            found.add(f"{module}:{operation}")
    return found


async def collect() -> dict:
    enforced = enforced_pairs()
    async with WorkerSessionLocal() as db:
        roles = (
            await db.execute(
                text(
                    "SELECT id_role, role_key, label FROM cms_roles "
                    "WHERE is_system = true ORDER BY role_key"
                )
            )
        ).all()
        by_role = {}
        for id_role, role_key, label in roles:
            rows = (
                await db.execute(
                    text(
                        "SELECT p.module || ':' || p.operation FROM cms_permissions p "
                        "JOIN cms_role_permissions rp ON rp.id_permission = p.id_permission "
                        "WHERE rp.id_role = :r ORDER BY 1"
                    ),
                    {"r": id_role},
                )
            ).all()
            by_role[role_key] = {"label": label, "perms": [r[0] for r in rows]}
        catalog = [
            r[0]
            for r in (
                await db.execute(
                    text("SELECT module || ':' || operation FROM cms_permissions ORDER BY 1")
                )
            ).all()
        ]

    inert = sorted(set(catalog) - enforced)
    return {
        "roles": by_role,
        "catalog": catalog,
        "enforced": sorted(enforced),
        "inert": inert,
        "planned": sorted(p for p in inert if p.split(":")[0] in PLANNED_MODULES),
    }


def to_markdown(d: dict) -> str:
    modules = sorted({p.split(":")[0] for p in d["catalog"]})
    # L'org-admin et le super-admin portent tout : les lister colonne par colonne
    # n'apprend rien, on les traite en note.
    shown = [k for k in sorted(d["roles"]) if k not in ("CMS_ORG_ADMIN", "CMS_SUPER_ADMIN")]

    out = [
        "| Module | " + " | ".join(k.replace("CMS_", "") for k in shown) + " |",
        "|---|" + "---|" * len(shown),
    ]
    for module in modules:
        cells = []
        for role in shown:
            ops = sorted(
                p.split(":")[1]
                for p in d["roles"][role]["perms"]
                if p.startswith(module + ":") and p in d["enforced"]
            )
            cells.append(", ".join(ops) if ops else "—")
        if any(c != "—" for c in cells):
            out.append(f"| `{module}` | " + " | ".join(cells) + " |")
    return "\n".join(out)


async def main() -> None:
    data = await collect()
    if "--json" in sys.argv:
        print(json.dumps(data, ensure_ascii=False, indent=1))
        return
    print(to_markdown(data))
    print()
    print(f"<!-- catalogue: {len(data['catalog'])} · vérifiées: {len(data['enforced'])} "
          f"· sans effet: {len(data['inert'])} (dont {len(data['planned'])} planifiées) -->")


asyncio.run(main())
