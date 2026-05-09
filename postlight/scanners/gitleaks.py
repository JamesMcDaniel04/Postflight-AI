from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from .base import Finding, Severity


class GitleaksScanner:
    name = "gitleaks"
    binary = "gitleaks"

    def is_available(self) -> bool:
        return shutil.which(self.binary) is not None

    def scan(self, target: str) -> list[Finding]:
        target_path = Path(target).resolve()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            report_path = tmp.name
        try:
            subprocess.run(
                [
                    self.binary, "detect",
                    "--source", str(target_path),
                    "--report-format", "json",
                    "--report-path", report_path,
                    "--no-banner",
                    "--exit-code", "0",
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            with open(report_path) as f:
                content = f.read().strip()
            data = json.loads(content) if content else []
        except (json.JSONDecodeError, FileNotFoundError):
            data = []
        finally:
            Path(report_path).unlink(missing_ok=True)

        return [
            Finding(
                severity=Severity.CRITICAL,
                source_tool=self.name,
                rule_id=item.get("RuleID", "secret"),
                message=item.get("Description") or "leaked secret",
                file=item.get("File"),
                line=item.get("StartLine"),
            )
            for item in data
        ]
