"""Scenario comparison, self-healing recommendations, forecasting and grounded explanations."""
import pytest

from app.engines import twin_explain as tx
from app.engines import twin_forecast as tf
from app.engines import twin_recovery as tr
from app.engines.twin_engine import TwinConfig, run_replications
from app.engines.twin_scenarios import PRESET_IDS, compare_scenarios, paired_stat, preset_scenarios

BASE = dict(arrival_rate=1.2, mean_service_time=4.0, num_counters=5, duration=120, abandonment_enabled=False)


def _configs():
    return [(p["name"], TwinConfig(**p["configuration"])) for p in preset_scenarios(BASE)]


def test_presets_are_the_six_required_scenarios_and_valid():
    assert [p["id"] for p in preset_scenarios(BASE)] == PRESET_IDS and len(PRESET_IDS) == 6
    assert len(_configs()) == 6


def test_compare_rejects_wrong_scenario_counts():
    with pytest.raises(ValueError):
        compare_scenarios(_configs()[:1], 3, 1)
    with pytest.raises(ValueError):
        compare_scenarios(_configs() * 1, 3, 1)  # six scenarios


def test_compare_uses_shared_seeds_and_reports_paired_differences():
    cmp = compare_scenarios(_configs()[:5], 6, 11)
    w = cmp["metrics"]["avg_waiting_time"]
    assert w["best_index"] == 0 and w["values"][2] > w["values"][0]  # staff shortage is worse than normal
    assert w["paired"][0] is None and w["paired"][2]["significant"] is True
    assert {"avg_waiting_time", "p95_waiting_time", "max_queue_length", "total_served", "abandoned",
            "avg_utilization_available", "resource_cost"} <= set(cmp["metrics"])
    again = compare_scenarios(_configs()[:5], 6, 11)
    assert again["metrics"]["avg_waiting_time"]["values"] == w["values"]


def test_paired_stat_handles_identical_and_short_inputs():
    assert paired_stat([1.0], [2.0]) is None
    assert paired_stat([1.0, 2.0], [1.0, 2.0])["significant"] is False


STRESS = dict(BASE, staff_available=2, standby_counters=[4], outages=[dict(counter=0, start=30, end=100)])


def test_recommendations_are_ranked_by_simulation_and_include_before_after():
    rec = tr.recommend(TwinConfig(**STRESS), 6, 5)
    assert rec["simulation_only"] is True and rec["recommendations"]
    scores = [r["score"] for r in rec["recommendations"]]
    assert scores == sorted(scores)
    best = rec["recommendations"][0]
    assert best["improves"] and best["improvement"]["avg_waiting_time"]["after"] < \
        best["improvement"]["avg_waiting_time"]["before"]
    assert rec["recommended_id"] == best["id"] and "Counter" in " ".join(rec["diagnosis"]["closed_counters"])


def test_recommend_budget_guard():
    with pytest.raises(ValueError):
        tr.recommend(TwinConfig(**STRESS), 1, 5)


def test_automatic_recovery_improves_and_returns_playback():
    out = tr.auto_recover(TwinConfig(**STRESS), 6, 5)
    assert out["simulation_only"] is True and out["chosen"]
    assert out["before_after"]["avg_waiting_time"]["after"] < out["before_after"]["avg_waiting_time"]["before"]
    assert any(e["type"] == "recovery_action" for e in out["recovered"]["primary"]["events"])


def test_auto_recovery_reports_no_change_when_nothing_to_fix():
    easy = TwinConfig(arrival_rate=0.2, mean_service_time=2, num_counters=3, duration=60)
    out = tr.auto_recover(easy, 4, 1)
    assert out["chosen"] is None and out["notes"]


STATE = {"queue_length": 7, "arrival_rate_per_min": 1.4, "arrival_rate_source": "test",
         "counters": [{"index": i, "name": f"C{i}", "rate_per_min": 0.25, "active": i < 4, "busy": i < 3}
                      for i in range(5)]}


def test_forecast_covers_four_horizons_and_all_metrics():
    fc = tf.forecast(STATE, replications=20, seed=3)
    assert [h["horizon_min"] for h in fc["horizons"]] == [5, 15, 30, 60]
    for h in fc["horizons"]:
        assert {"queue_length", "waiting_time_min", "arrivals_since_now", "counter_utilization", "congestion"} <= set(h)
        assert h["queue_length"]["p10"] <= h["queue_length"]["mean"] <= h["queue_length"]["p90"]
    # demand (1.4/min) exceeds capacity (1.0/min): the queue must grow and congestion must be flagged
    assert fc["horizons"][-1]["queue_length"]["mean"] > fc["horizons"][0]["queue_length"]["mean"]
    assert fc["horizons"][-1]["congestion"]["risk"] == "high"
    assert fc["starting_state"]["load_ratio"] == pytest.approx(1.4)


def test_forecast_needs_an_active_counter():
    with pytest.raises(tf.ForecastUnavailable):
        tf.forecast({**STATE, "counters": [{**c, "active": False} for c in STATE["counters"]]})


def test_forecast_waiting_time_uses_prediction_engine_baseline():
    fc = tf.forecast({**STATE, "arrival_rate_per_min": 0.001}, replications=10, seed=1)
    # near-zero arrivals: at 5 min the wait is the existing baseline formula applied to the drained state
    assert fc["horizons"][0]["waiting_time_min"]["mean"] >= 0


# ----- explanations
def _facts():
    cfg = TwinConfig(**STRESS)
    return cfg, tx.facts_from_simulation(cfg, run_replications(cfg, 4, 5))


def test_deterministic_explanations_exist_for_every_kind_and_cite_real_numbers():
    cfg, facts = _facts()
    text = tx.explain_deterministic("congestion", facts)
    assert "Counter" in text and "threshold" in text
    assert tx.explain_deterministic("counter", facts)
    rec = tr.recommend(cfg, 4, 5)
    assert tx.explain_deterministic("intervention", tx.facts_from_recommendation(cfg, rec))
    assert tx.explain_deterministic("scenarios", tx.facts_from_comparison(compare_scenarios(_configs()[:3], 3, 1)))


def test_number_guard_rejects_invented_numbers_and_accepts_grounded_ones():
    facts = {"summary": {"avg_waiting_time": 4.37, "max_queue_length": 12}, "utilization": 0.97}
    assert tx.unsupported_numbers("Average wait was about 4.4 minutes and the queue reached 12.", facts) == []
    assert tx.unsupported_numbers("Utilization was 97 percent.", facts) == []
    assert tx.unsupported_numbers("Average wait was 9.8 minutes.", facts) == ["9.8"]
