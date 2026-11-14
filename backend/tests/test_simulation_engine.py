import pytest
from pydantic import ValidationError

from app.engines.comparison import compare_results
from app.engines.queueing_theory import erlang_c, mmc
from app.engines.simulation_engine import QueueSimulation, SimulationConfig, run_simulation


def cfg(**kw):
    base = dict(arrival_rate=1, mean_service_time=1, num_counters=1, duration=100, seed=1)
    base.update(kw)
    return SimulationConfig(**base)


def test_deterministic_arrival_generation():
    r = run_simulation(cfg(arrival_rate=2, arrival_distribution="deterministic", mean_service_time=0.1,
                           service_distribution="deterministic", num_counters=2))
    assert r["total_arrivals"] == 199


def test_poisson_arrival_count_matches_rate():
    r = run_simulation(cfg(arrival_rate=3, duration=5000, mean_service_time=0.1, num_counters=2))
    assert abs(r["total_arrivals"] - 15000) < 4 * 15000**0.5


def test_uniform_arrivals_have_correct_mean():
    r = run_simulation(cfg(arrival_rate=2, arrival_distribution="uniform", duration=2000,
                           mean_service_time=0.1, num_counters=2))
    assert abs(r["total_arrivals"] - 4000) < 100


def test_arrival_profile_creates_spike():
    base = cfg(arrival_rate=1, duration=1000, mean_service_time=0.01, seed=3)
    spiked = cfg(arrival_rate=1, duration=1000, mean_service_time=0.01, seed=3,
                 arrival_profile=[{"start": 400, "end": 600, "multiplier": 5}])
    n0 = run_simulation(base)["total_arrivals"]
    n1 = run_simulation(spiked)["total_arrivals"]
    assert abs((n1 - n0) - 800) < 150


HAND = dict(arrival_rate=1, mean_service_time=2, num_counters=1, duration=10.5,
            arrival_distribution="deterministic", service_distribution="deterministic")


def test_waiting_time_and_service_completion_hand_calculated():
    """Arrivals at t=1..10, service 2 on one counter. Customer k starts at 2k-1, waits 2(k-1)... see below."""
    r = run_simulation(cfg(**HAND))
    assert r["total_arrivals"] == 10
    assert r["total_served"] == 4
    assert r["customers_in_service_at_end"] == 1
    assert r["customers_waiting_at_end"] == 5
    assert r["customers_remaining"] == 6
    assert r["avg_waiting_time"] == pytest.approx(2.0)
    assert r["max_waiting_time"] == pytest.approx(4.0)
    assert r["avg_service_time"] == pytest.approx(2.0)
    assert r["longest_unserved_wait"] == pytest.approx(4.5)
    assert r["max_queue_length"] == 5
    assert r["avg_queue_length"] == pytest.approx(22.5 / 10.5, abs=1e-5)
    assert r["throughput"] == pytest.approx(4 / 10.5, abs=1e-5)
    assert r["avg_utilization"] == pytest.approx(9.5 / 10.5, abs=1e-5)


def test_multiple_counters_share_load_and_utilization():
    """1 arrival/unit, service 3, 3 counters: nobody waits; counters start at t=1,2,3 and stay busy."""
    r = run_simulation(cfg(arrival_rate=1, mean_service_time=3, num_counters=3, duration=30.5,
                           arrival_distribution="deterministic", service_distribution="deterministic"))
    assert r["avg_waiting_time"] == 0 and r["max_queue_length"] <= 1
    util = [c["utilization"] for c in r["counters"]]
    assert util == pytest.approx([29.5 / 30.5, 28.5 / 30.5, 27.5 / 30.5], abs=1e-5)
    assert r["avg_utilization"] == pytest.approx(85.5 / (3 * 30.5), abs=1e-5)
    assert all(c["served"] >= 8 for c in r["counters"])


def test_lowest_index_assignment_is_uneven_and_longest_idle_is_even():
    common = dict(arrival_rate=0.5, mean_service_time=1, num_counters=3, duration=3000, seed=5)
    uneven = run_simulation(cfg(counter_assignment="lowest_index", **common))["counters"]
    even = run_simulation(cfg(counter_assignment="longest_idle", **common))["counters"]
    assert uneven[0]["utilization"] > 3 * uneven[2]["utilization"]
    assert max(c["utilization"] for c in even) - min(c["utilization"] for c in even) < 0.05


def test_counter_speed_factors():
    r = run_simulation(cfg(arrival_rate=1, mean_service_time=2, num_counters=2, duration=2000, seed=2,
                           service_distribution="deterministic", counter_speed_factors=[2.0, 0.5]))
    by_counter = {c["counter_index"]: c for c in r["counters"]}
    assert by_counter[0]["busy_time"] / by_counter[0]["served"] == pytest.approx(1.0, abs=0.01)
    assert by_counter[1]["busy_time"] / by_counter[1]["served"] == pytest.approx(4.0, abs=0.05)


def test_erlang_c_known_value():
    assert erlang_c(2, 1.0) == pytest.approx(1 / 3)
    assert mmc(1.0, 1.0, 2)["avg_waiting_time"] == pytest.approx(1 / 3)
    assert erlang_c(2, 2.0) is None


def test_mm1_matches_theory():
    r = run_simulation(cfg(arrival_rate=0.5, mean_service_time=1, duration=200_000, seed=11))
    th = r["theoretical"]
    assert th["model"] == "M/M/1" and th["avg_waiting_time"] == pytest.approx(1.0)
    assert r["avg_waiting_time"] == pytest.approx(1.0, rel=0.08)
    assert r["avg_queue_length"] == pytest.approx(0.5, rel=0.08)
    assert r["avg_utilization"] == pytest.approx(0.5, rel=0.03)
    assert r["throughput"] == pytest.approx(0.5, rel=0.03)


def test_mmc_matches_erlang_c():
    r = run_simulation(cfg(arrival_rate=1.8, mean_service_time=1, num_counters=2, duration=100_000, seed=4))
    th = r["theoretical"]
    assert th["model"] == "M/M/2"
    assert th["avg_waiting_time"] == pytest.approx(mmc(1.8, 1.0, 2)["avg_waiting_time"])
    assert r["avg_waiting_time"] == pytest.approx(th["avg_waiting_time"], rel=0.12)
    assert r["avg_utilization"] == pytest.approx(0.9, rel=0.03)


def test_md1_matches_pollaczek_khinchine():
    r = run_simulation(cfg(arrival_rate=0.5, mean_service_time=1, duration=200_000, seed=6,
                           service_distribution="deterministic"))
    assert r["theoretical"]["avg_waiting_time"] == pytest.approx(0.5)
    assert r["avg_waiting_time"] == pytest.approx(0.5, rel=0.08)


def test_theory_not_applicable_when_abandonment_enabled():
    r = run_simulation(cfg(abandonment_enabled=True, mean_patience=5))
    assert r["theoretical"]["applicable"] is False


def test_abandonment_and_conservation():
    r = run_simulation(cfg(arrival_rate=2, mean_service_time=1, duration=2000, seed=9,
                           abandonment_enabled=True, mean_patience=2))
    assert r["abandoned"] > 100
    assert r["total_arrivals"] == (
        r["total_served"] + r["customers_in_service_at_end"] + r["customers_waiting_at_end"] + r["abandoned"]
    )
    assert r["abandonment_rate"] == pytest.approx(r["abandoned"] / r["total_arrivals"], abs=1e-5)
    no_abandon = run_simulation(cfg(arrival_rate=2, mean_service_time=1, duration=2000, seed=9))
    assert no_abandon["abandoned"] == 0 and no_abandon["max_queue_length"] > r["max_queue_length"]


@pytest.mark.parametrize("arrival", ["poisson", "deterministic", "uniform"])
@pytest.mark.parametrize("service", ["exponential", "deterministic", "uniform", "lognormal"])
def test_all_distributions_run_and_conserve_customers(arrival, service):
    r = run_simulation(cfg(arrival_rate=1.5, mean_service_time=1, num_counters=2, duration=300,
                           arrival_distribution=arrival, service_distribution=service, seed=21))
    assert r["total_arrivals"] == r["total_served"] + r["customers_remaining"]
    assert 0 <= r["avg_utilization"] <= 1
    assert r["max_waiting_time"] >= r["avg_waiting_time"] >= 0


def test_service_time_mean_by_distribution():
    for dist in ("exponential", "uniform", "lognormal", "deterministic"):
        r = run_simulation(cfg(arrival_rate=0.2, mean_service_time=3, num_counters=2, duration=20000,
                               service_distribution=dist, seed=8))
        assert r["avg_service_time"] == pytest.approx(3.0, rel=0.05), dist


def test_overloaded_system_is_flagged_and_grows():
    r = run_simulation(cfg(arrival_rate=2, mean_service_time=1, duration=500, seed=3))
    assert r["theoretical"]["stable"] is False
    assert r["avg_utilization"] > 0.98 and r["customers_waiting_at_end"] > 400


def test_same_seed_reproduces_results():
    a = run_simulation(cfg(seed=123, duration=500, arrival_rate=2, num_counters=2))
    b = run_simulation(cfg(seed=123, duration=500, arrival_rate=2, num_counters=2))
    c = run_simulation(cfg(seed=124, duration=500, arrival_rate=2, num_counters=2))
    assert a == b
    assert a != c


def test_unseeded_run_reports_seed_that_reproduces_it():
    first = run_simulation(cfg(seed=None, duration=300, arrival_rate=2))
    again = run_simulation(cfg(seed=first["seed_used"], duration=300, arrival_rate=2))
    assert first == again


def test_reset_clears_state_and_replays_identically():
    sim = QueueSimulation(cfg(seed=77, duration=400, arrival_rate=2, num_counters=2))
    first = sim.run()
    assert sim.arrivals > 0
    sim.reset()
    assert sim.arrivals == 0 and sim.queue_len == 0 and sim.env.now == 0 and sim.waits == []
    assert sim.run() == first
    assert sim.run() == first


def test_trace_records_every_customer():
    r = run_simulation(cfg(**HAND, record_trace=True))
    trace = r["trace"]
    assert len(trace) == 10
    assert [t["service_start_time"] for t in trace[:5]] == [1, 3, 5, 7, 9]
    assert trace[0]["counter_index"] == 0 and trace[5]["service_start_time"] is None


@pytest.mark.parametrize("bad", [
    dict(arrival_rate=0), dict(arrival_rate=-1), dict(mean_service_time=0), dict(num_counters=0),
    dict(num_counters=101), dict(duration=0), dict(arrival_distribution="gaussian"),
    dict(service_distribution="weibull"), dict(seed=-1), dict(abandonment_enabled=True),
    dict(counter_speed_factors=[1.0, 1.0]), dict(counter_speed_factors=[0.0]),
    dict(arrival_rate=1000, duration=100_000), dict(unknown_field=1),
    dict(arrival_distribution="uniform", arrival_profile=[{"start": 0, "end": 5, "multiplier": 2}]),
    dict(arrival_profile=[{"start": 0, "end": 5, "multiplier": 2}, {"start": 4, "end": 8, "multiplier": 2}]),
])
def test_invalid_configurations_rejected(bad):
    with pytest.raises(ValidationError):
        cfg(**bad)


def test_compare_results_picks_best_and_deltas():
    one = run_simulation(cfg(arrival_rate=1.8, duration=2000, num_counters=2, seed=1))
    three = run_simulation(cfg(arrival_rate=1.8, duration=2000, num_counters=3, seed=1))
    out = compare_results(["two", "three"], [one, three])
    m = out["metrics"]["avg_waiting_time"]
    assert m["best_index"] == 1 and m["delta_vs_baseline"][1] < 0 and m["pct_change_vs_baseline"][0] == 0
    assert out["metrics"]["avg_utilization"]["best_index"] is None
