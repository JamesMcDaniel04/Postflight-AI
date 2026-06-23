"""The AGGREGATE + DECIDE stage: milestone readiness over goals/KPIs.

``assess`` replaces the old security ``compute`` and keeps its
``(verdict, breakdown)`` tuple shape — the breakdown grows from a bare Counter
into a Scorecard. It consumes only *aligned* gaps; quarantined gaps cannot move
the verdict.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from enum import Enum

from .evaluators.base import Gap, Impact
from .goals import GoalConfig
from .scoring import KpiResult


class Readiness(Enum):
    ON_TRACK = "ON_TRACK"
    NEEDS_WORK = "NEEDS_WORK"
    BLOCKED = "BLOCKED"


@dataclass
class Scorecard:
    kpi_results: list[KpiResult]
    counts: Counter
    milestone_ready: bool
    unaligned_count: int = 0
    blocking_kpi_id: str | None = None
    summary: str = ""


def _fmt(value: float | None) -> str:
    if value is None:
        return "—"
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _summarize(
    readiness: Readiness,
    config: GoalConfig,
    required_results: list[KpiResult],
    gaps_by_kpi: dict[str, list[Gap]],
) -> tuple[str | None, str]:
    name = config.milestone.name or config.milestone.id or "the next milestone"
    if readiness == Readiness.ON_TRACK:
        return None, f"ON_TRACK toward {name} — every required KPI is met"

    rank = {"fail": 0, "unmeasured": 1, "near": 2, "pass": 3}

    def severity_key(result: KpiResult):
        has_blocker = any(g.impact == Impact.BLOCKER for g in gaps_by_kpi.get(result.kpi_id, []))
        return (rank.get(result.status, 3), 0 if has_blocker else 1, -result.weight)

    candidates = [r for r in required_results if r.status != "pass"] or required_results
    if not candidates:
        return None, f"{readiness.value} toward {name}"
    worst = min(candidates, key=severity_key)

    if worst.status == "unmeasured" or worst.actual is None:
        detail = f"{worst.name} unmeasured"
    else:
        unit = f" {worst.unit}" if worst.unit and worst.unit != "ratio" else ""
        detail = f"{worst.name} {_fmt(worst.actual)}/{_fmt(worst.target)}{unit}"
    return worst.kpi_id, f"{readiness.value} toward {name} — {detail}"


def _decide_weighted(config: GoalConfig, required_results: list[KpiResult], flags: dict) -> Readiness:
    total_w = sum(r.weight for r in required_results) or 1
    passing_w = sum(r.weight for r in required_results if r.status == "pass")
    ratio = passing_w / total_w
    threshold = config.milestone.threshold
    if flags["blocker"] or (flags["fail"] and ratio < threshold):
        return Readiness.BLOCKED
    if ratio >= threshold and not flags["major"] and not flags["soft"]:
        return Readiness.ON_TRACK
    return Readiness.NEEDS_WORK


def _decide(
    config: GoalConfig,
    required_results: list[KpiResult],
    gaps_by_kpi: dict[str, list[Gap]],
) -> Readiness:
    required_ids = set(config.milestone.required_kpi_ids) or config.kpi_ids()

    def has_impact_on_required(impact: Impact) -> bool:
        return any(g.impact == impact for k in required_ids for g in gaps_by_kpi.get(k, []))

    flags = {
        "fail": any(r.status == "fail" for r in required_results),
        "blocker": has_impact_on_required(Impact.BLOCKER),
        "major": has_impact_on_required(Impact.MAJOR),
        "soft": any(r.status in ("near", "unmeasured") for r in required_results),
    }

    if config.milestone.gate == "weighted_threshold":
        return _decide_weighted(config, required_results, flags)
    if flags["fail"] or flags["blocker"]:
        return Readiness.BLOCKED
    return Readiness.NEEDS_WORK if (flags["soft"] or flags["major"]) else Readiness.ON_TRACK


def assess(
    aligned_gaps: list[Gap],
    config: GoalConfig,
    kpi_results: list[KpiResult],
    unaligned_count: int = 0,
) -> tuple[Readiness, Scorecard]:
    counts = Counter(g.impact for g in aligned_gaps)

    gaps_by_kpi: dict[str, list[Gap]] = defaultdict(list)
    for gap in aligned_gaps:
        if gap.kpi_id:
            gaps_by_kpi[gap.kpi_id].append(gap)

    required_ids = set(config.milestone.required_kpi_ids) or config.kpi_ids()
    result_by_id = {r.kpi_id: r for r in kpi_results}

    # Record which blocker/major gaps sit on each KPI (scorecard detail).
    for result in kpi_results:
        result.blocking_gap_ids = [
            g.check_id
            for g in gaps_by_kpi.get(result.kpi_id, [])
            if g.impact in (Impact.BLOCKER, Impact.MAJOR)
        ]

    required_results = [result_by_id[k] for k in required_ids if k in result_by_id]

    readiness = _decide(config, required_results, gaps_by_kpi)
    # A non-required KPI failing outright is worth a NEEDS_WORK nudge.
    if readiness == Readiness.ON_TRACK and any(
        r.status == "fail" and r.kpi_id not in required_ids for r in kpi_results
    ):
        readiness = Readiness.NEEDS_WORK

    blocking_kpi_id, summary = _summarize(readiness, config, required_results, gaps_by_kpi)
    scorecard = Scorecard(
        kpi_results=kpi_results,
        counts=counts,
        milestone_ready=(readiness == Readiness.ON_TRACK),
        unaligned_count=unaligned_count,
        blocking_kpi_id=blocking_kpi_id,
        summary=summary,
    )
    return readiness, scorecard
