"""Email à l'annonceur lors d'une décision d'approbation (retour Ed #9, 2026-07-12).

Réutilise le SMTP des rapports planifiés (§24.3, services.email_delivery) — aucune
infrastructure nouvelle. Best-effort : un échec d'envoi ne bloque JAMAIS la décision
(l'endpoint capture l'erreur et la renvoie au valideur à titre informatif).

Destinataires = comptes portail ACTIFS de l'annonceur de la campagne
(cms_users.id_advertiser, hors comptes démo), un envoi groupé par langue de profil.
Le lien portail n'apparaît que si PUBLIC_WEB_URL est configurée (URL publique du CMS,
ex. https://cms.example.com).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.models.approval import CmsApprovalRequest
from app.models.audit_log import CmsAuditLog
from app.models.campaign import CmsAdvertiser, CmsCampaign
from app.models.organization import CmsOrganization
from app.models.user import CmsUser
from app.services.email_delivery import send_email

# Actions qui déclenchent un email (la case UI n'existe que sur celles-ci).
DECISION_ACTIONS = ("approve", "reject", "request_changes")

# Gabarits par locale produit (fallback en). Le libellé de décision est neutre
# (« examinée : … ») pour couvrir les 3 actions avec la même phrase.
_TEMPLATES: dict[str, dict[str, str]] = {
    "en": {
        "approve": "approved",
        "reject": "rejected",
        "request_changes": "changes requested",
        "subject": "{org} — Your campaign “{campaign}”: {decision}",
        "greeting": "Hello,",
        "line": "Your campaign “{campaign}” ({advertiser}) has been reviewed: {decision}.",
        "period": "Period: {starts} to {ends}",
        "comment": "Reviewer comment:",
        "portal": "Follow your campaign on your portal: {url}",
        "signature": "— {org}",
    },
    "fr": {
        "approve": "approuvée",
        "reject": "rejetée",
        "request_changes": "modifications demandées",
        "subject": "{org} — Votre campagne « {campaign} » : {decision}",
        "greeting": "Bonjour,",
        "line": "Votre campagne « {campaign} » ({advertiser}) a été examinée : {decision}.",
        "period": "Période : du {starts} au {ends}",
        "comment": "Commentaire du valideur :",
        "portal": "Suivez votre campagne sur votre portail : {url}",
        "signature": "— {org}",
    },
    "es": {
        "approve": "aprobada",
        "reject": "rechazada",
        "request_changes": "cambios solicitados",
        "subject": "{org} — Su campaña “{campaign}”: {decision}",
        "greeting": "Hola,",
        "line": "Su campaña “{campaign}” ({advertiser}) ha sido revisada: {decision}.",
        "period": "Período: del {starts} al {ends}",
        "comment": "Comentario del revisor:",
        "portal": "Siga su campaña en su portal: {url}",
        "signature": "— {org}",
    },
    "pt": {
        "approve": "aprovada",
        "reject": "rejeitada",
        "request_changes": "alterações solicitadas",
        "subject": "{org} — A sua campanha “{campaign}”: {decision}",
        "greeting": "Olá,",
        "line": "A sua campanha “{campaign}” ({advertiser}) foi analisada: {decision}.",
        "period": "Período: de {starts} a {ends}",
        "comment": "Comentário do revisor:",
        "portal": "Acompanhe a sua campanha no seu portal: {url}",
        "signature": "— {org}",
    },
    "de": {
        "approve": "freigegeben",
        "reject": "abgelehnt",
        "request_changes": "Änderungen angefordert",
        "subject": "{org} — Ihre Kampagne „{campaign}“: {decision}",
        "greeting": "Guten Tag,",
        "line": "Ihre Kampagne „{campaign}“ ({advertiser}) wurde geprüft: {decision}.",
        "period": "Zeitraum: {starts} bis {ends}",
        "comment": "Kommentar des Prüfers:",
        "portal": "Verfolgen Sie Ihre Kampagne in Ihrem Portal: {url}",
        "signature": "— {org}",
    },
}


async def send_decision_email(
    db: AsyncSession, req: CmsApprovalRequest, user: CmsUser,
    action: str, comment: str | None,
) -> int:
    """Envoie le récap de décision aux comptes portail de l'annonceur de la campagne.

    → nombre de destinataires (0 si ressource non-campagne / aucun compte portail).
    Lève EmailError si le SMTP échoue — l'appelant traite en best-effort. Ajoute une
    trace `approval_email` dans l'audit log (sans commit — l'appelant commit)."""
    if req.resource_type != "campaign" or action not in DECISION_ACTIONS:
        return 0
    camp = (await db.execute(
        select(CmsCampaign).where(
            CmsCampaign.id_campaign == req.resource_id,
            CmsCampaign.id_org == req.id_org,
        )
    )).scalar_one_or_none()
    if camp is None or camp.id_advertiser is None:
        return 0
    rows = (await db.execute(
        select(CmsUser.email, CmsUser.locale).where(
            CmsUser.id_org == req.id_org,
            CmsUser.id_advertiser == camp.id_advertiser,
            CmsUser.is_active == True,  # noqa: E712
            CmsUser.is_demo == False,  # noqa: E712
        )
    )).all()
    if not rows:
        return 0

    adv_name = (await db.execute(
        select(CmsAdvertiser.advertiser_name).where(
            CmsAdvertiser.id_advertiser == camp.id_advertiser)
    )).scalar_one_or_none() or ""
    org_name = (await db.execute(
        select(CmsOrganization.org_name).where(CmsOrganization.id_org == req.id_org)
    )).scalar_one_or_none() or "Vitrail"

    by_locale: dict[str, list[str]] = {}
    for email, locale in rows:
        key = locale if locale in _TEMPLATES else "en"
        by_locale.setdefault(key, []).append(email)

    portal_url = (f"{settings.PUBLIC_WEB_URL.rstrip('/')}/portal"
                  if settings.PUBLIC_WEB_URL else None)
    for locale, emails in by_locale.items():
        tpl = _TEMPLATES[locale]
        decision = tpl[action]
        subject = tpl["subject"].format(
            org=org_name, campaign=camp.campaign_name, decision=decision)
        lines = [
            tpl["greeting"],
            "",
            tpl["line"].format(campaign=camp.campaign_name,
                               advertiser=adv_name, decision=decision),
            tpl["period"].format(starts=camp.starts_on.isoformat(),
                                 ends=camp.ends_on.isoformat()),
        ]
        if (comment or "").strip():
            lines += ["", tpl["comment"], (comment or "").strip()]
        if portal_url:
            lines += ["", tpl["portal"].format(url=portal_url)]
        lines += ["", tpl["signature"].format(org=org_name)]
        # smtplib = bloquant → threadpool (même approche que webhook_post §XXII)
        await run_in_threadpool(
            send_email, to=emails, subject=subject, body="\n".join(lines))

    recipients = sum(len(v) for v in by_locale.values())
    db.add(CmsAuditLog(
        id_org=req.id_org, id_user=user.id_user, action="approval_email",
        resource_type=req.resource_type, resource_id=str(req.resource_id),
        detail={"id_request": req.id_request, "decision": action,
                "recipients": recipients},
    ))
    return recipients
