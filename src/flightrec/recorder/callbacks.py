"""ADK callbacks (the only ADK-aware recorder file).

before_* either serve a cached/faulted result (and record it) or register a `pending` entry; after_* record the
real result if a `pending` entry exists. Both are idempotent, so the recorder is correct whether or not ADK calls
after_* for a short-circuited call.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from google.adk.models import LlmResponse

from flightrec.recorder import faults
from flightrec.recorder.core import (
    ReplayMiss,
    _current,
    add_event,
    estimate_tokens,
    jsonable,
    request_hash,
)
from flightrec.recorder.pricing import list_cost


def _system_text(si) -> str:
    if si is None:
        return ""
    if isinstance(si, str):
        return si
    if isinstance(si, list):
        return "\n".join(_system_text(x) for x in si)
    parts = getattr(si, "parts", None)
    if parts is not None:
        return "\n".join(p.text or "" for p in parts)
    return str(si)


def serialize_request(llm_request) -> dict:
    cfg = llm_request.config
    return {
        "model": llm_request.model,
        "system": _system_text(cfg.system_instruction if cfg else None),
        "contents": [c.model_dump(mode="json", exclude_none=True) for c in (llm_request.contents or [])],
        "tools": sorted((llm_request.tools_dict or {}).keys()),
        "temperature": getattr(cfg, "temperature", None) if cfg else None,
    }


def apply_overrides(ctx, agent: str, seq: int, llm_request) -> None:
    """Branch only, seq >= branch_seq: model, temperature, instruction_append {agent: text}."""
    if ctx.mode != "branch" or not ctx.overrides:
        return
    o = ctx.overrides
    if o.get("model"):
        llm_request.model = o["model"]
    if o.get("temperature") is not None and llm_request.config is not None:
        llm_request.config.temperature = float(o["temperature"])
    extra = (o.get("instruction_append") or {}).get(agent)
    if extra and llm_request.config is not None:
        base = _system_text(llm_request.config.system_instruction)
        llm_request.config.system_instruction = f"{base}\n\n{extra}" if base else extra


class Recorder:
    def __init__(self, limiter, chunk_sampler: Callable | None = None):
        self.limiter = limiter
        self.chunk_sampler = chunk_sampler

    def callbacks(self) -> dict:
        return dict(before_model_callback=self.before_model, after_model_callback=self.after_model,
                    before_tool_callback=self.before_tool, after_tool_callback=self.after_tool)

    # ------------------------------------------------------------------ model
    def before_model(self, callback_context, llm_request):
        ctx = _current.get()
        if ctx is None:
            return None
        t0 = time.perf_counter()
        agent = callback_context.agent_name
        ordinal = ctx.next_ordinal(agent, "llm")
        seq = ctx.seq
        ctx.seq += 1
        if ctx.from_cache(seq):
            req = serialize_request(llm_request)
            h = request_hash(req["model"], req["system"], req["contents"], req["tools"])
            src = ctx.find_source(agent, "llm_call", ordinal)
            if src:
                if ctx.mode == "replay" and src.get("request_hash") != h:
                    add_event(ctx, "divergence", agent, request=req, error="request_hash_mismatch",
                              name=f"llm_call#{ordinal}")
                add_event(ctx, "llm_call", agent, seq=seq, ordinal=ordinal, request=req, response=src["response"],
                          request_hash=h, replayed=True, latency_ms=0, tokens_in=src.get("tokens_in"),
                          tokens_out=src.get("tokens_out"), cost_list_usd=0.0, name=req["model"])
                ctx.self_ms += (time.perf_counter() - t0) * 1000
                return LlmResponse.model_validate(src["response"])
            if ctx.mode == "replay":
                add_event(ctx, "divergence", agent, request=req, error="no_cached_response", name=f"llm_call#{ordinal}")
                raise ReplayMiss(f"no cached llm_call for {agent} #{ordinal}")
        apply_overrides(ctx, agent, seq, llm_request)  # branch only, seq >= branch_seq
        req = serialize_request(llm_request)
        h = request_hash(req["model"], req["system"], req["contents"], req["tools"])
        t1 = time.perf_counter()
        waited = self.limiter.acquire(llm_request.model, estimate_tokens(req))
        ctx.throttle_ms += waited * 1000
        ctx.pending[(agent, "llm")] = dict(seq=seq, ordinal=ordinal, req=req, hash=h, t=time.perf_counter())
        ctx.self_ms += (time.perf_counter() - t0) * 1000 - (time.perf_counter() - t1) * 1000
        return None

    def after_model(self, callback_context, llm_response):
        ctx = _current.get()
        if ctx is None:
            return None
        p = ctx.pending.pop((callback_context.agent_name, "llm"), None)
        if p is None:
            return None  # already recorded in before_model (cache path)
        t0 = time.perf_counter()
        u = llm_response.usage_metadata
        tin, tout = ((u.prompt_token_count or 0), (u.candidates_token_count or 0)) if u else (0, 0)
        add_event(ctx, "llm_call", callback_context.agent_name, seq=p["seq"], ordinal=p["ordinal"],
                  request=p["req"], response=llm_response.model_dump(mode="json", exclude_none=True),
                  request_hash=p["hash"], latency_ms=int((t0 - p["t"]) * 1000),
                  tokens_in=tin, tokens_out=tout, cost_list_usd=list_cost(p["req"]["model"], tin, tout),
                  name=p["req"]["model"], error=llm_response.error_message)
        ctx.self_ms += (time.perf_counter() - t0) * 1000
        return None

    # ------------------------------------------------------------------ tools
    @staticmethod
    def _tool_key(agent, tool_context, name):
        return (agent, "tool", getattr(tool_context, "function_call_id", None) or name)

    def before_tool(self, tool, args, tool_context):
        ctx = _current.get()
        if ctx is None:
            return None
        t0 = time.perf_counter()
        agent = tool_context.agent_name
        name = tool.name
        ordinal = ctx.next_ordinal(agent, "tool")
        seq = ctx.seq
        ctx.seq += 1
        req = {"name": name, "args": jsonable(dict(args or {}))}
        h = request_hash(name, "", [req], [])
        if ctx.from_cache(seq):
            src = ctx.find_source(agent, "tool_call", ordinal)
            if src:
                if ctx.mode == "replay" and src.get("request_hash") != h:
                    add_event(ctx, "divergence", agent, request=req, error="request_hash_mismatch",
                              name=f"{name}#{ordinal}")
                add_event(ctx, "tool_call", agent, seq=seq, ordinal=ordinal, name=name, request=req,
                          response=src["response"], request_hash=h, replayed=True, latency_ms=0,
                          fault=src.get("fault"))
                ctx.self_ms += (time.perf_counter() - t0) * 1000
                return jsonable(src["response"])
            if ctx.mode == "replay":
                add_event(ctx, "divergence", agent, request=req, error="no_cached_response", name=f"{name}#{ordinal}")
                raise ReplayMiss(f"no cached tool_call for {agent} #{ordinal}")
        pre = faults.pre_tool_fault(ctx, name)
        if pre:
            fname, resp, sim_latency = pre
            add_event(ctx, "tool_call", agent, seq=seq, ordinal=ordinal, name=name, request=req, response=resp,
                      request_hash=h, latency_ms=sim_latency or 0, fault=fname)
            ctx.self_ms += (time.perf_counter() - t0) * 1000
            return resp
        ctx.pending[self._tool_key(agent, tool_context, name)] = dict(seq=seq, ordinal=ordinal, req=req, hash=h,
                                                                      t=time.perf_counter())
        ctx.self_ms += (time.perf_counter() - t0) * 1000
        return None

    def after_tool(self, tool, args, tool_context, tool_response):
        ctx = _current.get()
        if ctx is None:
            return None
        agent = tool_context.agent_name
        p = ctx.pending.pop(self._tool_key(agent, tool_context, tool.name), None)
        if p is None:
            return None
        t0 = time.perf_counter()
        resp = jsonable(tool_response if isinstance(tool_response, dict) else {"result": tool_response})
        post = faults.post_tool_fault(ctx, tool.name, resp, self.chunk_sampler)
        req = p["req"]
        fault_name, out = (post if post else (None, resp))
        if post:
            req = {**req, "_original_response": resp}
        add_event(ctx, "tool_call", agent, seq=p["seq"], ordinal=p["ordinal"], name=tool.name, request=req,
                  response=out, request_hash=p["hash"], latency_ms=int((t0 - p["t"]) * 1000), fault=fault_name,
                  error=out.get("error") if isinstance(out, dict) and isinstance(out.get("error"), str) else None)
        ctx.self_ms += (time.perf_counter() - t0) * 1000
        return out if post else None
