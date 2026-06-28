"""The `ascent init` setup wizard.

Interactively authors and ratifies a version-controlled goal config. No LLM —
pure local prompts, so it is instant and offline. The human owns the goal
statement, the KPI targets and weights, and the required-KPI readiness bar; the
wizard just captures them and stamps a ratification hash.
"""

from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime, timezone

import click

from .goals import (
    COMPARATORS,
    GATES,
    KPI,
    KPI_SOURCES,
    METRICS,
    Budgets,
    Goal,
    GoalConfig,
    Journey,
    Milestone,
    Persona,
    Replay,
    config_hash,
    dump_config,
    load_config,
)

_SCHEMES = ("web://", "api://", "ios://", "android://")
_LOWER_IS_BETTER = {"time_to_complete_s", "drop_off_rate", "error_rate"}


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")
    return slug or "item"


def suggest_comparator(metric: str) -> str:
    """Lower-is-better metrics want ``lte``; everything else ``gte``."""
    return "lte" if metric in _LOWER_IS_BETTER else "gte"


def detect_git_email() -> str:
    try:
        out = subprocess.run(
            ["git", "config", "user.email"], capture_output=True, text=True, timeout=5
        )
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def ratify(config: GoalConfig, *, ratified_by: str, now: datetime | None = None) -> GoalConfig:
    """Stamp the human sign-off: who, when, and the content hash the drift-gate
    compares against. ``config_hash`` excludes the ratification fields, so the
    order of stamping does not matter."""
    config.ratified_by = ratified_by
    config.ratified_at = (now or datetime.now(timezone.utc)).replace(microsecond=0).isoformat()
    config.config_hash = config_hash(config)
    return config


# ---- prompts -----------------------------------------------------------------

def _prompt_target(default: str) -> str:
    while True:
        target = click.prompt("Target (web://… | api://… | ios://… | android://…)", default=default)
        if target.startswith(_SCHEMES):
            if not target.startswith("web://"):
                click.echo("  note: only web:// is wired up today; other surfaces are stubs.")
            return target
        click.echo(f"  must start with one of: {', '.join(_SCHEMES)}")


def _prompt_id_subset(label: str, valid_ids: list[str], default: str = "all") -> list[str]:
    while True:
        raw = click.prompt(label, default=default)
        if raw.strip().lower() == "all":
            return list(valid_ids)
        chosen = [s.strip() for s in raw.split(",") if s.strip()]
        invalid = [c for c in chosen if c not in valid_ids]
        if invalid:
            click.echo(f"  unknown ids: {', '.join(invalid)} (valid: {', '.join(valid_ids)})")
            continue
        if not chosen:
            click.echo("  pick at least one")
            continue
        return chosen


def _prompt_kpis(goal_id: str) -> list[KPI]:
    click.echo("\n— KPIs — (the measurable proof of the goal; at least one)")
    kpis: list[KPI] = []
    while True:
        name = click.prompt("  KPI name")
        metric = click.prompt("  Metric", type=click.Choice(METRICS), default="task_success_rate")
        target = click.prompt("  Target value", type=float)
        comparator = click.prompt("  Comparator", type=click.Choice(COMPARATORS),
                                  default=suggest_comparator(metric))
        unit = click.prompt("  Unit", default="")
        weight = click.prompt("  Weight 1-5 (how much it matters)", type=click.IntRange(1, 5), default=3)
        source = click.prompt("  Measured by", type=click.Choice(KPI_SOURCES), default="any")
        kpis.append(KPI(id=slugify(name), goal_id=goal_id, name=name, metric=metric,
                        target=target, comparator=comparator, unit=unit, weight=weight, source=source))
        if not click.confirm("  Add another KPI?", default=False):
            return kpis


def _prompt_milestone(kpis: list[KPI]) -> Milestone:
    click.echo("\n— Milestone —")
    name = click.prompt("Next milestone name", default="Public Beta")
    unlock = click.prompt("What does reaching it unlock?", default="")
    ids = [k.id for k in kpis]
    click.echo(f"  KPIs available: {', '.join(ids)}")
    required = _prompt_id_subset(
        "Which KPIs are REQUIRED to clear it? (comma-separated ids, or 'all')", ids, default="all"
    )
    gate = click.prompt("Gate", type=click.Choice(GATES), default="all_required")
    threshold = 1.0
    if gate == "weighted_threshold":
        threshold = click.prompt("  Weighted pass threshold (0-1)", type=click.FloatRange(0, 1), default=0.8)
    return Milestone(id=slugify(name), name=name, unlock_criteria=unlock,
                     required_kpi_ids=required, gate=gate, threshold=threshold)


def _prompt_personas(kpis: list[KPI]) -> list[Persona]:
    click.echo("\n— Personas — (simulated users that exercise the goal; at least one)")
    ids = [k.id for k in kpis]
    personas: list[Persona] = []
    while True:
        name = click.prompt("  Persona name")
        description = click.prompt("  Description", default="")
        intent = click.prompt("  What is this persona trying to do?", default="")
        entry = click.prompt("  Entry point (blank = target root)", default="")
        success_signal = click.prompt("  Observable success signal", default="")
        kpi_ids = _prompt_id_subset(
            "  Which KPIs does this persona exercise? (comma-separated, or 'all')", ids, default="all"
        )
        personas.append(Persona(id=slugify(name), name=name, description=description, intent=intent,
                                entry_point=entry, success_signal=success_signal, kpi_ids=kpi_ids))
        if not click.confirm("  Add another persona?", default=False):
            return personas


def _prompt_budgets(default: Budgets) -> Budgets:
    click.echo("\n— Budgets — (per evaluator)")
    return Budgets(
        max_personas=click.prompt("  Max personas per run", type=int, default=default.max_personas),
        max_steps=click.prompt("  Max driver actions per persona", type=int, default=default.max_steps),
        max_turns=click.prompt("  Max LLM turns per persona", type=int, default=default.max_turns),
        timeout_s=click.prompt("  Timeout per persona (s)", type=int, default=default.timeout_s),
        min_sample_size=click.prompt("  Min samples to certify a KPI 'pass'", type=int,
                                     default=default.min_sample_size),
    )


def _prompt_integrations(kpis: list[KPI]) -> tuple[list[Journey], Replay | None]:
    """Optionally configure the analytics-replay and scripted-journey evaluators."""
    click.echo("\n— Evaluators — (persona_agent is always on; add others)")
    ids = [k.id for k in kpis]
    replay: Replay | None = None
    if click.confirm("  Enable analytics replay (KPI actuals from a funnel export)?", default=False):
        source = click.prompt("    Source", type=click.Choice(["posthog", "amplitude", "csv"]), default="csv")
        replay = Replay(export_path=click.prompt("    Export file path"), source=source)

    journeys: list[Journey] = []
    if ids and click.confirm("  Add a scripted journey?", default=False):
        while True:
            name = click.prompt("    Journey name")
            kpi_id = click.prompt("    Which KPI does it prove?", type=click.Choice(ids), default=ids[0])
            success_signal = click.prompt("    Success signal", default="")
            entry = click.prompt("    Entry point (blank = target root)", default="")
            click.echo("    (steps are added by hand in ascent.yaml — they need the app's element refs)")
            journeys.append(Journey(id=slugify(name), name=name, kpi_id=kpi_id,
                                    success_signal=success_signal, entry_point=entry, steps=[]))
            if not click.confirm("    Add another journey?", default=False):
                break
    return journeys, replay


def _warn_unobservable(kpis: list[KPI], personas: list[Persona]) -> None:
    covered: set[str] = set()
    for persona in personas:
        covered.update(persona.kpi_ids)
    for kpi in kpis:
        if kpi.source in ("persona", "any") and kpi.id not in covered:
            click.echo(
                f"  ⚠ KPI '{kpi.id}' (source={kpi.source}) isn't exercised by any persona — "
                "it will score 'unmeasured'."
            )


def _build_config(existing: GoalConfig | None) -> GoalConfig:
    product = click.prompt("Product name", default=(existing.product if existing else ""))
    target = _prompt_target(existing.target if existing else "web://http://localhost:3000")

    click.echo("\n— Main goal —")
    statement = click.prompt(
        "In one sentence, what is this app's single most important job?",
        default=(existing.goal.statement if existing else None),
    )
    success = click.prompt("How will you know it succeeded?",
                           default=(existing.goal.success_definition if existing else ""))
    goal_id = existing.goal.id if existing else (slugify(statement)[:24] or "goal")
    goal = Goal(id=goal_id, statement=statement, success_definition=success)

    kpis = _prompt_kpis(goal.id)
    milestone = _prompt_milestone(kpis)
    personas = _prompt_personas(kpis)
    _warn_unobservable(kpis, personas)
    budgets = _prompt_budgets(existing.budgets if existing else Budgets())
    journeys, replay = _prompt_integrations(kpis)

    evaluators = ["persona_agent"]
    if journeys:
        evaluators.append("journey")
    if replay is not None:
        evaluators.append("replay")

    return GoalConfig(
        version=existing.version if existing else 1,
        product=product, target=target, goal=goal, milestone=milestone,
        kpis=kpis, personas=personas, budgets=budgets, evaluators=evaluators,
        journeys=journeys, replay=replay,
        extra=existing.extra if existing else {},
    )


def _print_summary(config: GoalConfig) -> None:
    click.echo("\n=== Goal config ===")
    click.echo(f"product:   {config.product}")
    click.echo(f"target:    {config.target}")
    click.echo(f"goal:      {config.goal.statement}")
    click.echo(
        f"milestone: {config.milestone.name} "
        f"(gate={config.milestone.gate}, required={', '.join(config.milestone.required_kpi_ids)})"
    )
    click.echo("KPIs:")
    for k in config.kpis:
        unit = f" {k.unit}" if k.unit else ""
        click.echo(f"  - {k.id}: {k.name} [{k.comparator} {k.target:g}{unit}] w{k.weight} src={k.source}")
    click.echo("Personas:")
    for p in config.personas:
        click.echo(f"  - {p.id}: {p.name} → {', '.join(p.kpi_ids)}")
    click.echo(f"evaluators: {', '.join(config.evaluators)}")
    if config.replay is not None:
        click.echo(f"replay:    {config.replay.source} @ {config.replay.export_path}")
    for j in config.journeys:
        click.echo(f"journey:   {j.id} → {j.kpi_id} ({len(j.steps)} step(s))")


def run_init(config_path: str, force: bool = False) -> None:
    existing: GoalConfig | None = None
    if os.path.exists(config_path):
        if not force and not click.confirm(
            f"{config_path} already exists. Edit and re-ratify it?", default=True
        ):
            click.echo("Aborted — nothing written.")
            raise click.Abort()
        try:
            existing = load_config(config_path)
        except (OSError, ValueError, KeyError, TypeError):
            click.echo("  (could not parse the existing config — starting fresh)")
            existing = None

    config = _build_config(existing)
    _print_summary(config)

    default_by = (existing.ratified_by if existing and existing.ratified_by else detect_git_email())
    ratified_by = click.prompt("\nRatify as", default=default_by or "")
    if not click.confirm("Ratify this goal config as the bar for automated runs?", default=True):
        click.echo("Not ratified — nothing written.")
        raise click.Abort()

    ratify(config, ratified_by=ratified_by)
    dump_config(config, config_path)
    click.echo(
        f"\nWrote {config_path} (config_hash {config.config_hash[:21]}…). "
        "Run `ascent run` to use it."
    )
