from __future__ import annotations

from datetime import datetime, timezone

from click.testing import CliRunner

from ascent.alignment import drift_check
from ascent.cli import cli
from ascent.goals import KPI, Goal, GoalConfig, Milestone, config_hash, load_config
from ascent.wizard import ratify, slugify, suggest_comparator


# ---- pure helpers ------------------------------------------------------------

def test_slugify():
    assert slugify("Signup completion") == "signup-completion"
    assert slugify("  Foo!!  Bar ") == "foo-bar"
    assert slugify("") == "item"


def test_suggest_comparator():
    assert suggest_comparator("task_success_rate") == "gte"
    assert suggest_comparator("satisfaction_score") == "gte"
    assert suggest_comparator("time_to_complete_s") == "lte"
    assert suggest_comparator("drop_off_rate") == "lte"
    assert suggest_comparator("error_rate") == "lte"


def test_ratify_stamps_and_self_consistent_hash():
    config = GoalConfig(
        version=1, product="P", target="web://x", goal=Goal(id="g", statement="s"),
        milestone=Milestone(id="m", name="M", required_kpi_ids=["k1"]),
        kpis=[KPI(id="k1", goal_id="g", name="K1", metric="task_success_rate", target=0.8)],
    )
    out = ratify(config, ratified_by="me@example.com",
                 now=datetime(2026, 6, 23, 12, 0, 0, tzinfo=timezone.utc))
    assert out.ratified_by == "me@example.com"
    assert out.ratified_at == "2026-06-23T12:00:00+00:00"
    assert out.config_hash == config_hash(out)
    assert drift_check(out) is None  # freshly ratified -> no drift


# ---- end-to-end init ---------------------------------------------------------

_INIT_INPUT = "\n".join([
    "Demo App",                     # product
    "web://http://localhost:3000",  # target
    "Let a visitor sign up",        # goal statement
    "",                             # success definition (blank -> default)
    # one KPI
    "Signup completion",            # KPI name
    "task_success_rate",            # metric
    "0.8",                          # target
    "gte",                          # comparator
    "ratio",                        # unit
    "5",                            # weight
    "any",                          # source
    "n",                            # add another KPI? no
    # milestone
    "Public Beta",                  # name
    "",                             # unlock (blank)
    "all",                          # required KPIs
    "all_required",                 # gate
    # one persona
    "New user",                     # name
    "",                             # description (blank)
    "sign up fast",                 # intent
    "",                             # entry point (blank)
    "dashboard appears",            # success signal
    "all",                          # persona KPIs
    "n",                            # add another persona? no
    # budgets
    "3", "40", "25", "300",
    "qa@example.com",               # ratify as
    "y",                            # confirm ratify
]) + "\n"


def test_init_writes_ratified_config():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["init"], input=_INIT_INPUT)
        assert result.exit_code == 0, result.output

        config = load_config("ascent.yaml")
        assert config.product == "Demo App"
        assert config.target == "web://http://localhost:3000"
        assert config.goal.statement == "Let a visitor sign up"
        assert [k.id for k in config.kpis] == ["signup-completion"]
        assert config.kpis[0].weight == 5
        assert config.milestone.required_kpi_ids == ["signup-completion"]
        assert [p.id for p in config.personas] == ["new-user"]
        assert config.ratified_by == "qa@example.com"
        assert config.config_hash.startswith("sha256:")
        # The written config is internally consistent — no drift on first read.
        assert drift_check(config) is None


def test_init_force_reratifies_existing():
    runner = CliRunner()
    with runner.isolated_filesystem():
        assert runner.invoke(cli, ["init"], input=_INIT_INPUT).exit_code == 0
        # --force skips the overwrite prompt and re-ratifies with the same input.
        result = runner.invoke(cli, ["init", "--force"], input=_INIT_INPUT)
        assert result.exit_code == 0, result.output
        config = load_config("ascent.yaml")
        assert drift_check(config) is None
        assert config.config_hash.startswith("sha256:")


def test_init_run_roundtrip_no_drift():
    """A config authored by init is read identically by `ascent run`."""
    runner = CliRunner()
    with runner.isolated_filesystem():
        assert runner.invoke(cli, ["init"], input=_INIT_INPUT).exit_code == 0
        result = runner.invoke(cli, ["run"])  # uses target + config from ascent.yaml
        assert result.exit_code == 0  # no evaluators -> unmeasured -> NEEDS_WORK
        assert "[warn]" not in result.output  # ratified hash matches -> no drift warning
        assert "NEEDS_WORK" in result.output
