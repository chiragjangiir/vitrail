"""Alerte e-mail au modérateur d'un contenu gouverné (§XVIII R15/E, décision D8).

Quand un responsable local soumet une playlist gouvernée à modération, les MODÉRATEURS
(admins du plus proche nœud ancêtre, repli org-admins — cf. governance_access.
node_moderator_user_ids) sont prévenus par e-mail. Best-effort : un échec SMTP ne bloque
JAMAIS la soumission (l'endpoint capture l'erreur), même philosophie que approval_emails.

Réutilise le SMTP existant (services.email_delivery) — aucune infrastructure nouvelle.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.models.playlist import CmsPlaylist
from app.models.user import CmsUser
from app.services.email_delivery import send_email
from app.services.governance_access import node_moderator_user_ids

_SUBJECT = {
    "fr": "Modération — la playlist « {name} » attend votre validation",
    "en": "Moderation — playlist “{name}” awaits your approval",
}
_BODY = {
    "fr": ("Bonjour,\n\n{submitter} a soumis la playlist « {name} » à votre validation.\n"
           "Ouvrez la file d'approbation du CMS pour la relire et l'approuver.\n{portal}\n\n"
           "— Vitrail"),
    "en": ("Hello,\n\n{submitter} submitted the playlist “{name}” for your approval.\n"
           "Open the CMS approval queue to review and approve it.\n{portal}\n\n"
           "— Vitrail"),
}


async def notify_moderators_submitted(
    db: AsyncSession, pl: CmsPlaylist, submitter: CmsUser
) -> None:
    """Prévient par e-mail les modérateurs de la playlist soumise. Best-effort.

    Silencieux si le nœud n'a pas de modérateur joignable, si SMTP n'est pas configuré,
    ou en cas d'erreur d'envoi — la soumission reste valide dans tous les cas.
    """
    if pl.id_governance_node is None:
        return
    user_ids = await node_moderator_user_ids(db, pl.id_governance_node)
    # Ne pas s'auto-notifier (le soumetteur peut être admin d'un ancêtre par ailleurs).
    user_ids = [uid for uid in user_ids if uid != submitter.id_user]
    if not user_ids:
        return
    emails = [row[0] for row in (await db.execute(
        select(CmsUser.email).where(
            CmsUser.id_user.in_(user_ids),
            CmsUser.is_active.is_(True),
            CmsUser.email.is_not(None),
        )
    )).all() if row[0]]
    if not emails:
        return

    loc = (submitter.locale or "en")[:2]
    subj_t = _SUBJECT.get(loc, _SUBJECT["en"])
    body_t = _BODY.get(loc, _BODY["en"])
    who = submitter.full_name or submitter.email
    portal = (f"{settings.PUBLIC_WEB_URL.rstrip('/')}/approvals"
              if settings.PUBLIC_WEB_URL else "")
    try:
        await run_in_threadpool(
            send_email,
            to=emails,
            subject=subj_t.format(name=pl.playlist_name),
            body=body_t.format(name=pl.playlist_name, submitter=who, portal=portal),
        )
    except Exception:  # noqa: BLE001 — best-effort, ne bloque jamais la soumission
        return
