"""Optional Gemini integration for Digital Twin explanations.

Safety properties (enforced here and covered by tests):
  * The key is read from the backend environment (`GEMINI_API_KEY`) and is never logged or returned.
  * Gemini only receives aggregated simulation facts computed by the backend. It never receives customer rows.
  * Gemini cannot introduce metrics: any number in its answer that is not present in the facts causes the answer
    to be discarded and the deterministic explanation to be returned instead.
  * Any failure (no key, network error, HTTP error, empty answer) falls back to the deterministic explanation.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

import httpx

from app.core.config import get_settings
from app.engines import twin_explain as tx

logger = logging.getLogger("linezero.gemini")
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

Generator = Callable[[str], str]


class GeminiError(Exception):
    pass


def is_configured() -> bool:
    return bool((get_settings().gemini_api_key or "").strip())


def status() -> dict[str, Any]:
    s = get_settings()
    return {"configured": is_configured(), "model": s.gemini_model if is_configured() else None}


def generate(prompt: str) -> str:
    s = get_settings()
    key = (s.gemini_api_key or "").strip()
    if not key:
        raise GeminiError("GEMINI_API_KEY is not set")
    try:
        r = httpx.post(
            ENDPOINT.format(model=s.gemini_model),
            headers={"x-goog-api-key": key, "Content-Type": "application/json"},
            json={"contents": [{"parts": [{"text": prompt}]}],
                  "generationConfig": {"temperature": 0.2, "maxOutputTokens": 500}},
            timeout=s.gemini_timeout_s,
        )
    except httpx.HTTPError as exc:  # message never contains the key (it is sent in a header)
        raise GeminiError(f"Could not reach Gemini ({type(exc).__name__})") from None
    if r.status_code != 200:
        raise GeminiError(f"Gemini returned HTTP {r.status_code}")
    try:
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, ValueError, TypeError):
        raise GeminiError("Gemini returned an unexpected response") from None
    if not str(text).strip():
        raise GeminiError("Gemini returned an empty answer")
    return str(text).strip()


def explain(kind: str, facts: dict[str, Any], question: str | None = None,
            generator: Generator | None = None) -> dict[str, Any]:
    """Return an explanation grounded in `facts`. `generator` is injectable for tests."""
    if kind not in tx.KINDS:
        raise ValueError(f"kind must be one of {list(tx.KINDS)}")
    deterministic = tx.explain_deterministic(kind, facts)
    configured = generator is not None or is_configured()
    out: dict[str, Any] = {
        "kind": kind, "text": deterministic, "source": "deterministic", "deterministic_text": deterministic,
        "facts": facts, "gemini": {"configured": configured, "used": False, "model": status()["model"],
                                   "rejected_reason": None, "error": None},
    }
    if not configured:
        return out
    try:
        text = (generator or generate)(tx.build_prompt(kind, facts, question))
    except GeminiError as exc:
        out["gemini"]["error"] = str(exc)
        return out
    bad = tx.unsupported_numbers(text, facts, question or "")
    if bad:
        out["gemini"]["rejected_reason"] = ("Gemini's answer contained numbers that are not in the simulation facts "
                                            f"({', '.join(bad[:5])}), so it was discarded.")
        logger.warning("Gemini answer rejected: unsupported numbers %s", bad[:5])
        return out
    out.update(text=text, source="gemini")
    out["gemini"]["used"] = True
    return out
