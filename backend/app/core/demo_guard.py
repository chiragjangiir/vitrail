"""Mode démo (§II) — blocage serveur des écritures pour les comptes `is_demo`.

Un compte démo (marqué à la création par un admin) navigue partout en LECTURE comme un Org Admin
mais ne peut RIEN modifier. Ce middleware bloque toute requête MUTANTE (POST/PUT/PATCH/DELETE) d'un
porteur de token `is_demo`, SAUF la liste blanche : authentification (login/refresh/logout), langue
du profil (PATCH /users/me — `is_demo` y est strippé côté endpoint, pas d'évasion), et envoi de
feedback (POST /feedback…). La réponse porte le code machine **`demo_blocked`** → le front affiche un
toast localisé « compte démo, action impossible ». Le statut démo vit dans le JWT (claim `is_demo`),
posé au login/refresh → aucun accès DB par requête.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.core.security import decode_token

_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


def _demo_allows(method: str, path: str) -> bool:
    """Écritures tolérées pour un compte démo (liste blanche stricte).

    ⚠️ REFUS PAR DÉFAUT : un endpoint mutant NOUVEAU est bloqué d'office, sans rien à faire.
    Le risque n'est donc pas qu'une écriture s'échappe — c'est qu'un POST **en lecture seule**
    soit bloqué à tort et déclenche un toast « compte démo, action impossible » sur une action
    qui n'écrit rien.

    CRITÈRE pour entrer ici (et pas un autre) : l'appel doit être READ-ONLY **et** déclenché
    AUTOMATIQUEMENT par l'affichage d'un écran (un `queryFn`, pas un `mutationFn`). Un POST
    read-only derrière un clic explicite reste bloqué : le prospect voit alors un refus sur
    un geste qu'il a demandé, pas un refus surgi de nulle part en ouvrant un tiroir.

    `tests/test_demo_guard.py::test_no_unreviewed_readonly_post` force la relecture de ce
    choix à chaque nouvel endpoint au nom évocateur — la liste ci-dessous ne peut plus
    prendre du retard en silence (c'est ce qui était arrivé à `governance-scope` [27/07] et
    `storage-check` [06/08], tous deux armés automatiquement dans le tiroir de programme).
    """
    if path.startswith("/api/v1/auth/"):
        return True  # login / refresh / logout / revoke — nécessaire pour s'authentifier
    if method == "PATCH" and path == "/api/v1/users/me":
        return True  # profil self-service (langue/thème) ; is_demo strippé dans update_me
    if method == "POST" and path.startswith("/api/v1/feedback"):
        return True  # « Send Feedback » autorisé (retour prospect)
    if method == "POST" and path == "/api/v1/schedules/hdmi-check":
        return True  # check d'affectation HDMI : READ-ONLY (SELECT only) — sans ça, ouvrir le
        # drawer schedule en démo déclenchait un toast « compte démo » sur une action passive
    if method == "POST" and path == "/api/v1/campaigns/occupancy-check":
        return True  # projection d'occupation SOV (S2) : READ-ONLY — même cas que hdmi-check,
        # le drawer campagne la déclenche automatiquement à l'ouverture en édition
    if method == "POST" and path == "/api/v1/campaigns/import/dry-run":
        return True  # dry-run d'import JSON (S6) : READ-ONLY (rien n'est créé) — un prospect
        # démo peut tester le format d'ordre d'insertion ; l'import réel reste bloqué
    if method == "POST" and path == "/api/v1/portal/occupancy-check":
        return True  # dispo agrégée + devis du portail annonceur (C2) : READ-ONLY — le
        # formulaire de campagne la déclenche automatiquement ; la création reste bloquée
    if method == "POST" and path == "/api/v1/schedules/governance-scope":
        return True  # aperçu du périmètre résolu d'un programme gouverné : READ-ONLY, et
        # affiché EN PERMANENCE dans le tiroir (queryFn armé dès qu'un nœud est choisi)
    if method == "POST" and path == "/api/v1/players/storage-check":
        return True  # contrôle d'espace disque à l'affectation : READ-ONLY, armé
        # automatiquement dès que le tiroir a une playlist ET une cible
    return False


class DemoGuardMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.method in _MUTATING:
            auth = request.headers.get("authorization", "")
            if auth.startswith("Bearer "):
                claims = None
                try:
                    claims = decode_token(auth[7:])
                except Exception:  # noqa: BLE001 — token invalide/expiré → l'endpoint renverra 401
                    claims = None
                if (claims and claims.get("is_demo")
                        and not _demo_allows(request.method, request.url.path)):
                    return JSONResponse(status_code=403, content={"detail": "demo_blocked"})
        return await call_next(request)
