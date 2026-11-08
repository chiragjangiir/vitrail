from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, ForeignKey, Integer, Numeric, SmallInteger, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CmsNetworkMetricsDaily(Base):
    """Rollup quotidien des métriques réseau d'une org (§XXIV Executive Dashboard).

    Une ligne par org et par jour, écrite par la tâche beat `rollup_network_metrics`.
    Sert les séries temporelles du dashboard (uptime, alertes, health score) — l'historique
    se remplit à partir du déploiement (aucune donnée n'était collectée avant). TENANT-SCOPED (RLS).
    """

    __tablename__ = "cms_network_metrics_daily"

    id_metric: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_org: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_organizations.id_org", ondelete="CASCADE"), nullable=False)
    metric_date: Mapped[date] = mapped_column(Date, nullable=False)

    players_total: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    players_online: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    players_warning: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    players_offline: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    players_maintenance: Mapped[int] = mapped_column(
        Integer, server_default=text("0"), nullable=False)

    conformity_pct: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    alerts_active: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    plays_count: Mapped[int] = mapped_column(BigInteger, server_default=text("0"), nullable=False)
    play_seconds: Mapped[int] = mapped_column(BigInteger, server_default=text("0"), nullable=False)
    health_score: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)
