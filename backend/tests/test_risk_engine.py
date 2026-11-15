"""Risk scoring: exact formulas, severity bands, determinism, every category."""
import numpy as np
import pandas as pd
import pytest

from app.engines import prediction_engine as pe
from app.engines import risk_engine as rk
from tests.frames import T0, simulate_entries


def counters(n=3, rate=0.25, paused=0):
    cs = [dict(id=i + 1, name=f"Counter {i + 1}", status="active", service_rate=rate) for i in range(n)]
    cs += [dict(id=n + j + 1, name=f"Reserve {j + 1}", status="paused", service_rate=rate) for j in range(paused)]
    return cs


def frame(lam=0.5, n=500, seed=1, speeds=(1, 1, 1), svc=4.0, **kw):
    df, end = simulate_entries(lam=lam, mean_service_min=svc, speeds=speeds, n=n, seed=seed, **kw)
    return df, end


def ctx_for(df, end_min, cs=None, waiting=0, forecast=None, **kw):
    """Anchor just after the last arrival; optionally turn the last `waiting` customers into a live waiting line."""
    df = df.copy()
    if waiting:
        idx = df.index[-waiting:]
        df.loc[idx, ["start", "end", "counter_id"]] = [pd.NaT, pd.NaT, np.nan]
        df.loc[idx, "status"] = "waiting"
    h, _ = pe.prepare_history(df)
    anchor = float(pe.to_seconds(pd.Series([T0 + pd.Timedelta(minutes=end_min + 0.5)]))[0])
    return rk.RiskContext(h=h, counters=cs or counters(), anchor_s=anchor, forecast=forecast, **kw)


def by_cat(res, cat):
    return [a for a in res["assessments"] if a["category"] == cat]


def forecast_stub(p):
    return {"horizons": [{"horizon_min": m, "congestion": {"probability": pp},
                          "queue_length": {"p10": 0, "p90": 9}} for m, pp in zip((5, 15, 30, 60), p)]}


def test_severity_bands_and_clamp():
    assert [rk.severity_of(x) for x in (0.0, 0.199, 0.2, 0.399, 0.4, 0.599, 0.6, 0.799, 0.8, 1.0)] == \
        [None, None, "LOW", "LOW", "MEDIUM", "MEDIUM", "HIGH", "HIGH", "CRITICAL", "CRITICAL"]
    assert rk.clamp(-3) == 0 and rk.clamp(7) == 1 and rk.clamp(0.4) == 0.4


def test_every_category_is_assessed_and_scores_are_bounded_and_explained():
    df, end = frame(lam=0.6, seed=2)
    res = rk.assess(ctx_for(df, end, waiting=4))
    assert set(res["radar"]) == set(rk.CATEGORIES)
    for a in res["assessments"]:
        assert 0.0 <= a["score"] <= 1.0
        assert a["score_formula"] and a["explanation"] and a["recommended_intervention"]["type"]
        assert 0.0 <= a["confidence"] <= 1.0
        assert a["severity"] == rk.severity_of(a["score"])
    assert all(e["severity"] for e in res["events"])
    assert res["events"] == sorted(res["events"], key=lambda e: -e["score"])


def test_scoring_is_deterministic_no_randomness():
    df, end = frame(lam=0.6, seed=2)
    a = rk.assess(ctx_for(df, end, waiting=6, forecast=forecast_stub([.1, .3, .6, .8])))
    b = rk.assess(ctx_for(df, end, waiting=6, forecast=forecast_stub([.1, .3, .6, .8])))
    assert a == b


def test_calm_queue_raises_no_demand_risks():
    df, end = frame(lam=0.25, seed=4, n=600)
    res = rk.assess(ctx_for(df, end))
    for cat in ("queue_congestion", "capacity_shortage", "counter_overload"):
        assert all(a["severity"] is None for a in by_cat(res, cat)), cat


def test_capacity_shortage_follows_its_documented_formula():
    df, end = frame(lam=0.7, seed=5, n=700)
    ctx = ctx_for(df, end)
    res = rk.assess(ctx)
    a = by_cat(res, "capacity_shortage")[0]
    rho = res["snapshot"]["load_ratio"]
    assert a["score"] == pytest.approx(rk.clamp((rho - 0.85) / 0.35))
    assert a["supporting_metrics"]["capacity_per_min"] == pytest.approx(0.75)


def test_queue_congestion_formula_with_and_without_forecast():
    df, end = frame(lam=0.7, seed=5, n=700)
    ctx = ctx_for(df, end, waiting=10, forecast=forecast_stub([0.2, 0.5, 0.9, 0.9]))
    res = rk.assess(ctx)
    a = by_cat(res, "queue_congestion")[0]
    rho = res["snapshot"]["load_ratio"]
    expected = 0.4 * rk.clamp((rho - 0.7) / 0.4) + 0.3 * rk.clamp(10 / 6) + 0.3 * 0.9
    assert a["score"] == pytest.approx(expected)
    assert a["time_to_impact_min"] == 0.0  # 10 waiting >= threshold max(5, 2*3)=6: already congested
    no_fc = by_cat(rk.assess(ctx_for(df, end, waiting=10)), "queue_congestion")[0]
    assert no_fc["score_formula"].startswith("0.55 load") and no_fc["supporting_metrics"]["forecast_max_congestion_probability"] is None

    short = by_cat(rk.assess(ctx_for(df, end, waiting=2, forecast=forecast_stub([0.1, 0.55, 0.7, 0.9]))), "queue_congestion")[0]
    assert short["time_to_impact_min"] == 15  # first simulated horizon with probability >= 50%


def test_no_active_counters_is_critical():
    df, end = frame(seed=1, n=200)
    res = rk.assess(ctx_for(df, end, cs=counters(0, paused=2), waiting=3))
    for cat in ("queue_congestion", "capacity_shortage"):
        a = by_cat(res, cat)[0]
        assert a["score"] == 1.0 and a["severity"] == "CRITICAL" and a["time_to_impact_min"] == 0.0


def test_counter_overload_uses_busy_share_of_the_window():
    df, end = frame(lam=1.3, seed=6, n=900, speeds=(1, 1, 1, 1, 1))
    ctx = ctx_for(df, end, cs=counters(5))
    util = rk.counter_utilization(ctx.h, ctx.active, ctx.anchor_s, 60)
    assert all(0 <= u["utilization"] <= 1 for u in util.values())
    res = rk.assess(ctx)
    for a in by_cat(res, "counter_overload"):
        assert a["score"] == pytest.approx(rk.clamp((a["supporting_metrics"]["utilization"] - 0.75) / 0.25))
        assert a["resource_type"] == "counter"
    assert max(u["utilization"] for u in util.values()) > 0.75  # heavily loaded fixture really is loaded
    assert any(a["severity"] for a in by_cat(res, "counter_overload"))


def test_stalled_service_is_flagged_as_failure_precursor_not_prediction():
    df, end = frame(lam=0.4, seed=7, n=400)
    df = df.copy()
    last = df.index[-1]
    df.loc[last, ["end", "left"]] = pd.NaT
    df.loc[last, "status"] = "serving"
    df.loc[last, "start"] = df.loc[last, "arrival"]
    cid = int(df.loc[last, "counter_id"])
    ctx = ctx_for(df, end)
    ctx.anchor_s = float(pe.to_seconds(pd.Series([df.loc[last, "start"] + pd.Timedelta(minutes=60)]))[0])  # 60 min in service
    res = rk.assess(ctx)
    a = [x for x in by_cat(res, "counter_failure_precursor") if x["resource_id"] == cid][0]
    assert a["components"]["stall"] == 1.0 and a["severity"] == "CRITICAL"
    assert "Early-warning" in a["supporting_metrics"]["caveat"]
    assert a["recommended_intervention"]["type"] == "operator_inspection" and a["recommended_intervention"]["simulatable"] is False
    others = [x for x in by_cat(res, "counter_failure_precursor") if x["resource_id"] != cid]
    assert all(x["components"]["stall"] == 0 for x in others)


def test_degradation_flags_a_counter_whose_recent_services_got_slower():
    df, end = frame(lam=0.4, seed=8, n=800)
    df = df.copy()
    anchor_min = end + 0.5
    slow = ((df["start"] > T0 + pd.Timedelta(minutes=anchor_min - 75)) & (df["start"] < T0 + pd.Timedelta(minutes=anchor_min - 15))
            & (df["counter_id"] == 1))
    df.loc[slow, "end"] = df.loc[slow, "start"] + (df.loc[slow, "end"] - df.loc[slow, "start"]) * 3
    res = rk.assess(ctx_for(df, end))
    a = [x for x in by_cat(res, "counter_failure_precursor") if x["resource_id"] == 1][0]
    assert a["components"]["degradation"] > 0.5 and a["supporting_metrics"]["degradation_p_value"] < 0.05


def test_abnormal_arrivals_surge_is_significant_and_drop_is_capped_at_low():
    df, end = frame(lam=0.4, seed=9, n=500)
    # replay the same history but with a 4x surge in the last 30 minutes
    surge, end_s = frame(lam=0.4, seed=9, n=700, spikes=[(0.0, 0.0, 1.0)])
    spiky, end2 = simulate_entries(lam=0.4, mean_service_min=4.0, speeds=(1, 1, 1), n=700, seed=9,
                                   spikes=[(1000.0, 1e9, 4.0)])
    a = by_cat(rk.assess(ctx_for(spiky, end2, forecast=None)), "abnormal_arrivals")[0]
    assert a["components"]["direction"] == "surge" and a["components"]["significant"] is True
    assert a["severity"] in ("MEDIUM", "HIGH", "CRITICAL") and a["recommended_intervention"]["type"] == "redistribute_traffic"
    quiet, endq = simulate_entries(lam=0.6, mean_service_min=4.0, speeds=(1, 1, 1), n=700, seed=11,
                                   spikes=[(0.0, 1e9, 1.0)])
    # a real drop: thin the final 30 minutes to a quarter of the arrivals
    cut = T0 + pd.Timedelta(minutes=endq - 30)
    late = quiet["arrival"] > cut
    keep = ~late | (np.arange(len(quiet)) % 4 == 0)
    dropped = quiet[keep].reset_index(drop=True)
    d = by_cat(rk.assess(ctx_for(dropped, endq)), "abnormal_arrivals")[0]
    assert d["components"]["direction"] == "drop" and d["score"] <= rk.DROP_CAP and d["severity"] in (None, "LOW")


def test_waiting_time_trend_detects_a_significant_rise_and_ignores_flat_noise():
    base, end = frame(lam=0.3, seed=12, n=500)
    # force the last hour's waits to climb steadily: shift start (and end) later by a growing amount
    df = base.copy()
    t_end = T0 + pd.Timedelta(minutes=end + 0.5)
    win = df["start"] > t_end - pd.Timedelta(minutes=60)
    grow = (df.loc[win, "start"] - (t_end - pd.Timedelta(minutes=60))).dt.total_seconds() / 60.0 * 0.15
    df.loc[win, "arrival"] = df.loc[win, "start"] - pd.to_timedelta(grow + 1, unit="min")
    res = rk.assess(ctx_for(df, end))
    a = by_cat(res, "waiting_time_trend")[0]
    assert a["status"] == "assessed" and a["components"]["trend_significant"] is True
    assert a["supporting_metrics"]["wait_slope_min_per_min"] > 0
    flat = by_cat(rk.assess(ctx_for(*frame(lam=0.2, seed=13, n=500))), "waiting_time_trend")[0]
    assert flat["components"].get("trend") in (0.0, None) and (flat["severity"] is None)


def test_utilization_imbalance_when_one_counter_takes_the_load():
    df, end = simulate_entries(lam=0.45, mean_service_min=4.0, speeds=(1, 1, 1), n=700, seed=14, policy="lowest_index")
    res = rk.assess(ctx_for(df, end))
    a = by_cat(res, "utilization_imbalance")[0]
    assert a["status"] == "assessed" and a["supporting_metrics"]["spread"] > 0.25 and a["score"] > 0
    assert a["recommended_intervention"]["type"] == "assignment_strategy"
    balanced, endb = simulate_entries(lam=0.45, mean_service_min=4.0, speeds=(1, 1, 1), n=700, seed=14)
    b = by_cat(rk.assess(ctx_for(balanced, endb)), "utilization_imbalance")[0]
    assert b["score"] < a["score"]


def test_insufficient_data_is_reported_not_scored():
    df, end = frame(n=5, seed=3)
    res = rk.assess(ctx_for(df, end))
    for cat in ("waiting_time_trend", "abnormal_arrivals", "utilization_imbalance"):
        a = by_cat(res, cat)[0]
        assert a["status"] == "insufficient_data" and a["score"] == 0.0 and a["severity"] is None
    empty = rk.assess(rk.RiskContext(h=pe.prepare_history(df.iloc[0:0])[0], counters=counters(), anchor_s=0.0))
    assert empty["overall_severity"] is None or isinstance(empty["overall_score"], float)


def test_rate_estimate_exact_interval():
    r = rk.rate_estimate(10, 30.0)
    assert r["rate"] == pytest.approx(1 / 3)
    assert r["ci95"][0] < r["rate"] < r["ci95"][1] and 0 <= r["confidence"] <= 1
    assert rk.rate_estimate(0, 30.0)["ci95"][0] == 0.0
    assert rk.rate_estimate(5, 0)["rate"] is None
