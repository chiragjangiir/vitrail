"""
Service d'évaluation des conditions d'événement (§XX.4).

Évalue une expression logique AND/OR à partir d'un trigger_config JSONB.
Sources supportées Phase 2 : schedule, manual, webhook.
Source datafeed et audience ajoutées en Phase 3.

NOTE TIMEZONE : les heures dans trigger_config sont saisies en heure locale. Le fuseau
de référence est celui DÉCLARÉ PAR L'ÉVÉNEMENT (`cms_events.timezone`, P3.13), passé ici
par `context["tz_name"]` ; à défaut, SIGNFLOW_TZ. L'évaluateur convertit 'now' dans ce
fuseau avant comparaison.

⚠️ Un événement porte UNE ligne et UN `activated_at` : il ne peut donc pas s'activer à
l'heure locale de chaque écran ciblé. Il déclare ce que « 18 h » veut dire, une fois.
"""

from datetime import UTC, datetime, time as dt_time
from typing import Any
from zoneinfo import ZoneInfo


def _get_tz(tz_name: str | None = None) -> ZoneInfo:
    """Fuseau d'évaluation : celui de l'événement, sinon SIGNFLOW_TZ, sinon UTC."""
    from app.core.timezones import safe_zoneinfo
    return safe_zoneinfo(tz_name)


class EventConditionEvaluator:
    """Évalue si les conditions d'activation d'un event sont remplies."""

    def evaluate(
        self,
        trigger_config: dict[str, Any] | None,
        context: dict[str, Any] | None = None,
    ) -> bool:
        """
        Retourne True si l'expression logique complète est satisfaite.

        context peut contenir :
          - 'now' (datetime, timezone-aware ou naïve) : instant d'évaluation
          - 'tz_name' (str) : fuseau de référence de l'événement (défaut SIGNFLOW_TZ)
          - 'datafeed_values' (dict) : valeurs datafeed courantes (Phase 3)
        """
        if trigger_config is None:
            return True
        if context is None:
            context = {}
        if "now" not in context:
            context["now"] = datetime.now(UTC)

        logic = trigger_config.get("logic", "AND")
        conditions = trigger_config.get("conditions", [])
        if not conditions:
            return True

        results = [self._eval_condition(c, context) for c in conditions]
        return any(results) if logic == "OR" else all(results)

    def _eval_condition(self, condition: dict[str, Any], context: dict[str, Any]) -> bool:
        # Logique imbriquée AND/OR
        if "logic" in condition and "conditions" in condition:
            logic = condition["logic"]
            results = [self._eval_condition(c, context) for c in condition["conditions"]]
            return any(results) if logic == "OR" else all(results)

        source = condition.get("source")

        if source in ("manual", "webhook"):
            # L'appel API ou le webhook POST est lui-même le trigger — condition toujours vraie
            return True

        if source == "schedule":
            now = context["now"]
            # Convertit dans le fuseau de l'ÉVÉNEMENT — les heures sont saisies en heure locale
            tz = _get_tz(context.get("tz_name"))
            if hasattr(now, "tzinfo") and now.tzinfo is not None:
                now = now.astimezone(tz).replace(tzinfo=None)
            else:
                # datetime naïf reçu : on suppose UTC, on convertit
                from datetime import timezone
                now = now.replace(tzinfo=timezone.utc).astimezone(tz).replace(tzinfo=None)
            return self._eval_schedule(condition, now)

        # datafeed, audience, player_status, erp_promotion — Phase 3+
        return False

    def _eval_schedule(self, condition: dict[str, Any], now: datetime) -> bool:
        """Évalue une condition de plage horaire/jour (§XX.4 source=schedule)."""
        days_of_week = condition.get("days_of_week")
        time_start_str = condition.get("time_start")
        time_end_str = condition.get("time_end")

        # Vérification du jour (0=Lun … 6=Dim — convention Python weekday())
        if days_of_week is not None and now.weekday() not in days_of_week:
            return False

        # Vérification de la plage horaire
        if time_start_str and time_end_str:
            current = now.time().replace(microsecond=0)
            t_start = self._parse_time(time_start_str)
            t_end = self._parse_time(time_end_str)

            if t_start <= t_end:
                if not (t_start <= current <= t_end):
                    return False
            else:
                # Fenêtre nocturne, ex. 22:00 → 06:00
                if not (current >= t_start or current <= t_end):
                    return False

        return True

    @staticmethod
    def _parse_time(s: str) -> dt_time:
        parts = s.split(":")
        return dt_time(int(parts[0]), int(parts[1]))
