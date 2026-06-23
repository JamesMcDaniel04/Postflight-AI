"""Turn aligned gaps into ranked, goal-linked recommendations.

Runs over ALIGNED gaps only — every recommendation traces to a KPI and goal in
the ratified config by construction, so it cannot drift off-goal. Gaps are
clustered per KPI and ranked by a priority score that blends the human-set KPI
weight, gap impact, confidence, and how far the KPI is from its target.

Each Recommendation is triple-linked (gap_ids + kpi_id + goal_id) — exactly the
payload a later auto-fix tier (`ascent fix`) consumes, unchanged.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .evaluators.base import Gap, Impact
from .goals import GoalConfig
from .scoring import KpiResult


@dataclass
class Recommendation:
    id: str
    title: str
    action: str
    rationale: str
    kpi_id: str
    goal_id: str
    gap_ids: list[str] = field(default_factory=list)
    effort_hint: str = "M"  # S | M | L
    priority_score: float = 0.0


def _shortfall(result: KpiResult | None) -> float:
    """How far the KPI is from its target, normalized to ~0..1 (floored at 0.1
    so a gap on a passing KPI still ranks). Unmeasured -> 0.5 (unknown)."""
    if result is None or result.actual is None:
        return 0.5
    target = result.target or 1.0
    if result.comparator == "lte":
        gap = (result.actual - target) / abs(target)
    else:  # gte / eq
        gap = (target - result.actual) / abs(target)
    return max(0.1, min(1.0, gap))


def _effort(impacts: set[Impact]) -> str:
    if Impact.BLOCKER in impacts:
        return "L"
    if Impact.MAJOR in impacts:
        return "M"
    return "S"


def recommend(
    aligned_gaps: list[Gap],
    config: GoalConfig,
    kpi_results: list[KpiResult],
) -> list[Recommendation]:
    by_kpi: dict[str, list[Gap]] = defaultdict(list)
    for gap in aligned_gaps:
        if gap.kpi_id:
            by_kpi[gap.kpi_id].append(gap)

    result_by_id = {r.kpi_id: r for r in kpi_results}
    recs: list[Recommendation] = []
    for kpi_id, gaps in by_kpi.items():
        kpi = config.kpi(kpi_id)
        if kpi is None:
            continue  # belt-and-suspenders: quarantine already removed these
        rep = max(gaps, key=lambda g: (g.impact.rank, g.confidence))
        mean_conf = sum(g.confidence for g in gaps) / len(gaps)
        shortfall = _shortfall(result_by_id.get(kpi_id))
        priority = kpi.weight * (rep.impact.rank + 1) * mean_conf * shortfall
        recs.append(Recommendation(
            id=f"rec-{kpi_id}",
            title=rep.description,
            action=rep.recommendation or f"Address the friction blocking {kpi.name}.",
            rationale=f"Moves {kpi.name} toward its target ({kpi.comparator} {kpi.target:g}).",
            kpi_id=kpi_id,
            goal_id=kpi.goal_id,
            gap_ids=[g.check_id for g in gaps],
            effort_hint=_effort({g.impact for g in gaps}),
            priority_score=round(priority, 3),
        ))

    recs.sort(key=lambda r: -r.priority_score)
    return recs
