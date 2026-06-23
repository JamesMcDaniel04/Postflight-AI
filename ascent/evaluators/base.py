from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from ..goals import GoalConfig


class Impact(Enum):
    """How badly a gap hurts the app's ability to hit its goal.

    Replaces the security Severity enum. Same ordered-label-with-rank mechanism,
    so every ``sorted(..., key=lambda x: -x.rank)`` consumer keeps working.
    """

    BLOCKER = "blocker"
    MAJOR = "major"
    MODERATE = "moderate"
    MINOR = "minor"
    INFO = "info"

    @property
    def rank(self) -> int:
        order = ["info", "minor", "moderate", "major", "blocker"]
        return order.index(self.value)


@dataclass
class Locator:
    """Surface-neutral position of a gap, replacing the old file/line pair.

    ``kind`` is one of file | route | screen | endpoint. ``line`` is only
    meaningful for ``kind == "file"`` (it preserves the GitHub blob-link path).
    """

    kind: str
    value: str
    line: int | None = None


@dataclass
class Gap:
    """A normalized gap between the app's current behavior and its goal.

    The descendant of the security ``Finding`` — same flat shape so every
    downstream stage stays producer-agnostic. ``kpi_id`` is the load-bearing
    link back to the goal config; a gap whose kpi_id is not in the config is
    quarantined out of the verdict. Always build via ``goals.make_gap`` so the
    goal-linkage fields are never written ad hoc.
    """

    impact: Impact
    evaluator: str
    check_id: str
    description: str
    locator: Locator | None = None
    kpi_id: str | None = None
    persona: str | None = None
    evidence: list[str] = field(default_factory=list)
    recommendation: str | None = None
    confidence: float = 1.0
    extra: dict = field(default_factory=dict)


@dataclass
class KpiObservation:
    """A single measurement of a KPI emitted by an evaluator.

    ``scoring.roll_observations`` reduces these by kpi_id into KpiResults.
    """

    kpi_id: str
    value: float
    evaluator: str
    sample_weight: int = 1


@dataclass
class EvaluationResult:
    """What one evaluator produces: gaps plus the KPI measurements it made."""

    gaps: list[Gap] = field(default_factory=list)
    observations: list[KpiObservation] = field(default_factory=list)


@dataclass
class EvaluatorContext:
    """Everything an evaluator needs to run, resolved by the run layer.

    ``driver`` and ``judge`` are typed loosely here — the Driver and Judge
    ports arrive in a later phase; in Phase 0 they are ``None``.
    """

    config: GoalConfig
    target: str
    driver: object | None = None
    judge: object | None = None
    budget: dict = field(default_factory=dict)


class Evaluator(Protocol):
    """A producer of gaps + KPI observations.

    Same two-method contract as the old Scanner protocol, renamed: the run
    loop skips any evaluator whose ``is_available`` returns False, exactly as
    it skipped missing scanner binaries.
    """

    name: str

    def is_available(self, ctx: EvaluatorContext) -> bool: ...

    def evaluate(self, ctx: EvaluatorContext) -> EvaluationResult: ...
