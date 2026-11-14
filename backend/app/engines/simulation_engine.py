"""Discrete-event queue simulation built on SimPy.

Pure computation: no database, no HTTP. `QueueSimulation(config).run()` returns a plain, JSON-serialisable
dict, so it can be executed inline today and moved to a thread/process/worker later without changes.

Time is unitless; by convention the rest of LineZero treats one unit as one minute
(arrival_rate = customers/minute, mean_service_time = minutes).
"""
from __future__ import annotations

import math
import secrets
from typing import Literal

import numpy as np
import simpy
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.engines.queueing_theory import LOGNORMAL_SIGMA, theoretical_metrics

ArrivalDistribution = Literal["poisson", "deterministic", "uniform"]
ServiceDistribution = Literal["exponential", "deterministic", "uniform", "lognormal"]
CounterAssignment = Literal["longest_idle", "lowest_index"]

MAX_EXPECTED_ARRIVALS = 1_000_000


class ProfileSegment(BaseModel):
    """Multiply the base arrival rate by `multiplier` for start <= t < end (e.g. a rush-hour spike)."""

    model_config = ConfigDict(extra="forbid")
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    multiplier: float = Field(ge=0, le=100)

    @model_validator(mode="after")
    def _ordered(self):
        if self.end <= self.start:
            raise ValueError("end must be greater than start")
        return self


class SimulationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    arrival_rate: float = Field(gt=0, le=10_000, description="Mean customers per time unit")
    mean_service_time: float = Field(gt=0, le=1_000_000, description="Mean service duration (time units)")
    num_counters: int = Field(ge=1, le=100)
    duration: float = Field(gt=0, le=10_000_000, description="Simulated time horizon")
    arrival_distribution: ArrivalDistribution = "poisson"
    service_distribution: ServiceDistribution = "exponential"
    seed: int | None = Field(default=None, ge=0, le=2**32 - 1, description="Random seed (generated if omitted)")
    abandonment_enabled: bool = False
    mean_patience: float | None = Field(
        default=None, gt=0, description="Mean time a customer waits before leaving (exponential)"
    )
    counter_speed_factors: list[float] | None = Field(
        default=None, description="Per-counter speed multipliers (service time is divided by the factor)"
    )
    counter_assignment: CounterAssignment = "longest_idle"
    arrival_profile: list[ProfileSegment] | None = None
    record_trace: bool = Field(default=False, description="Return one record per customer (engine use only)")

    @model_validator(mode="after")
    def _cross_checks(self):
        if self.abandonment_enabled and self.mean_patience is None:
            raise ValueError("mean_patience is required when abandonment_enabled is true")
        if self.counter_speed_factors is not None:
            f = self.counter_speed_factors
            if len(f) != self.num_counters:
                raise ValueError("counter_speed_factors must have one entry per counter")
            if any(x <= 0 or x > 100 for x in f):
                raise ValueError("counter_speed_factors must be in (0, 100]")
        peak = 1.0
        if self.arrival_profile:
            if self.arrival_distribution != "poisson":
                raise ValueError("arrival_profile requires arrival_distribution='poisson'")
            segs = sorted(self.arrival_profile, key=lambda s: s.start)
            for a, b in zip(segs, segs[1:]):
                if b.start < a.end:
                    raise ValueError("arrival_profile segments must not overlap")
            peak = max(1.0, max(s.multiplier for s in segs))
        if self.arrival_rate * self.duration * peak > MAX_EXPECTED_ARRIVALS:
            raise ValueError(
                f"Too large: expected arrivals exceed {MAX_EXPECTED_ARRIVALS:,}; shorten duration or lower rate"
            )
        return self


def _r(x: float, nd: int = 6) -> float:
    return round(float(x), nd)


class QueueSimulation:
    def __init__(self, config: SimulationConfig):
        self.config = config
        self.seed_used = config.seed if config.seed is not None else secrets.randbits(32)
        self._has_run = False
        self.reset()

    def reset(self) -> None:
        """Discard all state and rebuild the model; the same seed will reproduce the same run."""
        cfg = self.config
        self.env = simpy.Environment()
        arrivals_ss, service_ss, patience_ss = np.random.SeedSequence(self.seed_used).spawn(3)
        self.rng_arrival = np.random.default_rng(arrivals_ss)
        self.rng_service = np.random.default_rng(service_ss)
        self.rng_patience = np.random.default_rng(patience_ss)

        self.factors = list(cfg.counter_speed_factors or [1.0] * cfg.num_counters)
        store_cls = simpy.PriorityStore if cfg.counter_assignment == "lowest_index" else simpy.Store
        self.idle_counters = store_cls(self.env)
        for i in range(cfg.num_counters):
            self.idle_counters.put(i)

        self.arrivals = 0
        self.abandoned = 0
        self.served_by = [0] * cfg.num_counters
        self.busy_time = [0.0] * cfg.num_counters
        self.busy_since: list[float | None] = [None] * cfg.num_counters
        self.waits: list[float] = []
        self.service_times: list[float] = []
        self.queue_len = 0
        self.max_queue_len = 0
        self._area = 0.0
        self._last_change = 0.0
        self._waiting_since: dict[int, float] = {}
        self.trace: dict[int, dict] = {}
        self._segments = sorted(cfg.arrival_profile or [], key=lambda s: s.start)
        self._peak = max([1.0] + [s.multiplier for s in self._segments])
        self._has_run = False

    def _multiplier(self, t: float) -> float:
        for s in self._segments:
            if s.start <= t < s.end:
                return s.multiplier
        return 1.0

    def _sample_service(self, counter: int) -> float:
        m, rng, d = self.config.mean_service_time, self.rng_service, self.config.service_distribution
        if d == "exponential":
            x = rng.exponential(m)
        elif d == "deterministic":
            x = m
        elif d == "uniform":
            x = rng.uniform(0.5 * m, 1.5 * m)
        else:
            x = rng.lognormal(math.log(m) - LOGNORMAL_SIGMA**2 / 2, LOGNORMAL_SIGMA)
        return float(x) / self.factors[counter]

    def _next_gap(self) -> float:
        cfg, rng = self.config, self.rng_arrival
        mean_gap = 1.0 / cfg.arrival_rate
        if self._segments:
            lam_max = cfg.arrival_rate * self._peak
            t = self.env.now
            while t < cfg.duration:
                t += rng.exponential(1.0 / lam_max)
                if rng.random() * lam_max <= cfg.arrival_rate * self._multiplier(t):
                    break
            return t - self.env.now
        if cfg.arrival_distribution == "poisson":
            return float(rng.exponential(mean_gap))
        if cfg.arrival_distribution == "deterministic":
            return mean_gap
        return float(rng.uniform(0.5 * mean_gap, 1.5 * mean_gap))

    def _queue_change(self, delta: int) -> None:
        now = self.env.now
        self._area += self.queue_len * (now - self._last_change)
        self._last_change = now
        self.queue_len += delta
        self.max_queue_len = max(self.max_queue_len, self.queue_len)

    def _arrival_process(self):
        cid = 0
        while True:
            yield self.env.timeout(self._next_gap())
            cid += 1
            self.env.process(self._customer(cid))

    def _customer(self, cid: int):
        env, cfg = self.env, self.config
        arrival = env.now
        self.arrivals += 1
        self._waiting_since[cid] = arrival
        if cfg.record_trace:
            self.trace[cid] = {
                "customer": cid, "arrival_time": arrival, "service_start_time": None,
                "service_end_time": None, "counter_index": None, "abandon_time": None,
            }
        self._queue_change(+1)
        request = self.idle_counters.get()
        if cfg.abandonment_enabled:
            patience = self.rng_patience.exponential(cfg.mean_patience)
            yield request | env.timeout(patience)
            if not request.triggered:
                request.cancel()
                self._queue_change(-1)
                self._waiting_since.pop(cid, None)
                self.abandoned += 1
                if cfg.record_trace:
                    self.trace[cid]["abandon_time"] = env.now
                return
        else:
            yield request
        counter = request.value
        wait = env.now - arrival
        self._queue_change(-1)
        self._waiting_since.pop(cid, None)
        self.waits.append(wait)
        service = self._sample_service(counter)
        self.busy_since[counter] = env.now
        if cfg.record_trace:
            self.trace[cid].update(service_start_time=env.now, counter_index=counter)
        yield env.timeout(service)
        self.busy_time[counter] += service
        self.busy_since[counter] = None
        self.served_by[counter] += 1
        self.service_times.append(service)
        if cfg.record_trace:
            self.trace[cid]["service_end_time"] = env.now
        yield self.idle_counters.put(counter)

    def run(self) -> dict:
        if self._has_run:
            self.reset()
        self.env.process(self._arrival_process())
        self.env.run(until=self.config.duration)
        self._has_run = True
        return self._collect()

    def _collect(self) -> dict:
        cfg, horizon = self.config, self.config.duration
        self._area += self.queue_len * (horizon - self._last_change)
        busy = list(self.busy_time)
        in_service = 0
        for i, since in enumerate(self.busy_since):
            if since is not None:
                busy[i] += horizon - since
                in_service += 1
        waits = np.asarray(self.waits, dtype=float)
        served = sum(self.served_by)
        still_waiting = [horizon - t for t in self._waiting_since.values()]
        util = [b / horizon for b in busy]

        result = {
            "seed_used": self.seed_used,
            "duration": horizon,
            "num_counters": cfg.num_counters,
            "total_arrivals": self.arrivals,
            "total_served": served,
            "customers_waiting_at_end": self.queue_len,
            "customers_in_service_at_end": in_service,
            "customers_remaining": self.queue_len + in_service,
            "abandoned": self.abandoned,
            "abandonment_rate": _r(self.abandoned / self.arrivals) if self.arrivals else 0.0,
            "avg_waiting_time": _r(waits.mean()) if waits.size else 0.0,
            "max_waiting_time": _r(waits.max()) if waits.size else 0.0,
            "p50_waiting_time": _r(np.percentile(waits, 50)) if waits.size else 0.0,
            "p95_waiting_time": _r(np.percentile(waits, 95)) if waits.size else 0.0,
            "longest_unserved_wait": _r(max(still_waiting)) if still_waiting else 0.0,
            "avg_queue_length": _r(self._area / horizon),
            "max_queue_length": self.max_queue_len,
            "avg_service_time": _r(np.mean(self.service_times)) if self.service_times else 0.0,
            "avg_utilization": _r(sum(util) / len(util)),
            "throughput": _r(served / horizon),
            "counters": [
                {
                    "counter_index": i, "speed_factor": self.factors[i], "served": self.served_by[i],
                    "busy_time": _r(busy[i]), "utilization": _r(util[i]),
                }
                for i in range(cfg.num_counters)
            ],
            "theoretical": _round_dict(theoretical_metrics(cfg)),
        }
        if cfg.record_trace:
            result["trace"] = [self.trace[k] for k in sorted(self.trace)]
        return result


def _round_dict(d: dict) -> dict:
    return {k: (_r(v) if isinstance(v, float) else v) for k, v in d.items()}


def run_simulation(config: SimulationConfig) -> dict:
    """Functional entry point (picklable args/return) - the hook for background execution."""
    return QueueSimulation(config).run()
