from __future__ import annotations

from collections import Counter
from enum import Enum

from .scanners.base import Finding, Severity


class Verdict(Enum):
    SHIP = "SHIP"
    REVIEW = "REVIEW"
    HOLD = "HOLD"


def compute(findings: list[Finding]) -> tuple[Verdict, Counter]:
    counts = Counter(f.severity for f in findings)
    if counts[Severity.CRITICAL] > 0:
        return Verdict.HOLD, counts
    if counts[Severity.HIGH] > 0:
        return Verdict.REVIEW, counts
    return Verdict.SHIP, counts
