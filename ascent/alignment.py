"""The alignment spine: keep off-goal noise out of the verdict.

Two cheap, pure checkpoints sit in the NORMALIZE -> AGGREGATE seam:

* ``quarantine`` partitions gaps by whether their ``kpi_id`` resolves to a KPI
  in the ratified config. Unaligned gaps are surfaced separately and can never
  move the verdict or generate a recommendation.
* ``drift_check`` warns (never blocks) when the live config no longer matches
  the hash that was ratified, preserving the expedited framing while leaving an
  audit trail.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .evaluators.base import Gap
from .goals import GoalConfig, config_hash


@dataclass
class Quarantine:
    aligned: list[Gap] = field(default_factory=list)
    unaligned: list[Gap] = field(default_factory=list)


def quarantine(gaps: list[Gap], config: GoalConfig) -> Quarantine:
    valid = config.kpi_ids()
    result = Quarantine()
    for gap in gaps:
        if gap.kpi_id and gap.kpi_id in valid:
            result.aligned.append(gap)
        else:
            result.unaligned.append(gap)
    return result


def drift_check(config: GoalConfig) -> str | None:
    """Return a warning if the goal moved since ratification, else None.

    An unratified config (no stored hash) never warns — there is nothing to
    drift from yet.
    """

    if not config.config_hash:
        return None
    live = config_hash(config)
    if live != config.config_hash:
        return (
            "goal config changed since it was ratified "
            f"(ratified {config.config_hash[:21]}…, live {live[:21]}…) — "
            "re-run `ascent init` to re-ratify the goal"
        )
    return None
