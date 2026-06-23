from __future__ import annotations

import os

from ascent.evaluators.base import EvaluatorContext, Impact
from ascent.evaluators.replay import ReplayEvaluator
from ascent.goals import KPI, Goal, GoalConfig, Milestone

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "analytics.json")


def _config(export_path: str | None) -> GoalConfig:
    extra = {"replay": {"export_path": export_path}} if export_path is not None else {}
    return GoalConfig(
        version=1, product="P", target="web://x", goal=Goal(id="activation", statement="s"),
        milestone=Milestone(id="m", name="Beta"),
        kpis=[
            KPI(id="completion", goal_id="activation", name="Completion", metric="task_success_rate",
                target=0.8, comparator="gte", source="any"),
            KPI(id="dropoff", goal_id="activation", name="Drop-off", metric="drop_off_rate",
                target=0.3, comparator="lte", source="replay"),
            KPI(id="errors", goal_id="activation", name="Errors", metric="error_rate",
                target=0.02, comparator="lte", source="replay"),
            KPI(id="speed", goal_id="activation", name="Speed", metric="time_to_complete_s",
                target=180, comparator="lte", source="replay"),
        ],
        extra=extra,
    )


def _ctx(config):
    return EvaluatorContext(config=config, target="web://x")


def test_is_available_only_when_export_exists():
    ev = ReplayEvaluator()
    assert ev.is_available(_ctx(_config(FIXTURE))) is True
    assert ev.is_available(_ctx(_config(None))) is False
    assert ev.is_available(_ctx(_config("/no/such/file.json"))) is False


def test_computes_kpi_actuals_from_funnel():
    result = ReplayEvaluator().evaluate(_ctx(_config(FIXTURE)))
    obs = {o.kpi_id: o.value for o in result.observations}
    assert obs["completion"] == 250 / 1000      # 0.25
    assert obs["dropoff"] == 1 - 250 / 1000      # 0.75
    assert obs["errors"] == 50 / 1000            # 0.05
    assert obs["speed"] == 210
    # observations are weighted by the cohort that entered the funnel
    assert all(o.sample_weight == 1000 for o in result.observations)


def test_emits_biggest_dropoff_gap():
    result = ReplayEvaluator().evaluate(_ctx(_config(FIXTURE)))
    dropoff = [g for g in result.gaps if g.check_id == "dropoff"]
    assert len(dropoff) == 1
    gap = dropoff[0]
    assert gap.impact == Impact.MAJOR          # 57% drop >= 30%
    assert "signup" in gap.description and "checkout" in gap.description
    assert "57%" in gap.description
    assert gap.kpi_id in ("dropoff", "completion")  # linked to a funnel KPI
