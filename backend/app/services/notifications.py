"""Dispatch d'alertes (§XXII) — canaux **webhook** (POST JSON) et **EMAIL** (SMTP
`email_delivery`, config = {"recipients": [...]}, ajouté 2026-07-12), journalisés.

Deux entrées selon le contexte : `dispatch_sync` (workers Celery, connexion psycopg2 BYPASSRLS →
filtre `id_org` explicite — ⚠️ SMTP_* doit être déclaré dans l'env du service celery-worker) et
`dispatch_async` (endpoints). Le message est construit à partir de `(event_type, ctx)` par
`build_message` ; la livraison par type de canal est factorisée dans `deliver_to_channel`.
Chaque tentative est tracée dans `cms_notification_log` (status sent/failed).
"""

from __future__ import annotations

import json

import httpx

from app.services.webhook_signature import headers_for

# Types d'événements alertables (whitelist ; l'UI ne propose que ceux-ci).
EVENT_TYPES: dict[str, str] = {
    "player_offline": "Player hors ligne (critique)",
    "player_storage_full": "Player à court de stockage",
    "deployment_failed": "Déploiement OTA en échec",
    "feed_error": "Feed en erreur",
    # Retail media §2.8 (campaign_worker) — cycle de vie + sous-diffusion des campagnes.
    "campaign_started": "Campagne démarrée (retail media)",
    "campaign_ended": "Campagne terminée (retail media)",
    "campaign_underserved": "Campagne sous-servie (SOV servi < vendu)",
    # Approval Workflow §XXI (endpoints /approvals) — cycle de validation.
    "approval_requested": "Demande d'approbation soumise",
    "approval_approved": "Demande d'approbation approuvée",
    "approval_rejected": "Demande d'approbation rejetée",
    "approval_changes_requested": "Modifications demandées (approbation)",
    "test": "Test",
}


def build_message(event_type: str, ctx: dict) -> tuple[str, str]:
    """(pur) → (subject, body) lisible pour l'alerte."""
    ctx = ctx or {}
    if event_type == "player_offline":
        return (
            f"⚠️ Player hors ligne : {ctx.get('player_name', '?')}",
            f"Le player « {ctx.get('player_name', '?')} » (#{ctx.get('id_player', '?')}) est hors "
            f"ligne depuis {ctx.get('offline_min', '?')} min.",
        )
    if event_type == "player_storage_full":
        # Le message doit dire ce qu'il FAUT FAIRE : un « disque plein » sans conduite à tenir
        # laisse l'exploitant chercher. Le contenu déjà en cache continue de diffuser — c'est
        # la playlist qui ne pourra pas être complétée.
        blocked = ctx.get("blocked_count")
        detail = (f" {blocked} contenu(s) n'ont pas pu être mis en cache."
                  if blocked else "")
        # Les surfaces navigateur (ChromeOS, extension, BrightSign) ne remontent AUCUN
        # pourcentage de disque : on ne fabrique pas « None % », on décrit la situation.
        pct = ctx.get("disk_usage")
        occupe = (f"occupe {pct} % de son stockage"
                  if pct is not None else "n'a plus de place pour de nouveaux contenus")
        return (
            f"🗄️ Stockage saturé : {ctx.get('player_name', '?')}",
            f"Le player « {ctx.get('player_name', '?')} » (#{ctx.get('id_player', '?')}) "
            f"{occupe}.{detail} Il continue de diffuser ce qu'il a déjà, mais ne peut plus "
            f"télécharger. Retirez-lui du contenu ou affectez-lui une playlist plus légère.",
        )
    if event_type == "deployment_failed":
        return (
            "❌ Déploiement OTA en échec",
            f"Le déploiement #{ctx.get('id_deployment', '?')} a échoué sur "
            f"{ctx.get('failed_count', '?')} player(s).",
        )
    if event_type == "feed_error":
        return (
            f"⚠️ Feed en erreur : {ctx.get('feed_name', '?')}",
            f"Le feed « {ctx.get('feed_name', '?')} » (#{ctx.get('id_feed', '?')}) est en erreur : "
            f"{ctx.get('error', '?')}",
        )
    if event_type == "campaign_started":
        return (
            f"📣 Campagne démarrée : {ctx.get('campaign_name', '?')}",
            f"La campagne « {ctx.get('campaign_name', '?')} » de l'annonceur "
            f"{ctx.get('advertiser_name', '?')} est en diffusion "
            f"(SOV {ctx.get('sov_percent', '?')} %, du {ctx.get('starts_on', '?')} "
            f"au {ctx.get('ends_on', '?')}).",
        )
    if event_type == "campaign_ended":
        extra = ""
        if ctx.get("plays") is not None:
            sov = ctx.get("sov_served_pct")
            extra = (
                f" Bilan : {ctx.get('plays')} passages "
                f"(dont {ctx.get('signed_plays', 0)} signés)"
                + (f", SOV servi {sov} %" if sov is not None else "") + "."
            )
        return (
            f"🏁 Campagne terminée : {ctx.get('campaign_name', '?')}",
            f"La campagne « {ctx.get('campaign_name', '?')} » de l'annonceur "
            f"{ctx.get('advertiser_name', '?')} est terminée "
            f"({ctx.get('starts_on', '?')} → {ctx.get('ends_on', '?')}).{extra}",
        )
    if event_type in ("approval_requested", "approval_approved", "approval_rejected",
                      "approval_changes_requested"):
        head = {
            "approval_requested": "📝 Demande d'approbation",
            "approval_approved": "✅ Approbation accordée",
            "approval_rejected": "❌ Approbation rejetée",
            "approval_changes_requested": "✏️ Modifications demandées",
        }[event_type]
        verb = {
            "approval_requested": "a été soumis pour approbation par",
            "approval_approved": "a été approuvé par",
            "approval_rejected": "a été rejeté par",
            "approval_changes_requested": "nécessite des modifications selon",
        }[event_type]
        body = (
            f"« {ctx.get('resource_name', '?')} » ({ctx.get('resource_type', '?')} "
            f"#{ctx.get('resource_id', '?')}) {verb} {ctx.get('actor_name', '?')}."
        )
        if ctx.get("comment"):
            body += f" Commentaire : {ctx['comment']}"
        if ctx.get("due_date"):
            body += f" Échéance : {ctx['due_date']}."
        return (f"{head} : {ctx.get('resource_name', '?')}", body)
    if event_type == "campaign_underserved":
        return (
            f"⚠️ Campagne sous-servie : {ctx.get('campaign_name', '?')}",
            f"La campagne « {ctx.get('campaign_name', '?')} » de l'annonceur "
            f"{ctx.get('advertiser_name', '?')} n'atteint que "
            f"{ctx.get('sov_served_pct', '?')} % de SOV servi pour "
            f"{ctx.get('sov_percent', '?')} % vendus (seuil : {ctx.get('threshold_pct', '?')} % "
            f"du vendu), sur la période du {ctx.get('period_from', '?')} "
            f"au {ctx.get('period_until', '?')}.",
        )
    return ("🔔 Alerte Vitrail (test)", "Ceci est un message de test Vitrail.")


# Codes qui méritent un réessai : le destinataire est en panne, saturé ou lent. ⛔ Un 4xx
# (hors 408/429) ne deviendra jamais un 2xx en le renvoyant — c'est l'URL, l'authentification
# ou le format qui ne va pas. Réessayer ces cas-là, c'est marteler un serveur qui a déjà
# répondu clairement, et masquer une erreur de configuration derrière quatre échecs de plus.
_RETRYABLE_STATUS = {408, 429}


def _is_retryable(status_code: int | None) -> bool:
    if status_code is None:
        return True  # pas de réponse du tout : réseau, DNS, délai dépassé
    return status_code >= 500 or status_code in _RETRYABLE_STATUS


def webhook_post(
    url: str, payload: dict, secret: str = "", event_type: str = "", attempt: int = 1
) -> tuple[bool, str, bool]:
    """POST JSON SIGNÉ, synchrone (worker / threadpool). → (ok, détail, réessayable).

    🔑 Le corps est sérialisé UNE FOIS et les mêmes octets partent à la signature et à
    `httpx` (`content=`, jamais `json=`) : signer une re-sérialisation produirait des
    signatures que le destinataire ne pourrait pas reproduire.
    """
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    headers = headers_for(secret, raw, event_type or payload.get("event", ""), attempt)
    try:
        r = httpx.post(url, content=raw, headers=headers, timeout=8.0)
    except Exception as exc:  # noqa: BLE001 — best-effort, l'échec est tracé
        return False, str(exc)[:200], True
    ok = 200 <= r.status_code < 300
    return ok, f"HTTP {r.status_code}", (not ok and _is_retryable(r.status_code))


# Réessai des webhooks — 4 tentatives différées après le premier essai synchrone, soit
# ~15 min de fenêtre (1, 3, 5 puis 6 min). Ni plus long ni plus dense : une alerte de
# signalétique perd sa valeur passé le quart d'heure, et marteler un serveur déjà en
# difficulté ne fait qu'aggraver sa panne.
RETRY_BACKOFF_S = (60, 180, 300, 360)


def _queue_retry(url: str, payload: dict, secret: str, event_type: str,
                 id_org: int | None, id_rule: int | None) -> None:
    """Confie le renvoi à la file `notifications`. Best-effort et silencieux par
    construction : si le courtier est injoignable, on a déjà tracé l'échec du premier
    essai — une alerte ne doit jamais casser l'action qui l'a déclenchée, et un réessai
    qui échoue à s'inscrire ne doit pas devenir une seconde panne.

    ⛔ Sans `id_org` on ne fait rien : la ligne de journal du réessai ne pourrait pas être
    rattachée à une organisation, et une trace hors tenant n'est lisible par personne.
    """
    if id_org is None:
        return
    try:
        from app.workers.celery_app import celery_app

        celery_app.send_task(
            "app.workers.notification_worker.retry_webhook",
            args=[url, payload, secret, event_type, id_org, id_rule, 2],
            countdown=RETRY_BACKOFF_S[0],
        )
    except Exception:  # noqa: BLE001 — cf. docstring
        pass


def email_send(recipients: list[str], subject: str, body: str) -> tuple[bool, str]:
    """Envoi SMTP synchrone (worker / threadpool) via email_delivery. → (ok, détail)."""
    from app.services.email_delivery import EmailError, send_email

    try:
        send_email(to=recipients, subject=f"[Vitrail] {subject}", body=body)
        return True, f"email → {len(recipients)} destinataire(s)"
    except EmailError as exc:
        return False, str(exc)[:200]


def deliver_to_channel(
    channel_type: str, config: dict | None, event_type: str,
    subject: str, body: str, ctx: dict,
    id_org: int | None = None, id_rule: int | None = None,
) -> tuple[bool, str]:
    """Livraison SYNCHRONE selon le type de canal (webhook | email). → (ok, détail)."""
    config = config or {}
    if channel_type == "webhook":
        url = config.get("url")
        if not url:
            return False, "url manquante"
        payload = _payload(event_type, subject, body, ctx)
        ok, detail, retryable = webhook_post(
            url, payload, secret=config.get("secret", ""), event_type=event_type)
        if not ok and retryable:
            # Le destinataire est injoignable ou en panne : on repasse la main à la file
            # `notifications` plutôt que de perdre l'alerte. ⚠️ Le premier essai reste
            # SYNCHRONE, volontairement — c'est lui qui alimente le journal et qui rend
            # le bouton « Tester » utile ; un envoi entièrement différé répondrait
            # « en file d'attente » à quelqu'un qui veut savoir si son URL marche.
            _queue_retry(url, payload, config.get("secret", ""), event_type, id_org, id_rule)
        return ok, detail
    if channel_type == "email":
        recipients = [r.strip() for r in config.get("recipients", []) if r and r.strip()]
        if not recipients:
            return False, "destinataires manquants"
        return email_send(recipients, subject, body)
    return False, f"type de canal non supporté : {channel_type}"


def _payload(event_type: str, subject: str, body: str, ctx: dict) -> dict:
    return {"event": event_type, "subject": subject, "body": body, "context": ctx or {},
            "source": "signflow"}


async def dispatch_async(db, id_org: int, event_type: str, ctx: dict) -> int:
    """(endpoints FastAPI) Miroir de `dispatch_sync` sur la session SQLAlchemy async (RLS déjà
    posée). Appelé APRÈS le commit de la transition métier ; commite lui-même ses lignes de log.
    Best-effort : l'appelant enveloppe dans try/except — une alerte ne doit jamais casser
    l'action qui la déclenche."""
    from fastapi.concurrency import run_in_threadpool
    from sqlalchemy import select

    from app.models.notification import CmsAlertRule, CmsNotificationChannel, CmsNotificationLog

    subject, body = build_message(event_type, ctx)
    rows = (await db.execute(
        select(CmsAlertRule.id_rule, CmsNotificationChannel.channel_type,
               CmsNotificationChannel.config)
        .join(CmsNotificationChannel, CmsNotificationChannel.id_channel == CmsAlertRule.id_channel)
        .where(
            CmsAlertRule.id_org == id_org,
            CmsAlertRule.event_type == event_type,
            CmsAlertRule.enabled == True,  # noqa: E712
            CmsNotificationChannel.enabled == True,  # noqa: E712
        )
    )).all()
    sent = 0
    for id_rule, ctype, config in rows:
        ok, detail = await run_in_threadpool(
            deliver_to_channel, ctype, config, event_type, subject, body, ctx,
            id_org, id_rule)
        db.add(CmsNotificationLog(
            id_org=id_org, id_rule=id_rule, event_type=event_type,
            subject=subject[:200], body=body,
            status="sent" if ok else "failed", detail=detail,
        ))
        sent += 1 if ok else 0
    if rows:
        await db.commit()
    return sent


def dispatch_sync(conn, id_org: int, event_type: str, ctx: dict) -> int:
    """(worker psycopg2) Envoie l'alerte à tous les canaux webhook des règles actives de l'org pour
    ce type d'événement, et journalise. Renvoie le nombre de succès. BYPASSRLS → filtre id_org."""
    subject, body = build_message(event_type, ctx)
    cur = conn.cursor()
    cur.execute(
        "SELECT r.id_rule, c.channel_type, c.config FROM cms_alert_rules r "
        "JOIN cms_notification_channels c ON c.id_channel = r.id_channel "
        "WHERE r.id_org = %s AND r.event_type = %s AND r.enabled AND c.enabled",
        (id_org, event_type),
    )
    sent = 0
    for id_rule, ctype, config in cur.fetchall():
        ok, detail = deliver_to_channel(
            ctype, config, event_type, subject, body, ctx, id_org, id_rule)
        cur.execute(
            "INSERT INTO cms_notification_log (id_org, id_rule, event_type, subject, body, status, "
            "detail, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s, now())",
            (id_org, id_rule, event_type, subject[:200], body, "sent" if ok else "failed", detail),
        )
        sent += 1 if ok else 0
    conn.commit()
    return sent
