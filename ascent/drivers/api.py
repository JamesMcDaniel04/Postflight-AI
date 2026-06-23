"""API driver — exercises an HTTP API as a sequence of user-intent calls.

A minimal, real driver on the stdlib HTTP client (no extra dependency): the
agent ``navigate``s to a path (GET) and ``observe``s the last response
(status + body). ``type``/``click`` don't apply to an API surface. This proves
the multi-surface seam end to end without a browser.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from ..evaluators.base import Locator
from .base import ActionResult, Observation


class ApiDriver:
    scheme = "api"

    def __init__(self, address: str):
        self.base_url = (address if address.startswith(("http://", "https://")) else f"http://{address}").rstrip("/")
        self._status = 0
        self._body = ""
        self._url = self.base_url
        self._start_time: float | None = None

    def available(self) -> bool:
        return True  # stdlib only

    def start(self, entry_point: str = "") -> None:
        self._start_time = time.monotonic()
        self._request(entry_point or "/")

    def _resolve(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            return path
        return self.base_url + (path if path.startswith("/") else "/" + path)

    def _request(self, path: str, method: str = "GET", body: dict | None = None) -> None:
        url = self._resolve(path)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method,
                                     headers={"Accept": "application/json", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                self._status = resp.status
                self._body = resp.read().decode("utf-8", errors="replace")[:2000]
        except urllib.error.HTTPError as err:
            self._status = err.code
            self._body = err.read().decode("utf-8", errors="replace")[:2000]
        except OSError as err:  # URLError and socket errors derive from OSError
            self._status = 0
            self._body = f"request failed: {err}"
        self._url = url

    def observe(self) -> Observation:
        return Observation(url=self._url, title=f"HTTP {self._status}", elements=[], text=self._body)

    def act(self, action: dict) -> ActionResult:
        kind = action.get("type")
        if kind == "navigate":
            self._request(action.get("url", "/"))
            return ActionResult(ok=self._status and self._status < 400, detail=f"HTTP {self._status}")
        return ActionResult(ok=False, detail=f"api driver supports 'navigate' only, not {kind!r}")

    def current_locator(self) -> Locator:
        return Locator(kind="endpoint", value=self._url)

    def metrics(self) -> dict:
        if self._start_time is None:
            return {}
        return {"elapsed_s": round(time.monotonic() - self._start_time, 1)}

    def close(self) -> None:
        pass
