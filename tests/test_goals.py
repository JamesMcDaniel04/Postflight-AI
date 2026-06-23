from __future__ import annotations

import dataclasses

from ascent.evaluators.base import Impact, Locator
from ascent.goals import (
    KPI,
    Goal,
    GoalConfig,
    Milestone,
    Persona,
    config_hash,
    dump_config,
    load_config,
    make_gap,
    make_observation,
)


def _config() -> GoalConfig:
    return GoalConfig(
        version=1,
        product="Sample App",
        target="web://http://localhost:3000",
        goal=Goal(id="activation", statement="Book a demo fast", success_definition="reaches confirmation"),
        milestone=Milestone(id="beta", name="Public Beta", required_kpi_ids=["k1", "k2"]),
        kpis=[
            KPI(id="k1", goal_id="activation", name="Completion", metric="task_success_rate",
                target=0.8, comparator="gte", unit="ratio", weight=5),
            KPI(id="k2", goal_id="activation", name="Time", metric="time_to_complete_s",
                target=180, comparator="lte", unit="s", weight=3),
        ],
        personas=[Persona(id="busy", name="Busy founder", intent="book demo", kpi_ids=["k1"])],
        evaluators=["persona_agent"],
        extra={"judge": {"provider": "anthropic", "model": "claude-opus-4-8"}},
    )


def test_round_trip_preserves_config(tmp_path):
    config = _config()
    path = str(tmp_path / "ascent.yaml")
    dump_config(config, path)
    loaded = load_config(path)

    assert loaded.product == config.product
    assert loaded.target == config.target
    assert loaded.goal == config.goal
    assert loaded.milestone == config.milestone
    assert loaded.kpis == config.kpis
    assert loaded.personas == config.personas
    # unknown top-level keys survive the round-trip
    assert loaded.extra["judge"]["model"] == "claude-opus-4-8"


def test_config_hash_is_stable():
    assert config_hash(_config()) == config_hash(_config())


def test_config_hash_ignores_ratification_fields():
    a = _config()
    b = _config()
    b.ratified_by = "someone@example.com"
    b.ratified_at = "2026-06-23T10:00:00Z"
    assert config_hash(a) == config_hash(b)


def test_config_hash_changes_with_kpi_target():
    a = _config()
    b = _config()
    b.kpis[0] = dataclasses.replace(b.kpis[0], target=0.95)
    assert config_hash(a) != config_hash(b)


def test_config_hash_order_independent():
    a = _config()
    b = _config()
    b.kpis = list(reversed(b.kpis))
    assert config_hash(a) == config_hash(b)


def test_make_gap_routes_linkage_fields():
    gap = make_gap(
        impact=Impact.BLOCKER, evaluator="persona_agent", check_id="dead-end",
        description="hit a dead end", kpi_id="k1", persona="busy",
        locator=Locator(kind="route", value="/checkout"),
        evidence=["clicked Pay", "spinner forever"], recommendation="fix the Pay button",
        confidence=0.8,
    )
    assert gap.kpi_id == "k1"
    assert gap.persona == "busy"
    assert gap.locator.value == "/checkout"
    assert gap.evidence == ["clicked Pay", "spinner forever"]
    assert gap.extra == {}


def test_make_observation():
    obs = make_observation(kpi_id="k1", value=0.7, evaluator="persona_agent", sample_weight=3)
    assert obs.kpi_id == "k1"
    assert obs.value == 0.7
    assert obs.sample_weight == 3
