from __future__ import annotations

from click.testing import CliRunner

from ascent.cli import cli

CONFIG = "examples/ascent.yaml"


def test_run_demo_renders_scorecard_and_blocks():
    # --demo injects a blocker + failing required KPIs, so readiness is BLOCKED (exit 1).
    result = CliRunner().invoke(cli, ["run", "--config", CONFIG, "--demo", "web://x"])
    assert result.exit_code == 1
    assert "BLOCKED" in result.output
    assert "KPI scorecard" in result.output


def test_run_without_evaluators_is_needs_work():
    # No evaluator is available in Phase 0 -> required KPIs are unmeasured -> NEEDS_WORK (exit 0).
    result = CliRunner().invoke(cli, ["run", "--config", CONFIG, "web://x"])
    assert result.exit_code == 0
    assert "NEEDS_WORK" in result.output
    assert "unmeasured" in result.output


def test_run_missing_config_errors():
    result = CliRunner().invoke(cli, ["run", "--config", "does-not-exist.yaml", "web://x"])
    assert result.exit_code == 2
    assert "config not found" in result.output


def test_config_evaluators_filters_which_run():
    """config.evaluators selects which evaluators execute — even an available one
    is skipped when it isn't listed."""
    from ascent.cli import _run_evaluators
    from ascent.drivers.base import ActionResult, Observation
    from ascent.evaluators.base import EvaluatorContext
    from ascent.goals import KPI, Goal, GoalConfig, Journey, Milestone
    from ascent.llm import RecordedJudge

    class _FakeDriver:
        scheme = "web"
        def available(self): return True
        def start(self, entry_point=""): pass
        def act(self, action): return ActionResult(ok=True)
        def observe(self): return Observation(url="/", title="t", elements=[], text="done")
        def current_locator(self): return None
        def close(self): pass

    journey = Journey(id="j", name="J", kpi_id="k", success_signal="done", steps=[])
    base_kwargs = dict(
        version=1, product="P", target="web://x", goal=Goal(id="g", statement="s"),
        milestone=Milestone(id="m", name="M", required_kpi_ids=["k"]),
        kpis=[KPI(id="k", goal_id="g", name="K", metric="task_success_rate", target=0.8)],
        journeys=[journey],
    )

    # journey is available but NOT selected -> nothing runs
    cfg_excluded = GoalConfig(evaluators=["replay"], **base_kwargs)
    ctx = EvaluatorContext(config=cfg_excluded, target="web://x",
                           driver=_FakeDriver(), judge=RecordedJudge(scores=[{"passed": True, "reason": "ok"}]))
    gaps, observations = _run_evaluators(ctx)
    assert observations == [] and gaps == []

    # select it -> it runs and records the observation
    cfg_included = GoalConfig(evaluators=["journey"], **base_kwargs)
    ctx2 = EvaluatorContext(config=cfg_included, target="web://x",
                            driver=_FakeDriver(), judge=RecordedJudge(scores=[{"passed": True, "reason": "ok"}]))
    _, observations2 = _run_evaluators(ctx2)
    assert any(o.kpi_id == "k" and o.evaluator == "journey" for o in observations2)
