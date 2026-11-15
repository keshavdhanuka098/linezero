"""Digital Twin simulation engine: parity with the base engine, outages, closed counters, actions, recovery."""
import pytest

from app.engines.simulation_engine import SimulationConfig, run_simulation
from app.engines.twin_engine import TwinConfig, run_replications, run_twin

BASE = dict(arrival_rate=1.2, mean_service_time=4.0, num_counters=6, duration=120, seed=7)


def test_matches_base_engine_when_no_twin_features_used():
    cfg = dict(arrival_rate=1.0, mean_service_time=1.5, num_counters=2, duration=500, seed=42)
    base, twin = run_simulation(SimulationConfig(**cfg)), run_twin(TwinConfig(**cfg))
    for key in ("total_arrivals", "total_served", "avg_waiting_time", "max_queue_length", "abandoned"):
        assert twin[key] == base[key], key


def test_same_seed_is_reproducible():
    cfg = TwinConfig(**BASE, outages=[dict(counter=0, start=20, end=100)])
    a, b = run_twin(cfg), run_twin(cfg)
    assert a["summary"] == b["summary"] and a["customers"] == b["customers"] and a["events"] == b["events"]


def test_outage_takes_counter_offline_and_logs_events():
    cfg = TwinConfig(**BASE, outages=[dict(counter=0, start=20, end=100), dict(counter=1, start=20, end=100)])
    r = run_twin(cfg)
    assert r["counters"][0]["failed_time"] == pytest.approx(80)
    assert not [c for c in r["customers"] if c[4] == 0 and c[2] is not None and 20 < c[2] < 100]
    kinds = [e["type"] for e in r["events"]]
    assert kinds.count("counter_failure") == 2 and kinds.count("counter_repaired") == 2
    assert r["avg_waiting_time"] >= run_twin(TwinConfig(**BASE))["avg_waiting_time"]


def test_standby_and_unstaffed_counters_never_serve_and_cost_less():
    r = run_twin(TwinConfig(**BASE, standby_counters=[5], staff_available=4))
    assert r["counters"][4]["closed_time"] == 120 and r["counters"][5]["closed_time"] == 120
    assert all(c[4] not in (4, 5) for c in r["customers"] if c[4] is not None)
    assert r["resource_cost"] < run_twin(TwinConfig(**BASE))["resource_cost"]


def test_activating_counters_helps_and_respects_the_activation_time():
    acts = [dict(type="activate_counter", at=30, counter=2), dict(type="activate_counter", at=30, counter=3)]
    with_acts = run_twin(TwinConfig(**BASE, staff_available=2, actions=acts))
    without = run_twin(TwinConfig(**BASE, staff_available=2))
    assert with_acts["avg_waiting_time"] < without["avg_waiting_time"]
    assert with_acts["counters"][2]["closed_time"] == pytest.approx(30)
    assert not [c for c in with_acts["customers"] if c[4] == 2 and c[2] is not None and c[2] < 30]


def test_slow_service_increases_service_time():
    slow = run_twin(TwinConfig(**BASE, speed_changes=[dict(counter=None, start=20, end=None, factor=0.5)]))
    assert slow["avg_service_time"] > run_twin(TwinConfig(**BASE))["avg_service_time"] * 1.2


def test_reactive_recovery_triggers_and_improves():
    cfg = TwinConfig(**BASE, staff_available=3,
                     recovery=dict(queue_threshold=6, sustain=1.0, max_activations=2, boost_factor=1.15))
    rec, none = run_twin(cfg), run_twin(cfg.model_copy(update={"recovery": None}))
    actions = [e["action"] for e in rec["events"] if e["type"] == "recovery_action"]
    assert actions.count("activate_counter") == 2 and "boost_speed" in actions
    assert rec["avg_waiting_time"] < none["avg_waiting_time"]


def test_initial_state_is_respected():
    r = run_twin(TwinConfig(arrival_rate=0.5, mean_service_time=2, num_counters=2, duration=30, seed=1,
                            initial_queue=10, initial_busy_counters=[0, 1], sample_interval=1.0))
    f0 = r["frames"][0]
    assert (f0["t"], f0["queue"], f0["in_service"], f0["arrivals"]) == (0.0, 10, 2, 0)
    assert r["new_arrivals"] == r["total_arrivals"] - 10


def test_playback_payload_shape():
    r = run_twin(TwinConfig(**BASE, outages=[dict(counter=0, start=20, end=100)]))
    assert r["frames"][0]["t"] == 0 and r["frames"][-1]["t"] == 120
    assert len(r["frames"][0]["counters"]) == 6
    assert 2 in r["frames"][int(len(r["frames"]) / 2)]["counters"]  # a failed counter is visible mid-outage
    assert all(len(c) == 6 for c in r["customers"]) and r["theoretical"]["applicable"] is False


def test_episodes_identify_overload():
    r = run_twin(TwinConfig(**{**BASE, "num_counters": 5}, staff_available=2))
    eps = r["episodes"]["bottlenecks"]
    assert eps and eps[0]["peak_queue"] >= r["episodes"]["congestion_threshold"]
    assert eps[0]["most_loaded_counter"] in (0, 1) and set(eps[0]["closed_counters"]) == {2, 3, 4}


@pytest.mark.parametrize("bad", [
    dict(outages=[dict(counter=9, start=1, end=2)]), dict(staff_available=99),
    dict(standby_counters=[0], initial_busy_counters=[0]), dict(arrival_rate=100, duration=1000),
    dict(outages=[dict(counter=0, start=5, end=5)]), dict(actions=[dict(type="activate_counter", at=1)]),
])
def test_invalid_twin_configs_are_rejected(bad):
    with pytest.raises(ValueError):
        TwinConfig(**{**BASE, **bad})


def test_replications_report_confidence_intervals():
    rr = run_replications(TwinConfig(**BASE), 5, 100)
    st = rr["stats"]["avg_waiting_time"]
    assert st["n"] == 5 and st["ci95"] is not None and rr["primary"]["customers"]
    assert rr["summary"]["avg_waiting_time"] == st["mean"]
