"""Mobile driver (iOS / Android) — declared seam.

Mobile automation (e.g. Appium against a simulator/emulator) is out of scope to
run in this environment; the driver is declared against the same protocol so a
later implementation is one file + one factory branch, with no change downstream.
"""

from __future__ import annotations

from ..evaluators.base import Locator
from .base import ActionResult, Observation


class MobileDriver:
    def __init__(self, scheme: str, address: str):
        self.scheme = scheme  # "ios" | "android"
        self.address = address

    def available(self) -> bool:
        return False

    def start(self, entry_point: str = "") -> None:
        raise NotImplementedError(f"the {self.scheme}:// driver is not implemented yet")

    def observe(self) -> Observation:
        raise NotImplementedError

    def act(self, action: dict) -> ActionResult:
        raise NotImplementedError

    def current_locator(self) -> Locator:
        return Locator(kind="screen", value=self.address)

    def metrics(self) -> dict:
        return {}

    def close(self) -> None:
        pass
