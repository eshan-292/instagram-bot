#!/usr/bin/env python3
"""Gemini API helper with automatic model rotation to avoid rate limits.

Free tier gives 20 RPM per model. By rotating across multiple models,
we get 100+ effective RPM without paying anything.
"""

from __future__ import annotations

import logging
import random
from typing import Any

log = logging.getLogger(__name__)

# Models to rotate through (all free-tier eligible, fast for text generation)
_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-2.5-flash-lite",
    "gemini-3-flash-preview",
]

_client: Any = None
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
    Returns the generated text, or None on failure.
    """
    global _model_idx
    client = _get_client(api_key)

    # Build model list: preferred first, then rotating through others
    models = list(_MODELS)
    if preferred_model and preferred_model in models:
        models.remove(preferred_model)
        models.insert(0, preferred_model)
    elif preferred_model:
        models.insert(0, preferred_model)

    for model in models:
        try:
            response = client.models.generate_content(model=model, contents=prompt)
            text = (response.text or "").strip().strip('"').strip("'")
            if text:
                return text
        except Exception as exc:
            exc_str = str(exc)
            if "429" in exc_str or "RESOURCE_EXHAUSTED" in exc_str:
                log.debug("Rate limited on %s, trying next model", model)
                continue
            log.warning("Gemini generation failed on %s: %s", model, exc)
            return None

    log.warning("All Gemini models rate limited")
    return None
