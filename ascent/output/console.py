from __future__ import annotations

from collections import Counter

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..scanners.base import Finding, Severity
from ..verdict import Verdict


_VERDICT_COLOR = {
    Verdict.SHIP: "green",
    Verdict.REVIEW: "yellow",
    Verdict.HOLD: "red",
}

_SEVERITY_STYLE = {
    Severity.CRITICAL: "bold red",
    Severity.HIGH: "red",
    Severity.MEDIUM: "yellow",
    Severity.LOW: "blue",
    Severity.INFO: "dim",
}


def render(findings: list[Finding], verdict: Verdict, counts: Counter) -> None:
    console = Console()

    severities_desc = sorted(Severity, key=lambda s: -s.rank)

    if findings:
        for sev in severities_desc:
            sev_findings = [f for f in findings if f.severity == sev]
            if not sev_findings:
                continue
            table = Table(
                title=f"{sev.value.upper()} ({len(sev_findings)})",
                title_style=_SEVERITY_STYLE[sev],
                show_lines=False,
            )
            table.add_column("Tool", style="cyan", no_wrap=True)
            table.add_column("Rule", no_wrap=True)
            table.add_column("Location")
            table.add_column("Message")
            for finding in sev_findings:
                location = finding.file or ""
                if finding.line:
                    location = f"{location}:{finding.line}"
                table.add_row(finding.source_tool, finding.rule_id, location, finding.message)
            console.print(table)
    else:
        console.print("[green]No findings.[/green]")

    summary_parts = [
        f"[{_SEVERITY_STYLE[sev]}]{counts[sev]} {sev.value}[/{_SEVERITY_STYLE[sev]}]"
        for sev in severities_desc
        if counts[sev]
    ]
    summary = "  ".join(summary_parts) if summary_parts else "no findings"

    color = _VERDICT_COLOR[verdict]
    console.print(
        Panel(
            f"[bold {color}]{verdict.value}[/bold {color}]\n{summary}",
            border_style=color,
        )
    )
