"""Process-wide singletons: the limiter (DB-backed daily counter) and the google-genai client."""

from __future__ import annotations

import os

from flightrec.config import load_limits
from flightrec.recorder.ratelimit import Limiter

_limiter: Limiter | None = None
_client = None


def limiter() -> Limiter:
    global _limiter
    if _limiter is None:
        from flightrec.recorder.store import DbQuotaStore
        _limiter = Limiter(DbQuotaStore(), load_limits())
    return _limiter


def set_limiter(lim: Limiter | None) -> None:
    global _limiter
    _limiter = lim


def genai_client():
    """google-genai client for the Gemini Developer API (AI Studio key, never Vertex)."""
    global _client
    if _client is None:
        from google import genai
        os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "FALSE")
        _client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY") or None)
    return _client
