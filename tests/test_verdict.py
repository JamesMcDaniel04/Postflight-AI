from __future__ import annotations

from ascent.evaluators.base import Impact, Locator
from ascent.goals import KPI, Goal, GoalConfig, Milestone, make_gap
from ascent.scoring import KpiResult
from ascent.verdict import Readiness, assess


def _config(required=("k1", "k2"), gate="all_required", threshold=1.0) -> GoalConfig:
    kpis = [
        KPI(id="k1", goal_id="g", name="Booking completion", metric="task_success_rate",
            target=0.8, comparator="gte", unit="ratio", weight=5),
        KPI(id="k2", goal_id="g", name="Time to book", metric="time_to_complete_s",
            target=180, comparator="lte", unit="s", weight=3),
        KPI(id="k3", goal_id="g", name="Drop-off", metric="drop_off_rate",
            target=0.3, comparator="lte", unit="ratio", weight=1),
    ]
    return GoalConfig(
        version=1, product="P", target="web://x", goal=Goal(id="g", statement="s"),
        milestone=Milestone(id="m", name="Public Beta", required_kpi_ids=list(required),
                            gate=gate, threshold=threshold),
        kpis=kpis,
    )


def _result(kpi_id, status, *, actual=None, target=0.8, weight=5, name=None, comparator="gte", unit="ratio"):
    return KpiResult(kpi_id=kpi_id, name=name or kpi_id, target=target, comparator=comparator,
                     actual=actual, status=status, sample_size=5, weight=weight, unit=unit)


def _gap(kpi_id, impact):
    return make_gap(impact=impact, evaluator="persona_agent", check_id=f"c-{kpi_id}",
                    description="friction", kpi_id=kpi_id, locator=Locator(kind="route", value="/"))


def test_all_required_pass_is_on_track():
    config = _config()
    results = [_result("k1", "pass"), _result("k2", "pass", comparator="lte", target=180),
               _result("k3", "pass", comparator="lte", target=0.3, weight=1)]
    readiness, scorecard = assess([], config, results)
    assert readiness == Readiness.ON_TRACK
    assert scorecard.milestone_ready is True
    assert "ON_TRACK toward Public Beta" in scorecard.summary


def test_required_fail_blocks():
    config = _config()
    results = [_result("k1", "fail", actual=0.4), _result("k2", "pass", comparator="lte", target=180),
               _result("k3", "pass", comparator="lte", target=0.3, weight=1)]
    readiness, _ = assess([], config, results)
    assert readiness == Readiness.BLOCKED


def test_required_unmeasured_needs_work():
    config = _config()
    results = [_result("k1", "unmeasured"), _result("k2", "pass", comparator="lte", target=180),
               _result("k3", "pass", comparator="lte", target=0.3, weight=1)]
    readiness, _ = assess([], config, results)
    assert readiness == Readiness.NEEDS_WORK


def test_required_near_needs_work_and_names_blocking_kpi():
    config = _config()
    results = [_result("k1", "near", actual=0.71, name="Booking completion"),
               _result("k2", "pass", comparator="lte", target=180),
               _result("k3", "pass", comparator="lte", target=0.3, weight=1)]
    readiness, scorecard = assess([], config, results)
    assert readiness == Readiness.NEEDS_WORK
    assert scorecard.blocking_kpi_id == "k1"
    assert "Booking completion" in scorecard.summary
    assert "0.71/0.8" in scorecard.summary


def test_blocker_gap_on_required_blocks_even_when_kpis_pass():
    config = _config()
    results = [_result("k1", "pass"), _result("k2", "pass", comparator="lte", target=180),
               _result("k3", "pass", comparator="lte", target=0.3, weight=1)]
    readiness, scorecard = assess([_gap("k1", Impact.BLOCKER)], config, results)
    assert readiness == Readiness.BLOCKED
    # the blocking gap is recorded on the KPI's scorecard row
    k1 = next(r for r in scorecard.kpi_results if r.kpi_id == "k1")
    assert k1.blocking_gap_ids == ["c-k1"]


def test_major_gap_on_required_needs_work():
    config = _config()
    results = [_result("k1", "pass"), _result("k2", "pass", comparator="lte", target=180),
               _result("k3", "pass", comparator="lte", target=0.3, weight=1)]
    readiness, _ = assess([_gap("k1", Impact.MAJOR)], config, results)
    assert readiness == Readiness.NEEDS_WORK


def test_blocker_on_non_required_kpi_does_not_block():
    config = _config(required=("k1", "k2"))
    results = [_result("k1", "pass"), _result("k2", "pass", comparator="lte", target=180),
               _result("k3", "pass", comparator="lte", target=0.3, weight=1)]
    readiness, _ = assess([_gap("k3", Impact.BLOCKER)], config, results)
    assert readiness == Readiness.ON_TRACK


def test_non_required_fail_nudges_to_needs_work():
    config = _config(required=("k1", "k2"))
    results = [_result("k1", "pass"), _result("k2", "pass", comparator="lte", target=180),
               _result("k3", "fail", comparator="lte", target=0.3, weight=1)]
    readiness, _ = assess([], config, results)
    assert readiness == Readiness.NEEDS_WORK


def test_no_kpis_is_trivially_on_track():
    config = GoalConfig(version=1, product="P", target="web://x", goal=Goal(id="g", statement="s"),
                        milestone=Milestone(id="m", name="M"))
    readiness, _ = assess([], config, [])
    assert readiness == Readiness.ON_TRACK


# ---- weighted_threshold gate -------------------------------------------------

def test_weighted_threshold_below_bar_with_fail_blocks():
    config = _config(gate="weighted_threshold", threshold=0.8)
    results = [_result("k1", "pass", weight=5), _result("k2", "fail", comparator="lte", target=180, weight=3)]
    readiness, _ = assess([], config, results)  # passing weight 5/8 = 0.625 < 0.8, has fail
    assert readiness == Readiness.BLOCKED


def test_weighted_threshold_below_bar_without_fail_needs_work():
    config = _config(gate="weighted_threshold", threshold=0.8)
    results = [_result("k1", "pass", weight=5), _result("k2", "near", comparator="lte", target=180, weight=3)]
    readiness, _ = assess([], config, results)  # 0.625 < 0.8 but no outright fail
    assert readiness == Readiness.NEEDS_WORK


def test_weighted_threshold_met_is_on_track():
    config = _config(gate="weighted_threshold", threshold=0.6)
    results = [_result("k1", "pass", weight=5), _result("k2", "fail", comparator="lte", target=180, weight=3)]
    readiness, _ = assess([], config, results)  # 5/8 = 0.625 >= 0.6, fail present but ratio over bar
    assert readiness == Readiness.ON_TRACK
