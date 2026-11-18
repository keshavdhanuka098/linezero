"""SLA engine: exact probabilities, consistency with the prediction engine, honest scores."""
import math

import numpy as np
import pytest
from scipy import stats as sps

from app.engines import prediction_engine as pe
from app.engines import sla_engine as se


def test_breach_probability_is_the_exact_erlang_tail():
    # k = 3 completions at 1/min, 3 minutes left: P(Poisson(3) <= 2)
    assert se.breach_probability(3, 1.0, 180) == pytest.approx(sps.poisson.cdf(2, 3.0))
    assert se.breach_probability(3, 1.0, 180) == pytest.approx(0.4232, abs=1e-4)


def test_breach_probability_limits_and_monotonicity():
    assert se.breach_probability(5, 1.0, 0) == 1.0 and se.breach_probability(5, 1.0, -30) == 1.0
    assert se.breach_probability(0, 1.0, 60) == 0.0
    longer = [se.breach_probability(4, 1.0, s) for s in (60, 120, 240, 480)]
    assert longer == sorted(longer, reverse=True)           # more time left -> lower risk
    more_ahead = [se.breach_probability(k, 1.0, 240) for k in (1, 3, 6, 12)]
    assert more_ahead == sorted(more_ahead)                 # more people ahead -> higher risk
    faster = [se.breach_probability(5, r, 240) for r in (0.5, 1, 2, 4)]
    assert faster == sorted(faster, reverse=True)           # more capacity -> lower risk
    with pytest.raises(ValueError):
        se.breach_probability(2, 0.0, 60)


def test_probability_matches_simulation_of_the_service_process():
    """k exponential services at total rate mu (all counters busy): empirical breach share == formula."""
    rng = np.random.default_rng(7)
    k, mu, remaining_min = 6, 2.0, 3.0
    waits = rng.gamma(shape=k, scale=1.0 / mu, size=200_000)
    empirical = float((waits > remaining_min).mean())
    assert se.breach_probability(k, mu, remaining_min * 60) == pytest.approx(empirical, abs=0.005)


def test_expected_wait_matches_the_existing_prediction_engine():
    rates = [0.25, 0.25, 0.5]
    bw = pe.baseline_wait(pe.BaselineInputs(queue_length=7, active_counters=3, busy_counters=3, counter_rates_per_min=rates))
    a = se.assess_customer(ahead=7, idle=0, rate_per_min=sum(rates), elapsed_s=30, target_s=1200, at_risk=0.25, critical=0.6)
    assert a["expected_remaining_wait_s"] == pytest.approx(bw["waiting_time_s"])
    assert a["completions_needed"] == bw["completions_needed"]
    assert a["predicted_total_wait_s"] == pytest.approx(30 + bw["waiting_time_s"])


def test_status_bands_follow_the_policy_thresholds():
    kw = dict(at_risk=0.25, critical=0.6)
    assert se.classify(0.10, 60, 600, **kw) == "safe"
    assert se.classify(0.25, 60, 600, **kw) == "at_risk" and se.classify(0.59, 60, 600, **kw) == "at_risk"
    assert se.classify(0.60, 60, 600, **kw) == "critical"
    assert se.classify(0.99, 600, 600, **kw) == "breached" and se.classify(0.0, 900, 600, **kw) == "breached"
    # different thresholds give different classes for the same probability: nothing is hardcoded
    assert se.classify(0.4, 0, 600, at_risk=0.5, critical=0.9) == "safe"


def test_no_active_counter_is_reported_not_guessed():
    a = se.assess_customer(2, 0, None, 120, 600, 0.25, 0.6)
    assert a["breach_probability"] == 1.0 and a["predicted_total_wait_s"] is None and a["basis"] == "no_active_counters"
    assert a["status"] == "critical"
    assert se.assess_customer(2, 0, None, 700, 600, 0.25, 0.6)["status"] == "breached"


def test_compliance_score_counts_only_completed_customers_within_target():
    c = se.compliance([1, 2, 5, 6, 10], [5, 5, 5, 5, 5])
    assert (c["n"], c["met"], c["breached"], c["score"]) == (5, 3, 2, 60.0)
    assert c["avg_over_target_min"] == pytest.approx(3.0) and c["interval95"][0] < 60 < c["interval95"][1]
    assert se.compliance([], [])["score"] is None                        # no customers -> no score, never 0 or 100
    assert se.compliance([5], [5])["score"] == 100.0                     # exactly at the target counts as met
    per = se.compliance([4, 8], [5, 10])                                 # each customer against their OWN target
    assert per["score"] == 100.0
    with pytest.raises(ValueError):
        se.compliance([1, 2], [5])


def test_trend_keeps_gaps_visible():
    start = 1000.0
    end_s = np.array([start + 10, start + 20, start + 7300])
    t = se.trend(end_s, np.array([1.0, 9.0, 2.0]), np.array([5.0, 5.0, 5.0]), start, start + 10800, 60)
    assert [b["served"] for b in t] == [2, 0, 1] and t[0]["score"] == 50.0
    assert t[1]["score"] is None and t[1]["avg_wait_min"] is None
    assert sum(b["served"] for b in t) == 3


def test_predicted_compliance_is_the_mean_survival():
    r = se.predicted_compliance([0.0, 0.5, 1.0, 0.5])
    assert r["score"] == 50.0 and r["expected_breaches"] == 2.0 and r["n"] == 4
    assert se.predicted_compliance([])["score"] is None


def test_required_rate_hits_the_requested_probability():
    r = se.required_rate_per_min(5, 300, 0.5)
    assert se.breach_probability(5, r, 300) == pytest.approx(0.5, abs=1e-6)
    assert se.required_rate_per_min(5, 0) is None and se.required_rate_per_min(0, 60) == 0.0
    assert math.isfinite(r)


def test_wilson_interval_bounds():
    lo, hi = se.wilson(0, 10)
    assert lo == 0.0 and 0 < hi < 0.4
    assert se.wilson(0, 0) is None
