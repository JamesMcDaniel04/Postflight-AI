from __future__ import annotations

import json
from collections import Counter
from unittest.mock import patch

import pytest

from postlight.integrations.github_api import GitHubAPIError, GitHubClient
from postlight.output.github import (
    ANNOTATIONS_CAP,
    STICKY_COMMENT_MARKER,
    blob_link,
    conclusion_for,
    relpath,
    render_findings_table,
    render_pr_comment_body,
    select_annotations,
    title_for,
)
from postlight.scanners.base import Finding, Severity
from postlight.verdict import Verdict, compute


def _f(sev: Severity, file: str | None = None, line: int | None = None, tool: str = "osv-scanner") -> Finding:
    return Finding(
        severity=sev,
        source_tool=tool,
        rule_id=f"rule-{sev.value}",
        message=f"{sev.value} finding",
        file=file,
        line=line,
    )


# ---- conclusion_for / title_for ---------------------------------------------

def test_conclusion_mapping():
    assert conclusion_for(Verdict.SHIP) == "success"
    assert conclusion_for(Verdict.REVIEW) == "neutral"
    assert conclusion_for(Verdict.HOLD) == "failure"


def test_title_for_no_findings():
    title = title_for(Verdict.SHIP, Counter())
    assert title == "SHIP (no findings)"


def test_title_for_with_findings():
    counts = Counter({Severity.CRITICAL: 2, Severity.HIGH: 5, Severity.MEDIUM: 0})
    title = title_for(Verdict.HOLD, counts)
    assert "HOLD" in title
    assert "2 critical" in title
    assert "5 high" in title
    assert "medium" not in title  # zero counts are omitted


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
    # Path that doesn't share a prefix with workspace should still produce something usable.
    out = relpath("/etc/passwd", "/var/log")
    assert out == "etc/passwd"


# ---- render_findings_table --------------------------------------------------

def test_render_findings_table_empty():
    assert render_findings_table([], Counter(), "o/r", "abc", "/ws") == "No findings."


def test_render_findings_table_groups_by_severity(tmp_path):
    f1 = _f(Severity.CRITICAL, file=str(tmp_path / "a.py"), line=10)
    (tmp_path / "a.py").write_text("x")
    f2 = _f(Severity.HIGH, file=str(tmp_path / "b.py"), line=20)
    (tmp_path / "b.py").write_text("x")
    counts = Counter({Severity.CRITICAL: 1, Severity.HIGH: 1})
    out = render_findings_table([f1, f2], counts, "o/r", "abc", str(tmp_path))
    assert "CRITICAL (1)" in out
    assert "HIGH (1)" in out
    # CRITICAL must appear before HIGH (severity desc)
    assert out.index("CRITICAL") < out.index("HIGH")
    # Linkified location with blob URL + line anchor
    assert "https://github.com/o/r/blob/abc/a.py#L10" in out
    assert "https://github.com/o/r/blob/abc/b.py#L20" in out


def test_render_findings_table_escapes_pipes():
    # A pipe in the message would break markdown table rendering if not escaped.
    f = Finding(
        severity=Severity.HIGH,
        source_tool="osv-scanner",
        rule_id="r",
        message="boom | this would | break the table",
    )
    out = render_findings_table([f], Counter({Severity.HIGH: 1}), "o/r", "abc", "/ws")
    assert "boom \\| this would \\| break" in out


# ---- render_pr_comment_body -------------------------------------------------

def test_pr_comment_body_includes_marker_and_verdict():
    body = render_pr_comment_body([], Verdict.SHIP, Counter(), "o/r", "abcdef1234567", "/ws")
    assert STICKY_COMMENT_MARKER in body
    assert "Postlight Code" in body
    assert "SHIP" in body
    # Short SHA hyperlink to the commit
    assert "abcdef1" in body
    assert "https://github.com/o/r/commit/abcdef1234567" in body


# ---- select_annotations -----------------------------------------------------

def test_select_annotations_skips_findings_without_file():
    f = _f(Severity.CRITICAL)  # no file
    assert select_annotations([f], "/ws") == []


def test_select_annotations_caps_at_50():
    findings = [_f(Severity.HIGH, file=f"/ws/file{i}.py", line=1) for i in range(120)]
    out = select_annotations(findings, "/ws", cap=ANNOTATIONS_CAP)
    assert len(out) == 50


def test_select_annotations_orders_by_severity():
    high = _f(Severity.HIGH, file="/ws/h.py", line=1)
    crit = _f(Severity.CRITICAL, file="/ws/c.py", line=1)
    low = _f(Severity.LOW, file="/ws/l.py", line=1)
    out = select_annotations([high, low, crit], "/ws", cap=10)
    assert out[0]["path"].endswith("c.py")
    assert out[1]["path"].endswith("h.py")
    assert out[2]["path"].endswith("l.py")


def test_select_annotations_level_mapping():
    findings = [
        _f(Severity.CRITICAL, file="/ws/a.py", line=1),
        _f(Severity.HIGH, file="/ws/b.py", line=1),
        _f(Severity.MEDIUM, file="/ws/c.py", line=1),
        _f(Severity.LOW, file="/ws/d.py", line=1),
        _f(Severity.INFO, file="/ws/e.py", line=1),
    ]
    out = select_annotations(findings, "/ws", cap=10)
    levels = {a["path"]: a["annotation_level"] for a in out}
    assert levels["a.py"] == "failure"
    assert levels["b.py"] == "failure"
    assert levels["c.py"] == "warning"
    assert levels["d.py"] == "notice"
    assert levels["e.py"] == "notice"


def test_select_annotations_default_line_is_one_when_missing():
    f = _f(Severity.HIGH, file="/ws/lockfile.txt", line=None)
    out = select_annotations([f], "/ws", cap=10)
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


@patch("postlight.integrations.github_api.urllib.request.urlopen")
def test_create_check_run_payload(mock_urlopen):
    mock_urlopen.return_value = _resp({"id": 1})
    client = GitHubClient(token="t0k", repo="owner/repo")
    annotations = [{"path": "x.py", "start_line": 1, "end_line": 1, "annotation_level": "failure", "title": "t", "message": "m"}]
    client.create_check_run(
        name="Postlight",
        head_sha="deadbeef",
        conclusion="failure",
        title="HOLD (1 critical)",
        summary="HOLD (1 critical)",
        text="## body",
        annotations=annotations,
    )
    assert mock_urlopen.call_count == 1
    req = mock_urlopen.call_args.args[0]
    assert req.method == "POST"
    assert req.full_url == "https://api.github.com/repos/owner/repo/check-runs"
    assert req.headers["Authorization"] == "Bearer t0k"
    payload = json.loads(req.data)
    assert payload["name"] == "Postlight"
    assert payload["head_sha"] == "deadbeef"
    assert payload["status"] == "completed"
    assert payload["conclusion"] == "failure"
    assert payload["output"]["title"] == "HOLD (1 critical)"
    assert payload["output"]["text"] == "## body"
    assert payload["output"]["annotations"] == annotations


@patch("postlight.integrations.github_api.urllib.request.urlopen")
def test_upsert_pr_comment_creates_when_no_existing(mock_urlopen):
    # First call (GET list) returns empty; second (POST) returns the new comment.
    mock_urlopen.side_effect = [_resp([]), _resp({"id": 99})]
    client = GitHubClient(token="t", repo="o/r")
    client.upsert_pr_comment(pr_number=42, marker=STICKY_COMMENT_MARKER, body="hello")
    assert mock_urlopen.call_count == 2
    create_req = mock_urlopen.call_args_list[1].args[0]
    assert create_req.method == "POST"
    assert create_req.full_url == "https://api.github.com/repos/o/r/issues/42/comments"
    assert json.loads(create_req.data)["body"] == "hello"


@patch("postlight.integrations.github_api.urllib.request.urlopen")
def test_upsert_pr_comment_patches_when_existing(mock_urlopen):
    # First call returns a list with one comment containing the marker; second is the PATCH.
    existing = {"id": 7, "body": f"{STICKY_COMMENT_MARKER}\nold"}
    mock_urlopen.side_effect = [_resp([existing]), _resp({"id": 7})]
    client = GitHubClient(token="t", repo="o/r")
    client.upsert_pr_comment(pr_number=42, marker=STICKY_COMMENT_MARKER, body="new")
    assert mock_urlopen.call_count == 2
    patch_req = mock_urlopen.call_args_list[1].args[0]
    assert patch_req.method == "PATCH"
    assert patch_req.full_url == "https://api.github.com/repos/o/r/issues/comments/7"
    assert json.loads(patch_req.data)["body"] == "new"


@patch("postlight.integrations.github_api.urllib.request.urlopen")
def test_http_error_raises_github_api_error(mock_urlopen):
    import urllib.error
    import io
    mock_urlopen.side_effect = urllib.error.HTTPError(
        url="https://api.github.com/repos/o/r/check-runs",
        code=403,
        msg="Forbidden",
        hdrs={},
        fp=io.BytesIO(b'{"message":"Resource not accessible by integration"}'),
    )
    client = GitHubClient(token="t", repo="o/r")
    with pytest.raises(GitHubAPIError) as excinfo:
        client.create_check_run(
            name="P", head_sha="s", conclusion="success",
            title="T", summary="T", text="x", annotations=None,
        )
    assert excinfo.value.status == 403
    assert "not accessible" in excinfo.value.body


# ---- compute() integration with output ---------------------------------------

def test_full_pipeline_smoke(tmp_path):
    # Mini end-to-end: synthesize findings, compute verdict, render outputs, ensure consistency.
    f1 = Finding(severity=Severity.CRITICAL, source_tool="gitleaks", rule_id="private-key",
                 message="Private key found", file=str(tmp_path / "leak.key"), line=1)
    f2 = Finding(severity=Severity.HIGH, source_tool="osv-scanner", rule_id="GHSA-x",
                 message="vulnerable dep", file=str(tmp_path / "reqs.txt"), line=None)
    (tmp_path / "leak.key").write_text("x")
    (tmp_path / "reqs.txt").write_text("x")

    verdict, counts = compute([f1, f2])
    assert verdict == Verdict.HOLD

    title = title_for(verdict, counts)
    assert "HOLD" in title
    assert conclusion_for(verdict) == "failure"

    body = render_pr_comment_body([f1, f2], verdict, counts, "o/r", "sha123", str(tmp_path))
    assert STICKY_COMMENT_MARKER in body
    assert "leak.key" in body
    assert "reqs.txt" in body

    annotations = select_annotations([f1, f2], str(tmp_path))
    assert len(annotations) == 2
    assert annotations[0]["annotation_level"] == "failure"  # CRITICAL first
