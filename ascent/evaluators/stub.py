from __future__ import annotations

from .base import EvaluationResult, EvaluatorContext


class StubEvaluator:
    """Placeholder evaluator so the registry + run loop are exercised in Phase 0.

    Always unavailable: the real PersonaAgentEvaluator (browser-driven) and the
    JourneyEvaluator / ReplayEvaluator stubs arrive in later phases. Until then
    ``ascent run`` produces an empty gap report and an all-unmeasured scorecard,
    which is the intended Phase 0 end-to-end behavior.
    """

    name = "stub"

    def is_available(self, ctx: EvaluatorContext) -> bool:
        return False

    def evaluate(self, ctx: EvaluatorContext) -> EvaluationResult:  # pragma: no cover
        return EvaluationResult()
