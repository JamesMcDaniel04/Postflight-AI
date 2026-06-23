"""The one real v1 evaluator: an LLM persona agent driving the running app.

For each persona, an agent loop (the Judge) drives the Driver toward the
persona's intent, bounded by the config's budgets. On finish it emits a KPI
observation per KPI the persona exercises (task success, time-to-complete) plus
a Gap per friction point — the agent's own findings, and a fallback gap if the
intent went unmet.
"""

from __future__ import annotations

from ..goals import GoalConfig, Persona, make_gap, make_observation
from .base import EvaluationResult, EvaluatorContext, Impact

_IMPACT_BY_NAME = {
    "blocker": Impact.BLOCKER,
    "major": Impact.MAJOR,
    "moderate": Impact.MODERATE,
    "minor": Impact.MINOR,
    "info": Impact.INFO,
}


def _impact_from_name(name: str | None) -> Impact:
    return _IMPACT_BY_NAME.get((name or "").lower(), Impact.MAJOR)


class PersonaAgentEvaluator:
    name = "persona_agent"

    def is_available(self, ctx: EvaluatorContext) -> bool:
        driver = ctx.driver
        return (
            driver is not None
            and getattr(driver, "available", lambda: False)()
            and ctx.judge is not None
            and bool(ctx.config.personas)
        )

    def evaluate(self, ctx: EvaluatorContext) -> EvaluationResult:
        result = EvaluationResult()
        cap = ctx.config.budgets.max_personas
        for persona in ctx.config.personas[:cap]:
            self._run_persona(ctx, persona, result)
        return result

    def _run_persona(self, ctx: EvaluatorContext, persona: Persona, result: EvaluationResult) -> None:
        driver, judge = ctx.driver, ctx.judge
        primary = self._primary_kpi(persona)
        try:
            driver.start(persona.entry_point)
        except Exception as err:
            result.gaps.append(make_gap(
                impact=Impact.BLOCKER, evaluator=self.name, check_id=f"start-failed-{persona.id}",
                description=f"Could not load the app for persona '{persona.name}': {err}",
                kpi_id=primary, persona=persona.id,
            ))
            return

        try:
            finished, success, agent_gaps, steps = self._drive(ctx, persona, judge, driver)
            self._emit_observations(ctx.config, persona, driver, finished and success, result)
            self._emit_gaps(persona, driver, finished, success, agent_gaps, steps, primary, result)
        finally:
            driver.close()

    def _drive(self, ctx, persona, judge, driver):
        system = self._system_prompt(persona, ctx.config)
        transcript: list[dict] = []
        budget = ctx.config.budgets
        finished = success = False
        agent_gaps: list[dict] = []
        steps = 0
        for steps in range(1, budget.max_steps + 1):
            obs = driver.observe()
            transcript.append({"role": "user", "content": self._render_obs(obs)})
            action = judge.next_action(system, transcript)
            transcript.append({"role": "assistant", "content": f"{action.kind}: {action.reasoning}"})
            if action.kind == "finish":
                finished, success, agent_gaps = True, bool(action.success), action.gaps
                break
            res = driver.act(self._to_driver_action(action))
            transcript.append({"role": "user", "content": f"result: {'ok' if res.ok else 'failed — ' + res.detail}"})
        return finished, success, agent_gaps, steps

    def _emit_observations(self, config: GoalConfig, persona: Persona, driver, succeeded: bool, result: EvaluationResult) -> None:
        elapsed = driver.metrics().get("elapsed_s")
        for kpi_id in persona.kpi_ids:
            kpi = config.kpi(kpi_id)
            if kpi is None:
                continue
            if kpi.metric == "task_success_rate":
                result.observations.append(
                    make_observation(kpi_id=kpi_id, value=1.0 if succeeded else 0.0, evaluator=self.name)
                )
            elif kpi.metric == "time_to_complete_s" and succeeded and elapsed is not None:
                result.observations.append(
                    make_observation(kpi_id=kpi_id, value=float(elapsed), evaluator=self.name)
                )

    def _emit_gaps(self, persona, driver, finished, success, agent_gaps, steps, primary, result) -> None:
        locator = driver.current_locator()
        if not (finished and success):
            result.gaps.append(make_gap(
                impact=Impact.MAJOR, evaluator=self.name, check_id=f"intent-unmet-{persona.id}",
                description=(
                    f"Persona '{persona.name}' could not {persona.intent or 'reach the goal'} "
                    f"within {steps} step(s)."
                ),
                kpi_id=primary, persona=persona.id, locator=locator,
                evidence=[f"stopped at {locator.value}"],
                recommendation="Trace the persona's path and remove the step where it got stuck.",
                confidence=0.6,
            ))
        for i, gap in enumerate(agent_gaps):
            result.gaps.append(make_gap(
                impact=_impact_from_name(gap.get("impact")), evaluator=self.name,
                check_id=f"friction-{persona.id}-{i}", description=gap.get("description", "friction point"),
                kpi_id=primary, persona=persona.id, locator=locator,
                recommendation=gap.get("recommendation"), confidence=0.6,
            ))

    @staticmethod
    def _primary_kpi(persona: Persona) -> str | None:
        return persona.kpi_ids[0] if persona.kpi_ids else None

    @staticmethod
    def _to_driver_action(action) -> dict:
        return {"type": action.kind, "ref": action.ref, "text": action.text, "url": action.url}

    @staticmethod
    def _system_prompt(persona: Persona, config: GoalConfig) -> str:
        return (
            f"You are a live user testing an app. Act as this persona:\n"
            f"- Name: {persona.name}\n- Description: {persona.description}\n"
            f"- Your intent right now: {persona.intent}\n"
            f"- You succeed when: {persona.success_signal}\n\n"
            f"The app's goal is: {config.goal.statement}\n\n"
            "Each turn you get the current page (URL, title, interactable elements with refs, visible text). "
            "Call the `decide` tool to act: click/type a ref, navigate to a url, or finish. "
            "Finish as soon as you've accomplished the intent (success=true) or are truly stuck (success=false). "
            "When finishing, report any friction points that block the goal as gaps."
        )

    @staticmethod
    def _render_obs(obs) -> str:
        lines = [f"URL: {obs.url}", f"Title: {obs.title}", "Elements:"]
        lines += [f"  [{e.ref}] {e.role}: {e.name}" for e in obs.elements] or ["  (none)"]
        if obs.text:
            lines.append(f"Visible text (truncated):\n{obs.text[:800]}")
        return "\n".join(lines)
