"""The Judge port — the one LLM boundary, swappable and fakeable.

``AnthropicJudge`` drives Claude (claude-opus-4-8) via the Messages API tool-use
loop; ``RecordedJudge`` replays scripted decisions so persona runs and the test
suite are deterministic and need no network or API key. Persona-driving and
journey/recommendation scoring share this one budgeted port.

The ``anthropic`` SDK is an optional dependency (``pip install 'ascent[live]'``),
imported lazily so the package works without it.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Protocol

MODEL = "claude-opus-4-8"

# A single tool the agent must call each turn. Not strict — optional fields vary
# by action — so we force use via tool_choice "any" with only this tool present.
_DECIDE_TOOL = {
    "name": "decide",
    "description": "Decide the next action to take in the app to pursue the persona's intent.",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["click", "type", "navigate", "finish"]},
            "ref": {"type": "string", "description": "Element ref to click or type into."},
            "text": {"type": "string", "description": "Text to type."},
            "url": {"type": "string", "description": "URL to navigate to."},
            "reasoning": {"type": "string", "description": "One sentence on why."},
            "success": {"type": "boolean", "description": "On finish: did the persona accomplish its intent?"},
            "gaps": {
                "type": "array",
                "description": "On finish: friction points encountered that block the goal.",
                "items": {
                    "type": "object",
                    "properties": {
                        "impact": {"type": "string", "enum": ["blocker", "major", "moderate", "minor"]},
                        "description": {"type": "string"},
                        "recommendation": {"type": "string"},
                    },
                    "required": ["impact", "description"],
                },
            },
        },
        "required": ["action", "reasoning"],
    },
}


@dataclass
class AgentAction:
    kind: str  # click | type | navigate | finish
    ref: str | None = None
    text: str | None = None
    url: str | None = None
    reasoning: str = ""
    success: bool | None = None  # finish only
    gaps: list[dict] = field(default_factory=list)  # finish only

    @classmethod
    def from_tool_input(cls, data: dict) -> "AgentAction":
        return cls(
            kind=data.get("action", "finish"),
            ref=data.get("ref"),
            text=data.get("text"),
            url=data.get("url"),
            reasoning=data.get("reasoning", ""),
            success=data.get("success"),
            gaps=list(data.get("gaps") or []),
        )


class Judge(Protocol):
    def next_action(self, system: str, transcript: list[dict]) -> AgentAction: ...

    def score(self, system: str, prompt: str, schema: dict) -> dict: ...


class RecordedJudge:
    """Replays scripted actions / scores. The deterministic double for CI and
    unit tests. Exhausting the action script yields a failed ``finish`` so a
    runaway loop terminates."""

    def __init__(self, actions: list[AgentAction] | None = None, scores: list[dict] | None = None):
        self._actions = list(actions or [])
        self._scores = list(scores or [])

    def next_action(self, system: str, transcript: list[dict]) -> AgentAction:
        if self._actions:
            return self._actions.pop(0)
        return AgentAction(kind="finish", success=False, reasoning="no scripted action remaining")

    def score(self, system: str, prompt: str, schema: dict) -> dict:
        return self._scores.pop(0) if self._scores else {}


class AnthropicJudge:
    """Drives Claude via the Messages API. Real-LLM path; not exercised in CI."""

    def __init__(self, model: str = MODEL, effort: str = "low", api_key: str | None = None):
        self.model = model
        self.effort = effort
        self._api_key = api_key
        self._client = None

    @staticmethod
    def available(api_key: str | None = None) -> bool:
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False
        return bool(api_key or os.environ.get("ANTHROPIC_API_KEY"))

    def _get_client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self._api_key) if self._api_key else anthropic.Anthropic()
        return self._client

    def next_action(self, system: str, transcript: list[dict]) -> AgentAction:
        response = self._get_client().messages.create(
            model=self.model,
            max_tokens=2048,
            system=system,
            messages=transcript,
            tools=[_DECIDE_TOOL],
            tool_choice={"type": "any"},
            output_config={"effort": self.effort},
        )
        for block in response.content:
            if block.type == "tool_use" and block.name == "decide":
                return AgentAction.from_tool_input(block.input)
        # No tool call (shouldn't happen with tool_choice "any") — stop safely.
        return AgentAction(kind="finish", success=False, reasoning="model returned no action")

    def score(self, system: str, prompt: str, schema: dict) -> dict:
        response = self._get_client().messages.create(
            model=self.model,
            max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": schema}},
        )
        text = next((b.text for b in response.content if b.type == "text"), "{}")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {}


def make_judge(config) -> Judge | None:
    """Build the real judge if the SDK + API key are present, else None
    (so the persona evaluator reports itself unavailable)."""
    judge_cfg = config.extra.get("judge", {}) if config.extra else {}
    model = judge_cfg.get("model", MODEL)
    effort = judge_cfg.get("effort", "low")
    if AnthropicJudge.available():
        return AnthropicJudge(model=model, effort=effort)
    return None
