from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import click

from .alignment import drift_check, quarantine
from .drivers.factory import make_driver
from .evaluators.base import EvaluatorContext, Impact, Locator
from .evaluators.journey import JourneyEvaluator
from .evaluators.persona_agent import PersonaAgentEvaluator
from .evaluators.replay import ReplayEvaluator
from .goals import GoalConfig, load_config, make_gap, make_observation
from .integrations.github_api import GitHubAPIError, GitHubClient
from .llm import make_judge
from .output.console import render
from .output.github import (
    STICKY_COMMENT_MARKER,
    conclusion_for,
    render_gap_table,
    render_pr_comment_body,
    render_recommendations,
    render_scorecard,
    select_annotations,
    title_for,
)
from .recommend import recommend
from .scoring import roll_observations
from .verdict import Readiness, assess

# The hybrid evaluator set — all implement one protocol and emit one Gap shape,
# so they merge into a single report. Journey/Replay self-gate on config presence.
EVALUATORS: list[type] = [PersonaAgentEvaluator, JourneyEvaluator, ReplayEvaluator]

_EXIT_CODE = {Readiness.ON_TRACK: 0, Readiness.NEEDS_WORK: 0, Readiness.BLOCKED: 1}

DEFAULT_CONFIG = "ascent.yaml"


@click.group()
@click.version_option()
def cli() -> None:
    """Ascent: goal-based app QA. Train your app to hit its KPIs and unlock its next milestone."""


@cli.command()
@click.option("--config", "config_path", default=DEFAULT_CONFIG, show_default=True,
              metavar="PATH", help="Where to write the goal config.")
@click.option("--force", is_flag=True, help="Overwrite an existing config without confirming.")
def init(config_path: str, force: bool) -> None:
    """Interactively author and ratify a goal config (ascent.yaml)."""
    from .wizard import run_init
    run_init(config_path, force=force)


@cli.command()
@click.argument("target", required=False)
@click.option("--config", "config_path", default=DEFAULT_CONFIG, show_default=True,
              metavar="PATH", help="Path to the goal config.")
@click.option("--demo", is_flag=True, hidden=True,
              help="Inject synthetic gaps so the report can be previewed end-to-end.")
def run(target: str | None, config_path: str, demo: bool) -> None:
    """Run evaluators against TARGET and report milestone readiness."""
    config = _load(config_path)
    _warn_on_drift(config)
    resolved = target or config.target
    if not resolved and not demo:
        click.echo("error: no target given and none set in config", err=True)
        sys.exit(2)

    if demo:
        gaps, observations = _demo_data(config)
    else:
        gaps, observations = _run_evaluators(_build_context(config, resolved))
    q = quarantine(gaps, config)
    kpi_results = roll_observations(observations, config.kpis)
    readiness, scorecard = assess(q.aligned, config, kpi_results, unaligned_count=len(q.unaligned))
    recommendations = recommend(q.aligned, config, kpi_results)
    render(q.aligned, readiness, scorecard, q.unaligned, recommendations)
    sys.exit(_EXIT_CODE[readiness])


@cli.command()
@click.argument("target", required=False)
@click.option("--config", "config_path", default=DEFAULT_CONFIG, metavar="PATH",
              help="Path to the goal config.")
def ci(target: str | None, config_path: str) -> None:
    """Run + post a readiness check-run and sticky PR comment. Reads GITHUB_* env vars."""
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    sha = os.environ.get("GITHUB_SHA")
    workspace = os.environ.get("GITHUB_WORKSPACE") or os.getcwd()
    if not (token and repo and sha):
        click.echo("error: GITHUB_TOKEN, GITHUB_REPOSITORY, and GITHUB_SHA must be set", err=True)
        sys.exit(2)

    config = _load(config_path)
    warning = drift_check(config)
    if warning:
        click.echo(f"[warn] {warning}", err=True)
    ctx = _build_context(config, target or config.target)
    gaps, observations = _run_evaluators(ctx)
    q = quarantine(gaps, config)
    kpi_results = roll_observations(observations, config.kpis)
    readiness, scorecard = assess(q.aligned, config, kpi_results, unaligned_count=len(q.unaligned))
    recommendations = recommend(q.aligned, config, kpi_results)

    title = title_for(readiness, scorecard)
    text_parts = [f"> :warning: {warning}" if warning else "",
                  render_scorecard(scorecard),
                  render_recommendations(recommendations),
                  render_gap_table(q.aligned, repo, sha, workspace)]
    text = "\n".join(p for p in text_parts if p)
    annotations = select_annotations(q.aligned, workspace)

    client = GitHubClient(token=token, repo=repo)
    click.echo(f"[post] check-run with {len(annotations)} annotations", err=True)
    try:
        client.create_check_run(
            name="Ascent",
            head_sha=sha,
            conclusion=conclusion_for(readiness),
            title=title,
            summary=title,
            text=text,
            annotations=annotations,
        )
    except GitHubAPIError as err:
        click.echo(f"error: failed to create check-run: {err}", err=True)
        sys.exit(2)

    pr_number = _pr_number_from_event()
    if pr_number is not None:
        body = render_pr_comment_body(
            q.aligned, readiness, scorecard, repo, sha, workspace, q.unaligned, recommendations
        )
        click.echo(f"[post] sticky comment on PR #{pr_number}", err=True)
        try:
            client.upsert_pr_comment(pr_number=pr_number, marker=STICKY_COMMENT_MARKER, body=body)
        except GitHubAPIError as err:
            click.echo(f"warn: failed to upsert PR comment: {err}", err=True)

    sys.exit(_EXIT_CODE[readiness])


@cli.command()
@click.argument("target", required=False)
@click.option("--config", "config_path", default=DEFAULT_CONFIG, metavar="PATH",
              help="Path to the goal config.")
@click.option("--out", "out_path", default=None, metavar="PATH",
              help="Write approved fix requests as JSON here (else printed).")
@click.option("--yes", is_flag=True, help="Approve all recommendations non-interactively.")
@click.option("--demo", is_flag=True, hidden=True)
def fix(target: str | None, config_path: str, out_path: str | None, yes: bool, demo: bool) -> None:
    """Review ranked recommendations and emit human-approved fix requests.

    Ascent does NOT modify code — each approved request is the goal-linked
    payload (kpi, goal, gaps, action) a downstream coding agent consumes.
    """
    config = _load(config_path)
    if demo:
        gaps, observations = _demo_data(config)
    else:
        gaps, observations = _run_evaluators(_build_context(config, target or config.target))
    q = quarantine(gaps, config)
    kpi_results = roll_observations(observations, config.kpis)
    recommendations = recommend(q.aligned, config, kpi_results)
    if not recommendations:
        click.echo("No recommendations — nothing to fix.")
        return

    approved = []
    for rec in recommendations:
        click.echo(
            f"\n[{rec.kpi_id}] {rec.title}\n"
            f"  action: {rec.action}\n"
            f"  clears: {', '.join(rec.gap_ids)} (effort {rec.effort_hint}, priority {rec.priority_score})"
        )
        if yes or click.confirm("Approve this fix?", default=False):
            approved.append(_fix_request(rec, config))

    click.echo(
        f"\n{len(approved)} fix request(s) approved. Ascent does not modify code — "
        "hand these to a coding agent or apply them yourself."
    )
    if not approved:
        return
    payload = json.dumps(approved, indent=2)
    if out_path:
        Path(out_path).write_text(payload)
        click.echo(f"Wrote {out_path}.")
    else:
        click.echo(payload)


def _fix_request(rec, config: GoalConfig) -> dict:
    return {
        "id": rec.id,
        "kpi_id": rec.kpi_id,
        "goal_id": rec.goal_id,
        "goal": config.goal.statement,
        "action": rec.action,
        "rationale": rec.rationale,
        "gap_ids": rec.gap_ids,
        "effort_hint": rec.effort_hint,
        "priority_score": rec.priority_score,
    }


def _load(config_path: str) -> GoalConfig:
    try:
        return load_config(config_path)
    except FileNotFoundError:
        click.echo(
            f"error: config not found: {config_path} — run `ascent init` to create one",
            err=True,
        )
        sys.exit(2)
    except (ValueError, KeyError, TypeError) as err:
        click.echo(f"error: invalid config {config_path}: {err}", err=True)
        sys.exit(2)


def _warn_on_drift(config: GoalConfig) -> None:
    warning = drift_check(config)
    if warning:
        click.echo(f"[warn] {warning}", err=True)


def _build_context(config: GoalConfig, target: str) -> EvaluatorContext:
    ctx = EvaluatorContext(config=config, target=target)
    try:
        ctx.driver = make_driver(target)
    except (ValueError, ImportError) as err:
        click.echo(f"[skip] no driver for target {target!r}: {err}", err=True)
    ctx.judge = make_judge(config)
    if ctx.judge is None:
        click.echo("[skip] no LLM judge available (set ANTHROPIC_API_KEY and install 'ascent[live]')", err=True)
    return ctx


def _run_evaluators(ctx: EvaluatorContext):
    gaps, observations = [], []
    for evaluator_cls in EVALUATORS:
        evaluator = evaluator_cls()
        if not evaluator.is_available(ctx):
            click.echo(f"[skip] {evaluator.name} not available", err=True)
            continue
        click.echo(f"[run]  {evaluator.name} against {ctx.target}", err=True)
        result = evaluator.evaluate(ctx)
        gaps.extend(result.gaps)
        observations.extend(result.observations)
    return gaps, observations


def _demo_data(config: GoalConfig):
    """Synthesize gaps + observations tied to the config's KPIs.

    Lets the full report (scorecard, gap tables, readiness banner, quarantine
    bucket) be previewed before real evaluators are wired up.
    """
    gaps, observations = [], []
    persona = config.personas[0].id if config.personas else None
    for i, kpi in enumerate(config.kpis):
        value = kpi.target * (1.4 if kpi.comparator == "lte" else 0.7)
        observations.append(
            make_observation(kpi_id=kpi.id, value=value, evaluator="demo", sample_weight=5)
        )
        gaps.append(make_gap(
            impact=Impact.BLOCKER if i == 0 else Impact.MAJOR,
            evaluator="demo",
            check_id=f"demo-{kpi.id}",
            description=f"Simulated friction affecting {kpi.name}.",
            kpi_id=kpi.id,
            persona=persona,
            locator=Locator(kind="route", value="/"),
            evidence=["demo step trace"],
            recommendation=f"Investigate the flow that drives {kpi.name}.",
            confidence=0.5,
        ))
    gaps.append(make_gap(
        impact=Impact.MINOR,
        evaluator="demo",
        check_id="demo-unaligned",
        description="A friction point not tied to any KPI.",
        locator=Locator(kind="route", value="/settings"),
    ))
    return gaps, observations


def _pr_number_from_event() -> int | None:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path or not Path(event_path).is_file():
        return None
    try:
        with open(event_path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    pr = data.get("pull_request")
    if isinstance(pr, dict) and pr.get("number"):
        return pr["number"]
    return data.get("number")


if __name__ == "__main__":
    cli()
