from __future__ import annotations

import dataclasses

from ascent.alignment import drift_check, quarantine
from ascent.evaluators.base import Impact
from ascent.goals import KPI, Goal, GoalConfig, Milestone, config_hash, make_gap


def _config() -> GoalConfig:
    return GoalConfig(
        version=1, product="P", target="web://x", goal=Goal(id="g", statement="s"),
        milestone=Milestone(id="m", name="M", required_kpi_ids=["k1"]),
        kpis=[KPI(id="k1", goal_id="g", name="K1", metric="task_success_rate", target=0.8)],
    )


def _gap(kpi_id):
    return make_gap(impact=Impact.MAJOR, evaluator="e", check_id="c", description="d", kpi_id=kpi_id)


def test_quarantine_partitions_by_kpi_id():
    config = _config()
    aligned_gap = _gap("k1")
    unknown_gap = _gap("does-not-exist")
    none_gap = _gap(None)
    result = quarantine([aligned_gap, unknown_gap, none_gap], config)
    assert result.aligned == [aligned_gap]
    assert result.unaligned == [unknown_gap, none_gap]


def test_drift_check_silent_when_unratified():
    config = _config()  # config_hash == ""
    assert drift_check(config) is None


def test_drift_check_silent_when_hash_matches():
    config = _config()
    config.config_hash = config_hash(config)
    assert drift_check(config) is None


def test_drift_check_warns_when_goal_changed():
    config = _config()
    config.config_hash = config_hash(config)
    # mutate a KPI target after ratification -> live hash diverges
    config.kpis[0] = dataclasses.replace(config.kpis[0], target=0.95)
    warning = drift_check(config)
    assert warning is not None
    assert "re-ratify" in warning
