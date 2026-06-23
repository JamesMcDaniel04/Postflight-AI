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


_CONSOLIDATE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "action": {"type": "string"},
        "effort_hint": {"type": "string", "enum": ["S", "M", "L"]},
    },
    "required": ["title", "action", "effort_hint"],
    "additionalProperties": False,
}


def _consolidate(judge, kpi, gaps: list[Gap], fallback: tuple[str, str, str]) -> tuple[str, str, str]:
    """Merge a multi-gap cluster into one recommendation, grounded strictly in
    the cluster's evidence. Falls back to the deterministic fields on any error
    or empty result, so the engine never depends on the LLM being reachable."""
    evidence = "\n".join(
        f"- [{g.impact.value}] {g.description}" + (f" (suggested: {g.recommendation})" if g.recommendation else "")
        for g in gaps
    )
    prompt = (
        f"KPI: {kpi.name} (target {kpi.comparator} {kpi.target:g}).\n"
        f"These gaps were observed and all affect this KPI:\n{evidence}\n\n"
        "Write ONE consolidated recommendation most likely to move this KPI toward its target. "
        "Ground it strictly in the evidence above — do not invent new problems. "
        "Provide a short title, a concrete action, and an effort estimate (S, M, or L)."
    )
    try:
        out = judge.score("You consolidate observed gaps into one goal-linked recommendation.", prompt, _CONSOLIDATE_SCHEMA)
    except Exception:
        out = {}
    if not out:
        return fallback
    return (out.get("title") or fallback[0], out.get("action") or fallback[1], out.get("effort_hint") or fallback[2])


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
    judge=None,
) -> list[Recommendation]:
    """Cluster aligned gaps per KPI and rank them. When ``judge`` is provided,
    multi-gap clusters get an LLM consolidation pass (grounded in the cluster's
    evidence); otherwise the highest-impact gap's wording is used verbatim."""
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
        title = rep.description
        action = rep.recommendation or f"Address the friction blocking {kpi.name}."
        effort = _effort({g.impact for g in gaps})
        if judge is not None and len(gaps) >= 2:
            title, action, effort = _consolidate(judge, kpi, gaps, (title, action, effort))

        mean_conf = sum(g.confidence for g in gaps) / len(gaps)
        shortfall = _shortfall(result_by_id.get(kpi_id))
        priority = kpi.weight * (rep.impact.rank + 1) * mean_conf * shortfall
        recs.append(Recommendation(
            id=f"rec-{kpi_id}",
            title=title,
            action=action,
            rationale=f"Moves {kpi.name} toward its target ({kpi.comparator} {kpi.target:g}).",
            kpi_id=kpi_id,
            goal_id=kpi.goal_id,
            gap_ids=[g.check_id for g in gaps],
            effort_hint=effort,
            priority_score=round(priority, 3),
        ))

    recs.sort(key=lambda r: -r.priority_score)
    return recs
