# Postlight Code

Unified security verdict for code repositories — `SHIP` / `REVIEW` / `HOLD`.

Runs open-source scanners (osv-scanner for SCA, gitleaks for secrets), normalizes
findings, and produces a single verdict suitable for blocking/approving a PR.

## Status

Day 1 spike: local CLI + two scanners. Day 2 adds a GitHub Action surface; Day 3
adds a DAST demo path.

## Install (development)

```bash
pip install -e .
```

You will also need the scanner binaries on PATH:

```bash
brew install osv-scanner gitleaks   # macOS
```

For Linux, see the [osv-scanner releases](https://github.com/google/osv-scanner/releases)
and [gitleaks releases](https://github.com/gitleaks/gitleaks/releases).

## Usage

```bash
postlight scan /path/to/repo
```

Exit codes: `0` for SHIP or REVIEW, `1` for HOLD.

## Verdict rules

- `HOLD` — any finding at CRITICAL severity (CVSS >= 9.0, or any leaked secret).
- `REVIEW` — any finding at HIGH severity (CVSS 7.0–8.9).
- `SHIP` — otherwise.

## Tests

```bash
pip install -e ".[dev]"
pytest
```
