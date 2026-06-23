from __future__ import annotations

from ascent.drivers.base import ActionResult, Element, Observation
from ascent.evaluators.base import EvaluatorContext, Impact, Locator
from ascent.evaluators.persona_agent import PersonaAgentEvaluator
from ascent.goals import KPI, Budgets, Goal, GoalConfig, Milestone, Persona
from ascent.llm import AgentAction, RecordedJudge


class FakeDriver:
    """In-memory driver for deterministic persona-evaluator tests."""

    scheme = "web"

    def __init__(self, elapsed: float = 12.0):
        self.elapsed = elapsed
        self.started = self.closed = False
        self.actions: list[dict] = []

    def available(self) -> bool:
        return True

    def start(self, entry_point: str = "") -> None:
        self.started = True

    def observe(self) -> Observation:
        return Observation(url="/", title="Home", elements=[Element("0", "button", "Book a demo")], text="welcome")

    def act(self, action: dict) -> ActionResult:
        self.actions.append(action)
        return ActionResult(ok=True)

    def current_locator(self) -> Locator:
        return Locator(kind="route", value="/checkout")

    def metrics(self) -> dict:
        return {"elapsed_s": self.elapsed}

    def close(self) -> None:
        self.closed = True


def _config(max_steps: int = 40) -> GoalConfig:
    return GoalConfig(
        version=1, product="P", target="web://x", goal=Goal(id="g", statement="Book a demo fast"),
        milestone=Milestone(id="m", name="Beta", required_kpi_ids=["completion", "speed"]),
        kpis=[
            KPI(id="completion", goal_id="g", name="Completion", metric="task_success_rate", target=0.8),
            KPI(id="speed", goal_id="g", name="Speed", metric="time_to_complete_s", target=180, comparator="lte"),
        ],
        personas=[Persona(id="busy", name="Busy founder", intent="book a demo",
                          success_signal="confirmation shown", kpi_ids=["completion", "speed"])],
        budgets=Budgets(max_steps=max_steps),
    )


def _ctx(config, judge, driver):
    return EvaluatorContext(config=config, target="web://x", driver=driver, judge=judge)


def test_is_available_requires_driver_judge_and_personas():
    ev = PersonaAgentEvaluator()
    config = _config()
    driver = FakeDriver()
    judge = RecordedJudge()
    assert ev.is_available(_ctx(config, judge, driver)) is True
    assert ev.is_available(_ctx(config, None, driver)) is False           # no judge
    assert ev.is_available(_ctx(config, judge, None)) is False            # no driver
    no_personas = _config()
    no_personas.personas = []
    assert ev.is_available(_ctx(no_personas, judge, driver)) is False     # no personas


def test_successful_run_emits_passing_observations_and_no_unmet_gap():
    config = _config()
    driver = FakeDriver(elapsed=42.0)
    judge = RecordedJudge(actions=[
        AgentAction(kind="click", ref="0", reasoning="click book"),
        AgentAction(kind="finish", success=True, reasoning="booked", gaps=[]),
    ])
    result = PersonaAgentEvaluator().evaluate(_ctx(config, judge, driver))

    obs = {o.kpi_id: o.value for o in result.observations}
    assert obs["completion"] == 1.0
    assert obs["speed"] == 42.0
    assert not any(g.check_id.startswith("intent-unmet") for g in result.gaps)
    assert driver.started and driver.closed


def test_failed_run_emits_zero_success_and_unmet_gap():
    config = _config()
    driver = FakeDriver()
    judge = RecordedJudge(actions=[AgentAction(kind="finish", success=False, reasoning="stuck")])
    result = PersonaAgentEvaluator().evaluate(_ctx(config, judge, driver))

    obs = {o.kpi_id: o.value for o in result.observations}
    assert obs["completion"] == 0.0
    assert "speed" not in obs  # time only recorded on success
    unmet = [g for g in result.gaps if g.check_id.startswith("intent-unmet")]
    assert len(unmet) == 1
    assert unmet[0].impact == Impact.MAJOR
    assert unmet[0].kpi_id == "completion"


def test_agent_reported_gaps_are_linked_to_the_persona_kpi():
    config = _config()
    judge = RecordedJudge(actions=[AgentAction(
        kind="finish", success=True, reasoning="done",
        gaps=[{"impact": "blocker", "description": "Pay button does nothing",
               "recommendation": "wire up the Pay handler"}],
    )])
    result = PersonaAgentEvaluator().evaluate(_ctx(config, judge, FakeDriver()))

    friction = [g for g in result.gaps if g.check_id.startswith("friction")]
    assert len(friction) == 1
    assert friction[0].impact == Impact.BLOCKER
    assert friction[0].kpi_id == "completion"
    assert friction[0].recommendation == "wire up the Pay handler"


def test_runs_out_of_steps_without_finishing():
    config = _config(max_steps=2)
    driver = FakeDriver()
    judge = RecordedJudge(actions=[  # only clicks, never finishes within the budget
        AgentAction(kind="click", ref="0", reasoning="1"),
        AgentAction(kind="click", ref="0", reasoning="2"),
        AgentAction(kind="click", ref="0", reasoning="3"),
    ])
    result = PersonaAgentEvaluator().evaluate(_ctx(config, judge, driver))

    assert {o.kpi_id: o.value for o in result.observations}["completion"] == 0.0
    assert any(g.check_id.startswith("intent-unmet") for g in result.gaps)
    assert len(driver.actions) == 2  # capped at max_steps
