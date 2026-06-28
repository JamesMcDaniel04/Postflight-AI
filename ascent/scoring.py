"""Reduce raw KPI observations into per-KPI results (the scorecard rows)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .evaluators.base import KpiObservation
from .goals import KPI

NEAR_TOLERANCE = 0.10  # within 10% of target counts as "near" rather than fail


@dataclass
class KpiResult:
    kpi_id: str
    name: str
    target: float
    comparator: str
    actual: float | None
    status: str  # pass | near | fail | unmeasured
    sample_size: int
    unit: str = ""
    weight: int = 3
    contributing_evaluators: list[str] = field(default_factory=list)
    blocking_gap_ids: list[str] = field(default_factory=list)


def _passes(actual: float, target: float, comparator: str) -> bool:
    if comparator == "gte":
        return actual >= target
    if comparator == "lte":
        return actual <= target
    return abs(actual - target) <= NEAR_TOLERANCE * (abs(target) or 1.0)


def _is_near(actual: float, target: float, comparator: str) -> bool:
    band = NEAR_TOLERANCE * (abs(target) or 1.0)
    if comparator == "gte":
        return actual >= target - band
    if comparator == "lte":
        return actual <= target + band
    return abs(actual - target) <= 2 * band


def _classify(actual: float, kpi: KPI, sample_size: int, min_sample_size: int) -> str:
    if _passes(actual, kpi.target, kpi.comparator):
        # Too little evidence to certify a pass — cap at "near" so a single
        # flaky run cannot flip the verdict to ON_TRACK.
        if sample_size < min_sample_size:
            return "near"
        return "pass"
    if _is_near(actual, kpi.target, kpi.comparator):
        return "near"
    return "fail"


# Which source kind each evaluator counts as (a KPI's `source` selects its
# evaluator). Unknown evaluators (e.g. the demo injector) count for any source.
_SOURCE_KIND = {"persona_agent": "persona", "journey": "journey", "replay": "replay"}
# Trust ground-truth analytics over simulated journeys over a single persona run
# when several measure the same KPI — folded into the weighted mean only.
_TRUST = {"replay": 3, "journey": 2, "persona_agent": 1}


def _matches_source(evaluator: str, kpi_source: str) -> bool:
    if kpi_source == "any":
        return True
    kind = _SOURCE_KIND.get(evaluator)
    return kind is None or kind == kpi_source


def roll_observations(
    observations: list[KpiObservation],
    kpis: list[KPI],
    min_sample_size: int = 1,
) -> list[KpiResult]:
    """One KpiResult per configured KPI. Only observations whose evaluator
    matches the KPI's ``source`` count; when several sources measure a KPI,
    replay outweighs journey outweighs persona. KPIs with no matching
    observations come back ``unmeasured``."""

    by_kpi: dict[str, list[KpiObservation]] = defaultdict(list)
    for obs in observations:
        by_kpi[obs.kpi_id].append(obs)

    results: list[KpiResult] = []
    for kpi in kpis:
        obs = [o for o in by_kpi.get(kpi.id, []) if _matches_source(o.evaluator, kpi.source)]
        if not obs:
            results.append(
                KpiResult(
                    kpi_id=kpi.id, name=kpi.name, target=kpi.target,
                    comparator=kpi.comparator, actual=None, status="unmeasured",
                    sample_size=0, unit=kpi.unit, weight=kpi.weight,
                )
            )
            continue
        sample_total = sum(max(o.sample_weight, 1) for o in obs)
        trust_total = sum(max(o.sample_weight, 1) * _TRUST.get(o.evaluator, 1) for o in obs)
        actual = sum(o.value * max(o.sample_weight, 1) * _TRUST.get(o.evaluator, 1) for o in obs) / trust_total
        results.append(
            KpiResult(
                kpi_id=kpi.id, name=kpi.name, target=kpi.target,
                comparator=kpi.comparator, actual=actual,
                status=_classify(actual, kpi, sample_total, min_sample_size),
                sample_size=sample_total, unit=kpi.unit, weight=kpi.weight,
                contributing_evaluators=sorted({o.evaluator for o in obs}),
            )
        )
    return results
