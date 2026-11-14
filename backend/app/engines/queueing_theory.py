"""Closed-form queueing results used to sanity-check the simulation."""
from __future__ import annotations

import math
from typing import Any

LOGNORMAL_SIGMA = 0.5


def service_cv2(distribution: str) -> float:
    """Squared coefficient of variation of the service-time distribution."""
    return {
        "exponential": 1.0,
        "deterministic": 0.0,
        "uniform": 1.0 / 12.0,
        "lognormal": math.exp(LOGNORMAL_SIGMA**2) - 1.0,
    }[distribution]


def erlang_c(servers: int, offered_load: float) -> float | None:
    """Probability an arrival has to wait in an M/M/c queue (None if unstable)."""
    rho = offered_load / servers
    if rho >= 1:
        return None
    term, partial = 1.0, 0.0
    for k in range(servers):
        partial += term
        term *= offered_load / (k + 1)
    last = term / (1 - rho)
    return last / (partial + last)


def mmc(arrival_rate: float, service_rate: float, servers: int) -> dict[str, Any]:
    a = arrival_rate / service_rate
    rho = a / servers
    if rho >= 1:
        return {"stable": False, "utilization": rho}
    c = erlang_c(servers, a)
    wq = c / (servers * service_rate - arrival_rate)
    return {
        "stable": True, "utilization": rho, "probability_of_wait": c,
        "avg_waiting_time": wq, "avg_queue_length": arrival_rate * wq,
    }


def mg1(arrival_rate: float, mean_service: float, cv2: float) -> dict[str, Any]:
    """Pollaczek-Khinchine mean wait for M/G/1."""
    rho = arrival_rate * mean_service
    if rho >= 1:
        return {"stable": False, "utilization": rho}
    wq = rho * mean_service * (1 + cv2) / (2 * (1 - rho))
    return {
        "stable": True, "utilization": rho, "probability_of_wait": rho,
        "avg_waiting_time": wq, "avg_queue_length": arrival_rate * wq,
    }


def theoretical_metrics(cfg) -> dict[str, Any]:
    """Exact steady-state values when the configuration matches a textbook model, else not applicable."""
    na = {"applicable": False, "model": None, "note": "No closed-form model for this configuration"}
    if cfg.abandonment_enabled or cfg.arrival_profile or cfg.arrival_distribution != "poisson":
        return na
    factors = cfg.counter_speed_factors or [1.0] * cfg.num_counters
    if cfg.num_counters == 1:
        res = mg1(cfg.arrival_rate, cfg.mean_service_time / factors[0], service_cv2(cfg.service_distribution))
        model = "M/M/1" if cfg.service_distribution == "exponential" else (
            "M/D/1" if cfg.service_distribution == "deterministic" else "M/G/1 (Pollaczek-Khinchine)"
        )
    elif cfg.service_distribution == "exponential" and len(set(factors)) == 1:
        res = mmc(cfg.arrival_rate, factors[0] / cfg.mean_service_time, cfg.num_counters)
        model = f"M/M/{cfg.num_counters}"
    else:
        return na
    return {"applicable": True, "model": model, "note": "Steady-state values; short runs deviate", **res}
