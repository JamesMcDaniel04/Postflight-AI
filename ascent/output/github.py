from __future__ import annotations

from pathlib import Path
from typing import Any

from ..evaluators.base import Gap, Impact, Locator
from ..verdict import Readiness, Scorecard

STICKY_COMMENT_MARKER = "<!-- ascent-marker -->"

ANNOTATIONS_CAP = 50

_CONCLUSION = {
    Readiness.ON_TRACK: "success",
    Readiness.NEEDS_WORK: "neutral",
    Readiness.BLOCKED: "failure",
}

_ANNOTATION_LEVEL = {
    Impact.BLOCKER: "failure",
    Impact.MAJOR: "failure",
    Impact.MODERATE: "warning",
    Impact.MINOR: "notice",
    Impact.INFO: "notice",
}


def conclusion_for(readiness: Readiness) -> str:
    return _CONCLUSION[readiness]


def title_for(readiness: Readiness, scorecard: Scorecard) -> str:
    return scorecard.summary or readiness.value


def blob_link(repo: str, sha: str, path: str, line: int | None) -> str:
    base = f"https://github.com/{repo}/blob/{sha}/{path}"
    return f"{base}#L{line}" if line else base


def relpath(abs_path: str | None, workspace: str) -> str | None:
    if not abs_path:
        return None
    try:
        return str(Path(abs_path).resolve().relative_to(Path(workspace).resolve()))
    except (ValueError, OSError):
        return abs_path.lstrip("/")


def locator_link(locator: Locator | None, repo: str, sha: str, workspace: str) -> str:
    """Render a locator as markdown, dispatching on its kind.

    File locators become GitHub blob links (the verbatim old behavior); web /
    api locators link out to the URL; everything else is a code span.
    """

    if locator is None:
        return ""
    if locator.kind == "file":
        rel = relpath(locator.value, workspace) or locator.value
        label = f"{rel}:{locator.line}" if locator.line else rel
        return f"[`{label}`]({blob_link(repo, sha, rel, locator.line)})"
    if locator.value.startswith(("http://", "https://")):
        return f"[`{locator.value}`]({locator.value})"
    return f"`{locator.value}`"


def render_scorecard(scorecard: Scorecard) -> str:
    if not scorecard.kpi_results:
        return ""
    lines = ["### KPI scorecard", "", "| KPI | Target | Actual | Status | Samples |", "|---|---|---|---|---|"]
    for r in scorecard.kpi_results:
        target = f"{r.comparator} {r.target:g}"
        actual = "—" if r.actual is None else f"{r.actual:g}"
        lines.append(f"| {_md_escape(r.name)} | {target} | {actual} | {r.status} | {r.sample_size} |")
    lines.append("")
    return "\n".join(lines)


def render_gap_table(gaps: list[Gap], repo: str, sha: str, workspace: str) -> str:
    if not gaps:
        return "No gaps tied to your KPIs."

    impacts_desc = sorted(Impact, key=lambda i: -i.rank)
    lines: list[str] = []
    for impact in impacts_desc:
        rows = [g for g in gaps if g.impact == impact]
        if not rows:
            continue
        lines.append(f"### {impact.value.upper()} ({len(rows)})")
        lines.append("")
        lines.append("| Evaluator | KPI | Where | Gap | Recommendation |")
        lines.append("|---|---|---|---|---|")
        for g in rows:
            where = locator_link(g.locator, repo, sha, workspace)
            lines.append(
                f"| {g.evaluator} | {g.kpi_id or '—'} | {where} | "
                f"{_md_escape(g.description)} | {_md_escape(g.recommendation or '')} |"
            )
        lines.append("")
    return "\n".join(lines)


def render_unaligned(gaps: list[Gap]) -> str:
    if not gaps:
        return ""
    lines = [
        f"### Unaligned observations ({len(gaps)})",
        "",
        "_Not tied to any KPI — excluded from the verdict. Consider expanding your goal config._",
        "",
        "| Evaluator | Observation |",
        "|---|---|",
    ]
    for g in gaps:
        lines.append(f"| {g.evaluator} | {_md_escape(g.description)} |")
    lines.append("")
    return "\n".join(lines)


def render_recommendations(recommendations: list, top: int = 10) -> str:
    if not recommendations:
        return ""
    lines = ["### Top recommendations", ""]
    for i, rec in enumerate(recommendations[:top], start=1):
        lines.append(
            f"{i}. **[{rec.kpi_id}]** {_md_escape(rec.action)} "
            f"_(clears {len(rec.gap_ids)} gap(s), effort {rec.effort_hint})_"
        )
    lines.append("")
    return "\n".join(lines)


def render_pr_comment_body(
    gaps: list[Gap],
    readiness: Readiness,
    scorecard: Scorecard,
    repo: str,
    sha: str,
    workspace: str,
    unaligned: list[Gap] | None = None,
    recommendations: list | None = None,
) -> str:
    parts = [
        STICKY_COMMENT_MARKER,
        "## Ascent",
        "",
        f"**Readiness:** `{readiness.value}` · commit "
        f"[`{sha[:7]}`](https://github.com/{repo}/commit/{sha})",
        "",
        scorecard.summary,
        "",
        render_scorecard(scorecard),
        render_recommendations(recommendations or []),
        render_gap_table(gaps, repo, sha, workspace),
    ]
    unaligned_md = render_unaligned(unaligned or [])
    if unaligned_md:
        parts.append("")
        parts.append(unaligned_md)
    return "\n".join(p for p in parts if p is not None)


def select_annotations(
    gaps: list[Gap],
    workspace: str,
    cap: int = ANNOTATIONS_CAP,
) -> list[dict[str, Any]]:
    annotatable = [g for g in gaps if g.locator and g.locator.kind == "file"]
    annotatable.sort(
        key=lambda g: (
            -g.impact.rank,
            g.evaluator,
            g.locator.value if g.locator else "",
            g.locator.line or 0 if g.locator else 0,
            g.check_id,
        )
    )
    out: list[dict[str, Any]] = []
    for g in annotatable[:cap]:
        assert g.locator is not None  # guaranteed by the filter above
        rel = relpath(g.locator.value, workspace) or ""
        line = g.locator.line or 1
        out.append({
            "path": rel,
            "start_line": line,
            "end_line": line,
            "annotation_level": _ANNOTATION_LEVEL[g.impact],
            "title": f"{g.evaluator}: {g.check_id}",
            "message": g.description or g.check_id,
        })
    return out


def _md_escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").replace("\r", " ")
