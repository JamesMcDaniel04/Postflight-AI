from __future__ import annotations

from ascent.evaluators.base import Impact, Locator
from ascent.goals import KPI, Goal, GoalConfig, Milestone, make_gap
from ascent.recommend import recommend
from ascent.scoring import KpiResult


def _config():
    return GoalConfig(
        version=1, product="P", target="web://x", goal=Goal(id="activation", statement="s"),
        milestone=Milestone(id="m", name="Beta", required_kpi_ids=["completion", "speed"]),
        kpis=[
            KPI(id="completion", goal_id="activation", name="Completion", metric="task_success_rate",
                target=0.8, comparator="gte", weight=5),
            KPI(id="speed", goal_id="activation", name="Speed", metric="time_to_complete_s",
                target=180, comparator="lte", weight=2),
        ],
    )


def _gap(kpi_id, impact, check_id, rec=None, conf=0.8):
    return make_gap(impact=impact, evaluator="persona_agent", check_id=check_id,
                    description=f"friction on {kpi_id}", kpi_id=kpi_id,
                    locator=Locator(kind="route", value="/"), recommendation=rec, confidence=conf)


def _result(kpi_id, actual, comparator, target):
    return KpiResult(kpi_id=kpi_id, name=kpi_id, target=target, comparator=comparator,
                     actual=actual, status="fail", sample_size=5)


def test_recommendation_per_kpi_cluster_triple_linked():
    config = _config()
    gaps = [
        _gap("completion", Impact.BLOCKER, "c1", rec="wire up Pay"),
        _gap("completion", Impact.MAJOR, "c2"),
        _gap("speed", Impact.MINOR, "s1"),
    ]
    results = [_result("completion", 0.5, "gte", 0.8), _result("speed", 240, "lte", 180)]
    recs = recommend(gaps, config, results)

    assert len(recs) == 2
    by_kpi = {r.kpi_id: r for r in recs}
    assert set(by_kpi["completion"].gap_ids) == {"c1", "c2"}  # clustered
    assert by_kpi["completion"].goal_id == "activation"        # linked to goal
    assert by_kpi["completion"].action == "wire up Pay"        # from highest-impact gap
    assert by_kpi["completion"].effort_hint == "L"             # cluster has a blocker


def test_priority_ranks_high_weight_high_impact_first():
    config = _config()
    gaps = [
        _gap("completion", Impact.BLOCKER, "c1"),  # weight 5, blocker
        _gap("speed", Impact.MINOR, "s1"),         # weight 2, minor
    ]
    results = [_result("completion", 0.5, "gte", 0.8), _result("speed", 200, "lte", 180)]
    recs = recommend(gaps, config, results)
    assert recs[0].kpi_id == "completion"
    assert recs[0].priority_score > recs[1].priority_score


def test_synthesized_action_when_gap_has_no_recommendation():
    config = _config()
    recs = recommend([_gap("completion", Impact.MAJOR, "c1")], config,
                     [_result("completion", 0.5, "gte", 0.8)])
    assert "Completion" in recs[0].action  # falls back to a KPI-referencing action


def test_no_gaps_no_recommendations():
    assert recommend([], _config(), []) == []


def test_render_recommendations_markdown():
    from ascent.output.github import render_recommendations
    recs = recommend([_gap("completion", Impact.BLOCKER, "c1", rec="wire up Pay")],
                     _config(), [_result("completion", 0.5, "gte", 0.8)])
    md = render_recommendations(recs)
    assert "Top recommendations" in md
    assert "completion" in md
    assert "wire up Pay" in md
    assert render_recommendations([]) == ""
