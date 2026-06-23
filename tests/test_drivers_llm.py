from __future__ import annotations

import pytest

from ascent.drivers.api import ApiDriver
from ascent.drivers.factory import make_driver, parse_target
from ascent.drivers.mobile import MobileDriver
from ascent.drivers.web import WebDriver
from ascent.llm import AgentAction, RecordedJudge


# ---- target parsing / driver factory ----------------------------------------

def test_parse_target_schemes():
    assert parse_target("web://http://localhost:3000").scheme == "web"
    assert parse_target("api://https://api.example.com").address == "https://api.example.com"
    assert parse_target("ios://com.acme.app").scheme == "ios"


def test_parse_target_rejects_unknown_scheme():
    with pytest.raises(ValueError):
        parse_target("ftp://nope")


def test_make_driver_returns_right_type():
    assert isinstance(make_driver("web://localhost:3000"), WebDriver)
    assert isinstance(make_driver("api://localhost:8000"), ApiDriver)
    assert isinstance(make_driver("android://com.acme.app"), MobileDriver)


def test_seam_drivers_report_unavailable():
    # mobile surfaces are declared seams; the api driver is concrete (stdlib only).
    assert make_driver("ios://x").available() is False
    assert make_driver("android://x").available() is False
    assert make_driver("api://x").available() is True


def test_web_driver_url_normalization():
    assert WebDriver("localhost:3000").base_url == "http://localhost:3000"
    assert WebDriver("https://app.example.com").base_url == "https://app.example.com"


# ---- AgentAction / RecordedJudge --------------------------------------------

def test_agent_action_from_tool_input():
    action = AgentAction.from_tool_input({
        "action": "type", "ref": "3", "text": "hello@x.com", "reasoning": "enter email",
    })
    assert action.kind == "type"
    assert action.ref == "3"
    assert action.text == "hello@x.com"
    assert action.gaps == []


def test_recorded_judge_replays_then_finishes():
    judge = RecordedJudge(actions=[AgentAction(kind="click", ref="0", reasoning="go")])
    first = judge.next_action("sys", [])
    assert first.kind == "click"
    # exhausted -> a failed finish so a loop terminates
    second = judge.next_action("sys", [])
    assert second.kind == "finish"
    assert second.success is False


def test_recorded_judge_scores():
    judge = RecordedJudge(scores=[{"passed": True}])
    assert judge.score("sys", "prompt", {}) == {"passed": True}
    assert judge.score("sys", "prompt", {}) == {}  # exhausted -> empty
