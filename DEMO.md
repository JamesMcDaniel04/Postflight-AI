# Ascent — 60-second demo script

Goal: a single screen recording that shows the goal-based QA loop — declare a
goal, run the app, get a milestone-readiness verdict + ranked recommendations —
in under a minute.

## Setup (off-camera, before recording)

```bash
git clone https://github.com/JamesMcDaniel04/Postflight-AI
cd Postflight-AI
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

The repo ships `examples/ascent.yaml` — a sample goal config (activation goal,
three KPIs, a "busy founder" persona) you can run immediately with `--demo`.

For the live persona run (optional, heavier): `pip install -e ".[live]"`,
`playwright install chromium`, export `ANTHROPIC_API_KEY`, and point `--config`
at a real `ascent.yaml` whose `target` is a running web app.

## Recording (≈60s)

| Time | Action | What the viewer sees |
|---|---|---|
| 0–8s | Type the title as a comment: `# Ascent — is my app ready for its next milestone?` | sets context |
| 8–20s | Run `ascent init` and breeze through the prompts (goal → KPIs → milestone → persona) | the wizard authoring + ratifying `ascent.yaml` |
| 20–45s | Run `ascent run --config examples/ascent.yaml --demo` | the KPI scorecard, gap tables grouped by impact, the "unaligned observations" bucket, and a red **BLOCKED toward Public Beta** banner naming the blocking KPI |
| 45–55s | Highlight the **Top recommendations** table | ranked, goal-linked fixes — each tagged with its KPI and the gaps it clears |
| 55–60s | Voiceover: "Every gap traces to a KPI you chose. Drop it into CI as a GitHub Action." | end frame |

## Talking points

- "Not 'does the app match its spec?' — 'is the app good enough at its goal to
  clear the next milestone?'"
- "Persona agents drive the real running app like live users; every gap and
  recommendation traces back to a KPI in your version-controlled goal config."
- "Humans stay in the loop — Ascent reports and ranks; it doesn't auto-merge."

## In CI (GitHub Action)

```yaml
name: ascent
on: [pull_request]
jobs:
  readiness:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      checks: write
      pull-requests: write
    steps:
      - uses: actions/checkout@v4
      - uses: jamesmcdaniel04/Postflight-AI@main
        with:
          target: web://https://staging.your-app.com
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

The action posts a milestone-readiness check-run (readiness as the conclusion)
and a sticky PR comment with the KPI scorecard, ranked recommendations, and the
gap report.

## Not yet in the demo

- A real persona run against a live web app — needs `[live]` deps, a browser,
  and an API key; show the `--demo` path for a deterministic recording.
- The `journey` and `replay` evaluators (scripted journeys + analytics) — they
  register but stay inactive until a journeys file / analytics export is present.
