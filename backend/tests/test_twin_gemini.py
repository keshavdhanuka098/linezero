"""Gemini integration is optional and cannot introduce metrics."""
import json

import pytest

from app.core.config import get_settings
from app.services import gemini_service as gs

FACTS = {"kind": "simulation", "scenario": {"peak_arrival_multiplier": 1.0, "arrival_rate_per_min": 1.2,
                                            "num_counters": 3, "slowdowns": []},
         "summary": {"avg_waiting_time": 4.37, "p95_waiting_time": 9.0, "max_queue_length": 12.0},
         "bottlenecks": [], "counters": [{"name": "Counter 3", "utilization_while_open": 0.97, "served": 30,
                                          "failed_minutes": 0, "closed_minutes": 0}]}


@pytest.fixture
def no_key(monkeypatch):
    monkeypatch.setattr(get_settings(), "gemini_api_key", None)


@pytest.fixture
def with_key(monkeypatch):
    monkeypatch.setattr(get_settings(), "gemini_api_key", "SECRET-TEST-KEY")


def test_works_without_api_key(no_key):
    out = gs.explain("congestion", FACTS)
    assert out["source"] == "deterministic" and out["text"] and out["gemini"]["configured"] is False


def test_grounded_gemini_answer_is_used(with_key):
    out = gs.explain("counter", FACTS, generator=lambda p: "The queue reached 12 and the average wait was 4.4 minutes.")
    assert out["source"] == "gemini" and out["gemini"]["used"] is True


def test_fabricated_metric_is_rejected_and_falls_back(with_key):
    out = gs.explain("counter", FACTS, generator=lambda p: "The average wait was 9.8 minutes at 55 percent load.")
    assert out["source"] == "deterministic" and "not in the simulation facts" in out["gemini"]["rejected_reason"]


def test_gemini_errors_fall_back_and_key_never_leaks(with_key):
    def boom(_):
        raise gs.GeminiError("Gemini returned HTTP 429")

    out = gs.explain("counter", FACTS, generator=boom)
    assert out["source"] == "deterministic" and out["gemini"]["error"]
    assert "SECRET-TEST-KEY" not in json.dumps(out) and "SECRET-TEST-KEY" not in json.dumps(gs.status())


def test_unknown_kind_is_rejected():
    with pytest.raises(ValueError):
        gs.explain("nope", FACTS)
