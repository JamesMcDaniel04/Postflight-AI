"""The surface-neutral driver boundary.

A Driver lets an evaluator exercise a running app — web, API, or mobile —
through one interface. The persona agent calls these verbs as tools and never
sees Playwright / httpx / Appium specifics. Web is the only concrete driver in
v1; api/mobile are declared seams (see factory).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..evaluators.base import Locator


@dataclass
class Element:
    """An interactable element the agent can act on, addressed by ``ref``."""

    ref: str
    role: str
    name: str


@dataclass
class Observation:
    """A snapshot of the app's current state for the agent to reason over."""

    url: str
    title: str
    elements: list[Element] = field(default_factory=list)
    text: str = ""


@dataclass
class ActionResult:
    ok: bool
    detail: str = ""


@dataclass
class TargetSpec:
    scheme: str  # web | api | ios | android
    address: str


class Driver(Protocol):
    scheme: str

    def available(self) -> bool:
        """True if this driver's runtime dependency is installed."""
        ...

    def start(self, entry_point: str = "") -> None:
        """Launch / connect and navigate to the entry point."""
        ...

    def observe(self) -> Observation: ...

    def act(self, action: dict) -> ActionResult:
        """Perform an action: {"type": click|type|navigate, "ref"/"text"/"url": ...}."""
        ...

    def current_locator(self) -> Locator: ...

    def metrics(self) -> dict:
        """Timings/counters for KPI observation, e.g. {"elapsed_s": 12.4}."""
        ...

    def close(self) -> None: ...
