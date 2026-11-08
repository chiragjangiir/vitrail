"""AI Assistant RAG (§XXVII) — schéma pgvector + sessions + stats

Revision ID: 0046
Revises: 0045
Create Date: 2026-06-20 00:00:00.000000

Trois tables pour l'AI Assistant (Sprint 2.10) :

  1. cms_doc_chunks — chunks de la documentation produit indexés en pgvector
     (embedding `nomic-embed-text` 768 dims, recherche cosine top-K). **GLOBAL,
     PAS tenant-scoped** : la doc est la même pour toutes les orgs ; l'isolation
     se fait par RÔLE (colonne `roles TEXT[]` — un VIEWER ne voit pas un chunk
     réservé ORG_ADMIN). `roles` vide/NULL = visible par tous les rôles.
     Index IVFFlat (vector_cosine_ops, lists=100) pour la recherche approchée.

  2. cms_assistant_sessions — historique conversationnel par utilisateur
     (messages JSONB, contexte de page), TTL 24h (`expires_at`). TENANT-SCOPED
     (RLS `id_org`) — une org ne voit jamais les sessions d'une autre.

  3. cms_assistant_stats — compteurs quotidiens par org (messages + tokens) pour
     surveiller l'usage/coût. TENANT-SCOPED (RLS `id_org`).

L'extension `vector` est créée par docker/postgres/init.sql ; on la (re)crée ici
en IF NOT EXISTS pour les bases de test qui ne passent pas par init.sql.

Grants : les tables créées par le rôle `signflow` héritent des ALTER DEFAULT
PRIVILEGES posés en 0044 → auto-grantées à signflow_app / signflow_worker.
Les policies RLS suivent le pattern 0044 (USING = WITH CHECK implicite).
"""

from alembic import op

revision: str = "0046"
down_revision: str | None = "0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── 1. cms_doc_chunks (GLOBAL, filtrage par rôle, PAS de RLS org) ───────────
    op.execute(
        """
        CREATE TABLE cms_doc_chunks (
            id_chunk        BIGSERIAL PRIMARY KEY,
            chunk_id        TEXT NOT NULL UNIQUE,        -- hash(source_file + section) → upsert incrémental
            source_file     VARCHAR(255) NOT NULL,
            title           TEXT,                        -- titre du document (H1)
            section_anchor  TEXT,                        -- titre de section (H2/H3)
            content         TEXT NOT NULL,
            roles           TEXT[] NOT NULL DEFAULT '{}',  -- rôles autorisés ; vide = tous
            keywords        TEXT[] NOT NULL DEFAULT '{}',
            embedding       vector(768),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX idx_doc_chunks_source ON cms_doc_chunks (source_file)")
    # IVFFlat cosine — recherche approchée top-K. lists=100 (cf. spec §27.3).
    op.execute(
        """
        CREATE INDEX idx_doc_chunks_embedding ON cms_doc_chunks
            USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)
        """
    )

    # ── 2. cms_assistant_sessions (tenant-scoped, RLS, TTL 24h) ────────────────
    op.execute(
        """
        CREATE TABLE cms_assistant_sessions (
            id_session    BIGSERIAL PRIMARY KEY,
            id_org        BIGINT NOT NULL REFERENCES cms_organizations(id_org),
            id_user       BIGINT NOT NULL REFERENCES cms_users(id_user),
            messages      JSONB NOT NULL DEFAULT '[]'::jsonb,
            page_context  JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at    TIMESTAMPTZ NOT NULL DEFAULT now() + interval '24 hours'
        )
        """
    )
    op.execute("CREATE INDEX idx_assistant_sessions_org ON cms_assistant_sessions (id_org)")
    op.execute("CREATE INDEX idx_assistant_sessions_user ON cms_assistant_sessions (id_user)")
    op.execute("CREATE INDEX idx_assistant_sessions_expires ON cms_assistant_sessions (expires_at)")
    op.execute("ALTER TABLE cms_assistant_sessions ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY cms_assistant_sessions_org_isolation ON cms_assistant_sessions
            USING (id_org = current_setting('app.current_org_id', true)::bigint)
        """
    )

    # ── 3. cms_assistant_stats (tenant-scoped, RLS, 1 ligne/org/jour) ──────────
    op.execute(
        """
        CREATE TABLE cms_assistant_stats (
            id_stat        BIGSERIAL PRIMARY KEY,
            id_org         BIGINT NOT NULL REFERENCES cms_organizations(id_org),
            stat_date      DATE NOT NULL DEFAULT current_date,
            message_count  INTEGER NOT NULL DEFAULT 0,
            token_count    BIGINT NOT NULL DEFAULT 0,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (id_org, stat_date)
        )
        """
    )
    op.execute("ALTER TABLE cms_assistant_stats ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY cms_assistant_stats_org_isolation ON cms_assistant_stats
            USING (id_org = current_setting('app.current_org_id', true)::bigint)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cms_assistant_stats")
    op.execute("DROP TABLE IF EXISTS cms_assistant_sessions")
    op.execute("DROP TABLE IF EXISTS cms_doc_chunks")
