from postlight.scanners.base import Finding, Severity
from postlight.verdict import Verdict, compute


def _f(sev: Severity) -> Finding:
    return Finding(severity=sev, source_tool="test", rule_id="r", message="m")


def test_no_findings_ships():
    verdict, _ = compute([])
    assert verdict == Verdict.SHIP


def test_only_low_and_medium_ships():
    verdict, counts = compute([_f(Severity.LOW), _f(Severity.MEDIUM), _f(Severity.INFO)])
    assert verdict == Verdict.SHIP
    assert counts[Severity.MEDIUM] == 1


def test_high_triggers_review():
    verdict, counts = compute([_f(Severity.HIGH), _f(Severity.LOW)])
    assert verdict == Verdict.REVIEW
    assert counts[Severity.HIGH] == 1


def test_critical_triggers_hold():
    verdict, _ = compute([_f(Severity.CRITICAL), _f(Severity.HIGH)])
    assert verdict == Verdict.HOLD


def test_critical_overrides_high():
    findings = [_f(Severity.CRITICAL)] * 2 + [_f(Severity.HIGH)] * 5
    verdict, counts = compute(findings)
    assert verdict == Verdict.HOLD
    assert counts[Severity.HIGH] == 5
    assert counts[Severity.CRITICAL] == 2
