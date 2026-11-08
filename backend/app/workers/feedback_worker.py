"""Worker de triage IA des retours utilisateurs (§ retours UI).

Charge un retour, appelle LiteLLM (best-effort) pour catégorie/sévérité/résumé, et écrit les
colonnes `ai_*`. DB via psycopg2 sur le rôle signflow_worker (BYPASSRLS), comme les autres
workers. Best-effort : si le triage échoue, `ai_processed_at` reste NULL (le tri manuel reste).
"""

from __future__ import annotations

import logging

import psycopg2
import psycopg2.extras

from app.core.config import settings
from app.services import ai_credentials, feedback_ai
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _db_conn():
    url = settings.db_worker_url.replace("postgresql+asyncpg://", "postgresql://")
    return psycopg2.connect(url)


@celery_app.task(name="app.workers.feedback_worker.triage_feedback")
def triage_feedback(id_feedback: int) -> dict:
    """Remplit ai_category / ai_severity / ai_summary / ai_processed_at pour un retour."""
    conn = _db_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute(
            "SELECT id_org, feedback_type, description FROM cms_feedback WHERE id_feedback = %s",
            (id_feedback,),
        )
        row = cur.fetchone()
    finally:
        conn.close()
    if row is None:
        return {"id_feedback": id_feedback, "triaged": False, "reason": "not_found"}

    # BYOK §XXVII : résoudre la clé Anthropic de l'org du retour (rien d'auto).
    conn = _db_conn()
    try:
        ai_key, ai_mode = ai_credentials.resolve_anthropic_for_worker(conn, row["id_org"])
    finally:
        conn.close()
    if ai_mode is None:
        return {"id_feedback": id_feedback, "triaged": False, "reason": "no_ai_key"}

    result = feedback_ai.triage(
        row["feedback_type"], row["description"],
        api_key=(ai_key if ai_mode == "org" else None),
    )
    if result is None:
        return {"id_feedback": id_feedback, "triaged": False, "reason": "llm_unavailable"}

    conn = _db_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE cms_feedback SET ai_category = %s, ai_severity = %s, ai_summary = %s, "
            "ai_processed_at = now(), updated_at = now() WHERE id_feedback = %s",
            (result["category"], result["severity"], result["summary"], id_feedback),
        )
        conn.commit()
    finally:
        conn.close()
    return {"id_feedback": id_feedback, "triaged": True, **result}
