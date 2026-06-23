"""Web driver — drives a real running web app via Playwright (headless Chromium).

Playwright is an optional dependency (``pip install 'ascent[live]'`` +
``playwright install chromium``). The import is guarded so the package works
without it; ``available()`` reports whether it's installed, and the persona
evaluator skips this driver when it isn't. CI runs against a fake driver, so
this module is not exercised by the test suite.
"""

from __future__ import annotations

import time

from ..evaluators.base import Locator
from .base import ActionResult, Element, Observation

_INTERACTABLE = "a, button, input, textarea, select, [role=button], [role=link], [onclick]"
_MAX_ELEMENTS = 60
_TEXT_BUDGET = 2000


def _sync_playwright():
    try:
        from playwright.sync_api import sync_playwright
        return sync_playwright
    except ImportError:
        return None


class WebDriver:
    scheme = "web"

    def __init__(self, address: str):
        self.base_url = address if address.startswith(("http://", "https://")) else f"http://{address}"
        self._pw = None
        self._browser = None
        self._page = None
        self._start_time: float | None = None

    def available(self) -> bool:
        return _sync_playwright() is not None

    def start(self, entry_point: str = "") -> None:
        self.close()  # support restart between personas
        sync_playwright = _sync_playwright()
        if sync_playwright is None:
            raise RuntimeError(
                "playwright is not installed — pip install 'ascent[live]' && playwright install chromium"
            )
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)
        self._page = self._browser.new_page()
        self._start_time = time.monotonic()
        target = self.base_url + (entry_point or "")
        self._page.goto(target, wait_until="domcontentloaded", timeout=30000)

    def _handles(self):
        return self._page.query_selector_all(_INTERACTABLE)[:_MAX_ELEMENTS]

    def observe(self) -> Observation:
        page = self._page
        elements: list[Element] = []
        for i, handle in enumerate(self._handles()):
            try:
                role = handle.evaluate("el => el.getAttribute('role') || el.tagName.toLowerCase()")
                name = (
                    handle.inner_text()
                    or handle.get_attribute("aria-label")
                    or handle.get_attribute("placeholder")
                    or handle.get_attribute("value")
                    or ""
                ).strip()
            except Exception:
                role, name = "", ""
            elements.append(Element(ref=str(i), role=str(role), name=name[:80]))
        try:
            text = page.inner_text("body")[:_TEXT_BUDGET]
        except Exception:
            text = ""
        return Observation(url=page.url, title=page.title(), elements=elements, text=text)

    def act(self, action: dict) -> ActionResult:
        kind = action.get("type")
        try:
            if kind == "navigate":
                self._page.goto(action["url"], wait_until="domcontentloaded", timeout=30000)
                return ActionResult(ok=True)
            handles = self._handles()
            ref = int(action.get("ref", -1))
            if not (0 <= ref < len(handles)):
                return ActionResult(ok=False, detail=f"no element with ref {action.get('ref')}")
            handle = handles[ref]
            if kind == "type":
                handle.fill(action.get("text", ""))
                return ActionResult(ok=True)
            if kind == "click":
                handle.click(timeout=10000)
                return ActionResult(ok=True)
            return ActionResult(ok=False, detail=f"unknown action type {kind!r}")
        except Exception as err:  # Playwright raises on missing/blocked elements
            return ActionResult(ok=False, detail=str(err))

    def current_locator(self) -> Locator:
        url = self._page.url if self._page else self.base_url
        return Locator(kind="route", value=url)

    def metrics(self) -> dict:
        if self._start_time is None:
            return {}
        return {"elapsed_s": round(time.monotonic() - self._start_time, 1)}

    def close(self) -> None:
        for closer in (self._page, self._browser):
            try:
                if closer is not None:
                    closer.close()
            except Exception:
                pass
        try:
            if self._pw is not None:
                self._pw.stop()
        except Exception:
            pass
        self._page = self._browser = self._pw = None
