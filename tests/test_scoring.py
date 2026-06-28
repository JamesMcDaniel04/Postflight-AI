from __future__ import annotations

from ascent.goals import KPI, make_observation
from ascent.scoring import roll_observations


def _kpi(comparator="gte", target=0.8):
    return KPI(id="k", goal_id="g", name="K", metric="task_success_rate",
               target=target, comparator=comparator)


def _obs(value, weight=1, evaluator="persona_agent"):
    return make_observation(kpi_id="k", value=value, evaluator=evaluator, sample_weight=weight)


def test_unmeasured_when_no_observations():
    [result] = roll_observations([], [_kpi()])
    assert result.status == "unmeasured"
    assert result.actual is None
    assert result.sample_size == 0


def test_pass_gte():
    [result] = roll_observations([_obs(0.9)], [_kpi(comparator="gte", target=0.8)])
    assert result.status == "pass"
    assert result.actual == 0.9


def test_near_gte_within_tolerance():
    # 0.75 is below the 0.8 target but within 10% (>= 0.72)
    [result] = roll_observations([_obs(0.75)], [_kpi(comparator="gte", target=0.8)])
    assert result.status == "near"


def test_fail_gte_outside_tolerance():
    [result] = roll_observations([_obs(0.5)], [_kpi(comparator="gte", target=0.8)])
    assert result.status == "fail"


def test_pass_lte():
    [result] = roll_observations([_obs(150)], [_kpi(comparator="lte", target=180)])
    assert result.status == "pass"


def test_fail_lte():
    [result] = roll_observations([_obs(250)], [_kpi(comparator="lte", target=180)])
    assert result.status == "fail"


def test_sample_weighted_mean():
    # (0.6*1 + 0.9*3) / 4 = 0.825 -> passes a gte-0.8 target
    [result] = roll_observations([_obs(0.6, weight=1), _obs(0.9, weight=3)],
                                 [_kpi(comparator="gte", target=0.8)])
    assert result.status == "pass"
    assert round(result.actual, 3) == 0.825
    assert result.sample_size == 4


def test_min_sample_size_caps_pass_at_near():
    # A passing value with too little evidence cannot certify a pass.
    [result] = roll_observations([_obs(0.9, weight=1)], [_kpi(comparator="gte", target=0.8)],
                                 min_sample_size=5)
    assert result.status == "near"


def test_contributing_evaluators_recorded():
    obs = [_obs(0.9, evaluator="persona_agent"), _obs(0.85, evaluator="replay")]
    [result] = roll_observations(obs, [_kpi()])
    assert result.contributing_evaluators == ["persona_agent", "replay"]


# ---- KPI.source routing + cross-evaluator trust ------------------------------

def _kpi_src(source):
    return KPI(id="k", goal_id="g", name="K", metric="task_success_rate", target=0.8, source=source)


def test_source_routing_ignores_mismatched_evaluator():
    # a persona-only KPI must ignore a replay observation
    obs = [make_observation(kpi_id="k", value=0.95, evaluator="replay")]
    [result] = roll_observations(obs, [_kpi_src("persona")])
    assert result.status == "unmeasured"


def test_source_any_counts_every_evaluator():
    obs = [make_observation(kpi_id="k", value=0.95, evaluator="replay")]
    [result] = roll_observations(obs, [_kpi_src("any")])
    assert result.status == "pass"


def test_replay_outweighs_persona_on_shared_kpi():
    # persona says 0.4 (fail), replay says 1.0 (pass); replay's higher trust wins
    obs = [make_observation(kpi_id="k", value=0.4, evaluator="persona_agent"),
           make_observation(kpi_id="k", value=1.0, evaluator="replay")]
    [result] = roll_observations(obs, [_kpi_src("any")])
    assert round(result.actual, 3) == 0.85  # (0.4*1 + 1.0*3) / 4
    assert result.status == "pass"
