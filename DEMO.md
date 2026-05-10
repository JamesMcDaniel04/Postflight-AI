# Postlight Code — 60-second demo script

Goal: a single screen recording that proves the unified-verdict + DAST wedges
in under a minute. Use this as your prompt for the recording.

## Setup (do this off-camera, before pressing record)

1. Clone & install:
   ```bash
   git clone https://github.com/JamesMcDaniel04/Postflight-AI
   cd Postflight-AI
   python3 -m venv .venv && source .venv/bin/activate
   pip install -e .
   brew install osv-scanner gitleaks
   ```
2. Open a fresh terminal window — large font, dark theme, prompt already in
   `Postflight-AI/`. The repo's `tests/fixtures/vulnerable-demo/` contains
   intentional vulnerable inputs that always produce a HOLD verdict.
3. Optional (for the DAST clip): start a vulnerable target locally.
   ```bash
   docker run --rm -p 3000:3000 bkimminich/juice-shop
   ```

## Recording (≈60s)

| Time | Action | What the viewer sees |
|---|---|---|
| 0–5s | Type the title in the terminal as a comment: `# Postlight Code — security verdict in <2s` | sets context |
| 5–25s | Run `postlight scan tests/fixtures/vulnerable-demo/` | rich-formatted finding tables grouped by severity (CRITICAL / HIGH / MEDIUM / LOW), then a red HOLD verdict panel with counts |
| 25–35s | Briefly highlight: "50+ findings across two scanners, one verdict, one exit code" | scrollback or `echo $?` showing `1` |
| 35–55s | Run `postlight scan tests/fixtures/vulnerable-demo/ --demo-dast http://localhost:3000` (skip this segment if you don't want to spin up Juice Shop) | additional ZAP findings appear under the same verdict |
| 55–60s | Title card or voiceover: "drop into your CI as a GitHub Action — link in description" | end frame |

## Talking points (for voiceover, if any)

- "Three open-source scanners — osv-scanner, gitleaks, ZAP — under one verdict."
- "Same verdict on your laptop and in your PR check-run."
- "Not trying to be Snyk. Trying to be the unified gate that decides ship/hold."

## Things NOT to demo (yet)

- The GitHub Action posting a check-run + PR comment — pending billing fix on
  the test repo. Re-record with that segment once unlocked; it's the strongest
  wedge clip.
- Inline diff annotations — same blocker.
- Real DAST against a built-from-source target — needs sandboxing; v0.2 work.

## Distribution

Drop the recording into wedge conversations as the answer to "what is this?"
Don't link to a landing page (we don't have one and the spike doesn't need one).
A 60s clip + this README is the whole pitch surface.
