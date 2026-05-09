from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Iterator

from .base import Finding, Severity


class OsvScanner:
    name = "osv-scanner"
    binary = "osv-scanner"

    def is_available(self) -> bool:
        return shutil.which(self.binary) is not None

    def scan(self, target: str) -> list[Finding]:
        target_path = Path(target).resolve()
        proc = subprocess.run(
            [self.binary, "--format", "json", "-r", str(target_path)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if not proc.stdout.strip():
            return []
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return []
        return list(self._parse(data))

    def _parse(self, data: dict) -> Iterator[Finding]:
        for result in data.get("results", []):
            source_path = (result.get("source") or {}).get("path", "")
            for pkg in result.get("packages", []):
                package = pkg.get("package") or {}
                name = package.get("name", "?")
                version = package.get("version", "?")
                for vuln in pkg.get("vulnerabilities", []):
                    yield Finding(
                        severity=_severity_from_vuln(vuln),
                        source_tool=self.name,
                        rule_id=vuln.get("id", "UNKNOWN"),
                        message=f"{name}@{version}: {vuln.get('summary', vuln.get('id', ''))}",
                        file=source_path or None,
                        cve=_pick_cve(vuln),
                    )


def _pick_cve(vuln: dict) -> str | None:
    for alias in vuln.get("aliases", []) or []:
        if isinstance(alias, str) and alias.startswith("CVE-"):
            return alias
    vid = vuln.get("id", "")
    if isinstance(vid, str) and vid.startswith("CVE-"):
        return vid
    return None


def _severity_from_vuln(vuln: dict) -> Severity:
    label = (vuln.get("database_specific") or {}).get("severity")
    if isinstance(label, str):
        for sev in Severity:
            if sev.value == label.lower():
                return sev
    for entry in vuln.get("severity", []) or []:
        score = entry.get("score", "") if isinstance(entry, dict) else ""
        try:
            return _from_cvss(float(score))
        except (ValueError, TypeError):
            continue
    return Severity.MEDIUM


def _from_cvss(score: float) -> Severity:
    if score >= 9.0:
        return Severity.CRITICAL
    if score >= 7.0:
        return Severity.HIGH
    if score >= 4.0:
        return Severity.MEDIUM
    if score > 0:
        return Severity.LOW
    return Severity.INFO
