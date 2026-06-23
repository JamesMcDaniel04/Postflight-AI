from __future__ import annotations

import json
from collections import Counter
from unittest.mock import patch

import pytest

from ascent.evaluators.base import Impact, Locator
from ascent.goals import make_gap
from ascent.integrations.github_api import GitHubAPIError, GitHubClient
from ascent.output.github import (
    ANNOTATIONS_CAP,
    STICKY_COMMENT_MARKER,
    blob_link,
    conclusion_for,
    locator_link,
    relpath,
    render_gap_table,
    render_pr_comment_body,
    render_scorecard,
    select_annotations,
    title_for,
)
from ascent.scoring import KpiResult
from ascent.verdict import Readiness, Scorecard


def _gap(impact, kpi_id="k1", *, file=None, line=None, route=None,
         evaluator="persona_agent", desc=None, rec=None):
    if file is not None:
        locator = Locator(kind="file", value=file, line=line)
    elif route is not None:
        locator = Locator(kind="route", value=route)
    else:
        locator = None
    return make_gap(
        impact=impact, evaluator=evaluator, check_id=f"chk-{impact.value}",
        description=desc or f"{impact.value} gap", kpi_id=kpi_id,
        locator=locator, recommendation=rec,
    )


def _scorecard(summary="", results=None):
    return Scorecard(kpi_results=results or [], counts=Counter(), milestone_ready=False, summary=summary)


# ---- conclusion_for / title_for ---------------------------------------------

def test_conclusion_mapping():
    assert conclusion_for(Readiness.ON_TRACK) == "success"
    assert conclusion_for(Readiness.NEEDS_WORK) == "neutral"
    assert conclusion_for(Readiness.BLOCKED) == "failure"


def test_title_for_uses_summary():
    sc = _scorecard(summary="NEEDS_WORK toward Public Beta — Booking completion 0.71/0.8")
    assert title_for(Readiness.NEEDS_WORK, sc) == "NEEDS_WORK toward Public Beta — Booking completion 0.71/0.8"


def test_title_for_falls_back_to_readiness_value():
    assert title_for(Readiness.ON_TRACK, _scorecard()) == "ON_TRACK"


# ---- blob_link / relpath ----------------------------------------------------

def test_blob_link_with_line():
    assert blob_link("o/r", "abc123", "path/to/file.py", 42) == \
        "https://github.com/o/r/blob/abc123/path/to/file.py#L42"


def test_blob_link_without_line():
    assert blob_link("o/r", "abc123", "path/to/file.py", None) == \
        "https://github.com/o/r/blob/abc123/path/to/file.py"


def test_relpath_inside_workspace(tmp_path):
    sub = tmp_path / "sub" / "file.py"
    sub.parent.mkdir(parents=True)
    sub.write_text("x")
    assert relpath(str(sub), str(tmp_path)) == "sub/file.py"


def test_relpath_none_returns_none():
    assert relpath(None, "/anything") is None


def test_relpath_outside_workspace_falls_back():
    assert relpath("/etc/passwd", "/var/log") == "etc/passwd"


# ---- locator_link (pluggable, dispatch on kind) -----------------------------

def test_locator_link_file_is_blob_link(tmp_path):
    loc = Locator(kind="file", value=str(tmp_path / "a.py"), line=10)
    out = locator_link(loc, "o/r", "abc", str(tmp_path))
    assert "https://github.com/o/r/blob/abc/a.py#L10" in out


def test_locator_link_web_url_links_out():
    loc = Locator(kind="route", value="https://app.example.com/checkout")
    assert locator_link(loc, "o/r", "abc", "/ws") == \
        "[`https://app.example.com/checkout`](https://app.example.com/checkout)"


def test_locator_link_relative_route_is_code_span():
    loc = Locator(kind="route", value="/checkout")
    assert locator_link(loc, "o/r", "abc", "/ws") == "`/checkout`"


def test_locator_link_none_is_empty():
    assert locator_link(None, "o/r", "abc", "/ws") == ""


# ---- render_gap_table -------------------------------------------------------

def test_render_gap_table_empty():
    assert render_gap_table([], "o/r", "abc", "/ws") == "No gaps tied to your KPIs."


def test_render_gap_table_groups_by_impact():
    g1 = _gap(Impact.BLOCKER, route="/pay")
    g2 = _gap(Impact.MAJOR, route="/signup")
    out = render_gap_table([g2, g1], "o/r", "abc", "/ws")
    assert "BLOCKER (1)" in out
    assert "MAJOR (1)" in out
    assert out.index("BLOCKER") < out.index("MAJOR")  # impact desc
    assert "persona_agent" in out
    assert "`/pay`" in out


def test_render_gap_table_escapes_pipes():
    g = _gap(Impact.MAJOR, route="/x", desc="boom | this would | break")
    out = render_gap_table([g], "o/r", "abc", "/ws")
    assert "boom \\| this would \\| break" in out


# ---- render_scorecard -------------------------------------------------------

def test_render_scorecard_lists_kpis():
    results = [
        KpiResult(kpi_id="k1", name="Booking completion", target=0.8, comparator="gte",
                  actual=0.71, status="near", sample_size=5, unit="ratio", weight=5),
        KpiResult(kpi_id="k2", name="Time to book", target=180, comparator="lte",
                  actual=None, status="unmeasured", sample_size=0, unit="s", weight=3),
    ]
    out = render_scorecard(_scorecard(results=results))
    assert "KPI scorecard" in out
    assert "Booking completion" in out
    assert "near" in out
    assert "unmeasured" in out
    assert "—" in out  # unmeasured actual


def test_render_scorecard_empty_is_blank():
    assert render_scorecard(_scorecard()) == ""


# ---- render_pr_comment_body -------------------------------------------------

def test_pr_comment_body_includes_marker_and_readiness():
    sc = _scorecard(summary="NEEDS_WORK toward Public Beta — Booking completion 0.71/0.8")
    body = render_pr_comment_body([], Readiness.NEEDS_WORK, sc, "o/r", "abcdef1234567", "/ws")
    assert STICKY_COMMENT_MARKER in body
    assert "## Ascent" in body
    assert "NEEDS_WORK" in body
    assert "abcdef1" in body
    assert "https://github.com/o/r/commit/abcdef1234567" in body


def test_pr_comment_body_includes_unaligned_section():
    sc = _scorecard(summary="ON_TRACK toward Public Beta")
    unaligned = [_gap(Impact.MINOR, kpi_id=None, route="/settings", desc="off-goal nit")]
    body = render_pr_comment_body([], Readiness.ON_TRACK, sc, "o/r", "sha", "/ws", unaligned)
    assert "Unaligned observations (1)" in body
    assert "off-goal nit" in body


# ---- select_annotations -----------------------------------------------------

def test_select_annotations_skips_non_file_locators():
    assert select_annotations([_gap(Impact.BLOCKER, route="/pay")], "/ws") == []


def test_select_annotations_skips_gaps_without_locator():
    assert select_annotations([_gap(Impact.BLOCKER)], "/ws") == []


def test_select_annotations_caps_at_50():
    gaps = [_gap(Impact.MAJOR, file=f"/ws/file{i}.py", line=1) for i in range(120)]
    out = select_annotations(gaps, "/ws", cap=ANNOTATIONS_CAP)
    assert len(out) == 50


def test_select_annotations_orders_by_impact():
    out = select_annotations(
        [_gap(Impact.MAJOR, file="/ws/h.py", line=1),
         _gap(Impact.MINOR, file="/ws/l.py", line=1),
         _gap(Impact.BLOCKER, file="/ws/c.py", line=1)],
        "/ws", cap=10,
    )
    assert out[0]["path"].endswith("c.py")
    assert out[1]["path"].endswith("h.py")
    assert out[2]["path"].endswith("l.py")


def test_select_annotations_level_mapping():
    gaps = [
        _gap(Impact.BLOCKER, file="/ws/a.py", line=1),
        _gap(Impact.MAJOR, file="/ws/b.py", line=1),
        _gap(Impact.MODERATE, file="/ws/c.py", line=1),
        _gap(Impact.MINOR, file="/ws/d.py", line=1),
        _gap(Impact.INFO, file="/ws/e.py", line=1),
    ]
    levels = {a["path"]: a["annotation_level"] for a in select_annotations(gaps, "/ws", cap=10)}
    assert levels["a.py"] == "failure"
    assert levels["b.py"] == "failure"
    assert levels["c.py"] == "warning"
    assert levels["d.py"] == "notice"
    assert levels["e.py"] == "notice"


def test_select_annotations_default_line_is_one_when_missing():
    out = select_annotations([_gap(Impact.MAJOR, file="/ws/lockfile.txt", line=None)], "/ws", cap=10)
    assert out[0]["start_line"] == 1
    assert out[0]["end_line"] == 1


# ---- GitHubClient (mocked urllib) -------------------------------------------

class _FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self) -> bytes:
        return self._body


def _resp(payload) -> _FakeResponse:
    return _FakeResponse(json.dumps(payload).encode())


@patch("ascent.integrations.github_api.urllib.request.urlopen")
def test_create_check_run_payload(mock_urlopen):
    mock_urlopen.return_value = _resp({"id": 1})
    client = GitHubClient(token="t0k", repo="owner/repo")
    annotations = [{"path": "x.py", "start_line": 1, "end_line": 1,
                    "annotation_level": "failure", "title": "t", "message": "m"}]
    client.create_check_run(
        name="Ascent", head_sha="deadbeef", conclusion="failure",
        title="BLOCKED toward Public Beta", summary="BLOCKED toward Public Beta",
        text="## body", annotations=annotations,
    )
    assert mock_urlopen.call_count == 1
    req = mock_urlopen.call_args.args[0]
    assert req.method == "POST"
    assert req.full_url == "https://api.github.com/repos/owner/repo/check-runs"
    assert req.headers["User-agent"] == "ascent/0.2"
    payload = json.loads(req.data)
    assert payload["name"] == "Ascent"
    assert payload["conclusion"] == "failure"
    assert payload["output"]["annotations"] == annotations


@patch("ascent.integrations.github_api.urllib.request.urlopen")
def test_upsert_pr_comment_creates_when_no_existing(mock_urlopen):
    mock_urlopen.side_effect = [_resp([]), _resp({"id": 99})]
    client = GitHubClient(token="t", repo="o/r")
    client.upsert_pr_comment(pr_number=42, marker=STICKY_COMMENT_MARKER, body="hello")
    assert mock_urlopen.call_count == 2
    create_req = mock_urlopen.call_args_list[1].args[0]
    assert create_req.method == "POST"
    assert create_req.full_url == "https://api.github.com/repos/o/r/issues/42/comments"
    assert json.loads(create_req.data)["body"] == "hello"


@patch("ascent.integrations.github_api.urllib.request.urlopen")
def test_upsert_pr_comment_patches_when_existing(mock_urlopen):
    existing = {"id": 7, "body": f"{STICKY_COMMENT_MARKER}\nold"}
    mock_urlopen.side_effect = [_resp([existing]), _resp({"id": 7})]
    client = GitHubClient(token="t", repo="o/r")
    client.upsert_pr_comment(pr_number=42, marker=STICKY_COMMENT_MARKER, body="new")
    patch_req = mock_urlopen.call_args_list[1].args[0]
    assert patch_req.method == "PATCH"
    assert patch_req.full_url == "https://api.github.com/repos/o/r/issues/comments/7"


@patch("ascent.integrations.github_api.urllib.request.urlopen")
def test_http_error_raises_github_api_error(mock_urlopen):
    import io
    import urllib.error
    mock_urlopen.side_effect = urllib.error.HTTPError(
        url="https://api.github.com/repos/o/r/check-runs", code=403, msg="Forbidden",
        hdrs={}, fp=io.BytesIO(b'{"message":"Resource not accessible by integration"}'),
    )
    client = GitHubClient(token="t", repo="o/r")
    with pytest.raises(GitHubAPIError) as excinfo:
        client.create_check_run(name="Ascent", head_sha="s", conclusion="success",
                                title="T", summary="T", text="x", annotations=None)
    assert excinfo.value.status == 403
    assert "not accessible" in excinfo.value.body
