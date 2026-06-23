from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..evaluators.base import Gap, Impact, Locator
from ..verdict import Readiness, Scorecard

_READINESS_COLOR = {
    Readiness.ON_TRACK: "green",
    Readiness.NEEDS_WORK: "yellow",
    Readiness.BLOCKED: "red",
}

_IMPACT_STYLE = {
    Impact.BLOCKER: "bold red",
    Impact.MAJOR: "red",
    Impact.MODERATE: "yellow",
    Impact.MINOR: "blue",
    Impact.INFO: "dim",
}

_STATUS_STYLE = {
    "pass": "green",
    "near": "yellow",
    "fail": "red",
    "unmeasured": "dim",
}


def locator_label(locator: Locator | None) -> str:
    if locator is None:
        return ""
    if locator.kind == "file" and locator.line:
        return f"{locator.value}:{locator.line}"
    return locator.value


def _scorecard_table(scorecard: Scorecard) -> Table:
    table = Table(title="KPI scorecard", title_style="bold", show_lines=False)
    table.add_column("KPI")
    table.add_column("Target", no_wrap=True)
    table.add_column("Actual", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Samples", justify="right", no_wrap=True)
    for r in scorecard.kpi_results:
        target = f"{r.comparator} {r.target:g}".strip()
        actual = "—" if r.actual is None else f"{r.actual:g}"
        style = _STATUS_STYLE.get(r.status, "white")
        table.add_row(
            r.name,
            target,
            actual,
            f"[{style}]{r.status}[/{style}]",
            str(r.sample_size),
        )
    return table


def _gap_tables(gaps: list[Gap], console: Console) -> None:
    impacts_desc = sorted(Impact, key=lambda i: -i.rank)
    for impact in impacts_desc:
        rows = [g for g in gaps if g.impact == impact]
        if not rows:
            continue
        table = Table(
            title=f"{impact.value.upper()} ({len(rows)})",
            title_style=_IMPACT_STYLE[impact],
            show_lines=False,
        )
        table.add_column("Evaluator", style="cyan", no_wrap=True)
        table.add_column("KPI", no_wrap=True)
        table.add_column("Where")
        table.add_column("Gap")
        table.add_column("Recommendation")
        for g in rows:
            table.add_row(
                g.evaluator,
                g.kpi_id or "—",
                locator_label(g.locator),
                g.description,
                g.recommendation or "",
            )
        console.print(table)


def render(
    gaps: list[Gap],
    readiness: Readiness,
    scorecard: Scorecard,
    unaligned: list[Gap] | None = None,
) -> None:
    console = Console()

    if scorecard.kpi_results:
        console.print(_scorecard_table(scorecard))

    if gaps:
        _gap_tables(gaps, console)
    else:
        console.print("[green]No gaps tied to your KPIs.[/green]")

    unaligned = unaligned or []
    if unaligned:
        table = Table(
            title=f"Unaligned observations ({len(unaligned)})",
            title_style="dim",
            show_lines=False,
        )
        table.add_column("Evaluator", style="dim", no_wrap=True)
        table.add_column("Where", style="dim")
        table.add_column("Observation", style="dim")
        for g in unaligned:
            table.add_row(g.evaluator, locator_label(g.locator), g.description)
        console.print(table)
        console.print(
            f"[dim]{len(unaligned)} observation(s) could not be tied to a KPI — "
            "consider expanding your goal config.[/dim]"
        )

    impacts_desc = sorted(Impact, key=lambda i: -i.rank)
    chips = [
        f"[{_IMPACT_STYLE[i]}]{scorecard.counts[i]} {i.value}[/{_IMPACT_STYLE[i]}]"
        for i in impacts_desc
        if scorecard.counts.get(i)
    ]
    breakdown = "  ".join(chips) if chips else "no aligned gaps"

    color = _READINESS_COLOR[readiness]
    console.print(
        Panel(
            f"[bold {color}]{scorecard.summary or readiness.value}[/bold {color}]\n{breakdown}",
            border_style=color,
        )
    )
