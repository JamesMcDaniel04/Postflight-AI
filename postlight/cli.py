from __future__ import annotations

import sys

import click

from .output.console import render
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
    findings = []
    for scanner_cls in SCANNERS:
        scanner = scanner_cls()
        if not scanner.is_available():
            click.echo(f"[skip] {scanner.name} not on PATH", err=True)
            continue
        click.echo(f"[run]  {scanner.name} on {path}", err=True)
        findings.extend(scanner.scan(path))
    verdict, counts = compute(findings)
    render(findings, verdict, counts)
    sys.exit(_EXIT_CODE[verdict])


if __name__ == "__main__":
    cli()
