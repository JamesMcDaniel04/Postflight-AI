from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import click

from .integrations.github_api import GitHubAPIError, GitHubClient
from .output.console import render
from .output.github import (
    STICKY_COMMENT_MARKER,
    conclusion_for,
    render_findings_table,
    render_pr_comment_body,
    select_annotations,
    title_for,
)
from .scanners.base import Finding
from .scanners.gitleaks import GitleaksScanner
from .scanners.osv import OsvScanner
from .verdict import Verdict, compute


SCANNERS = [OsvScanner, GitleaksScanner]

_EXIT_CODE = {Verdict.SHIP: 0, Verdict.REVIEW: 0, Verdict.HOLD: 1}


@click.group()
@click.version_option()
def cli() -> None:
    pass


@cli.command()
@click.argument("path", type=click.Path(exists=True, file_okay=False, dir_okay=True))
def scan(path: str) -> None:
    findings = _run_scanners(path)
    verdict, counts = compute(findings)
    render(findings, verdict, counts)
    sys.exit(_EXIT_CODE[verdict])


@cli.command()
@click.argument("path", type=click.Path(exists=True, file_okay=False, dir_okay=True), required=False)
def ci(path: str | None) -> None:
    """Run scan + post results to GitHub. Reads GITHUB_* env vars."""
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    sha = os.environ.get("GITHUB_SHA")
    workspace = path or os.environ.get("GITHUB_WORKSPACE")
    if not (token and repo and sha and workspace):
        click.echo(
            "error: GITHUB_TOKEN, GITHUB_REPOSITORY, GITHUB_SHA, and "
            "GITHUB_WORKSPACE (or PATH arg) must be set",
            err=True,
        )
        sys.exit(2)

    findings = _run_scanners(workspace)
    verdict, counts = compute(findings)

    title = title_for(verdict, counts)
    text = render_findings_table(findings, counts, repo, sha, workspace)
    annotations = select_annotations(findings, workspace)

    client = GitHubClient(token=token, repo=repo)
    click.echo(f"[post] check-run with {len(annotations)} annotations", err=True)
    try:
        client.create_check_run(
            name="Postlight",
            head_sha=sha,
            conclusion=conclusion_for(verdict),
            title=title,
            summary=title,
            text=text,
            annotations=annotations,
        )
    except GitHubAPIError as err:
        click.echo(f"error: failed to create check-run: {err}", err=True)
        sys.exit(2)

    pr_number = _pr_number_from_event()
    if pr_number is not None:
        body = render_pr_comment_body(findings, verdict, counts, repo, sha, workspace)
        click.echo(f"[post] sticky comment on PR #{pr_number}", err=True)
        try:
            client.upsert_pr_comment(pr_number=pr_number, marker=STICKY_COMMENT_MARKER, body=body)
        except GitHubAPIError as err:
            click.echo(f"warn: failed to upsert PR comment: {err}", err=True)

    sys.exit(_EXIT_CODE[verdict])


def _run_scanners(path: str) -> list[Finding]:
    findings: list[Finding] = []
    for scanner_cls in SCANNERS:
        scanner = scanner_cls()
        if not scanner.is_available():
            click.echo(f"[skip] {scanner.name} not on PATH", err=True)
            continue
        click.echo(f"[run]  {scanner.name} on {path}", err=True)
        findings.extend(scanner.scan(path))
    return findings


def _pr_number_from_event() -> int | None:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path or not Path(event_path).is_file():
        return None
    try:
        with open(event_path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    pr = data.get("pull_request")
    if isinstance(pr, dict) and pr.get("number"):
        return pr["number"]
    return data.get("number")


if __name__ == "__main__":
    cli()
