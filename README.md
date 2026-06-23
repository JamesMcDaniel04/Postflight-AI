# Postlight Code

Unified security verdict for code repositories — `SHIP` / `REVIEW` / `HOLD`.

Runs three open-source scanners (osv-scanner for SCA, gitleaks for secrets,
ZAP baseline for DAST), normalizes findings, and produces a single verdict
suitable for blocking or approving a PR.

## Status

3-day spike (v0.1). Local CLI + GitHub Action + DAST demo path all working.
The GitHub Action wrapper is implemented but un-validated against a live
runner pending an Actions billing fix on the test repo. Not a product yet —
the goal is to learn which of three wedges (unified verdict, GitHub-native UX,
or distribution speed via Actions) resonates before committing to v0.2 scope.

## Install

```bash
pip install -e .
```

You will also need the scanner binaries on PATH:

```bash
brew install osv-scanner gitleaks   # macOS
```

For Linux, see the [osv-scanner releases](https://github.com/google/osv-scanner/releases)
and [gitleaks releases](https://github.com/gitleaks/gitleaks/releases).

The DAST path additionally requires Docker (the ZAP baseline scanner runs in a
container).

## Usage

### Local scan (SCA + secrets)

```bash
postlight scan /path/to/repo
```

Exit codes: `0` for SHIP or REVIEW, `1` for HOLD.

### Local scan + DAST against a running URL

```bash
postlight scan /path/to/repo --demo-dast http://localhost:3000
```

This is a demo path. ZAP runs against whatever URL you provide — typically a
local app, Juice Shop in Docker, or a staging environment. Production DAST
against builds-from-source needs a real sandbox; that's v0.2 work.

### As a GitHub Action

Add to `.github/workflows/security.yml`:

```yaml
name: postlight
on: [pull_request]
jobs:
  scan:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      checks: write
      pull-requests: write
    steps:
      - uses: actions/checkout@v4
      - uses: jamesmcdaniel04/Postflight-AI@main
```

The action posts:

- a **check-run** with the verdict as conclusion (success / neutral / failure),
- inline **annotations** on the diff (top 50 findings by severity), and
- a sticky **PR comment** with the full finding table and links into the GitHub
  blob at the scanned commit.

The `permissions:` block above is required — the default `GITHUB_TOKEN` does
not get `checks: write` and `pull-requests: write` unless declared.

## Branch protection

To make the verdict actually block merges, add a branch protection rule on
`main`:

1. Settings → Branches → Add branch protection rule.
2. Branch name pattern: `main`.
3. Check **Require status checks to pass before merging**.
4. Search for `Postlight` in the status check list and select it.
5. (Optional) Check **Require branches to be up to date**.

GitHub only surfaces a check name in the protection UI after it has appeared
on at least one successful run, so this configuration step waits until after
the first PR has run the action.

## Verdict rules

- `HOLD` — any finding at CRITICAL severity (CVSS ≥ 9.0, or any leaked secret).
- `REVIEW` — any finding at HIGH severity (CVSS 7.0–8.9, or ZAP riskcode 3).
- `SHIP` — otherwise.

## Tests

```bash
pip install -e ".[dev]"
pytest
```

35 tests cover the verdict engine, GitHub markdown/annotations builders, the
mocked GitHub API client, and the ZAP JSON parser.
