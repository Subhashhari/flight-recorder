"""Direct (non-agent) Gemini calls for the judge, corpus and case generation. Always through the limiter."""

from __future__ import annotations

import json
import time

from pydantic import BaseModel

from flightrec.config import is_fake

RETRY_WAITS = (30, 60, 120)


def _call(model: str, contents, config):
    from flightrec.agents.executor import is_rate_limit, is_transient
    from flightrec.runtime import genai_client, limiter
    est = int(len(json.dumps(contents, default=str)) / 4) + 512 + int(len(str(getattr(config, "system_instruction", "") or "")) / 4)
    for attempt in range(len(RETRY_WAITS) + 1):
        limiter().acquire(model, est)
        try:
            return genai_client().models.generate_content(model=model, contents=contents, config=config)
        except Exception as e:  # noqa: BLE001
            if (is_rate_limit(e) or is_transient(e)) and attempt < len(RETRY_WAITS):
                time.sleep(RETRY_WAITS[attempt])
                continue
            raise


def generate_text(model: str, prompt: str, *, system: str | None = None, temperature: float = 0.7) -> str:
    if is_fake(model):
        return f"(fake {model} output for: {prompt[:60]})"
    from google.genai import types
    r = _call(model, prompt, types.GenerateContentConfig(system_instruction=system, temperature=temperature))
    return r.text or ""


def generate_json(model: str, prompt: str, schema: type[BaseModel], *, system: str | None = None,
                  temperature: float = 0.0) -> dict:
    from google.genai import types
    r = _call(model, prompt, types.GenerateContentConfig(system_instruction=system, temperature=temperature,
                                                         response_mime_type="application/json",
                                                         response_schema=schema))
    if getattr(r, "parsed", None) is not None:
        p = r.parsed
        return p.model_dump() if isinstance(p, BaseModel) else (p if isinstance(p, dict) else {"items": p})
    return schema.model_validate_json(r.text).model_dump()
