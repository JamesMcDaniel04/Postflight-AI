from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from ascent.drivers.api import ApiDriver


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path == "/missing":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"error": "not found"}')
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok": true, "page": "home"}')

    def log_message(self, *args):  # silence test server logging
        pass


@pytest.fixture()
def server():
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_api_driver_is_available():
    assert ApiDriver("127.0.0.1:8000").available() is True


def test_api_driver_get_and_observe(server):
    driver = ApiDriver(server)
    driver.start("/")
    obs = driver.observe()
    assert obs.title == "HTTP 200"
    assert '"ok": true' in obs.text
    assert driver.metrics().get("elapsed_s") is not None
    assert driver.current_locator().kind == "endpoint"


def test_api_driver_navigate_to_error(server):
    driver = ApiDriver(server)
    driver.start("/")
    res = driver.act({"type": "navigate", "url": "/missing"})
    assert res.ok is False
    assert driver.observe().title == "HTTP 404"


def test_api_driver_rejects_ui_actions(server):
    driver = ApiDriver(server)
    driver.start("/")
    res = driver.act({"type": "click", "ref": "0"})
    assert res.ok is False
    assert "navigate" in res.detail
