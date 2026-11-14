import json

import numpy as np
import pandas as pd
import pytest

from app.engines import analytics_engine as ae
from tests.frames import T0, simulate_entries, ts

CTRS = [{"id": i, "name": f"Counter {i}", "status": "active", "service_rate": 0.25} for i in (1, 2, 3)]


def build(n=1200, seed=11):
    df, d = simulate_entries(0.5, 4, (1, 1, 1), n, seed)
    done = df[df.status == "completed"]
    rec = pd.DataFrame({"completed_at": done.end, "waiting_time": (done.start - done.arrival).dt.total_seconds(),
                        "service_time": (done.end - done.start).dt.total_seconds(), "counter_id": done.counter_id})
    return df, rec, d


def test_overview_kpis_match_independent_calculation():
    df, rec, _ = build()
    o = ae.overview(ae.AnalyticsData(df, rec, CTRS))
    k = o["summary"]["kpis"]
    assert k["arrivals"] == len(df) and k["served"] == len(rec)
    assert k["avg_waiting_time_min"] == pytest.approx(rec.waiting_time.mean() / 60, abs=1e-3)
    assert sum(r["arrivals"] for r in o["tables"]["hourly"]) == len(df)
    assert sum(r["served"] for r in o["tables"]["daily"]) == len(rec)
    lam = k["arrival_rate_per_hour"] / 60
    assert k["avg_queue_length"] == pytest.approx(lam * k["avg_waiting_time_min"], rel=0.05)
    json.dumps(o)


def test_utilization_matches_busy_time():
    df, rec, _ = build()
    d = ae.AnalyticsData(df, rec, CTRS)
    start, end = ae.resolve_range(d)
    u = {c["counter_id"]: c["utilization"] for c in ae.utilization(d)["tables"]["by_counter"]}
    busy = (df.end - df.start).dt.total_seconds()[df.counter_id == 1].sum()
    assert u[1] == pytest.approx(busy / (end - start).total_seconds(), abs=1e-3)
    assert all(0 <= v <= 1 for v in u.values())


def test_queue_length_function_matches_brute_force():
    df, _, _ = build(400)
    _, _, length_at, _ = ae.queue_length_function(df)
    leave = df.start.fillna(df.left)
    for m in (20, 90, 250, 400):
        t = ts(m)
        want = int(((df.arrival <= t) & (leave > t)).sum())
        got = int(length_at(np.array([(t - pd.Timestamp("1970-01-01", tz="UTC")).total_seconds()]))[0])
        assert got == want


def test_date_and_queue_filters_are_applied_by_the_engine():
    df, rec, d = build()
    a, b = ts(100), ts(220)
    sub_e = df[(df.arrival >= a) & (df.arrival <= b)]
    sub_r = rec[(rec.completed_at >= a) & (rec.completed_at <= b)]
    o = ae.overview(ae.AnalyticsData(sub_e, sub_r, CTRS, start=a, end=b, filters={"queue_id": 7}))
    assert o["summary"]["kpis"]["arrivals"] == len(sub_e) and o["filters"]["queue_id"] == 7
    assert o["filters"]["start_date"].startswith("2026-11-02T09:40")
    with pytest.raises(ae.AnalyticsError):
        ae.arrivals(ae.AnalyticsData(df, rec, CTRS, start=b, end=a))


def test_empty_datasets_return_same_structure():
    E = ae.AnalyticsData(pd.DataFrame(), pd.DataFrame(), [])
    for fn in (ae.overview, ae.arrivals, ae.waiting_times, ae.utilization, ae.peak_hours):
        r = fn(E)
        assert r["meta"]["empty"] is True and set(r) == {"filters", "meta", "summary", "charts", "tables"}
        json.dumps(r)


def test_chart_ready_output_shape():
    df, rec, _ = build()
    d = ae.AnalyticsData(df, rec, CTRS)
    for r in (ae.overview(d), ae.arrivals(d), ae.waiting_times(d), ae.utilization(d), ae.peak_hours(d)):
        assert r["charts"]
        for c in r["charts"].values():
            assert c["type"] in ("line", "bar") and {"label", "type"} <= set(c["x"]) and {"label", "unit"} <= set(c["y"])
            for s in c["series"]:
                assert {"key", "name", "data"} <= set(s) and all({"x", "y"} == set(p) for p in s["data"])
    assert ae.arrivals(d, "day")["summary"]["granularity"] == "day"
    with pytest.raises(ae.AnalyticsError):
        ae.arrivals(d, "week")


def test_peak_hours_found_for_real_peak_but_not_for_flat_demand():
    rng = np.random.default_rng(0)
    rows = []
    for day in range(5):
        for hr in range(8, 18):
            for _ in range(rng.poisson(60 if hr in (10, 11) else 20)):
                t = T0 + pd.Timedelta(days=day, hours=hr - 8, minutes=float(rng.uniform(0, 60)))
                rows.append(dict(status="completed", arrival=t, start=t, end=t + pd.Timedelta(minutes=3),
                                 left=pd.NaT, counter_id=1.0))
    peaked = ae.peak_hours(ae.AnalyticsData(pd.DataFrame(rows), pd.DataFrame(), CTRS[:1]))
    assert peaked["summary"]["peak_hours"] == [10, 11] or set(peaked["summary"]["peak_hours"]) == {10, 11}
    df, rec, _ = build(1500)
    assert ae.peak_hours(ae.AnalyticsData(df, rec, CTRS))["summary"]["peak_hours"] == []


def test_previous_period_comparison_and_tz_offset():
    df, rec, d = build()
    mid = ts(d / 2)
    cur = ae.AnalyticsData(df[df.arrival >= mid], rec[rec.completed_at >= mid], CTRS, start=mid, end=ts(d))
    prev = ae.AnalyticsData(df[df.arrival < mid], rec[rec.completed_at < mid], CTRS, start=ts(0), end=mid)
    c = ae.overview(cur, prev, True)["summary"]["comparison"]
    assert c["available"] and c["metrics"]["arrivals"]["previous"] > 0
    assert ae.overview(cur, None, True)["summary"]["comparison"]["available"] is False
    ist = ae.arrivals(ae.AnalyticsData(df, rec, CTRS, tz_offset_minutes=330))
    assert ist["charts"]["arrivals_over_time"]["series"][0]["data"][0]["x"].endswith("+05:30")


def test_overview_with_non_utc_offsets_keeps_all_data():
    df, rec, _ = build(600)
    for off in (0, 330, -300):
        o = ae.overview(ae.AnalyticsData(df, rec, CTRS, tz_offset_minutes=off))
        assert sum(r["arrivals"] for r in o["tables"]["hourly"]) == len(df)
        assert sum(r["arrivals"] for r in o["tables"]["daily"]) == len(df)
