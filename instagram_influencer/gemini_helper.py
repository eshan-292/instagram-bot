#!/usr/bin/env python3
"""Gemini API helper with automatic model rotation to avoid rate limits.

Free tier gives limited RPM per model. By rotating across multiple models,
we get higher effective RPM without paying anything.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any

log = logging.getLogger(__name__)

# Models to rotate through — ordered by preference (best → fallback).
# Free tier limits vary by model. Rotating avoids hitting any single limit.
_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-3-flash",
]

_client: Any = None
# Track which model to start with next (round-robin across calls)
_model_idx: int = 0


def _get_client(api_key: str) -> Any:
    global _client
    if _client is None:
        from google import genai
        _client = genai.Client(api_key=api_key)
    return _client


def generate(api_key: str, prompt: str, preferred_model: str | None = None) -> str | None:
    """Generate text with automatic model rotation on rate limit.

    Tries the preferred model first, then rotates through alternatives.
    On rate limits (429), waits briefly and tries the next model.
    Returns the generated text, or None on failure.
    """
    global _model_idx
    client = _get_client(api_key)

    # Build model list: preferred first, then round-robin through others
    models = list(_MODELS)
    if preferred_model and preferred_model in models:
        models.remove(preferred_model)
        models.insert(0, preferred_model)
    elif preferred_model:
        models.insert(0, preferred_model)
    else:
        # Round-robin: start from where we left off last time
        models = models[_model_idx:] + models[:_model_idx]

    rate_limited_count = 0
    for i, model in enumerate(models):
        try:
            response = client.models.generate_content(model=model, contents=prompt)
            text = (response.text or "").strip().strip('"').strip("'")
            if text:
                # Advance round-robin for next call
                _model_idx = (_model_idx + 1) % len(_MODELS)
                return text
        except Exception as exc:
            exc_str = str(exc)
            if "429" in exc_str or "RESOURCE_EXHAUSTED" in exc_str or "quota" in exc_str.lower():
                rate_limited_count += 1
                log.debug("Rate limited on %s, trying next model", model)
                # Brief wait before trying next model (prevents rapid-fire 429s)
                if i < len(models) - 1:
                    time.sleep(random.uniform(1, 3))
                continue
            if "not found" in exc_str.lower() or "404" in exc_str:
                log.debug("Model %s not available, skipping", model)
                continue
            log.warning("Gemini generation failed on %s: %s", model, exc)
            continue

    if rate_limited_count == len(models):
        log.warning("All %d Gemini models rate limited, waiting 10s before giving up", len(models))
        time.sleep(10)
        # One last attempt with a random model
        try:
            fallback = random.choice(_MODELS)
            response = client.models.generate_content(model=fallback, contents=prompt)
            text = (response.text or "").strip().strip('"').strip("'")
            if text:
                return text
        except Exception:
            pass

    log.warning("All Gemini models exhausted (rate_limited=%d)", rate_limited_count)
    return None
