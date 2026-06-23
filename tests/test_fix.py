from __future__ import annotations

import json

from click.testing import CliRunner

from ascent.cli import cli

CONFIG = "examples/ascent.yaml"


def test_fix_approve_all_emits_goal_linked_requests(tmp_path):
    out = tmp_path / "fix.json"
    result = CliRunner().invoke(
        cli, ["fix", "--config", CONFIG, "--demo", "--yes", "--out", str(out), "web://x"]
    )
    assert result.exit_code == 0
    assert "fix request(s) approved" in result.output
    # the written JSON payload is what a downstream coding agent consumes
    payload = json.loads(out.read_text())
    assert payload, "expected at least one approved fix request"
    first = payload[0]
    assert {"kpi_id", "goal_id", "goal", "action", "gap_ids"} <= set(first)
    assert first["goal"]  # carries the goal statement


def test_fix_declining_approves_nothing():
    # demo config has three KPI clusters -> three confirm prompts; decline each.
    result = CliRunner().invoke(cli, ["fix", "--config", CONFIG, "--demo", "web://x"],
                                input="n\nn\nn\n")
    assert result.exit_code == 0
    assert "0 fix request(s) approved" in result.output


def test_fix_does_not_claim_to_modify_code():
    result = CliRunner().invoke(cli, ["fix", "--config", CONFIG, "--demo", "--yes", "web://x"])
    assert "does not modify code" in result.output
