"""Signature des webhooks de notification (P1.7, 2026-08-05).

CE QUE ÇA RÉPARE. Un canal webhook postait un JSON nu : rien ne permettait au
destinataire de savoir que l'appel venait bien de nous. Quiconque connaît (ou devine)
l'URL du crochet d'un client pouvait donc lui fabriquer de fausses alertes — « écran
hors ligne », « campagne sous-servie » — et déclencher chez lui les automatismes
branchés dessus. Une URL n'est pas un secret : elle voyage dans des journaux, des
tickets, des copies d'écran.

CE QUI EST SIGNÉ, ET POURQUOI PAS SEULEMENT LE CORPS. On signe
`f"{horodatage}.{corps}"`, pas le corps seul. Signer le corps seul rend chaque appel
**rejouable à vie** : il suffit de capturer une notification une fois pour pouvoir la
renvoyer indéfiniment, avec une signature parfaitement valable. L'horodatage entre dans
l'empreinte, donc un rejeu au-delà de la tolérance se détecte — et il ne peut pas être
modifié sans invalider la signature.

Le corps signé est le corps **réellement envoyé**, octet pour octet : l'appelant
sérialise une fois et transmet les mêmes octets à la signature et à `httpx`. Signer une
re-sérialisation (avec un espacement ou un ordre de clés différent) produirait des
signatures que le destinataire ne pourrait jamais reproduire.

VÉRIFICATION CÔTÉ INTÉGRATEUR — à publier telle quelle dans la documentation :

    import hmac, hashlib, time

    def signflow_webhook_is_authentic(secret, headers, raw_body, tolerance=300):
        ts  = headers.get("X-SignFlow-Timestamp", "")
        sig = headers.get("X-SignFlow-Signature", "")
        if not ts.isdigit() or abs(time.time() - int(ts)) > tolerance:
            return False                      # trop vieux (ou daté du futur) = rejeu
        expected = "sha256=" + hmac.new(
            secret.encode(), f"{ts}.".encode() + raw_body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, sig)   # jamais `==`

⚠️ Deux pièges pour qui implémente la vérification : comparer avec `==` rend l'égalité
mesurable au temps de calcul (on retrouve la signature octet par octet) — d'où
`compare_digest` ; et il faut signer le corps **brut reçu**, pas le JSON re-sérialisé
après décodage.
"""

from __future__ import annotations

import hmac
import secrets
import time
from hashlib import sha256

HEADER_SIGNATURE = "X-SignFlow-Signature"
HEADER_TIMESTAMP = "X-SignFlow-Timestamp"
HEADER_EVENT = "X-SignFlow-Event"
HEADER_ATTEMPT = "X-SignFlow-Attempt"

# Fenêtre d'acceptation conseillée au destinataire. Assez large pour absorber une horloge
# mal réglée et nos réessais des premières minutes, assez étroite pour qu'un enregistrement
# capturé ne serve pas éternellement.
DEFAULT_TOLERANCE_S = 300

SECRET_PREFIX = "whsec_"


def new_secret() -> str:
    """Secret d'un canal webhook. Préfixé pour être reconnaissable dans un journal ou une
    capture d'écran — un secret qu'on identifie du premier coup d'œil se révoque vite."""
    return SECRET_PREFIX + secrets.token_urlsafe(32)


def sign(secret: str, timestamp: int, body: bytes) -> str:
    """Signature d'un envoi. `body` = les octets EXACTS transmis sur le réseau."""
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, sha256)
    return "sha256=" + mac.hexdigest()


def headers_for(secret: str, body: bytes, event_type: str, attempt: int = 1,
                timestamp: int | None = None) -> dict[str, str]:
    """En-têtes d'un envoi signé. Sans secret, on n'invente rien : les canaux créés avant
    P1.7 continuent de fonctionner sans signature plutôt que de cesser d'émettre (leur
    destinataire n'attend de toute façon aucune signature)."""
    base = {
        "Content-Type": "application/json",
        HEADER_EVENT: event_type,
        HEADER_ATTEMPT: str(attempt),
    }
    if not secret:
        return base
    ts = int(time.time()) if timestamp is None else timestamp
    base[HEADER_TIMESTAMP] = str(ts)
    base[HEADER_SIGNATURE] = sign(secret, ts, body)
    return base


def verify(secret: str, headers: dict, body: bytes,
           tolerance_s: int = DEFAULT_TOLERANCE_S, now: float | None = None) -> bool:
    """Implémentation de référence de la vérification — celle que nous publions.

    Elle vit ici plutôt que dans la documentation seule pour une raison précise : les
    tests l'exercent contre ce que produit `headers_for`. Un extrait de documentation
    qu'aucun test ne traverse finit toujours par décrire une version antérieure du
    format.
    """
    ts_raw = headers.get(HEADER_TIMESTAMP) or headers.get(HEADER_TIMESTAMP.lower()) or ""
    sig = headers.get(HEADER_SIGNATURE) or headers.get(HEADER_SIGNATURE.lower()) or ""
    if not ts_raw.isdigit() or not sig:
        return False
    current = time.time() if now is None else now
    if abs(current - int(ts_raw)) > tolerance_s:
        return False
    return hmac.compare_digest(sign(secret, int(ts_raw), body), sig)
