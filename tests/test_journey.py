from __future__ import annotations

from ascent.drivers.base import ActionResult, Element, Observation
from ascent.evaluators.base import EvaluatorContext, Impact, Locator
from ascent.evaluators.journey import JourneyEvaluator
from ascent.goals import KPI, Goal, GoalConfig, Milestone
from ascent.llm import RecordedJudge


class FakeDriver:
    scheme = "web"

    def __init__(self):
        self.steps: list[dict] = []
        self.closed = False

    def available(self) -> bool:
        return True

    def start(self, entry_point: str = "") -> None:
        pass

    def act(self, action: dict) -> ActionResult:
        self.steps.append(action)
        return ActionResult(ok=True)

    def observe(self) -> Observation:
        return Observation(url="/confirm", title="Confirmed", elements=[Element("0", "h1", "Booked")], text="Booking confirmed")

    def current_locator(self) -> Locator:
        return Locator(kind="route", value="/confirm")

    def close(self) -> None:
        self.closed = True


def _config():
    return GoalConfig(
        version=1, product="P", target="web://x", goal=Goal(id="g", statement="s"),
        milestone=Milestone(id="m", name="Beta", required_kpi_ids=["completion"]),
        kpis=[KPI(id="completion", goal_id="g", name="Completion", metric="task_success_rate", target=0.8)],
        extra={"journeys": [{
            "id": "book", "name": "Book a demo", "kpi_id": "completion",
            "success_signal": "a confirmation screen is shown",
            "steps": [{"type": "click", "ref": "0"}, {"type": "type", "ref": "1", "text": "x@y.com"}],
        }]},
    )


def _ctx(config, judge, driver):
    return EvaluatorContext(config=config, target="web://x", driver=driver, judge=judge)


def test_is_available_requires_journeys_driver_and_judge():
    ev = JourneyEvaluator()
    cfg = _config()
    assert ev.is_available(_ctx(cfg, RecordedJudge(), FakeDriver())) is True
    no_journeys = _config()
    no_journeys.extra = {}
    assert ev.is_available(_ctx(no_journeys, RecordedJudge(), FakeDriver())) is False
    assert ev.is_available(_ctx(cfg, None, FakeDriver())) is False


def test_passing_journey_runs_steps_and_records_success():
    driver = FakeDriver()
    judge = RecordedJudge(scores=[{"passed": True, "reason": "confirmation shown"}])
    result = JourneyEvaluator().evaluate(_ctx(_config(), judge, driver))
    assert len(driver.steps) == 2  # both scripted steps executed
    assert {o.kpi_id: o.value for o in result.observations}["completion"] == 1.0
    assert not result.gaps
    assert driver.closed


def test_failing_journey_records_failure_and_gap():
    judge = RecordedJudge(scores=[{"passed": False, "reason": "stuck on payment"}])
    result = JourneyEvaluator().evaluate(_ctx(_config(), judge, FakeDriver()))
    assert {o.kpi_id: o.value for o in result.observations}["completion"] == 0.0
    failed = [g for g in result.gaps if g.check_id.startswith("journey-failed")]
    assert len(failed) == 1
    assert failed[0].impact == Impact.MAJOR
    assert failed[0].kpi_id == "completion"
    assert "stuck on payment" in failed[0].evidence
