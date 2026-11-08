"""Worker AI Assistant (§XXVII) — indexation de la documentation produit en pgvector.

Une seule tâche (file `default`, worker celery-worker) : `index_docs(force)` re-construit
les chunks de `backend/docs/kb/`, embedde les nouveaux/modifiés via LiteLLM→Ollama, et
upserte `cms_doc_chunks`. Déclenchée à la main (POST /admin/assistant/reindex) ou au déploiement.
"""

from app.services.doc_index import index_all_docs
from app.workers.celery_app import celery_app


@celery_app.task(name="app.workers.assistant_worker.index_docs")
def index_docs(force: bool = False) -> dict:
    return index_all_docs(force=force)
