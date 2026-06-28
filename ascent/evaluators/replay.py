"""Replay evaluator — derive KPI actuals from a real analytics/session export.

The ground-truth signal: instead of simulating, it reads a funnel export
(PostHog/Amplitude/CSV exported to JSON) and computes completion / drop-off /
error rates from real behavior, plus a gap at the biggest drop-off step.
Needs no driver or LLM, so it is fully deterministic and testable.

Activates only when ``replay.export_path`` in the config points at a file that
exists, so it stays inactive until you wire up an export.
"""

from __future__ import annotations

import json
import os

from ..goals import GoalConfig, make_gap, make_observation
from .base import EvaluationResult, EvaluatorContext, Impact

_REPLAY_METRICS = {"drop_off_rate", "task_success_rate", "error_rate", "time_to_complete_s"}


class ReplayEvaluator:
    name = "replay"

    def _export_path(self, config: GoalConfig) -> str | None:
        return config.replay.export_path if config.replay else None

    def is_available(self, ctx: EvaluatorContext) -> bool:
        path = self._export_path(ctx.config)
        return bool(path) and os.path.isfile(path)

    def evaluate(self, ctx: EvaluatorContext) -> EvaluationResult:
        result = EvaluationResult()
        with open(self._export_path(ctx.config)) as f:
            data = json.load(f)

        funnel = data.get("funnel") or []
        if len(funnel) < 2:
            return result
        entered = max(int(funnel[0].get("users", 0)), 1)
        completed = int(funnel[-1].get("users", 0))
        completion_rate = completed / entered
        drop_off_rate = 1.0 - completion_rate
        errors = data.get("errors")
        error_rate = (int(errors) / entered) if errors is not None else None
        median_time = data.get("median_time_to_complete_s")

        value_by_metric = {
            "task_success_rate": completion_rate,
            "drop_off_rate": drop_off_rate,
            "error_rate": error_rate,
            "time_to_complete_s": median_time,
        }
        for kpi in ctx.config.kpis:
            if kpi.source not in ("replay", "any") or kpi.metric not in _REPLAY_METRICS:
                continue
            value = value_by_metric.get(kpi.metric)
            if value is None:
                continue
            result.observations.append(
                make_observation(kpi_id=kpi.id, value=float(value), evaluator=self.name, sample_weight=entered)
            )

        self._emit_dropoff_gap(ctx.config, funnel, result)
        return result

    def _emit_dropoff_gap(self, config: GoalConfig, funnel: list[dict], result: EvaluationResult) -> None:
        worst_drop = 0.0
        worst_pair = None
        for prev, cur in zip(funnel, funnel[1:]):
            prev_users = max(int(prev.get("users", 0)), 1)
            drop = (prev_users - int(cur.get("users", 0))) / prev_users
            if drop > worst_drop:
                worst_drop, worst_pair = drop, (prev, cur)
        if worst_pair is None or worst_drop <= 0:
            return
        kpi_id = self._funnel_kpi(config)
        prev, cur = worst_pair
        result.gaps.append(make_gap(
            impact=Impact.MAJOR if worst_drop >= 0.3 else Impact.MODERATE,
            evaluator=self.name, check_id="dropoff",
            description=(
                f"Biggest drop-off: {prev.get('step')} → {cur.get('step')} "
                f"loses {round(worst_drop * 100)}% of users."
            ),
            kpi_id=kpi_id,
            recommendation=f"Reduce friction at the '{cur.get('step')}' step.",
            confidence=0.9,
        ))

    @staticmethod
    def _funnel_kpi(config: GoalConfig) -> str | None:
        for kpi in config.kpis:
            if kpi.metric in ("drop_off_rate", "task_success_rate"):
                return kpi.id
        return config.kpis[0].id if config.kpis else None
