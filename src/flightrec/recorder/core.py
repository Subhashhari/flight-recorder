"""Framework-agnostic recorder core: run context, event buffer, request hashing, cache lookup."""

from __future__ import annotations

import contextvars
import datetime as dt
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

_current: contextvars.ContextVar[RunContext | None] = contextvars.ContextVar("flightrec_run", default=None)

# Keys stripped before hashing: they are generated per call (function-call ids, thought signatures) and would make
# a faithful replay look like a divergence.
_VOLATILE_KEYS = {"id", "thought_signature", "thoughtSignature", "thought"}


class ReplayMiss(Exception):
    """Replay mode needed a cached response that the source run does not have."""


@dataclass
class RunContext:
    run_id: str
    mode: str  # live | replay | branch | chaos
    seq: int = 0
    ordinals: dict = field(default_factory=dict)
    pending: dict = field(default_factory=dict)
    events: list = field(default_factory=list)  # buffered; flushed once at run end
    source_events: list = field(default_factory=list)
    branch_seq: int | None = None
    overrides: dict = field(default_factory=dict)
    fault: dict | None = None
    fault_fired: bool = False
    self_ms: float = 0.0
    throttle_ms: float = 0.0
    case_seed: str = ""
    _source_index: dict | None = None

    def next_ordinal(self, agent, kind):
        k = (agent, kind)
        n = self.ordinals.get(k, 0)
        self.ordinals[k] = n + 1
        return n

    def from_cache(self, seq: int) -> bool:
        if self.mode == "replay":
            return True
        return self.mode == "branch" and self.branch_seq is not None and seq < self.branch_seq

    def find_source(self, agent: str, etype: str, ordinal: int) -> dict | None:
        if self._source_index is None:
            self._source_index = {(e["agent"], e["type"], e["ordinal"]): e for e in self.source_events}
        return self._source_index.get((agent, etype, ordinal))


def current() -> RunContext | None:
    return _current.get()


def _strip(o: Any) -> Any:
    if isinstance(o, dict):
        return {k: _strip(v) for k, v in o.items() if k not in _VOLATILE_KEYS}
    if isinstance(o, list):
        return [_strip(v) for v in o]
    return o


def request_hash(model, system, contents, tool_names) -> str:
    blob = json.dumps({"m": model, "s": system, "c": _strip(contents), "t": sorted(tool_names)},
                      sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def estimate_tokens(req: dict) -> int:
    return int(len(json.dumps([req.get("contents"), req.get("system")], default=str)) / 4) + 512


def jsonable(o: Any) -> Any:
    return json.loads(json.dumps(o, default=str))


def add_event(ctx: RunContext, etype: str, agent: str, *, seq: int | None = None, ordinal: int | None = None,
              **fields) -> dict:
    if seq is None:
        seq = ctx.seq
        ctx.seq += 1
    if ordinal is None:
        ordinal = ctx.next_ordinal(agent, etype)
    ev = {"seq": seq, "ordinal": ordinal, "type": etype, "agent": agent, "name": fields.pop("name", None),
          "request": fields.pop("request", None), "response": fields.pop("response", None),
          "request_hash": fields.pop("request_hash", None), "latency_ms": fields.pop("latency_ms", None),
          "tokens_in": fields.pop("tokens_in", None), "tokens_out": fields.pop("tokens_out", None),
          "cost_list_usd": fields.pop("cost_list_usd", None), "replayed": bool(fields.pop("replayed", False)),
          "fault": fields.pop("fault", None), "error": fields.pop("error", None),
          "ts": dt.datetime.now(dt.UTC).isoformat()}
    if fields:
        raise TypeError(f"unknown event fields {sorted(fields)}")
    ctx.events.append(ev)
    return ev
