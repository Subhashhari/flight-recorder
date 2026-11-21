"""Replay and branch (guide 5.3).

replay: every LLM/tool call is served from the source run's event with the same (agent, kind, ordinal); a changed
request hash emits a `divergence` event but the cached response is still served (status `diverged`). Zero API calls.
branch(N): events with seq < N from cache; from N on LLM calls are live (overrides applied) and tools execute.
The cache decision itself lives in RunContext.from_cache / Recorder callbacks.
"""

from __future__ import annotations

from flightrec.agents.executor import RunResult, execute

ALLOWED_OVERRIDES = {"model", "temperature", "instruction_append"}


def parse_overrides(sets: list[str] | None, appends: list[str] | None) -> dict:
    o: dict = {}
    for s in sets or []:
        k, _, v = s.partition("=")
        k = k.strip()
        if k not in ("model", "temperature"):
            raise ValueError(f"--set supports model and temperature, not {k!r}")
        o[k] = float(v) if k == "temperature" else v.strip()
    for a in appends or []:
        agent, _, txt = a.partition("=")
        o.setdefault("instruction_append", {})[agent.strip()] = txt.strip().strip('"')
    return o


async def replay(run_id: str, *, label: str | None = None, record: bool = True, **kw) -> RunResult:
    return await execute(None, None, mode="replay", source_run_id=run_id, label=label, record=record, **kw)


async def branch(run_id: str, step: int, overrides: dict | None = None, *, label: str | None = None,
                 record: bool = True, **kw) -> RunResult:
    bad = set(overrides or {}) - ALLOWED_OVERRIDES
    if bad:
        raise ValueError(f"unsupported overrides {bad}")
    return await execute(None, None, mode="branch", source_run_id=run_id, branch_seq=step, overrides=overrides,
                         label=label, record=record, **kw)


def tool_sequence(events: list[dict]) -> list[tuple]:
    import json
    return [(e["name"], json.dumps((e.get("request") or {}).get("args", {}), sort_keys=True))
            for e in sorted(events, key=lambda e: e["seq"]) if e["type"] == "tool_call"]


def same_outcome(a_events, a_final, b_events, b_final) -> bool:
    return tool_sequence(a_events) == tool_sequence(b_events) and (a_final or "").strip() == (b_final or "").strip()
