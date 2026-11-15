"""Shared vocabulary and loop logic for LineZero's autonomous operations-intelligence layer.

The closed loop is

    observe -> calibrate -> detect risk -> propose interventions -> operator approval -> outcome -> recalibrate

This module holds the pure pieces that every stage shares: data-provenance labelling (so observed, synthetic,
simulated, predicted and explained values are never confused), time helpers and the loop-stage summary.
Nothing here touches the database or the network.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

from app.engines import prediction_engine as pe

LOOP_STAGES = [
    ("observe", "Operational data"),
    ("calibrate", "Self-learning digital twin"),
    ("detect", "Predictive risk detection"),
    ("propose", "Intervention engine"),
    ("approve", "Human-approved recovery"),
    ("evaluate", "Outcome evaluation"),
    ("recalibrate", "Model recalibration"),
]

DATA_KINDS = {
    "observed": "Measured from the queue database (customers, counters, timestamps).",
    "synthetic": "Generated demonstration data labelled is_synthetic; never real-world measurements.",
    "simulated": "Produced by running the SimPy digital twin; a what-if state, not an observation.",
    "predicted": "A model estimate (queueing formula, calibration or forecast) with stated uncertainty.",
    "explanation": "Deterministic text assembled from the numbers above; no generative AI is used by these modules.",
}


def provenance(queue_is_synthetic: bool) -> dict[str, Any]:
    """Describe where a response's observations came from. Attach to every adaptive-intelligence response."""
    return {
        "observations": "synthetic_demo_data" if queue_is_synthetic else "observed_real_data",
        "is_synthetic": bool(queue_is_synthetic),
        "notice": ("This queue holds SYNTHETIC demonstration data. Calibration, risks and intervention outcomes below "
                   "are computed on it for demonstration and are NOT real-world observations or verified results."
                   if queue_is_synthetic else None),
        "legend": DATA_KINDS,
        "explanations": "deterministic_template",
    }


def epoch_to_dt(seconds: float | None) -> datetime | None:
    return None if seconds is None else datetime.fromtimestamp(float(seconds), tz=timezone.utc)


def dt_to_epoch(dt: datetime | None) -> float | None:
    if dt is None:
        return None
    ts = pd.Timestamp(dt)
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    return float((ts - pe.EPOCH).total_seconds())


def loop_status(
    *, n_served: int, active_version: int | None, drift_detected: bool | None, open_risks: int, proposals_pending: int,
    approved_waiting_apply: int, applied_waiting_outcome: int, outcomes_recorded: int,
) -> list[dict[str, Any]]:
    """One line per loop stage so the UI can show where the closed loop currently stands. Counts only; no judgement."""
    return [
        {"stage": "observe", "label": dict(LOOP_STAGES)["observe"], "metric": n_served, "unit": "served customers observed"},
        {"stage": "calibrate", "label": dict(LOOP_STAGES)["calibrate"],
         "metric": active_version, "unit": "active calibration version", "attention": bool(drift_detected)},
        {"stage": "detect", "label": dict(LOOP_STAGES)["detect"], "metric": open_risks, "unit": "open risk events",
         "attention": open_risks > 0},
        {"stage": "propose", "label": dict(LOOP_STAGES)["propose"], "metric": proposals_pending,
         "unit": "proposals awaiting a decision", "attention": proposals_pending > 0},
        {"stage": "approve", "label": dict(LOOP_STAGES)["approve"], "metric": approved_waiting_apply,
         "unit": "approved, not yet applied by an operator", "attention": approved_waiting_apply > 0},
        {"stage": "evaluate", "label": dict(LOOP_STAGES)["evaluate"], "metric": applied_waiting_outcome,
         "unit": "applied, outcome not yet recorded", "attention": applied_waiting_outcome > 0},
        {"stage": "recalibrate", "label": dict(LOOP_STAGES)["recalibrate"], "metric": outcomes_recorded,
         "unit": "outcomes recorded"},
    ]


__all__ = ["provenance", "loop_status", "epoch_to_dt", "dt_to_epoch", "DATA_KINDS", "LOOP_STAGES"]
