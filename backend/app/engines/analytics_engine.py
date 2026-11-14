"""Analytics over queue history (Pandas / NumPy). Pure: DataFrames in, JSON-serialisable dicts out.

Conventions
  * Durations in the analytics API are MINUTES (keys end in `_min`); rates are customers per hour or per minute as
    named. (The prediction API works in seconds; its keys end in `_s`.)
  * Time buckets are aligned to the clock in the requested UTC offset (`tz_offset_minutes`, default 0 = UTC).
  * Every response uses the same envelope: {filters, meta, summary, charts, tables}. A chart is
    {type, title, x:{label,type}, y:{label,unit}, series:[{key,name,data:[{x,y}]}]} so a front end can plot any of
    them with one generic component.
  * Empty datasets never raise: they return the same structure with zero/None values and meta.empty = true.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import poisson

MAX_BUCKETS = 5000
PEAK_FACTOR = 1.25
PEAK_ALPHA = 0.01
HISTOGRAM_BINS = 10

ENTRY_COLUMNS = ["status", "arrival", "start", "end", "left", "counter_id"]
RECORD_COLUMNS = ["completed_at", "waiting_time", "service_time", "counter_id"]


class AnalyticsError(ValueError):
    """Invalid analytics request (maps to HTTP 422)."""


@dataclass
class AnalyticsData:
    entries: pd.DataFrame
    records: pd.DataFrame
    counters: list[dict[str, Any]] = field(default_factory=list)
    start: pd.Timestamp | None = None
    end: pd.Timestamp | None = None
    tz_offset_minutes: int = 0
    filters: dict[str, Any] = field(default_factory=dict)
    contains_synthetic: bool = False

    def __post_init__(self):
        self.entries = _normalise(self.entries, ENTRY_COLUMNS, ["arrival", "start", "end", "left"])
        self.records = _normalise(self.records, RECORD_COLUMNS, ["completed_at"])

    @property
    def tz(self) -> timezone:
        return timezone(timedelta(minutes=self.tz_offset_minutes))


def _normalise(df: pd.DataFrame, columns: list[str], datetime_cols: list[str]) -> pd.DataFrame:
    df = df.copy() if df is not None else pd.DataFrame()
    for c in columns:
        if c not in df.columns:
            df[c] = pd.NaT if c in datetime_cols else np.nan
    for c in datetime_cols:
        df[c] = pd.to_datetime(df[c], utc=True)
    return df[columns].reset_index(drop=True)


def _r(x: Any, nd: int = 4) -> float | None:
    if x is None:
        return None
    x = float(x)
    return None if (math.isnan(x) or math.isinf(x)) else round(x, nd)


def _iso(ts: pd.Timestamp | None, tz: timezone) -> str | None:
    return None if ts is None or pd.isna(ts) else ts.tz_convert(tz).isoformat()


def _minutes(seconds: Any) -> float | None:
    return None if seconds is None or (isinstance(seconds, float) and math.isnan(seconds)) else _r(float(seconds) / 60.0)


def chart(kind: str, title: str, x_label: str, x_type: str, y_label: str, y_unit: str,
          series: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": kind, "title": title, "x": {"label": x_label, "type": x_type},
            "y": {"label": y_label, "unit": y_unit}, "series": series}


def series(key: str, name: str, xs: list[Any], ys: list[Any]) -> dict[str, Any]:
    return {"key": key, "name": name, "data": [{"x": x, "y": _r(y) if isinstance(y, (float, np.floating)) else y}
                                                for x, y in zip(xs, ys)]}


def data_extent(d: AnalyticsData) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    """Earliest / latest timestamp present in the (already filtered) data."""
    cols = [d.entries["arrival"], d.entries["start"], d.entries["end"], d.entries["left"], d.records["completed_at"]]
    cols = [c.dropna() for c in cols if c.notna().any()]
    if not cols:
        return None, None
    all_ts = pd.concat(cols)
    return all_ts.min(), all_ts.max()


def resolve_range(d: AnalyticsData) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    lo, hi = data_extent(d)
    start = d.start if d.start is not None else lo
    end = d.end if d.end is not None else hi
    if start is not None and end is not None and end < start:
        raise AnalyticsError("end_date must not be earlier than start_date")
    return start, end


def _buckets(start: pd.Timestamp, end: pd.Timestamp, freq: str, tz: timezone) -> pd.DatetimeIndex:
    first = start.tz_convert(tz).floor(freq)
    idx = pd.date_range(first, end.tz_convert(tz), freq=freq)
    if len(idx) > MAX_BUCKETS:
        raise AnalyticsError(
            f"The requested range produces {len(idx)} '{freq}' buckets (max {MAX_BUCKETS}); narrow the date range"
        )
    return idx


def _freq(granularity: str) -> str:
    try:
        return {"hour": "h", "day": "D"}[granularity]
    except KeyError:
        raise AnalyticsError("granularity must be 'hour' or 'day'") from None


def _envelope(d: AnalyticsData, start, end, summary: dict, charts: dict, tables: dict, empty: bool,
              notes: list[str] | None = None) -> dict[str, Any]:
    notice = ("Contains SYNTHETIC (generated) data." if d.contains_synthetic else "Based on recorded queue data.")
    return {
        "filters": {**d.filters, "start_date": _iso(start, d.tz), "end_date": _iso(end, d.tz),
                    "tz_offset_minutes": d.tz_offset_minutes},
        "meta": {"empty": empty, "contains_synthetic_data": d.contains_synthetic, "data_notice": notice,
                 "timezone": f"UTC{d.tz_offset_minutes // 60:+03d}:{abs(d.tz_offset_minutes) % 60:02d}",
                 "duration_unit": "minutes", "notes": notes or []},
        "summary": summary, "charts": charts, "tables": tables,
    }


def _in_range(s: pd.Series, start, end) -> pd.Series:
    m = s.notna()
    if start is not None:
        m &= s >= start
    if end is not None:
        m &= s <= end
    return m


def queue_length_function(entries: pd.DataFrame):
    """Piecewise-constant queue length L(t): +1 at each arrival, -1 when a customer starts service or leaves."""
    e = entries
    arr = e["arrival"]
    leave = e["start"].fillna(e["left"])
    t_up = (arr.dropna() - pd.Timestamp("1970-01-01", tz="UTC")).dt.total_seconds().to_numpy()
    t_dn = (leave.dropna() - pd.Timestamp("1970-01-01", tz="UTC")).dt.total_seconds().to_numpy()
    times = np.concatenate([t_up, t_dn])
    deltas = np.concatenate([np.ones(len(t_up)), -np.ones(len(t_dn))])
    order = np.lexsort((deltas, times))
    times, deltas = times[order], deltas[order]
    level = np.cumsum(deltas)
    area = np.concatenate([[0.0], np.cumsum(level[:-1] * np.diff(times))]) if len(times) else np.array([])

    def length_at(t: np.ndarray) -> np.ndarray:
        i = np.searchsorted(times, t, side="right") - 1
        return np.where(i >= 0, level[np.clip(i, 0, None)] if len(level) else 0.0, 0.0)

    def integral(t: np.ndarray) -> np.ndarray:
        if not len(times):
            return np.zeros_like(t, dtype=float)
        i = np.searchsorted(times, t, side="right") - 1
        base = np.where(i >= 0, area[np.clip(i, 0, None)] + level[np.clip(i, 0, None)] * (t - times[np.clip(i, 0, None)]), 0.0)
        return base

    return times, level, length_at, integral


def _queue_stats_per_bucket(entries: pd.DataFrame, edges: pd.DatetimeIndex, end: pd.Timestamp) -> tuple[list, list]:
    """Time-weighted average and maximum queue length per bucket [edge_i, edge_{i+1})."""
    times, level, length_at, integral = queue_length_function(entries)
    ep = pd.Timestamp("1970-01-01", tz="UTC")
    e_s = (edges.tz_convert("UTC") - ep).total_seconds().to_numpy()
    ends = np.append(e_s[1:], (end - ep).total_seconds())
    avg, mx = [], []
    for a, b in zip(e_s, ends):
        span = max(b - a, 1e-9)
        avg.append(float((integral(np.array([b]))[0] - integral(np.array([a]))[0]) / span) if len(times) else 0.0)
        inside = level[(times > a) & (times < b)] if len(times) else np.array([])
        mx.append(float(max([length_at(np.array([a]))[0], *inside.tolist()])) if len(times) else 0.0)
    return avg, mx


def _kpis(d: AnalyticsData, start, end) -> dict[str, Any]:
    e, r = d.entries, d.records
    arr = e[_in_range(e["arrival"], start, end)]
    rec = r[_in_range(r["completed_at"], start, end)]
    hours = ((end - start).total_seconds() / 3600.0) if (start is not None and end is not None) else 0.0
    waits = rec["waiting_time"].to_numpy(float)
    svc = rec["service_time"].to_numpy(float)
    served = int(len(rec))
    out = {
        "arrivals": int(len(arr)), "served": served,
        "abandoned": int((arr["status"] == "abandoned").sum()), "removed": int((arr["status"] == "removed").sum()),
        "still_waiting_or_serving": int(arr["status"].isin(["waiting", "serving"]).sum()),
        "avg_waiting_time_min": _minutes(waits.mean()) if served else None,
        "median_waiting_time_min": _minutes(np.median(waits)) if served else None,
        "p95_waiting_time_min": _minutes(np.percentile(waits, 95)) if served else None,
        "max_waiting_time_min": _minutes(waits.max()) if served else None,
        "avg_service_time_min": _minutes(svc.mean()) if served else None,
        "throughput_per_hour": _r(served / hours) if hours > 0 else None,
        "arrival_rate_per_hour": _r(len(arr) / hours) if hours > 0 else None,
        "period_hours": _r(hours, 3),
    }
    return out


def _busy_intervals(d: AnalyticsData, end: pd.Timestamp) -> pd.DataFrame:
    e = d.entries[d.entries["start"].notna()].copy()
    e["end"] = e["end"].fillna(end)
    return e[["counter_id", "start", "end"]]


def _overlap_seconds(iv: pd.DataFrame, a: pd.Timestamp, b: pd.Timestamp) -> float:
    if iv.empty:
        return 0.0
    lo = iv["start"].clip(lower=a)
    hi = iv["end"].clip(upper=b)
    return float(((hi - lo).dt.total_seconds().clip(lower=0)).sum())


def _counter_utilization(d: AnalyticsData, start, end) -> list[dict[str, Any]]:
    iv_all = _busy_intervals(d, end)
    window = (end - start).total_seconds()
    ids = [c["id"] for c in d.counters] or sorted({int(x) for x in iv_all["counter_id"].dropna().unique()})
    names = {c["id"]: c.get("name", f"Counter {c['id']}") for c in d.counters}
    out = []
    for cid in ids:
        iv = iv_all[iv_all["counter_id"] == cid]
        busy = _overlap_seconds(iv, start, end)
        served = int(((iv["end"] >= start) & (iv["end"] <= end)).sum()) if not iv.empty else 0
        out.append({"counter_id": int(cid), "counter_name": names.get(cid, f"Counter {cid}"),
                    "busy_time_min": _minutes(busy), "utilization": _r(busy / window) if window > 0 else None,
                    "customers_served": served})
    return out


def arrivals(d: AnalyticsData, granularity: str = "hour") -> dict[str, Any]:
    freq = _freq(granularity)
    start, end = resolve_range(d)
    e = d.entries
    if start is None or e["arrival"].notna().sum() == 0:
        return _envelope(d, start, end, {"total_arrivals": 0}, {}, {}, True, ["No arrivals match the filters."])
    arr = e.loc[_in_range(e["arrival"], start, end), "arrival"]
    if arr.empty:
        return _envelope(d, start, end, {"total_arrivals": 0}, {}, {}, True, ["No arrivals in the requested range."])
    tz = d.tz
    idx = _buckets(start, end, freq, tz)
    local = arr.dt.tz_convert(tz)
    counts = local.dt.floor(freq).value_counts().reindex(idx, fill_value=0).sort_index()
    xs = [_iso(t, tz) for t in idx]
    ys = counts.to_numpy(int).tolist()

    by_hour = local.dt.hour.value_counts().reindex(range(24), fill_value=0).sort_index()
    by_weekday = local.dt.dayofweek.value_counts().reindex(range(7), fill_value=0).sort_index()
    wd = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    peak_i = int(np.argmax(ys))
    trend = None
    if len(ys) >= 4:
        h = len(ys) // 2
        a, b = float(np.mean(ys[:h])), float(np.mean(ys[h:]))
        change = None if a == 0 else (b - a) / a * 100
        direction = "stable" if change is None or abs(change) < 10 else ("increasing" if change > 0 else "decreasing")
        trend = {"direction": direction, "change_pct_second_half_vs_first": _r(change, 1),
                 "basis": f"mean arrivals per {granularity}, second half of range vs first half"}
    hours = max((end - start).total_seconds() / 3600.0, 1e-9)
    summary = {
        "total_arrivals": int(len(arr)), "arrival_rate_per_hour": _r(len(arr) / hours),
        "granularity": granularity, "buckets": len(idx), "peak_bucket_start": xs[peak_i],
        "peak_bucket_arrivals": int(ys[peak_i]), "trend": trend,
    }
    charts = {
        "arrivals_over_time": chart("line", f"Arrivals per {granularity}", "Time", "time", "Arrivals", "customers",
                                    [series("arrivals", "Arrivals", xs, ys)]),
        "arrivals_by_hour_of_day": chart("bar", "Arrivals by hour of day", "Hour of day", "category", "Arrivals",
                                         "customers", [series("arrivals", "Arrivals", list(range(24)),
                                                              by_hour.to_numpy(int).tolist())]),
        "arrivals_by_weekday": chart("bar", "Arrivals by weekday", "Weekday", "category", "Arrivals", "customers",
                                     [series("arrivals", "Arrivals", wd, by_weekday.to_numpy(int).tolist())]),
    }
    return _envelope(d, start, end, summary, charts, {}, False)


def waiting_times(d: AnalyticsData, granularity: str = "hour") -> dict[str, Any]:
    freq = _freq(granularity)
    start, end = resolve_range(d)
    r = d.records
    rec = r[_in_range(r["completed_at"], start, end)] if start is not None else r.iloc[0:0]
    if rec.empty:
        return _envelope(d, start, end, {"customers_served": 0, "avg_waiting_time_min": None}, {}, {}, True,
                         ["No completed services match the filters."])
    tz = d.tz
    idx = _buckets(start, end, freq, tz)
    local = rec["completed_at"].dt.tz_convert(tz).dt.floor(freq)
    g = rec.assign(bucket=local).groupby("bucket")
    w = g["waiting_time"]
    mean = (w.mean() / 60).reindex(idx)
    p95 = (w.quantile(0.95) / 60).reindex(idx)
    svc = (g["service_time"].mean() / 60).reindex(idx)
    n = g.size().reindex(idx, fill_value=0)
    xs = [_iso(t, tz) for t in idx]
    waits_min = rec["waiting_time"].to_numpy(float) / 60
    edges = np.linspace(0, max(waits_min.max(), 1e-9), HISTOGRAM_BINS + 1)
    hist = np.histogram(waits_min, bins=edges)[0]
    labels = [f"{edges[i]:.1f}-{edges[i + 1]:.1f}" for i in range(HISTOGRAM_BINS)]

    def col(sr):
        return [None if pd.isna(v) else _r(v) for v in sr]

    summary = {
        "customers_served": int(len(rec)), "avg_waiting_time_min": _r(waits_min.mean()),
        "median_waiting_time_min": _r(np.median(waits_min)), "p95_waiting_time_min": _r(np.percentile(waits_min, 95)),
        "max_waiting_time_min": _r(waits_min.max()), "avg_service_time_min": _r(rec["service_time"].mean() / 60),
        "granularity": granularity,
    }
    charts = {
        "waiting_time_over_time": chart("line", f"Waiting time per {granularity}", "Time", "time", "Waiting time",
                                        "minutes", [series("avg", "Average", xs, col(mean)),
                                                    series("p95", "95th percentile", xs, col(p95))]),
        "service_time_over_time": chart("line", f"Average service time per {granularity}", "Time", "time",
                                        "Service time", "minutes", [series("avg_service", "Average", xs, col(svc))]),
        "waiting_time_distribution": chart("bar", "Waiting-time distribution", "Waiting time (min)", "category",
                                           "Customers", "customers", [series("customers", "Customers", labels,
                                                                             hist.astype(int).tolist())]),
    }
    tables = {"by_bucket": [{"bucket_start": x, "customers_served": int(c), "avg_waiting_time_min": a,
                             "p95_waiting_time_min": p, "avg_service_time_min": s}
                            for x, c, a, p, s in zip(xs, n.to_numpy(int), col(mean), col(p95), col(svc))]}
    return _envelope(d, start, end, summary, charts, tables, False)


def utilization(d: AnalyticsData, granularity: str = "hour") -> dict[str, Any]:
    freq = _freq(granularity)
    start, end = resolve_range(d)
    if start is None or d.entries["start"].notna().sum() == 0:
        return _envelope(d, start, end, {"avg_utilization": None}, {}, {"by_counter": []}, True,
                         ["No service activity matches the filters."])
    per_counter = _counter_utilization(d, start, end)
    iv = _busy_intervals(d, end)
    tz = d.tz
    idx = _buckets(start, end, freq, tz)
    edges = list(idx) + [idx[-1] + pd.tseries.frequencies.to_offset(freq)]
    xs = [_iso(t, tz) for t in idx]
    ids = [c["counter_id"] for c in per_counter]
    ser = []
    for cid in ids:
        civ = iv[iv["counter_id"] == cid]
        ys = []
        for a, b in zip(edges[:-1], edges[1:]):
            lo, hi = max(a, start), min(b, end)
            span = (hi - lo).total_seconds()
            ys.append(_overlap_seconds(civ, lo, hi) / span if span > 0 else None)
        name = next(c["counter_name"] for c in per_counter if c["counter_id"] == cid)
        ser.append(series(f"counter_{cid}", name, xs, [None if v is None else _r(v) for v in ys]))
    utils = [c["utilization"] for c in per_counter if c["utilization"] is not None]
    summary = {
        "avg_utilization": _r(np.mean(utils)) if utils else None,
        "max_utilization": _r(max(utils)) if utils else None, "min_utilization": _r(min(utils)) if utils else None,
        "utilization_spread": _r(max(utils) - min(utils)) if utils else None, "counters": len(per_counter),
        "granularity": granularity,
        "basis": "busy time / elapsed time in the range; time a counter spent paused or closed is not excluded",
    }
    charts = {
        "utilization_by_counter": chart("bar", "Utilisation by counter", "Counter", "category", "Utilisation",
                                        "fraction", [series("utilization", "Utilisation",
                                                            [c["counter_name"] for c in per_counter],
                                                            [c["utilization"] for c in per_counter])]),
        "utilization_over_time": chart("line", f"Utilisation per {granularity}", "Time", "time", "Utilisation",
                                       "fraction", ser),
    }
    return _envelope(d, start, end, summary, charts, {"by_counter": per_counter}, False)


def peak_hours(d: AnalyticsData) -> dict[str, Any]:
    """Hour-of-day demand profile: mean arrivals per calendar hour, plus the hours that stand out."""
    start, end = resolve_range(d)
    e = d.entries
    arr = e.loc[_in_range(e["arrival"], start, end), "arrival"] if start is not None else e["arrival"].iloc[0:0]
    if arr.empty:
        return _envelope(d, start, end, {"peak_hours": []}, {}, {"by_hour_of_day": []}, True,
                         ["No arrivals match the filters."])
    tz = d.tz
    idx = _buckets(start, end, "h", tz)
    counts = arr.dt.tz_convert(tz).dt.floor("h").value_counts().reindex(idx, fill_value=0).sort_index()
    notes: list[str] = []
    if len(idx) >= 4:
        counts = counts.iloc[1:-1]
        notes.append("The first and last (partially observed) calendar hours were excluded.")
    prof = counts.groupby(counts.index.hour).agg(["mean", "sum", "count"])
    open_hours = prof.index[prof["sum"] > 0]
    open_counts = counts[counts.index.hour.isin(open_hours)]
    overall = float(open_counts.mean()) if len(open_counts) else 0.0
    waits = pd.Series(dtype=float)
    r = d.records
    rec = r[_in_range(r["completed_at"], start, end)]
    if not rec.empty:
        waits = rec.assign(h=rec["completed_at"].dt.tz_convert(tz).dt.hour).groupby("h")["waiting_time"].mean() / 60
    rows = []
    for h in range(24):
        has = h in prof.index
        mean = float(prof.loc[h, "mean"]) if has else None
        rows.append({
            "hour": h, "label": f"{h:02d}:00-{(h + 1) % 24:02d}:00",
            "avg_arrivals_per_hour": _r(mean), "total_arrivals": int(prof.loc[h, "sum"]) if has else 0,
            "hours_observed": int(prof.loc[h, "count"]) if has else 0,
            "avg_waiting_time_min": _r(waits.get(h)) if h in waits.index else None,
            "relative_to_average": _r(mean / overall) if (has and overall > 0) else None,
            "p_value_vs_flat_demand": None, "is_peak": False,
        })
        if has and overall > 0:
            total, k = float(prof.loc[h, "sum"]), float(prof.loc[h, "count"])
            pval = float(poisson.sf(total - 1, overall * k))
            rows[-1]["p_value_vs_flat_demand"] = pval
            rows[-1]["is_peak"] = bool(mean >= PEAK_FACTOR * overall and pval < PEAK_ALPHA / 24)
    peaks = sorted([x for x in rows if x["is_peak"]], key=lambda x: -x["avg_arrivals_per_hour"])
    summary = {
        "peak_hours": [p["hour"] for p in peaks], "busiest_hour": peaks[0]["hour"] if peaks else (
            max((x for x in rows if x["avg_arrivals_per_hour"] is not None),
                key=lambda x: x["avg_arrivals_per_hour"])["hour"]),
        "mean_arrivals_per_hour_baseline": _r(overall),
        "baseline_basis": "mean arrivals per hour over hours of the day that had any arrivals",
        "peak_definition": (f"hour-of-day whose mean arrivals per hour is >= {PEAK_FACTOR}x the baseline mean and "
                            f"whose excess over flat demand has a Poisson tail probability < {PEAK_ALPHA}/24"),
        "hours_with_data": int(len(prof)),
    }
    if not peaks:
        notes.append("No hour stands out by the peak definition; demand is relatively flat in the observed range.")
    charts = {
        "arrivals_by_hour_of_day": chart("bar", "Average arrivals by hour of day", "Hour of day", "category",
                                         "Average arrivals per hour", "customers",
                                         [series("avg_arrivals", "Average arrivals", [x["hour"] for x in rows],
                                                 [x["avg_arrivals_per_hour"] for x in rows])]),
        "waiting_time_by_hour_of_day": chart("bar", "Average waiting time by hour of day", "Hour of day", "category",
                                             "Waiting time", "minutes",
                                             [series("avg_wait", "Average wait", [x["hour"] for x in rows],
                                                     [x["avg_waiting_time_min"] for x in rows])]),
    }
    return _envelope(d, start, end, summary, charts, {"by_hour_of_day": rows}, False, notes)


def _performance_table(d: AnalyticsData, start, end, freq: str) -> list[dict[str, Any]]:
    tz = d.tz
    idx = _buckets(start, end, freq, tz)
    edges = list(idx) + [idx[-1] + pd.tseries.frequencies.to_offset(freq)]
    e, r = d.entries, d.records
    arr_b = e.loc[_in_range(e["arrival"], start, end), ["arrival", "status"]]
    arr_b = arr_b.assign(b=arr_b["arrival"].dt.tz_convert(tz).dt.floor(freq))
    arrivals_ = arr_b.groupby("b").size().reindex(idx, fill_value=0)
    abandoned = arr_b[arr_b["status"] == "abandoned"].groupby("b").size().reindex(idx, fill_value=0)
    rec = r[_in_range(r["completed_at"], start, end)]
    rec = rec.assign(b=rec["completed_at"].dt.tz_convert(tz).dt.floor(freq))
    g = rec.groupby("b")
    served = g.size().reindex(idx, fill_value=0)
    wait = (g["waiting_time"].mean() / 60).reindex(idx)
    svc = (g["service_time"].mean() / 60).reindex(idx)
    avg_q, max_q = _queue_stats_per_bucket(e, pd.DatetimeIndex([max(a, start).tz_convert("UTC") for a in edges[:-1]]), end)
    hours_each = [(min(b, end) - max(a, start)).total_seconds() / 3600.0 for a, b in zip(edges[:-1], edges[1:])]
    rows = []
    for i, t in enumerate(idx):
        rows.append({
            "bucket_start": _iso(t, tz), "arrivals": int(arrivals_.iloc[i]), "served": int(served.iloc[i]),
            "abandoned": int(abandoned.iloc[i]),
            "avg_waiting_time_min": None if pd.isna(wait.iloc[i]) else _r(wait.iloc[i]),
            "avg_service_time_min": None if pd.isna(svc.iloc[i]) else _r(svc.iloc[i]),
            "throughput_per_hour": _r(served.iloc[i] / hours_each[i]) if hours_each[i] > 0 else None,
            "avg_queue_length": _r(avg_q[i]), "max_queue_length": int(max_q[i]),
            "hours_observed": _r(hours_each[i], 3),
        })
    return rows


def _delta(cur: float | None, prev: float | None) -> dict[str, Any]:
    if cur is None or prev is None:
        return {"current": cur, "previous": prev, "change": None, "change_pct": None}
    ch = cur - prev
    return {"current": cur, "previous": prev, "change": _r(ch), "change_pct": None if prev == 0 else _r(ch / abs(prev) * 100, 2)}


COMPARE_KEYS = {
    "arrivals": None, "served": "higher", "abandoned": "lower", "avg_waiting_time_min": "lower",
    "p95_waiting_time_min": "lower", "avg_service_time_min": "lower", "throughput_per_hour": "higher",
    "arrival_rate_per_hour": None,
}


def compare_periods(cur: dict[str, Any], prev: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k, better in COMPARE_KEYS.items():
        dlt = _delta(cur.get(k), prev.get(k))
        verdict = None
        if better and dlt["change"] not in (None, 0):
            improved = dlt["change"] > 0 if better == "higher" else dlt["change"] < 0
            verdict = "improved" if improved else "worsened"
        dlt["verdict"] = verdict
        out[k] = dlt
    return out


def overview(d: AnalyticsData, previous: AnalyticsData | None = None, compare: bool = False) -> dict[str, Any]:
    """KPIs, daily and hourly performance, queue length, utilisation, peak hours and an optional previous-period comparison.

    `previous` must hold the data of the period immediately before the current one (same length).
    """
    start, end = resolve_range(d)
    has_data = start is not None and (d.entries["arrival"].notna().any() or d.records["completed_at"].notna().any())
    if not has_data or end <= start:
        return _envelope(d, start, end, {"kpis": _kpis(d, start, end) if start is not None else {}}, {},
                         {"hourly": [], "daily": [], "by_counter": []}, True, ["No data matches the filters."])
    tz = d.tz
    kpis = _kpis(d, start, end)
    util = _counter_utilization(d, start, end)
    uvals = [u["utilization"] for u in util if u["utilization"] is not None]
    kpis["avg_utilization"] = _r(np.mean(uvals)) if uvals else None
    hourly = _performance_table(d, start, end, "h") if (end - start) <= timedelta(days=60) else []
    daily = _performance_table(d, start, end, "D")
    notes = []
    if not hourly:
        notes.append("Hourly table omitted for ranges longer than 60 days; use a narrower range.")
    peak = peak_hours(d)
    kpis["avg_queue_length"] = _r(np.average([r["avg_queue_length"] for r in hourly or daily],
                                              weights=[max(r["hours_observed"], 1e-9) for r in hourly or daily]))
    kpis["max_queue_length"] = max(r["max_queue_length"] for r in hourly or daily)
    kpis["peak_hours"] = peak["summary"].get("peak_hours", [])
    xs_h = [r["bucket_start"] for r in hourly]
    xs_d = [r["bucket_start"] for r in daily]
    charts: dict[str, Any] = {}
    if hourly:
        charts["arrivals_per_hour"] = chart("line", "Arrivals per hour", "Time", "time", "Arrivals", "customers",
                                            [series("arrivals", "Arrivals", xs_h, [r["arrivals"] for r in hourly]),
                                             series("served", "Served", xs_h, [r["served"] for r in hourly])])
        charts["waiting_time_per_hour"] = chart("line", "Average waiting time per hour", "Time", "time", "Waiting time",
                                                "minutes", [series("avg_wait", "Average wait", xs_h,
                                                                   [r["avg_waiting_time_min"] for r in hourly])])
        charts["queue_length_over_time"] = chart("line", "Queue length (hourly average and maximum)", "Time", "time",
                                                 "Customers waiting", "customers",
                                                 [series("avg_queue", "Average", xs_h, [r["avg_queue_length"] for r in hourly]),
                                                  series("max_queue", "Maximum", xs_h, [r["max_queue_length"] for r in hourly])])
        charts["throughput_per_hour"] = chart("bar", "Service throughput per hour", "Time", "time", "Customers served",
                                              "customers/hour", [series("throughput", "Throughput", xs_h,
                                                                        [r["throughput_per_hour"] for r in hourly])])
    charts["daily_performance"] = chart("bar", "Daily arrivals and customers served", "Day", "time", "Customers",
                                        "customers", [series("arrivals", "Arrivals", xs_d, [r["arrivals"] for r in daily]),
                                                      series("served", "Served", xs_d, [r["served"] for r in daily])])
    charts["utilization_by_counter"] = chart(
        "bar", "Utilisation by counter", "Counter", "category", "Utilisation", "fraction",
        [series("utilization", "Utilisation", [u["counter_name"] for u in util], [u["utilization"] for u in util])])
    tables = {"hourly": hourly, "daily": daily, "by_counter": util}
    summary: dict[str, Any] = {"kpis": kpis}
    if compare:
        if previous is None:
            summary["comparison"] = {"available": False, "reason": "No previous-period data was supplied."}
        else:
            ps, pe = previous.start, previous.end
            pk = _kpis(previous, ps, pe) if ps is not None else {}
            if not pk or pk.get("arrivals", 0) == 0 and pk.get("served", 0) == 0:
                summary["comparison"] = {"available": False, "reason": "No data exists in the previous period.",
                                         "previous_period": {"start": _iso(ps, tz), "end": _iso(pe, tz)}}
            else:
                summary["comparison"] = {"available": True,
                                         "previous_period": {"start": _iso(ps, tz), "end": _iso(pe, tz)},
                                         "previous_kpis": pk, "metrics": compare_periods(kpis, pk)}
    env = _envelope(d, start, end, summary, charts, tables, False, notes)
    env["summary"]["peak_hours_detail"] = peak["summary"]
    return env
