# Ascent

Goal-based app QA — **train your app to hit its KPIs and unlock its next milestone.**

Most testing answers "does the app match its spec?" (Playwright/Cypress) or
"what did users do?" (FullStory/PostHog). Ascent answers the question no one
else owns: **is this app good enough at its main goal to unlock its next
milestone — and exactly which gaps block each KPI?**

You declare your app's goal, the KPIs that prove it, the milestone it must
reach, and the personas that exercise it. Ascent drives the real running app
like live users, scores each KPI, and returns a **milestone-readiness verdict**
(`ON_TRACK` / `NEEDS_WORK` / `BLOCKED`) plus a prioritized, **goal-linked gap
report**. Every gap traces back to a KPI in your config, or it is quarantined
out of the verdict. Humans (or downstream coding agents) do the fixing — Ascent
reports and ranks; it does not auto-merge or deploy.

## Status

A pivot from a security-verdict CLI. The full pipeline runs end to end: goal
config → hybrid evaluators → goal-alignment quarantine → KPI scoring →
milestone-readiness verdict → ranked recommendations → console/GitHub report,
with `ascent init` (author the config), `ascent run` / `ascent ci` (evaluate),
and `ascent fix` (human-approve recommendations).

Three evaluators implement one protocol and merge into one report:

- **`persona_agent`** — LLM persona agents drive the real running app (web via
  Playwright) toward each persona's intent. Needs the `live` extra + an API key.
- **`journey`** — scripted journeys scored by the LLM judge. Activates when the
  config declares `journeys`.
- **`replay`** — KPI actuals + drop-off gaps from an analytics export. Activates
  when `replay.export_path` points at a file.

Each self-gates on its requirements, so without the optional deps `ascent run`
produces an all-`unmeasured` scorecard and `ascent run --demo` injects synthetic
gaps to preview the full report.

## Install

```bash
pip install -e .            # core engine + CLI (no browser / LLM)
pip install -e ".[live]"    # + anthropic + playwright for the persona evaluator
playwright install chromium # browser for the web driver
export ANTHROPIC_API_KEY=…  # the LLM judge
```

The target is a surface-prefixed spec: `web://`, `api://` (concrete), or
`ios://` / `android://` (declared seams). Each surface is one driver behind one
interface.

## The goal config

Everything keys off a version-controlled `ascent.yaml` — your app's goal, KPIs
(with targets, weights, and which evaluator measures them), the next milestone
and its **required KPIs** (the readiness bar *you* choose), and your personas.
See [examples/ascent.yaml](examples/ascent.yaml) for an annotated sample.

```bash
# Interactively author + ratify ./ascent.yaml (no LLM; instant and offline).
ascent init
```

The wizard walks you through the target, goal, KPIs (auto-suggesting the
comparator from the metric), the milestone and its required KPIs, and your
personas, then stamps a ratification hash. Re-running it edits and re-ratifies.

## Usage

```bash
# Run the evaluators against a target and print a readiness report + recommendations.
ascent run web://http://localhost:3000 --config ascent.yaml

# Preview the full report (scorecard + gap tables + recs + verdict) with synthetic gaps.
ascent run --config examples/ascent.yaml --demo

# Review ranked recommendations and approve fix requests (human-in-the-loop).
ascent fix --config ascent.yaml --out fixes.json
```

Exit codes: `0` for `ON_TRACK` or `NEEDS_WORK`, `1` for `BLOCKED`.

`ascent fix` re-runs the pipeline, then walks you through each ranked
recommendation for approval. Ascent **does not modify code** — each approved
request is the goal-linked payload (kpi, goal, gap ids, action) that a
downstream coding agent consumes. That keeps the human in the loop on alignment.

### In CI (GitHub)

`ascent ci` runs the same pipeline and posts a check-run (readiness as the
conclusion), inline annotations for any file-anchored gaps, and a sticky PR
comment with the KPI scorecard, ranked recommendations, and gap report. It reads
`GITHUB_TOKEN`, `GITHUB_REPOSITORY`, and `GITHUB_SHA`. The packaged
[action.yml](action.yml) + [Dockerfile](Dockerfile) bundle Playwright + Chromium;
pass `ANTHROPIC_API_KEY` and `GITHUB_TOKEN` via the step `env` (see [DEMO.md](DEMO.md)).

## Readiness rules

Each required KPI is scored `pass` / `near` / `fail` / `unmeasured`, then the
milestone gate decides:

- **BLOCKED** — a required KPI fails, or a blocker-impact gap sits on a required
  KPI. *(exit 1)*
- **NEEDS_WORK** — a required KPI is near/unmeasured, a major gap sits on a
  required KPI, or a non-required KPI fails. *(exit 0 — surfaces in CI without
  hard-failing)*
- **ON_TRACK** — every required KPI passes with no blocker/major gap on a
  required KPI. *(exit 0)*

The verdict always names the blocking KPI, e.g.
`NEEDS_WORK toward Public Beta — Booking completion 0.71/0.80`.

## Alignment (human-in-the-loop)

Alignment is enforced structurally, not by convention:

- **Quarantine** — a gap whose `kpi_id` is not in your config is bucketed as an
  "unaligned observation," excluded from the scorecard and verdict, and surfaced
  as a "should the goal config be expanded?" nudge.
- **Drift-gate** — if the goal changed since it was ratified (config-hash
  mismatch), runs *warn* (never block), preserving the expedited workflow while
  leaving an audit trail.

## Roadmap

- **Phase 0 (done)** — engine re-skin: goals/KPIs, quarantine, scoring,
  readiness verdict, scorecard + gap report, CLI.
- **Phase 1 (done)** — `ascent init` wizard + ratification + drift-gate.
- **Phase 2 (done)** — Driver protocol + Playwright web driver + LLM Judge port
  (`AnthropicJudge` + `RecordedJudge`) + the `persona_agent` evaluator.
- **Phase 3 (done)** — recommendation ranking + the GitHub Action surface.
- **Phase 4 (done)** — `journey` + `replay` evaluators, a concrete `api://`
  driver (`ios`/`android` declared seams), and `ascent fix` — the human-gated
  recommendation → fix-request bridge a coding agent consumes.

Recommendations get an optional LLM consolidation pass: when a judge is
available, multi-gap clusters are merged into one recommendation grounded in the
cluster's evidence; without one it falls back to deterministic clustering.

Future: concrete mobile drivers (Appium) and a closed, still-human-gated
`fix → re-test` loop.

## Tests

```bash
pip install -e ".[dev]"
pytest
```

104 tests cover the readiness engine, KPI scoring, goal-alignment quarantine and
drift-gate, config (de)serialization + hashing, the `init` wizard, the driver
factory + Judge port, the persona / journey / replay evaluators, the `api://`
driver, the recommendation engine, the `fix` command, the console/GitHub output
builders, and the CLI. The live persona stack runs deterministically in tests
via a fake driver + recorded judge (no browser or API key).
