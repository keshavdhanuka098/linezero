"""SLA & customer-experience maths (pure functions, no database access).

Waiting-time model (the same one the existing prediction engine uses; see `prediction_engine.baseline_wait`)
  A customer with `ahead` people in front needs k = max(ahead + 1 - idle, 0) service completions before their service
  starts. With total service rate mu (customers per minute, summed over the active counters) and memoryless service
  times, the time for k completions is Erlang(k, mu), so for a customer who has already waited `elapsed`:

      P(breach) = P(remaining wait > target - elapsed) = P(Poisson(mu * (target - elapsed)) <= k - 1)

  The expected remaining wait is k / mu, exactly `baseline_wait`'s point estimate; the probability adds the spread.
  Assumptions (stated in every response): first-come-first-served within the line, constant service rate, service
  times memoryless, counters keep their current state. The service class sets the TARGET, not the order of service.

Status of a waiting customer
  breached  already waited >= target (probability 1);
  critical  P(breach) >= the policy's `critical_probability`;
  at_risk   P(breach) >= the policy's `at_risk_probability`;
  safe      otherwise.

Compliance score (0-100) = 100 x (completed customers who waited <= their target) / (completed customers).
It is computed only from customers whose service has started and finished; abandoned customers are reported separately
and are not in the score. No customers means no score (None), never 0 or 100.
"""
from __future__ import annotations

import math
from typing import Any, Sequence

import numpy as np
from scipy import stats as sps

STATUSES = ("safe", "at_risk", "critical", "breached")
STATUS_RANK = {s: i for i, s in enumerate(STATUSES)}
ASSUMPTIONS = [
    "Customers are served first-come-first-served; a service class changes the SLA target, not the order of service.",
    "Service rate is the sum of the active counters' rates (calibrated rates if an active calibration exists).",
    "Service times are treated as memoryless (exponential), so the time to the k-th completion is Erlang(k, rate).",
    "Counters keep their current state during the wait; later breakdowns or reopenings are not anticipated.",
]


def breach_probability(completions_needed: int, rate_per_min: float, remaining_s: float) -> float:
    """P(the customer's remaining wait exceeds `remaining_s`). 1.0 once the target has already been reached."""
    if remaining_s <= 0:
        return 1.0
    if completions_needed <= 0:
        return 0.0
    if not (rate_per_min > 0 and math.isfinite(rate_per_min)):
        raise ValueError("rate_per_min must be a finite number > 0")
    return float(sps.poisson.cdf(completions_needed - 1, rate_per_min * remaining_s / 60.0))


def classify(probability: float, elapsed_s: float, target_s: float, at_risk: float, critical: float) -> str:
    if elapsed_s >= target_s:
        return "breached"
    if probability >= critical:
        return "critical"
    if probability >= at_risk:
        return "at_risk"
    return "safe"


def assess_customer(ahead: int, idle: int, rate_per_min: float | None, elapsed_s: float, target_s: float,
                    at_risk: float, critical: float) -> dict[str, Any]:
    """Per-customer prediction. `rate_per_min` None means no active counter (no finite wait can be predicted)."""
    remaining = target_s - elapsed_s
    if rate_per_min is None:
        status = "breached" if remaining <= 0 else "critical"
        return {"completions_needed": max(ahead + 1 - idle, 0), "expected_remaining_wait_s": None,
                "predicted_total_wait_s": None, "remaining_sla_s": remaining, "breach_probability": 1.0,
                "status": status, "basis": "no_active_counters"}
    k = max(ahead + 1 - idle, 0)
    expected_remaining = k / rate_per_min * 60.0
    p = breach_probability(k, rate_per_min, remaining)
    return {"completions_needed": k, "expected_remaining_wait_s": expected_remaining,
            "predicted_total_wait_s": elapsed_s + expected_remaining, "remaining_sla_s": remaining,
            "breach_probability": p, "status": classify(p, elapsed_s, target_s, at_risk, critical),
            "basis": "erlang_from_live_state"}


def wilson(met: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n <= 0:
        return None
    p = met / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, centre - half), min(1.0, centre + half)


def compliance(waits_min: Sequence[float], targets_min: Sequence[float]) -> dict[str, Any]:
    """Share of completed customers whose wait was within their own target."""
    w, t = np.asarray(waits_min, dtype=float), np.asarray(targets_min, dtype=float)
    if len(w) != len(t):
        raise ValueError("waits and targets must have the same length")
    n = int(len(w))
    if n == 0:
        return {"n": 0, "met": 0, "breached": 0, "score": None, "interval95": None, "avg_wait_min": None,
                "p95_wait_min": None, "avg_target_min": None, "avg_over_target_min": None}
    met = int((w <= t).sum())
    ci = wilson(met, n)
    over = w[w > t] - t[w > t]
    return {"n": n, "met": met, "breached": n - met, "score": round(100.0 * met / n, 2),
            "interval95": None if ci is None else [round(100 * ci[0], 2), round(100 * ci[1], 2)],
            "avg_wait_min": float(w.mean()), "p95_wait_min": float(np.percentile(w, 95)),
            "avg_target_min": float(t.mean()), "avg_over_target_min": float(over.mean()) if len(over) else 0.0}


def trend(end_s: np.ndarray, waits_min: np.ndarray, targets_min: np.ndarray, start_s: float, stop_s: float,
          bucket_min: float) -> list[dict[str, Any]]:
    """Per-bucket compliance of customers by the time their wait ended (service start). Empty buckets are kept with
    n = 0 and no score, so gaps are visible rather than interpolated."""
    width = bucket_min * 60.0
    n_b = max(int(math.ceil((stop_s - start_s) / width)), 1)
    out = []
    idx = np.floor((end_s - start_s) / width).astype(int) if len(end_s) else np.array([], dtype=int)
    for b in range(n_b):
        m = idx == b
        c = compliance(waits_min[m], targets_min[m])
        out.append({"start_s": start_s + b * width, "end_s": min(start_s + (b + 1) * width, stop_s),
                    "served": c["n"], "met": c["met"], "breached": c["breached"], "score": c["score"],
                    "avg_wait_min": c["avg_wait_min"], "avg_target_min": c["avg_target_min"]})
    return out


def predicted_compliance(probabilities: Sequence[float]) -> dict[str, Any]:
    """Expected share of the customers currently waiting who will be served within their target = mean(1 - p)."""
    p = np.asarray(probabilities, dtype=float)
    if len(p) == 0:
        return {"n": 0, "score": None, "expected_breaches": None}
    return {"n": int(len(p)), "score": round(100.0 * float((1.0 - p).mean()), 2),
            "expected_breaches": float(p.sum())}


def required_rate_per_min(completions_needed: int, remaining_s: float, quantile: float = 0.5) -> float | None:
    """Smallest total service rate at which the customer's breach probability is <= `quantile`; None if the
    target has already passed. Found by bisection on the exact Erlang tail (no closed form)."""
    if remaining_s <= 0:
        return None
    if completions_needed <= 0:
        return 0.0
    lo, hi = 1e-9, max(completions_needed / remaining_s * 60.0 * 20.0, 1.0)
    for _ in range(80):
        mid = (lo + hi) / 2
        if breach_probability(completions_needed, mid, remaining_s) > quantile:
            lo = mid
        else:
            hi = mid
    return hi


__all__ = ["STATUSES", "STATUS_RANK", "ASSUMPTIONS", "breach_probability", "classify", "assess_customer", "compliance",
           "trend", "predicted_compliance", "required_rate_per_min", "wilson"]
