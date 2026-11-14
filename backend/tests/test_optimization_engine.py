import pytest

from app.engines import optimization_engine as oe
from tests.frames import fake_simulate

ST = oe.Settings(duration_min=480, replications=6, seed=7)


def counters(rates, statuses=None):
    statuses = statuses or ["active"] * len(rates)
    return [oe.CounterSpec(str(i + 1), f"Counter {i + 1}", r, s, i + 1) for i, (r, s) in enumerate(zip(rates, statuses))]


def run(cs, lam, cons=None, **kw):
    return oe.optimize(cs, lam, cons, ST, simulate=fake_simulate, **kw)


def test_overloaded_queue_gets_more_counters_and_waits_drop():
    r = run(counters([0.25] * 5, ["active"] * 3 + ["paused"] * 2), 1.0)
    assert r["proposed_allocation"]["active_counter_count"] > 3
    imp = r["estimated_improvement"]["avg_waiting_time_min"]
    assert imp["proposed"] < imp["current"] and imp["percent_reduction"] > 50
    assert imp["absolute_reduction"] == pytest.approx(imp["current"] - imp["proposed"])
    assert imp["paired_difference"]["significant"] is True
    assert r["current_metrics"]["demand_to_capacity_ratio"] > 1 >= r["proposed_metrics"]["demand_to_capacity_ratio"] - 0.5


def test_constraints_are_respected():
    r = run(counters([0.25] * 5, ["active"] * 3 + ["paused"] * 2), 1.0,
            oe.Constraints(max_active_counters=4, max_cost_per_hour=4.0))
    rq = r["resource_requirements"]
    assert rq["active_counters"] <= 4 and rq["cost_per_hour"] <= 4.0 and rq["within_constraints"]
    assert all(c["ok"] for c in rq["constraint_checks"])


def test_impossible_requests_are_rejected_not_approximated():
    cs = counters([0.25] * 3)
    with pytest.raises(oe.OptimizationInfeasible):
        run(cs, 1.0, oe.Constraints(max_cost_per_hour=0.5))
    with pytest.raises(oe.OptimizationInfeasible):
        run(cs, 1.0, oe.Constraints(max_counter_utilization=0.05))
    with pytest.raises(oe.OptimizationInfeasible):
        run(counters([0.25] * 2, ["paused", "paused"]), 1.0)
    with pytest.raises(oe.OptimizationError):
        run(cs, -1.0)
    with pytest.raises(oe.OptimizationError):
        run(cs, 1.0, oe.Constraints(min_active_counters=3, max_active_counters=2))


def test_closed_counters_are_never_used_and_new_counters_only_when_allowed():
    cs = counters([0.25] * 4, ["active", "active", "closed", "closed"])
    r = run(cs, 0.9)
    used = {c["counter_id"] for c in r["proposed_allocation"]["counters"]}
    assert used <= {1, 2} and r["resource_requirements"]["new_counters_required"] == 0
    r2 = run(cs, 0.9, oe.Constraints(allow_new_counters=2))
    assert r2["resource_requirements"]["new_counters_required"] >= 1
    assert r2["resource_requirements"]["new_counters_required"] <= 2


def test_excess_capacity_reduces_cost_and_uneven_load_changes_policy():
    r = run(counters([0.25] * 6), 0.3)
    assert r["proposed_allocation"]["active_counter_count"] < 6
    assert r["estimated_improvement"]["cost_per_hour"]["change"] < 0
    assert [d["name"] for d in r["proposed_allocation"]["counters_to_deactivate"]]
    u = run(counters([0.25] * 4), 0.4)
    assert u["proposed_allocation"]["assignment_policy"] == "longest_idle"
    assert u["proposed_metrics"]["utilization_imbalance"] < u["current_metrics"]["utilization_imbalance"]


def test_no_change_when_current_is_already_good_and_optimality_not_claimed():
    r = run(counters([0.25] * 3), 0.3, oe.Constraints(min_active_counters=3, allow_policy_change=False))
    assert r["estimated_improvement"]["is_improvement"] is False
    assert r["proposed_allocation"]["active_counter_count"] == 3
    assert "not" in r["details"]["optimality"].lower() and "optimal" in r["details"]["optimality"].lower()
    assert r["details"]["candidates_evaluated"] == len(r["details"]["candidates"])


def test_same_seeds_give_reproducible_results_and_paired_stats():
    a = run(counters([0.25] * 3), 0.6)
    b = run(counters([0.25] * 3), 0.6)
    assert a["current_metrics"]["waits_per_rep"] == b["current_metrics"]["waits_per_rep"]
    d = oe.paired_difference([5, 6, 7], [1, 2, 3])
    assert d["mean"] == pytest.approx(4.0) and d["ci95"][0] > 0 and d["significant"] is True
    assert oe.paired_difference([1.0], [0.5])["significant"] is None


def test_validate_allocation_catches_violations():
    pool = {s.key: s for s in counters([0.25] * 3, ["active", "active", "closed"])}
    bad = oe.Allocation(("1", "3", "9"), "weird")
    names = {c["name"] for c in oe.validate_allocation(bad, pool, oe.Constraints(max_active_counters=2)) if not c["ok"]}
    assert {"counters_exist_and_distinct", "no_closed_counters", "max_active_counters",
            "assignment_policy_allowed"} <= names
