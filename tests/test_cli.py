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
