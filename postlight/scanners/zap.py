from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Iterator

from .base import Finding, Severity


_RISK_TO_SEVERITY = {
    "3": Severity.HIGH,
    "2": Severity.MEDIUM,
    "1": Severity.LOW,
    "0": Severity.INFO,
}

ZAP_IMAGE = "ghcr.io/zaproxy/zaproxy:stable"


class ZapBaselineScanner:
    """ZAP baseline (passive) DAST scan against a running URL.

    Demo-only: shells out to Docker, no sandboxing of the target. Production
    DAST against builds-from-source needs a real sandbox (v0.2 work).
    """

    name = "zap-baseline"

    def __init__(self, target_url: str):
        self.target_url = target_url

    def is_available(self) -> bool:
        return shutil.which("docker") is not None

    def scan(self, _path_unused: str = "") -> list[Finding]:
        with tempfile.TemporaryDirectory(prefix="postlight-zap-") as tmpdir:
            output_name = "report.json"
            try:
                subprocess.run(
                    [
                        "docker", "run", "--rm",
                        "-v", f"{tmpdir}:/zap/wrk",
                        "-t", ZAP_IMAGE,
                        "zap-baseline.py",
                        "-t", self.target_url,
                        "-J", output_name,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
                report_path = Path(tmpdir) / output_name
                if not report_path.is_file():
                    return []
                with report_path.open() as f:
                    data = json.load(f)
            except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
                return []
        return list(self._parse(data))

    def _parse(self, data: dict) -> Iterator[Finding]:
        for site in data.get("site", []) or []:
            site_name = site.get("@name", self.target_url)
            for alert in site.get("alerts", []) or []:
                severity = _RISK_TO_SEVERITY.get(str(alert.get("riskcode", "0")), Severity.INFO)
                instances = alert.get("instances") or []
                first_uri = (
                    instances[0].get("uri")
                    if instances and isinstance(instances[0], dict)
                    else site_name
                )
                count = _safe_int(alert.get("count"), default=len(instances) or 1)
                noun = "occurrence" if count == 1 else "occurrences"
                yield Finding(
                    severity=severity,
                    source_tool=self.name,
                    rule_id=str(alert.get("pluginid") or alert.get("alertRef") or "ZAP"),
                    message=f"{alert.get('name', 'ZAP alert')} on {first_uri} ({count} {noun})",
                    extra={
                        "url": first_uri,
                        "cwe": alert.get("cweid"),
                        "wasc": alert.get("wascid"),
                    },
                )


def _safe_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
