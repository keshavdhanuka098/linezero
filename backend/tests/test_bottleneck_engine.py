import pandas as pd
import pytest

from app.engines import bottleneck_engine as be
from app.engines.prediction_engine import prepare_history, to_seconds
from tests.frames import simulate_entries, ts


def analyse(df, dur, rates, **kw):
    h, _ = prepare_history(df)
    cs = [be.CounterInfo(i + 1, f"Counter {i + 1}", r, "active") for i, r in enumerate(rates)]
    return be.analyze(1, h, cs, to_seconds(pd.Series([ts(dur)]))[0], **kw)


def types(res):
    return {f.bottleneck_type for f in res.findings}


def test_healthy_queue_has_no_findings():
    df, d = simulate_entries(0.5, 4, (1, 1, 1), 600, 1)
    res = analyse(df, d, [0.25] * 3)
    assert res.findings == [] and res.notes


def test_counter_overload_and_capacity_imbalance_with_evidence():
    df, d = simulate_entries(1.0, 4, (1, 1, 1), 900, 2, patience_min=25)
    res = analyse(df, d, [0.25] * 3)
    assert {"counter_overload", "capacity_demand_imbalance"} <= types(res)
    cap = next(f for f in res.findings if f.bottleneck_type == "capacity_demand_imbalance")
    assert cap.supporting_metrics["demand_to_capacity_ratio"] > 1.0 and cap.severity in ("HIGH", "CRITICAL")
    assert cap.supporting_metrics["counters_needed_for_target_utilization"] >= 4
    ov = [f for f in res.findings if f.bottleneck_type == "counter_overload"]
    assert all(f.supporting_metrics["utilization"] >= 0.85 and f.counter_id for f in ov)
    for f in res.findings:
        assert f.explanation and f.operational_impact and f.recommendation and f.supporting_metrics
        assert f.severity in be.SEVERITIES and f.window_end_s > f.window_start_s


def test_uneven_utilization():
    df, d = simulate_entries(0.4, 4, (1, 1, 1, 1), 700, 3, policy="lowest_index")
    res = analyse(df, d, [0.25] * 4)
    f = next(x for x in res.findings if x.bottleneck_type == "uneven_utilization")
    m = f.supporting_metrics
    assert m["utilization_spread"] >= 0.25 and f.counter_id == m["most_loaded_counter_id"] == 1
    assert m["utilization_by_counter"][str(m["least_loaded_counter_id"])] < m["utilization_by_counter"]["1"]


def test_balanced_assignment_is_not_flagged_uneven():
    df, d = simulate_entries(0.4, 4, (1, 1, 1, 1), 700, 3, policy="longest_idle")
    assert "uneven_utilization" not in types(analyse(df, d, [0.25] * 4))


def test_arrival_spike_window_and_severity():
    df, d = simulate_entries(0.4, 4, (1, 1, 1), 600, 5, spikes=[(300, 420, 4.0)])
    res = analyse(df, d, [0.25] * 3, lookback_minutes=2000)
    spikes = [f for f in res.findings if f.bottleneck_type == "arrival_spike"]
    assert spikes
    m = spikes[0].supporting_metrics
    assert m["peak_to_typical_ratio"] >= 3 and m["poisson_p_value_of_peak"] < 1e-4
    assert 290 * 60 <= m["episode_start_s"] - to_seconds(pd.Series([ts(0)]))[0] <= 340 * 60
    assert spikes[0].severity in ("HIGH", "CRITICAL")


def test_no_false_spike_on_steady_poisson_demand():
    for seed in range(12):
        df, d = simulate_entries(0.5, 4, (1, 1, 1), 600, 100 + seed)
        assert "arrival_spike" not in types(analyse(df, d, [0.25] * 3, lookback_minutes=2000)), seed


def test_slow_service_vs_peers_and_configuration():
    df, d = simulate_entries(0.45, 4, (1, 1, 0.3), 1200, 4)
    res = analyse(df, d, [0.25, 0.25, 0.25], window_minutes=900)
    f = next(x for x in res.findings if x.bottleneck_type == "slow_service")
    assert f.counter_id == 3 and f.supporting_metrics["worst_ratio"] >= 1.6
    assert {c["reference"] for c in f.supporting_metrics["comparisons"]} >= {"peer_median", "configured_rate"}


def test_capacity_with_no_active_counters_is_critical():
    df, d = simulate_entries(0.5, 4, (1, 1), 300, 9)
    h, _ = prepare_history(df)
    cs = [be.CounterInfo(1, "A", 0.25, "paused"), be.CounterInfo(2, "B", 0.25, "paused")]
    res = be.analyze(1, h, cs, to_seconds(pd.Series([ts(d)]))[0])
    assert any(f.bottleneck_type == "capacity_demand_imbalance" and f.severity == "CRITICAL" for f in res.findings)


def test_insufficient_data_and_empty_queue():
    empty = pd.DataFrame(columns=["status", "arrival", "start", "end", "left", "counter_id"])
    assert be.analyze(1, empty, [], 0.0).findings == []
    df, _ = simulate_entries(n=5, seed=1)
    res = analyse(df, 2.0, [0.25] * 3)
    assert res.findings == [] and "no bottleneck rules" in res.notes[0]


def test_severity_ladder_helpers():
    assert be.severity_from_ladder(0.5, (0.85, 0.92, 0.97)) is None
    assert be.severity_from_ladder(0.93, (0.85, 0.92, 0.97)) == "MEDIUM"
    assert be.bump("HIGH") == "CRITICAL" and be.bump("CRITICAL") == "CRITICAL"
