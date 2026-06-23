from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from ..scanners.base import Finding, Severity
from ..verdict import Verdict


STICKY_COMMENT_MARKER = "<!-- postlight-marker -->"

ANNOTATIONS_CAP = 50

_CONCLUSION = {
    Verdict.SHIP: "success",
    Verdict.REVIEW: "neutral",
    Verdict.HOLD: "failure",
}

_ANNOTATION_LEVEL = {
    Severity.CRITICAL: "failure",
    Severity.HIGH: "failure",
    Severity.MEDIUM: "warning",
    Severity.LOW: "notice",
    Severity.INFO: "notice",
}


def conclusion_for(verdict: Verdict) -> str:
    return _CONCLUSION[verdict]


def title_for(verdict: Verdict, counts: Counter) -> str:
    chips = " · ".join(
        f"{counts[sev]} {sev.value}"
        for sev in sorted(Severity, key=lambda s: -s.rank)
        if counts[sev]
    )
    return f"{verdict.value} ({chips})" if chips else f"{verdict.value} (no findings)"


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


def render_findings_table(
    findings: list[Finding],
    counts: Counter,
    repo: str,
    sha: str,
    workspace: str,
) -> str:
    if not findings:
        return "No findings."

    severities_desc = sorted(Severity, key=lambda s: -s.rank)
    chips = [f"{counts[sev]} {sev.value}" for sev in severities_desc if counts[sev]]
    lines: list[str] = [" · ".join(chips), ""]

    for sev in severities_desc:
        sev_findings = [f for f in findings if f.severity == sev]
        if not sev_findings:
            continue
        lines.append(f"### {sev.value.upper()} ({len(sev_findings)})")
        lines.append("")
        lines.append("| Tool | Rule | Location | Message |")
        lines.append("|---|---|---|---|")
        for f in sev_findings:
            location = ""
            rel = relpath(f.file, workspace)
            if rel:
                link = blob_link(repo, sha, rel, f.line)
                label = f"{rel}:{f.line}" if f.line else rel
                location = f"[`{label}`]({link})"
            msg = _md_escape(f.message or "")
            lines.append(f"| {f.source_tool} | `{f.rule_id}` | {location} | {msg} |")
        lines.append("")

    return "\n".join(lines)


def render_pr_comment_body(
    findings: list[Finding],
    verdict: Verdict,
    counts: Counter,
    repo: str,
    sha: str,
    workspace: str,
) -> str:
    table = render_findings_table(findings, counts, repo, sha, workspace)
    return "\n".join([
        STICKY_COMMENT_MARKER,
        "## Postlight Code",
        "",
        f"**Verdict:** `{verdict.value}` · commit [`{sha[:7]}`](https://github.com/{repo}/commit/{sha})",
        "",
        table,
    ])


def select_annotations(
    findings: list[Finding],
    workspace: str,
    cap: int = ANNOTATIONS_CAP,
) -> list[dict[str, Any]]:
    annotatable = [f for f in findings if f.file]
    annotatable.sort(
        key=lambda f: (
            -f.severity.rank,
            f.source_tool,
            f.file or "",
            f.line or 0,
            f.rule_id,
        )
    )
    out: list[dict[str, Any]] = []
    for f in annotatable[:cap]:
        rel = relpath(f.file, workspace) or ""
        line = f.line or 1
        out.append({
            "path": rel,
            "start_line": line,
            "end_line": line,
            "annotation_level": _ANNOTATION_LEVEL[f.severity],
            "title": f"{f.source_tool}: {f.rule_id}",
            "message": f.message or f.rule_id,
        })
    return out


def _md_escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").replace("\r", " ")
