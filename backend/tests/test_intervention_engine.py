"""Intervention engine: candidates, common random numbers, costs, ranking, feasibility, reproducibility."""
import pytest

from app.engines import intervention_engine as ie

CM = dict(counter_hour_cost=1.0, assist_staff_hour_cost=0.5, diversion_cost_per_customer=0.25, max_extra_cost=None,
          max_assist_staff=2, cost_weight=0.25)


def state(queue=12, lam=0.9, active=3, total=5, rate=0.25):
    return {"queue_length": queue, "arrival_rate_per_min": lam, "arrival_rate_source": "test",
            "counters": [{"index": i, "name": f"Counter {i + 1}", "rate_per_min": rate, "active": i < active,
                          "busy": i < active and queue > 0} for i in range(total)]}


@pytest.fixture(scope="module")
def hot():
    return ie.evaluate(state(), 60, 8, 7, CM)


def by_key(res, key):
    return next(c for c in res["candidates"] if c["key"] == key)


def test_result_never_claims_execution(hot):
    assert hot["simulation_only"] is True and hot["executed"] is False and hot["requires_operator_approval"] is True
    assert "not executed" in hot["disclaimer"] or "has not executed" in hot["disclaimer"]
    assert "nothing has been done" in hot["explanation"]


def test_candidate_families_are_generated(hot):
    types = {c["type"] for c in hot["candidates"]}
    assert types == {"activate_counters", "reallocate_staff", "adjust_service_capacity", "redistribute_traffic",
                     "assignment_strategy", "combined"}
    assert {"activate_1", "activate_2", "assist_15", "assist_30", "divert_10", "divert_20", "assign_lowest_index",
            "combined"} == {c["key"] for c in hot["candidates"]}


def test_reproducible_with_same_seed_and_different_with_another(hot):
    again = ie.evaluate(state(), 60, 8, 7, CM)
    assert again == hot
    assert hot["reproducibility"]["config_hash"] == again["reproducibility"]["config_hash"]
    other = ie.evaluate(state(), 60, 8, 8, CM)
    assert other["reproducibility"]["config_hash"] != hot["reproducibility"]["config_hash"]
    assert other["baseline"]["summary"]["avg_waiting_time"] != hot["baseline"]["summary"]["avg_waiting_time"]
    assert hot["reproducibility"]["seeds"] == list(range(7, 15)) and hot["reproducibility"]["common_random_numbers"]


def test_common_random_numbers_make_a_no_op_candidate_identical_to_baseline(hot):
    """The assignment rule cannot change totals in a shared queue; with shared seeds the paired difference is exactly 0."""
    a = by_key(hot, "assign_lowest_index")
    assert a["score_delta"] == pytest.approx(0.0, abs=1e-9) and a["significant"] is False
    assert a["is_recommended"] is False


def test_helpful_interventions_reduce_wait_and_are_significant(hot):
    for key in ("activate_1", "activate_2", "assist_30", "combined"):
        c = by_key(hot, key)
        assert c["wait_reduction_min"]["mean"] > 0 and c["significant"] and c["improves"], key
    assert by_key(hot, "activate_2")["wait_reduction_min"]["mean"] > by_key(hot, "activate_1")["wait_reduction_min"]["mean"]
    assert by_key(hot, "activate_1")["utilization_change"] is not None
    assert by_key(hot, "activate_1")["throughput_change_per_min"] is not None


def test_ranking_follows_the_documented_net_value_rule(hot):
    ranked = [c for c in hot["candidates"] if c["rank"]]
    assert [c["rank"] for c in ranked] == list(range(1, len(ranked) + 1))
    assert [c["net_value"] for c in ranked] == sorted((c["net_value"] for c in ranked), reverse=True)
    for c in hot["candidates"]:
        expected = -c["score_delta"] - CM["cost_weight"] * c["extra_cost"]["total"]
        assert c["net_value"] == pytest.approx(expected)
    best = by_key(hot, hot["recommended_key"])
    assert best["rank"] == 1 and best["is_recommended"] and best["significant"] and best["net_value"] > 0
    assert sum(c["is_recommended"] for c in hot["candidates"]) == 1
    assert hot["baseline"]["score"] > best["score"]
    assert "Recommended:" in hot["explanation"] and best["label"] in hot["explanation"]


def test_cost_arithmetic():
    res = ie.evaluate(state(), 60, 4, 1, {**CM, "assist_staff_hour_cost": 2.0, "diversion_cost_per_customer": 1.0})
    a30 = by_key(res, "assist_30")["extra_cost"]
    assert a30["assisting_staff"] == pytest.approx(2 * 2.0 * 1.0)  # 2 staff x 2.0/h x 1 h
    d20 = by_key(res, "divert_20")["extra_cost"]
    assert d20["expected_diverted_customers"] == pytest.approx(0.9 * 0.2 * 60)
    assert d20["diversion"] == pytest.approx(0.9 * 0.2 * 60 * 1.0)
    act = by_key(res, "activate_2")["extra_cost"]
    assert act["counter_hours"] > 0 and act["total"] == pytest.approx(act["counter_hours"])
    assert by_key(res, "activate_1")["extra_cost"]["counter_hours"] < act["counter_hours"]
    cheap = ie.evaluate(state(), 60, 4, 1, {**CM, "counter_hour_cost": 0.0})
    assert by_key(cheap, "activate_2")["extra_cost"]["counter_hours"] == pytest.approx(0.0)


def test_traffic_redirection_trades_waiting_for_fewer_customers_served(hot):
    d = by_key(hot, "divert_20")
    assert d["wait_reduction_min"]["mean"] > 0
    assert d["served_change"] < 0  # honest: fewer people are served in this queue
    assert "serves fewer people" in ie.explain({**hot, "recommended_key": "divert_20"})


def test_infeasible_candidates_are_reported_with_reasons():
    none_reserve = ie.evaluate(state(total=3), 60, 4, 1, CM)
    assert {s["key"] for s in none_reserve["not_evaluated"]} == {"activate_counters"}
    assert not any(c["type"] in ("activate_counters", "combined") for c in none_reserve["candidates"])
    one_staff = ie.evaluate(state(), 60, 4, 1, {**CM, "max_assist_staff": 1})
    assert [s["key"] for s in one_staff["not_evaluated"]] == ["assist_30"] and "only 1" in one_staff["not_evaluated"][0]["reason"]
    no_staff = ie.evaluate(state(), 60, 4, 1, {**CM, "max_assist_staff": 0})
    assert {s["key"] for s in no_staff["not_evaluated"]} == {"assist_15", "assist_30"}
    assert "combined" not in {c["key"] for c in no_staff["candidates"]}


def test_budget_makes_expensive_candidates_infeasible_and_never_recommended():
    res = ie.evaluate(state(), 60, 6, 3, {**CM, "max_extra_cost": 0.8})
    for c in res["candidates"]:
        if c["extra_cost"]["total"] > 0.8:
            assert c["feasible"] is False and c["rank"] is None and not c["is_recommended"]
            assert "exceeds the budget" in c["infeasible_reason"]
        else:
            assert c["feasible"] is True
    assert res["recommended_key"] is None or by_key(res, res["recommended_key"])["extra_cost"]["total"] <= 0.8
    zero = ie.evaluate(state(), 60, 4, 3, {**CM, "max_extra_cost": 0.0})
    assert zero["recommended_key"] is None or by_key(zero, zero["recommended_key"])["extra_cost"]["total"] == 0


def test_no_recommendation_when_the_queue_is_fine():
    calm = ie.evaluate(state(queue=0, lam=0.2), 60, 6, 5, CM)
    assert calm["recommended_key"] is None
    assert any("does not currently need an intervention" in n for n in calm["notes"])
    assert "Recommended:" not in calm["explanation"]


def test_cost_weight_can_flip_the_ranking():
    free = ie.evaluate(state(), 60, 6, 2, {**CM, "cost_weight": 0.0})
    dear = ie.evaluate(state(), 60, 6, 2, {**CM, "cost_weight": 50.0})
    assert free["recommended_key"] == "combined" or by_key(free, free["recommended_key"])["rank"] == 1
    assert dear["recommended_key"] != free["recommended_key"] or dear["recommended_key"] is None


def test_confidence_is_bounded_and_zero_for_noise(hot):
    for c in hot["candidates"]:
        assert 0.0 <= c["confidence"]["value"] <= 1.0
        if not c["significant"]:
            assert c["confidence"]["value"] == 0.0


def test_status_transition_table():
    assert ie.can_transition("proposed", "approved") and ie.can_transition("approved", "applied")
    assert ie.can_transition("applied", "evaluated") and ie.can_transition("approved", "rejected")
    for a, b in [("proposed", "applied"), ("proposed", "evaluated"), ("rejected", "approved"),
                 ("evaluated", "applied"), ("applied", "approved"), ("approved", "evaluated")]:
        assert not ie.can_transition(a, b), (a, b)


def test_no_active_counters_is_not_simulated():
    from app.engines import twin_forecast as tf

    with pytest.raises(tf.ForecastUnavailable):
        ie.evaluate(state(active=0), 60, 4, 1, CM)
