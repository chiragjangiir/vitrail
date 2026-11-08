"""Feed Display (§XXV.3) — sources de flux RSS/Atom + items agrégés

Revision ID: 0042
Revises: 0041
Create Date: 2026-06-15 12:00:00.000000

Première tranche des Feeds (§25.3) : RSS/Atom rendus sur le player en mode `ticker` ou
`card_carousel`. Un feed = une source pollable (`cms_datafeeds`) ; ses items dédupliqués
vivent dans `cms_feed_items`. Le contenu schedulable est un `cms_media`
(`media_type='feed_display'`, `metadata.id_feed`+`display_mode`+`display_config`) — comme
URL Display, il hérite de toute la machinerie (médiathèque, scheduling, sync, offline-first)
et réutilise le module RBAC `media` (pas de nouvelle permission à seeder).

`cms_datafeeds` est volontairement créée avec les colonnes feed_display + un socle commun
réutilisable par le futur module DataFeeds (§XV) — feed_type couvre ici rss/atom/google_news.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0042"
down_revision: str | None = "0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cms_datafeeds",
        sa.Column("id_feed", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("id_org", sa.BigInteger, nullable=False),
        sa.Column("feed_name", sa.String(255), nullable=False),
        sa.Column("feed_type", sa.String(30), nullable=False),          # rss | atom | google_news
        sa.Column("config", postgresql.JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("polling_interval_s", sa.Integer, server_default="900", nullable=False),
        sa.Column("status", sa.String(20), server_default="active", nullable=False),  # active|paused|error
        sa.Column("last_fetched_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("consecutive_errors", sa.Integer, server_default="0", nullable=False),
        # ── colonnes feed_display (§25.3) ──
        sa.Column("display_mode", sa.String(30), nullable=True),         # ticker | card_carousel
        sa.Column("display_config", postgresql.JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("moderation_enabled", sa.Boolean, server_default=sa.text("false"), nullable=False),
        sa.Column("max_items", sa.Integer, server_default="10", nullable=False),
        sa.Column("dedup_window_h", sa.Integer, server_default="24", nullable=False),
        sa.Column("lang_filter", sa.String(5), nullable=True),
        sa.Column("ai_summary_enabled", sa.Boolean, server_default=sa.text("false"), nullable=False),
        sa.Column("is_deleted", sa.Boolean, server_default=sa.text("false"), nullable=False),
        sa.Column("created_by", sa.BigInteger, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["id_org"], ["cms_organizations.id_org"]),
        sa.ForeignKeyConstraint(["created_by"], ["cms_users.id_user"]),
    )
    op.create_index("ix_cms_datafeeds_id_org", "cms_datafeeds", ["id_org"])
    op.create_index("ix_cms_datafeeds_status", "cms_datafeeds", ["status"])

    op.create_table(
        "cms_feed_items",
        sa.Column("id_item", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("id_feed", sa.BigInteger, nullable=False),
        sa.Column("item_guid", sa.Text, nullable=False),
        sa.Column("title", sa.Text, nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("content_html", sa.Text, nullable=True),
        sa.Column("summary_ai", sa.Text, nullable=True),
        sa.Column("image_url", sa.Text, nullable=True),
        sa.Column("thumbnail_s3", sa.Text, nullable=True),
        sa.Column("link_url", sa.Text, nullable=True),
        sa.Column("author", sa.Text, nullable=True),
        sa.Column("categories", postgresql.ARRAY(sa.Text), nullable=True),
        sa.Column("published_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("fetched_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("moderation_status", sa.String(20), server_default="approved", nullable=False),  # pending|approved|rejected
        sa.Column("is_shown", sa.Boolean, server_default=sa.text("false"), nullable=False),
        sa.Column("show_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("last_shown_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["id_feed"], ["cms_datafeeds.id_feed"], ondelete="CASCADE"),
        sa.UniqueConstraint("id_feed", "item_guid", name="uq_cms_feed_items_guid"),
    )
    op.create_index("ix_cms_feed_items_feed_pub", "cms_feed_items", ["id_feed", sa.text("published_at DESC")])
    op.create_index("ix_cms_feed_items_moderate", "cms_feed_items", ["id_feed", "moderation_status"])


def downgrade() -> None:
    op.drop_table("cms_feed_items")
    op.drop_table("cms_datafeeds")
