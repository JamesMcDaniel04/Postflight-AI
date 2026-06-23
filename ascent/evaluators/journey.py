"""Journey evaluator — run scripted user journeys, score each with the Judge.

Navigation is deterministic (the steps are fixed); only the soft judgment of
"did this checkpoint pass?" is delegated to the Judge's structured-output
``score`` call. Activates only when the config declares ``journeys``.

A journey in the config:
    journeys:
      - id: book-demo
        name: "Book a demo"
        kpi_id: booking_completion
        success_signal: "a confirmed booking screen is shown"
        steps:
          - {type: click, ref: "0"}
          - {type: type, ref: "1", text: "me@example.com"}
"""

from __future__ import annotations

from ..goals import GoalConfig, make_gap, make_observation
from .base import EvaluationResult, EvaluatorContext, Impact

_SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        "passed": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["passed", "reason"],
    "additionalProperties": False,
}


class JourneyEvaluator:
    name = "journey"

    def _journeys(self, config: GoalConfig) -> list[dict]:
        return (config.extra.get("journeys") or []) if config.extra else []

    def is_available(self, ctx: EvaluatorContext) -> bool:
        driver = ctx.driver
        return (
            bool(self._journeys(ctx.config))
            and driver is not None
            and getattr(driver, "available", lambda: False)()
            and ctx.judge is not None
        )

    def evaluate(self, ctx: EvaluatorContext) -> EvaluationResult:
        result = EvaluationResult()
        for journey in self._journeys(ctx.config):
            self._run_journey(ctx, journey, result)
        return result

    def _run_journey(self, ctx: EvaluatorContext, journey: dict, result: EvaluationResult) -> None:
        driver, judge = ctx.driver, ctx.judge
        kpi_id = journey.get("kpi_id")
        try:
            driver.start(journey.get("entry_point", ""))
            for step in journey.get("steps", []):
                driver.act(step)
            obs = driver.observe()
        except Exception as err:
            result.gaps.append(make_gap(
                impact=Impact.BLOCKER, evaluator=self.name, check_id=f"journey-error-{journey.get('id')}",
                description=f"Journey '{journey.get('name')}' failed to run: {err}", kpi_id=kpi_id,
            ))
            return
        finally:
            driver.close()

        verdict = judge.score(
            "You score whether a scripted user journey reached its success signal.",
            f"Journey: {journey.get('name')}\nSuccess signal: {journey.get('success_signal')}\n"
            f"Final page — URL: {obs.url}, title: {obs.title}\nVisible text:\n{obs.text[:1000]}\n\n"
            "Did the journey reach its success signal?",
            _SCORE_SCHEMA,
        )
        passed = bool(verdict.get("passed"))
        if kpi_id:
            result.observations.append(
                make_observation(kpi_id=kpi_id, value=1.0 if passed else 0.0, evaluator=self.name)
            )
        if not passed:
            result.gaps.append(make_gap(
                impact=Impact.MAJOR, evaluator=self.name, check_id=f"journey-failed-{journey.get('id')}",
                description=f"Journey '{journey.get('name')}' did not reach: {journey.get('success_signal')}.",
                kpi_id=kpi_id, locator=driver.current_locator() if hasattr(driver, "current_locator") else None,
                evidence=[verdict.get("reason", "")],
                recommendation="Fix the step where the scripted journey stops short of its success signal.",
                confidence=0.8,
            ))
