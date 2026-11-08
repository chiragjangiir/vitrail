"""Indexation de la documentation produit dans pgvector (§XXVII).

Pipeline (appelé par la tâche Celery `app.workers.assistant_worker.index_docs`) :
  1. Lire les `.md` de `backend/docs/kb/`.
  2. Lire le frontmatter (title / section / roles / keywords).
  3. Découper par section H2/H3 (chunks ~1800 caractères max).
  4. Embedder les chunks NOUVEAUX ou MODIFIÉS via LiteLLM→Ollama (nomic-embed-text, 768d) —
     les chunks inchangés réutilisent leur vecteur (upsert COALESCE → pas de ré-embed inutile).
  5. Upsert `cms_doc_chunks` (chunk_id stable = hash(fichier+index)) + suppression des chunks
     d'un fichier qui ont disparu.

Table GLOBALE (pas de RLS org) : on se connecte via le rôle worker (BYPASSRLS), comme les
autres workers. L'isolation de la doc se fait par RÔLE (colonne `roles`), au moment de la
recherche.
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Any, TypedDict

import psycopg2
import psycopg2.extras

from app.core.config import settings
from app.services.embeddings import embed_texts, to_pgvector

logger = logging.getLogger(__name__)

DOCS_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "kb"
MAX_CHUNK_CHARS = 1800   # ~350 tokens, sous le plafond de nomic-embed-text
MIN_CHUNK_CHARS = 30


class DocChunk(TypedDict):
    chunk_id: str
    source_file: str
    title: str
    section_anchor: str
    content: str
    roles: list[str]
    keywords: list[str]


# ── Frontmatter ───────────────────────────────────────────────────────────────

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [v.strip().strip("'\"") for v in inner.split(",") if v.strip()]
    return value.strip("'\"")


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Sépare le frontmatter (clé: valeur, listes `[a, b]` supportées) du corps Markdown."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    meta: dict[str, Any] = {}
    for line in m.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, _, raw = line.partition(":")
        meta[key.strip()] = _parse_scalar(raw)
    return meta, text[m.end():]


# ── Chunking Markdown (H2/H3) ─────────────────────────────────────────────────

def _strip_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)


def chunk_markdown(text: str) -> list[tuple[str, str]]:
    """Découpe le corps en (section_title, content). H3 intégrés au chunk H2 courant.

    Un chunk trop long est re-découpé par paragraphes. Renvoie une liste ordonnée.
    """
    text = _strip_comments(text)
    chapter = ""
    section = ""
    buf: list[str] = []
    out: list[tuple[str, str]] = []

    def flush() -> None:
        content = "\n".join(buf).strip()
        if len(content) < MIN_CHUNK_CHARS:
            return
        label = section or chapter
        if len(content) <= MAX_CHUNK_CHARS:
            out.append((label, content))
            return
        # Re-découpe par paragraphes
        parts = re.split(r"\n{2,}", content)
        acc = ""
        for part in parts:
            if acc and len(acc) + len(part) > MAX_CHUNK_CHARS:
                out.append((label, acc.strip()))
                acc = part
            else:
                acc = (acc + "\n\n" + part).strip() if acc else part
        if acc.strip():
            out.append((label, acc.strip()))

    for line in text.split("\n"):
        if m := re.match(r"^# (.+)", line):
            chapter = m.group(1).strip()
        elif m := re.match(r"^## (.+)", line):
            flush()
            section = m.group(1).strip()
            buf = []
        else:
            buf.append(line)
    flush()
    return out


def build_chunks(path: Path) -> list[DocChunk]:
    """Construit les chunks d'un fichier (frontmatter + sections)."""
    raw = path.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(raw)
    title = str(meta.get("title") or path.stem)
    roles = meta.get("roles") or []
    if isinstance(roles, str):
        roles = [roles] if roles else []
    keywords = meta.get("keywords") or []
    if isinstance(keywords, str):
        keywords = [keywords] if keywords else []

    chunks: list[DocChunk] = []
    for i, (section, content) in enumerate(chunk_markdown(body)):
        chunk_id = hashlib.sha256(f"{path.name}::{i}".encode()).hexdigest()[:40]
        chunks.append(
            DocChunk(
                chunk_id=chunk_id,
                source_file=path.name,
                title=title,
                section_anchor=section,
                content=content,
                roles=list(roles),
                keywords=list(keywords),
            )
        )
    return chunks


# ── Indexation (worker, sync psycopg2) ────────────────────────────────────────

def _db_conn():
    url = settings.db_worker_url.replace("postgresql+asyncpg://", "postgresql://")
    return psycopg2.connect(url)


def _embed_input(c: DocChunk) -> str:
    """Texte embeddé : on préfixe titre + section pour ancrer le contexte de retrieval."""
    head = " — ".join(p for p in (c["title"], c["section_anchor"]) if p)
    return f"{head}\n\n{c['content']}" if head else c["content"]


def index_all_docs(force: bool = False) -> dict:
    """Indexe tous les `.md` de DOCS_DIR. Incrémental : ne ré-embedde que ce qui a changé."""
    if not DOCS_DIR.exists():
        logger.warning("doc_index: répertoire absent %s", DOCS_DIR)
        return {"files": 0, "chunks": 0, "embedded": 0, "errors": [f"missing dir {DOCS_DIR}"]}

    stats = {"files": 0, "chunks": 0, "embedded": 0, "errors": []}
    conn = _db_conn()
    try:
        for path in sorted(DOCS_DIR.glob("*.md")):
            try:
                _index_file(conn, path, force, stats)
                stats["files"] += 1
            except Exception as exc:  # noqa: BLE001
                conn.rollback()
                logger.error("doc_index: erreur sur %s: %s", path.name, exc)
                stats["errors"].append(f"{path.name}: {exc}")
    finally:
        conn.close()
    return stats


def _index_file(conn, path: Path, force: bool, stats: dict) -> None:
    chunks = build_chunks(path)
    if not chunks:
        return

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT chunk_id, content FROM cms_doc_chunks WHERE source_file = %s",
            (path.name,),
        )
        existing = {r["chunk_id"]: r["content"] for r in cur.fetchall()}

    # Déterminer les chunks à (ré)embedder
    to_embed = [c for c in chunks if force or existing.get(c["chunk_id"]) != c["content"]]
    vectors: dict[str, str] = {}
    if to_embed:
        embs = embed_texts([_embed_input(c) for c in to_embed])
        vectors = {c["chunk_id"]: to_pgvector(v) for c, v in zip(to_embed, embs)}
        stats["embedded"] += len(to_embed)

    new_ids = {c["chunk_id"] for c in chunks}
    with conn.cursor() as cur:
        for c in chunks:
            vec = vectors.get(c["chunk_id"])  # None si inchangé → COALESCE garde l'ancien
            cur.execute(
                """
                INSERT INTO cms_doc_chunks
                    (chunk_id, source_file, title, section_anchor, content, roles, keywords,
                     embedding, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::vector, now())
                ON CONFLICT (chunk_id) DO UPDATE SET
                    source_file    = EXCLUDED.source_file,
                    title          = EXCLUDED.title,
                    section_anchor = EXCLUDED.section_anchor,
                    content        = EXCLUDED.content,
                    roles          = EXCLUDED.roles,
                    keywords       = EXCLUDED.keywords,
                    embedding      = COALESCE(EXCLUDED.embedding, cms_doc_chunks.embedding),
                    updated_at     = now()
                """,
                (
                    c["chunk_id"], c["source_file"], c["title"], c["section_anchor"],
                    c["content"], c["roles"], c["keywords"], vec,
                ),
            )
        # Supprimer les chunks de ce fichier qui n'existent plus
        stale = [cid for cid in existing if cid not in new_ids]
        if stale:
            cur.execute(
                "DELETE FROM cms_doc_chunks WHERE source_file = %s AND chunk_id = ANY(%s)",
                (path.name, stale),
            )
    conn.commit()
    stats["chunks"] += len(chunks)
