"""The goal config — the human-ratified spine threaded through every stage.

A ``GoalConfig`` (persisted as ``ascent.yaml``) declares the app's main goal,
the KPIs that prove it, the next milestone, and the personas that exercise it.
Every gap, KPI score, verdict, and recommendation traces back to a KPI defined
here, or it is quarantined out of the report.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field

import yaml

from .evaluators.base import Gap, Impact, KpiObservation, Locator

METRICS = (
    "task_success_rate",
    "time_to_complete_s",
    "drop_off_rate",
    "error_rate",
    "satisfaction_score",
    "custom",
)
COMPARATORS = ("gte", "lte", "eq")
KPI_SOURCES = ("persona", "journey", "replay", "any")
GATES = ("all_required", "weighted_threshold")


@dataclass
class Goal:
    id: str
    statement: str
    success_definition: str = ""


@dataclass
class KPI:
    id: str
    goal_id: str
    name: str
    metric: str
    target: float
    comparator: str = "gte"
    unit: str = ""
    weight: int = 3  # human-set importance 1-5; ranks recs + breaks verdict ties
    source: str = "any"  # which evaluator kind measures it


@dataclass
class Persona:
    id: str
    name: str
    description: str = ""
    intent: str = ""
    entry_point: str = ""
    success_signal: str = ""
    kpi_ids: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)


@dataclass
class Milestone:
    id: str
    name: str
    unlock_criteria: str = ""
    required_kpi_ids: list[str] = field(default_factory=list)
    gate: str = "all_required"
    threshold: float = 1.0


@dataclass
class Budgets:
    max_personas: int = 3
    max_steps: int = 40
    max_turns: int = 25
    timeout_s: int = 300
    # A KPI needs at least this many samples to be certified "pass"; below it,
    # a passing value is capped at "near" so one flaky run can't flip the verdict.
    min_sample_size: int = 1


@dataclass
class Journey:
    """A scripted user journey for the JourneyEvaluator. ``steps`` are driver
    actions ({type: click|type|navigate, ref/text/url})."""

    id: str
    name: str
    kpi_id: str
    success_signal: str = ""
    entry_point: str = ""
    steps: list[dict] = field(default_factory=list)


@dataclass
class Replay:
    """Points the ReplayEvaluator at an analytics/session funnel export."""

    export_path: str
    source: str = "csv"  # posthog | amplitude | csv


@dataclass
class GoalConfig:
    version: int
    product: str
    target: str
    goal: Goal
    milestone: Milestone
    kpis: list[KPI] = field(default_factory=list)
    personas: list[Persona] = field(default_factory=list)
    budgets: Budgets = field(default_factory=Budgets)
    evaluators: list[str] = field(default_factory=lambda: ["persona_agent"])
    journeys: list[Journey] = field(default_factory=list)
    replay: Replay | None = None
    ratified_by: str = ""
    ratified_at: str = ""
    config_hash: str = ""
    # Unmapped top-level keys (judge:, ...) preserved across a round-trip.
    extra: dict = field(default_factory=dict)

    def kpi_ids(self) -> set[str]:
        return {k.id for k in self.kpis}

    def kpi(self, kpi_id: str) -> KPI | None:
        return next((k for k in self.kpis if k.id == kpi_id), None)

    def required_kpis(self) -> list[KPI]:
        """The KPIs that gate the milestone. Empty ``required_kpi_ids`` means
        every KPI is part of the bar."""
        required = self.milestone.required_kpi_ids or list(self.kpi_ids())
        return [k for k in self.kpis if k.id in set(required)]


# ---- goal-linkage write path -------------------------------------------------
# Building gaps/observations only through these helpers keeps the kpi_id/persona/
# evidence/recommendation fields off ad-hoc ``extra`` usage.

def make_gap(
    *,
    impact: Impact,
    evaluator: str,
    check_id: str,
    description: str,
    kpi_id: str | None = None,
    persona: str | None = None,
    locator: Locator | None = None,
    evidence: list[str] | None = None,
    recommendation: str | None = None,
    confidence: float = 1.0,
    **extra,
) -> Gap:
    return Gap(
        impact=impact,
        evaluator=evaluator,
        check_id=check_id,
        description=description,
        locator=locator,
        kpi_id=kpi_id,
        persona=persona,
        evidence=list(evidence or []),
        recommendation=recommendation,
        confidence=confidence,
        extra=dict(extra),
    )


def make_observation(*, kpi_id: str, value: float, evaluator: str, sample_weight: int = 1) -> KpiObservation:
    return KpiObservation(kpi_id=kpi_id, value=float(value), evaluator=evaluator, sample_weight=sample_weight)


# ---- ratification hash -------------------------------------------------------

def config_hash(config: GoalConfig) -> str:
    """Stable sha256 over goal + milestone + kpis + personas.

    Excludes ``ratified_*`` and ``config_hash`` themselves so the drift-gate can
    compare a freshly computed hash against the stored ratified one. Lists are
    sorted by id so reordering does not change the hash.
    """

    payload = {
        "goal": asdict(config.goal),
        "milestone": asdict(config.milestone),
        "kpis": [asdict(k) for k in sorted(config.kpis, key=lambda k: k.id)],
        "personas": [asdict(p) for p in sorted(config.personas, key=lambda p: p.id)],
        "journeys": [asdict(j) for j in sorted(config.journeys, key=lambda j: j.id)],
        "replay": asdict(config.replay) if config.replay else None,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ---- (de)serialization -------------------------------------------------------

_TOP_KEYS = {
    "version", "product", "target", "goal", "milestone", "kpis", "personas",
    "budgets", "evaluators", "journeys", "replay", "ratified_by", "ratified_at", "config_hash",
}


def _from_dict(data: dict) -> GoalConfig:
    goal = Goal(**data["goal"])
    milestone = Milestone(**data["milestone"])
    kpis = [KPI(**k) for k in data.get("kpis", [])]
    personas = [Persona(**p) for p in data.get("personas", [])]
    budgets = Budgets(**data["budgets"]) if data.get("budgets") else Budgets()
    journeys = [Journey(**j) for j in data.get("journeys", [])]
    replay = Replay(**data["replay"]) if data.get("replay") else None
    extra = {k: v for k, v in data.items() if k not in _TOP_KEYS}
    return GoalConfig(
        version=int(data.get("version", 1)),
        product=data.get("product", ""),
        target=data.get("target", ""),
        goal=goal,
        milestone=milestone,
        kpis=kpis,
        personas=personas,
        budgets=budgets,
        evaluators=data.get("evaluators", ["persona_agent"]),
        journeys=journeys,
        replay=replay,
        ratified_by=data.get("ratified_by", ""),
        ratified_at=data.get("ratified_at", ""),
        config_hash=data.get("config_hash", ""),
        extra=extra,
    )


def to_dict(config: GoalConfig) -> dict:
    out: dict = {
        "version": config.version,
        "product": config.product,
        "target": config.target,
        "ratified_by": config.ratified_by,
        "ratified_at": config.ratified_at,
        "config_hash": config.config_hash,
        "goal": asdict(config.goal),
        "milestone": asdict(config.milestone),
        "kpis": [asdict(k) for k in config.kpis],
        "personas": [asdict(p) for p in config.personas],
        "budgets": asdict(config.budgets),
        "evaluators": list(config.evaluators),
    }
    if config.journeys:
        out["journeys"] = [asdict(j) for j in config.journeys]
    if config.replay is not None:
        out["replay"] = asdict(config.replay)
    out.update(config.extra)
    return out


def load_config(path: str) -> GoalConfig:
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a YAML mapping at the top level")
    return _from_dict(data)


def dump_config(config: GoalConfig, path: str) -> None:
    with open(path, "w") as f:
        yaml.safe_dump(to_dict(config), f, sort_keys=False, default_flow_style=False)
