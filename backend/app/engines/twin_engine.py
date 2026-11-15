"""Digital Twin simulation engine.

Extends the existing SimPy `QueueSimulation` (it does not modify it) with what a "twin" needs:

  * counter outages (failures) with optional repair time;
  * time-limited slow-downs of one counter or all counters;
  * counters that start closed: reserve ("standby") counters and counters with no staff;
  * recovery actions: scheduled (manual) or reactive (automatic, queue-threshold triggered);
  * starting from a given live state (customers already waiting, counters already busy);
  * playback data: periodic frames, a per-customer trace and a system event log.

Units follow the rest of LineZero: one time unit = one minute, rates are customers per minute.

Modelling notes (also surfaced in the API responses and README):
  * A counter failure is *graceful*: the customer being served finishes, then the counter goes offline.
  * All counters share one FIFO queue, so "redistributing customers" is already implicit. The assignment strategy only
    changes which idle counter takes the next customer.
  * "boost_speed" represents extra staff assisting. Its factor is an assumption supplied by the user, not data.
  * Everything here is simulation. Nothing writes to the real queues in the database.
"""
from __future__ import annotations

import heapq
import math
from typing import Any, Literal

import numpy as np
import simpy
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.engines.simulation_engine import QueueSimulation, SimulationConfig

TWIN_MAX_EXPECTED_ARRIVALS = 8_000
MAX_FRAMES = 400

CLOSED_REASONS = ("standby", "no_staff")
STATE_IDLE, STATE_BUSY, STATE_FAILED, STATE_CLOSED = 0, 1, 2, 3
STATE_NAMES = {STATE_IDLE: "idle", STATE_BUSY: "busy", STATE_FAILED: "failed", STATE_CLOSED: "closed"}

SUMMARY_KEYS = [
    "avg_waiting_time", "p95_waiting_time", "max_queue_length", "total_served", "abandoned", "abandonment_rate",
    "avg_utilization_available", "resource_cost", "avg_queue_length", "throughput",
]


class CounterOutage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    counter: int = Field(ge=0, description="Zero-based counter index")
    start: float = Field(ge=0)
    end: float | None = Field(default=None, gt=0, description="Repair time; omit for 'down until the end'")
    kind: Literal["failure", "outage"] = "failure"

    @model_validator(mode="after")
    def _ordered(self):
        if self.end is not None and self.end <= self.start:
            raise ValueError("outage end must be greater than start")
        return self


class SpeedChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    counter: int | None = Field(default=None, ge=0, description="Counter index, or omit for every counter")
    start: float = Field(ge=0)
    end: float | None = Field(default=None, gt=0)
    factor: float = Field(gt=0, le=100, description="Service speed multiplier (0.6 = 40% slower)")

    @model_validator(mode="after")
    def _ordered(self):
        if self.end is not None and self.end <= self.start:
            raise ValueError("speed change end must be greater than start")
        return self


class ScheduledAction(BaseModel):
    """A recovery action applied at a fixed time (manual mode, or chosen by the recommender)."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["activate_counter", "deactivate_counter", "boost_speed"]
    at: float = Field(ge=0)
    counter: int | None = Field(default=None, ge=0)
    factor: float | None = Field(default=None, gt=0, le=10, description="boost_speed multiplier")
    duration: float | None = Field(default=None, gt=0, description="boost_speed: revert after this long")

    @model_validator(mode="after")
    def _needs(self):
        if self.type in ("activate_counter", "deactivate_counter") and self.counter is None:
            raise ValueError(f"{self.type} requires a counter index")
        if self.type == "boost_speed" and self.factor is None:
            raise ValueError("boost_speed requires a factor")
        return self


class RecoveryPolicy(BaseModel):
    """Reactive controller: when the queue stays long, open a closed counter, then apply a speed boost."""

    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    queue_threshold: int = Field(default=8, ge=1, le=1000)
    sustain: float = Field(default=2.0, ge=0, le=1000, description="Minutes the queue must stay above the threshold")
    check_interval: float = Field(default=1.0, gt=0, le=1000)
    cooldown: float = Field(default=2.0, ge=0, le=1000, description="Minutes between consecutive actions")
    max_activations: int = Field(default=2, ge=0, le=100)
    boost_factor: float = Field(default=1.0, ge=1.0, le=10, description="1.0 disables the boost step")


class TwinConfig(SimulationConfig):
    outages: list[CounterOutage] = Field(default_factory=list, max_length=50)
    speed_changes: list[SpeedChange] = Field(default_factory=list, max_length=50)
    standby_counters: list[int] = Field(default_factory=list, description="Counters that start closed (reserve)")
    staff_available: int | None = Field(default=None, ge=0, description="Staffed counters; higher indices start closed")
    actions: list[ScheduledAction] = Field(default_factory=list, max_length=100)
    recovery: RecoveryPolicy | None = None
    initial_queue: int = Field(default=0, ge=0, le=500, description="Customers already waiting at t=0")
    initial_busy_counters: list[int] = Field(default_factory=list, description="Counters already serving at t=0")
    cost_per_counter_hour: float = Field(default=1.0, ge=0, le=1_000_000)
    sample_interval: float | None = Field(default=None, gt=0, description="Frame spacing; default duration/240")
    congestion_queue: int | None = Field(default=None, ge=1, description="Queue length that counts as congestion")

    @model_validator(mode="after")
    def _twin_checks(self):
        n = self.num_counters

        def in_range(idx: int, what: str) -> None:
            if idx < 0 or idx >= n:
                raise ValueError(f"{what} refers to counter {idx}, but there are only {n} counters (0-{n - 1})")

        for o in self.outages:
            in_range(o.counter, "outage")
        for s in self.speed_changes:
            if s.counter is not None:
                in_range(s.counter, "speed change")
        for a in self.actions:
            if a.counter is not None:
                in_range(a.counter, f"{a.type} action")
        for i in self.standby_counters:
            in_range(i, "standby_counters")
        for i in self.initial_busy_counters:
            in_range(i, "initial_busy_counters")
        if len(set(self.initial_busy_counters)) != len(self.initial_busy_counters):
            raise ValueError("initial_busy_counters must not repeat a counter")
        if self.staff_available is not None and self.staff_available > n:
            raise ValueError("staff_available cannot exceed num_counters")
        closed_at_start = set(self.standby_counters)
        if self.staff_available is not None:
            closed_at_start |= set(range(self.staff_available, n))
        if closed_at_start & set(self.initial_busy_counters):
            raise ValueError("a counter that starts closed cannot also start busy")
        peak = max([1.0] + [s.multiplier for s in (self.arrival_profile or [])])
        if self.arrival_rate * self.duration * peak + self.initial_queue > TWIN_MAX_EXPECTED_ARRIVALS:
            raise ValueError(
                f"Too large for the Digital Twin: expected customers exceed {TWIN_MAX_EXPECTED_ARRIVALS:,}; "
                "shorten the duration or lower the arrival rate"
            )
        return self

    @property
    def congestion_threshold(self) -> int:
        return self.congestion_queue if self.congestion_queue is not None else max(5, 2 * self.num_counters)

    @property
    def frame_dt(self) -> float:
        dt = self.sample_interval if self.sample_interval is not None else self.duration / 240.0
        return max(dt, self.duration / MAX_FRAMES)


def _r(x: float, nd: int = 4) -> float:
    return round(float(x), nd)


class TwinSimulation(QueueSimulation):
    """QueueSimulation plus availability, chaos, recovery and playback recording."""

    config: TwinConfig

    # ------------------------------------------------------------------ state
    def reset(self) -> None:
        if not self.config.record_trace:  # the twin always needs the per-customer trace for playback
            self.config = self.config.model_copy(update={"record_trace": True})
        super().reset()
        cfg = self.config
        n = cfg.num_counters
        self.closed_reasons: dict[int, set[str]] = {i: set() for i in range(n)}
        self.offline_now: set[int] = set()
        self._mark = [0.0] * n
        self.closed_time = [0.0] * n
        self.failed_time = [0.0] * n
        self.boost = 1.0
        self.log: list[dict[str, Any]] = []
        self._frames: list[dict[str, Any]] = []
        self._outage_seq = 0
        self._last_recovery = -math.inf
        self.activations_done = 0
        self.boost_applied = False

        for i in cfg.standby_counters:
            self._close(i, "standby")
        if cfg.staff_available is not None:
            for i in range(cfg.staff_available, n):
                self._close(i, "no_staff")
        for i in cfg.initial_busy_counters:
            self._remove_idle(i)
            self.busy_since[i] = 0.0

    # ------------------------------------------------------- counter availability
    def _remove_idle(self, idx: int) -> bool:
        items = self.idle_counters.items
        if idx not in items:
            return False
        items.remove(idx)
        heapq.heapify(items)  # harmless for a plain list, required if the store is a PriorityStore
        return True

    def _accrue(self, idx: int) -> None:
        now = self.env.now
        dt = now - self._mark[idx]
        if dt > 0:
            reasons = self.closed_reasons[idx]
            if reasons & set(CLOSED_REASONS):
                self.closed_time[idx] += dt
            elif reasons:
                self.failed_time[idx] += dt
        self._mark[idx] = now

    def _close(self, idx: int, reason: str) -> None:
        self._accrue(idx)
        self.closed_reasons[idx].add(reason)
        if idx not in self.offline_now and self.busy_since[idx] is None and self._remove_idle(idx):
            self.offline_now.add(idx)

    def _open(self, idx: int, *reasons: str) -> bool:
        """Remove the given closing reasons; returns True if the counter is now fully available."""
        self._accrue(idx)
        for r in reasons:
            self.closed_reasons[idx].discard(r)
        if self.closed_reasons[idx]:
            return False
        if idx in self.offline_now:
            self.offline_now.discard(idx)
            self.idle_counters.put(idx)
        return True

    def _release(self, counter: int):
        """Called when a counter finishes a customer: it returns to the pool unless it has been closed."""
        if self.closed_reasons[counter]:
            self.offline_now.add(counter)
        else:
            yield self.idle_counters.put(counter)

    def _event(self, kind: str, **detail: Any) -> None:
        self.log.append({"t": _r(self.env.now), "type": kind, **detail})

    # -------------------------------------------------------------- service speed
    def _effective_factor(self, counter: int) -> float:
        now = self.env.now
        f = self.factors[counter] * self.boost
        for sc in self.config.speed_changes:
            if (sc.counter is None or sc.counter == counter) and sc.start <= now and (sc.end is None or now < sc.end):
                f *= sc.factor
        return f

    def _sample_service(self, counter: int) -> float:
        base = super()._sample_service(counter)  # raw sample divided by the nominal factor
        return base * self.factors[counter] / self._effective_factor(counter)

    # ------------------------------------------------------------------ processes
    def _customer(self, cid: int):
        env, cfg = self.env, self.config
        arrival = env.now
        self.arrivals += 1
        self._waiting_since[cid] = arrival
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
        self.trace[cid].update(service_start_time=env.now, counter_index=counter)
        yield env.timeout(service)
        self.busy_time[counter] += service
        self.busy_since[counter] = None
        self.served_by[counter] += 1
        self.service_times.append(service)
        self.trace[cid]["service_end_time"] = env.now
        yield from self._release(counter)

    def _residual_service(self, counter: int):
        """A customer already at the counter when the twin starts (their arrival is before t=0)."""
        service = self._sample_service(counter)
        yield self.env.timeout(service)
        self.busy_time[counter] += service
        self.busy_since[counter] = None
        yield from self._release(counter)

    def _twin_arrivals(self):
        cid = self.config.initial_queue
        while True:
            yield self.env.timeout(self._next_gap())
            cid += 1
            self.env.process(self._customer(cid))

    def _outage_process(self, o: CounterOutage):
        self._outage_seq += 1
        reason = f"failure:{self._outage_seq}"
        if o.start > 0:
            yield self.env.timeout(o.start)
        self._close(o.counter, reason)
        self._event("counter_failure" if o.kind == "failure" else "counter_outage", counter=o.counter,
                    scheduled_end=o.end)
        if o.end is None:
            return
        yield self.env.timeout(o.end - o.start)
        self._open(o.counter, reason)
        self._event("counter_repaired", counter=o.counter)

    def _apply_action(self, a: ScheduledAction, source: str):
        if a.type == "activate_counter":
            was_closed = bool(self.closed_reasons[a.counter] & set(CLOSED_REASONS))
            fully_open = self._open(a.counter, *CLOSED_REASONS)
            if was_closed:
                self.activations_done += 1
            note = None
            if not was_closed:
                note = "counter was already open"
            elif not fully_open:
                note = "counter reopened but is still failed"
            self._event("recovery_action", action=a.type, counter=a.counter, source=source,
                        applied=was_closed, note=note)
        elif a.type == "deactivate_counter":
            self._close(a.counter, "standby")
            self._event("recovery_action", action=a.type, counter=a.counter, source=source, applied=True)
        else:
            self.boost *= a.factor
            self.boost_applied = True
            self._event("recovery_action", action=a.type, factor=a.factor, source=source, applied=True)
            if a.duration is not None:
                yield self.env.timeout(a.duration)
                self.boost /= a.factor
                self._event("recovery_action", action="boost_ended", factor=a.factor, source=source, applied=True)

    def _action_process(self, a: ScheduledAction):
        if a.at > 0:
            yield self.env.timeout(a.at)
        yield from self._apply_action(a, "manual")

    def _controller(self):
        pol = self.config.recovery
        breach_since: float | None = None
        while True:
            yield self.env.timeout(pol.check_interval)
            now = self.env.now
            if self.queue_len >= pol.queue_threshold:
                breach_since = now if breach_since is None else breach_since
            else:
                breach_since = None
                continue
            if now - breach_since < pol.sustain or now - self._last_recovery < pol.cooldown:
                continue
            closable = [i for i in range(self.config.num_counters)
                        if self.closed_reasons[i] and not any(r.startswith("failure") for r in self.closed_reasons[i])]
            if closable and self.activations_done < pol.max_activations:
                idx = closable[0]
                self._last_recovery = now
                self._event("recovery_trigger", queue=self.queue_len, threshold=pol.queue_threshold)
                yield from self._apply_action(ScheduledAction(type="activate_counter", at=0, counter=idx), "auto")
            elif pol.boost_factor > 1.0 and not self.boost_applied:
                self._last_recovery = now
                self._event("recovery_trigger", queue=self.queue_len, threshold=pol.queue_threshold)
                self.boost *= pol.boost_factor
                self.boost_applied = True
                self._event("recovery_action", action="boost_speed", factor=pol.boost_factor, source="auto",
                            applied=True)

    def _frame(self) -> dict[str, Any]:
        n = self.config.num_counters
        states = []
        for i in range(n):
            if self.busy_since[i] is not None:
                states.append(STATE_BUSY)
            elif self.closed_reasons[i]:
                failed = any(r.startswith("failure") for r in self.closed_reasons[i])
                states.append(STATE_FAILED if failed else STATE_CLOSED)
            else:
                states.append(STATE_IDLE)
        now = self.env.now
        longest = max((now - t for t in self._waiting_since.values()), default=0.0)
        return {
            "t": _r(now), "queue": self.queue_len, "in_service": sum(1 for b in self.busy_since if b is not None),
            "arrivals": self.arrivals - self.config.initial_queue, "served": sum(self.served_by),
            "abandoned": self.abandoned, "longest_wait": _r(longest), "counters": states,
        }

    def _sampler(self):
        dt, horizon = self.config.frame_dt, self.config.duration
        while True:
            self._frames.append(self._frame())
            if self.env.now + dt > horizon + 1e-9:
                return
            yield self.env.timeout(dt)

    # ------------------------------------------------------------------------ run
    def run(self) -> dict:
        if self._has_run:
            self.reset()
        cfg, env = self.config, self.env
        for i in range(cfg.initial_queue):
            env.process(self._customer(i + 1))
        for idx in cfg.initial_busy_counters:
            env.process(self._residual_service(idx))
        env.process(self._twin_arrivals())
        env.process(self._sampler())
        for o in cfg.outages:
            env.process(self._outage_process(o))
        for a in cfg.actions:
            env.process(self._action_process(a))
        if cfg.recovery is not None and cfg.recovery.enabled:
            env.process(self._controller())
        env.run(until=cfg.duration)
        self._has_run = True
        return self._collect_twin()

    # ------------------------------------------------------------------ results
    def _collect_twin(self) -> dict[str, Any]:
        cfg, horizon = self.config, self.config.duration
        for i in range(cfg.num_counters):
            self._accrue(i)
        if not self._frames or self._frames[-1]["t"] < _r(self.env.now):
            self._frames.append(self._frame())
        res = super()._collect()
        trace = res.pop("trace", [])
        hours = horizon / 60.0

        waits = np.asarray(self.waits, dtype=float)
        censored = np.asarray([horizon - t for t in self._waiting_since.values()], dtype=float)
        all_waits = np.concatenate([waits, censored]) if censored.size else waits
        res["p95_waiting_time_incl_waiting"] = _r(np.percentile(all_waits, 95), 6) if all_waits.size else 0.0

        counters = []
        cost = 0.0
        util_avail = []
        for c in res["counters"]:
            i = c["counter_index"]
            available = max(horizon - self.closed_time[i] - self.failed_time[i], 1e-9)
            u = min(1.0, c["busy_time"] / available)
            open_hours = (horizon - self.closed_time[i]) / 60.0
            cost += open_hours * cfg.cost_per_counter_hour
            counters.append({
                **c, "name": f"Counter {i + 1}", "closed_time": _r(self.closed_time[i]),
                "failed_time": _r(self.failed_time[i]), "available_time": _r(available),
                "utilization_available": _r(u),
                "state_at_end": STATE_NAMES[self._frames[-1]["counters"][i]],
            })
            if available > 1e-6:
                util_avail.append(u)
        res["counters"] = counters
        if (cfg.outages or cfg.speed_changes or cfg.standby_counters or cfg.staff_available is not None
                or cfg.actions or cfg.recovery or cfg.initial_queue or cfg.initial_busy_counters):
            res["theoretical"] = {"applicable": False, "model": None,
                                  "note": "Closed-form queueing results do not cover this twin configuration"}
        res["avg_waiting_time_incl_waiting"] = _r(all_waits.mean(), 6) if all_waits.size else 0.0
        res["avg_utilization_available"] = _r(sum(util_avail) / len(util_avail)) if util_avail else 0.0
        res["resource_cost"] = _r(cost, 4)
        res["counter_hours_open"] = _r(sum((horizon - t) for t in self.closed_time) / 60.0, 4)
        res["new_arrivals"] = self.arrivals - cfg.initial_queue
        res["initial_queue"] = cfg.initial_queue
        res["frames"] = self._frames
        res["events"] = sorted(self.log, key=lambda e: e["t"])
        res["customers"] = [
            [t["customer"], _r(t["arrival_time"]),
             None if t["service_start_time"] is None else _r(t["service_start_time"]),
             None if t["service_end_time"] is None else _r(t["service_end_time"]),
             t["counter_index"], None if t["abandon_time"] is None else _r(t["abandon_time"])]
            for t in trace
        ]
        res["episodes"] = detect_episodes(res["frames"], trace, cfg, res["events"])
        res["hours"] = _r(hours, 6)
        return res


# ---------------------------------------------------------------- episode detection
def _episodes(frames: list[dict], up: int, down: int, min_len: float) -> list[tuple[float, float, int]]:
    """Hysteresis episodes where `queue >= up` until it falls to `<= down`. Returns (start, end, peak)."""
    out: list[tuple[float, float, int]] = []
    start: float | None = None
    peak = 0
    for f in frames:
        q = f["queue"]
        if start is None:
            if q >= up:
                start, peak = f["t"], q
        else:
            peak = max(peak, q)
            if q <= down:
                if f["t"] - start >= min_len:
                    out.append((start, f["t"], peak))
                start = None
    if start is not None and frames and frames[-1]["t"] - start >= min_len:
        out.append((start, frames[-1]["t"], peak))
    return out


def _busy_fraction(trace: list[dict], counter: int, a: float, b: float) -> float:
    span = max(b - a, 1e-9)
    tot = 0.0
    for t in trace:
        if t["counter_index"] != counter or t["service_start_time"] is None:
            continue
        s = t["service_start_time"]
        e = t["service_end_time"] if t["service_end_time"] is not None else b
        tot += max(0.0, min(e, b) - max(s, a))
    return min(1.0, tot / span)


def detect_episodes(frames: list[dict], trace: list[dict], cfg: TwinConfig, events: list[dict]) -> dict[str, Any]:
    """Queue-formation and bottleneck episodes, with the overloaded counter taken from the trace."""
    dt = cfg.frame_dt
    form_q = max(2, cfg.num_counters)
    cong_q = cfg.congestion_threshold
    formation = [{"start": s, "end": e, "peak_queue": p} for s, e, p in _episodes(frames, form_q, 1, 0.0)]
    bottlenecks = []
    for s, e, p in _episodes(frames, cong_q, max(1, cong_q // 2), max(dt, 1.0)):
        busy = [(_busy_fraction(trace, i, s, e), i) for i in range(cfg.num_counters)]
        top_u, top_i = max(busy)
        failed: set[int] = set()
        for ev in events:
            if ev["type"] in ("counter_failure", "counter_outage") and ev["t"] <= e:
                repaired = any(r["type"] == "counter_repaired" and r["counter"] == ev["counter"]
                               and ev["t"] < r["t"] <= s for r in events)
                if not repaired:
                    failed.add(ev["counter"])
        closed = set(cfg.standby_counters) | (
            set(range(cfg.staff_available, cfg.num_counters)) if cfg.staff_available is not None else set())
        for ev in events:
            if ev["type"] == "recovery_action" and ev.get("action") == "activate_counter" and ev.get("applied") \
                    and ev["t"] <= s:
                closed.discard(ev["counter"])
        down, closed_at_start = sorted(failed), sorted(closed)
        in_window = [f for f in frames if s <= f["t"] <= e]
        avail_counters = round(float(np.mean([sum(1 for c in f["counters"] if c in (STATE_IDLE, STATE_BUSY))
                                              for f in in_window])), 3) if in_window else None
        bottlenecks.append({
            "start": s, "end": e, "peak_queue": p, "most_loaded_counter": top_i,
            "most_loaded_utilization": _r(top_u), "failed_counters": down, "closed_counters": closed_at_start,
            "avg_counters_available": avail_counters, "threshold": cong_q,
        })
    return {"formation": formation, "bottlenecks": bottlenecks, "formation_threshold": form_q,
            "congestion_threshold": cong_q}


# ------------------------------------------------------------------- public API
def _summary(res: dict[str, Any]) -> dict[str, float]:
    return {
        "avg_waiting_time": res["avg_waiting_time"], "p95_waiting_time": res["p95_waiting_time_incl_waiting"],
        "max_queue_length": res["max_queue_length"], "total_served": res["total_served"],
        "abandoned": res["abandoned"], "abandonment_rate": res["abandonment_rate"],
        "avg_utilization_available": res["avg_utilization_available"], "resource_cost": res["resource_cost"],
        "avg_queue_length": res["avg_queue_length"], "throughput": res["throughput"],
    }


def run_twin(config: TwinConfig, detail: bool = True) -> dict[str, Any]:
    """One run. `detail=False` drops the heavy playback payload (frames, customers, events)."""
    res = TwinSimulation(config).run()
    res["summary"] = _summary(res)
    if not detail:
        for k in ("customers", "events", "episodes"):
            res.pop(k, None)
    return res


def _stat(values: list[float]) -> dict[str, Any]:
    a = np.asarray(values, dtype=float)
    n = len(a)
    out: dict[str, Any] = {"mean": _r(a.mean(), 6), "min": _r(a.min(), 6), "max": _r(a.max(), 6), "n": n,
                           "std": _r(a.std(ddof=1), 6) if n > 1 else None, "ci95": None}
    if n > 1:
        from scipy.stats import t as student_t
        half = float(student_t.ppf(0.975, n - 1) * a.std(ddof=1) / math.sqrt(n))
        out["ci95"] = _r(half, 6)
    return out


def run_replications(config: TwinConfig, replications: int, base_seed: int,
                     detail_first: bool = True, keep_frames: bool = False) -> dict[str, Any]:
    """Run `replications` independent seeds (base_seed, base_seed+1, ...) - the same seeds for every scenario, so
    scenarios can be compared with common random numbers. The first replication carries the playback payload."""
    runs: list[dict[str, Any]] = []
    for r in range(replications):
        cfg = config.model_copy(update={"seed": base_seed + r})
        runs.append(run_twin(cfg, detail=(detail_first and r == 0)))
    summaries = [x["summary"] for x in runs]
    stats = {k: _stat([s[k] for s in summaries]) for k in SUMMARY_KEYS}
    counters = []
    for i in range(config.num_counters):
        counters.append({
            "counter_index": i, "name": f"Counter {i + 1}",
            "utilization_available": _r(np.mean([x["counters"][i]["utilization_available"] for x in runs]), 4),
            "served": _r(np.mean([x["counters"][i]["served"] for x in runs]), 2),
            "closed_time": _r(np.mean([x["counters"][i]["closed_time"] for x in runs]), 3),
            "failed_time": _r(np.mean([x["counters"][i]["failed_time"] for x in runs]), 3),
        })
    out = {
        "replications": replications, "base_seed": base_seed, "stats": stats,
        "summary": {k: stats[k]["mean"] for k in SUMMARY_KEYS}, "counters": counters,
        "per_replication": summaries,
        "primary": runs[0] if detail_first else None,
    }
    if keep_frames:
        out["all_runs"] = runs
    return out
