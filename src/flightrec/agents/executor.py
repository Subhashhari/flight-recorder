"""execute(): one PolicyDesk run (live | replay | branch | chaos), recorded and flushed in one transaction."""

from __future__ import annotations

import asyncio
import datetime as dt
import os
import re
import time
import uuid
from dataclasses import asdict, dataclass, field

from google.adk.agents.run_config import RunConfig
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from flightrec.agents.pipeline import build_pipeline
from flightrec.agents.prompts import BUDGET_APOLOGY, get_prompts
from flightrec.agents.tools import get_tools
from flightrec.config import is_fake, settings
from flightrec.recorder.callbacks import Recorder
from flightrec.recorder.core import ReplayMiss, RunContext, _current
from flightrec.recorder.ratelimit import QuotaExhausted

# Rate-limit match (spike (f)): the google-genai ClientError text for HTTP 429 contains "429 RESOURCE_EXHAUSTED".
RATE_LIMIT_RE = re.compile(r"429|RESOURCE_EXHAUSTED|quota", re.I)
RETRY_WAITS = (30, 60, 120)
APP = "policydesk"


@dataclass
class RunResult:
    run_id: str
    status: str
    final_answer: str | None
    mode: str
    user_query: str
    employee_id: str
    label: str | None = None
    case_id: str | None = None
    fault: str | None = None
    parent_run_id: str | None = None
    branch_seq: int | None = None
    events: list = field(default_factory=list)
    totals: dict = field(default_factory=dict)
    config: dict = field(default_factory=dict)
    error: str | None = None
    started_at: str | None = None
    ended_at: str | None = None

    def row(self) -> dict:
        d = asdict(self)
        d.pop("events")
        d.pop("error")
        return d


def _chain(exc: BaseException):
    seen, stack = set(), [exc]
    while stack:
        e = stack.pop()
        if e is None or id(e) in seen:
            continue
        seen.add(id(e))
        yield e
        stack += [e.__cause__, e.__context__]
        stack += list(getattr(e, "exceptions", []) or [])


def find_exc(exc: BaseException, cls) -> BaseException | None:
    return next((e for e in _chain(exc) if isinstance(e, cls)), None)


def is_rate_limit(exc: BaseException) -> bool:
    return any(RATE_LIMIT_RE.search(f"{type(e).__name__} {e}") for e in _chain(exc)
               if not isinstance(e, QuotaExhausted))


def is_budget(exc: BaseException) -> bool:
    return any(type(e).__name__ == "LlmCallsLimitExceededError" for e in _chain(exc))


def compute_totals(ctx: RunContext, wall_ms: float, outputs: dict) -> dict:
    llm = [e for e in ctx.events if e["type"] == "llm_call"]
    tools = [e for e in ctx.events if e["type"] == "tool_call"]
    return {
        "tokens_in": sum(e.get("tokens_in") or 0 for e in llm),
        "tokens_out": sum(e.get("tokens_out") or 0 for e in llm),
        "cost_list_usd": round(sum(float(e.get("cost_list_usd") or 0) for e in llm if not e["replayed"]), 6),
        "latency_ms": int(max(0.0, wall_ms - ctx.throttle_ms)),
        "throttle_ms": int(ctx.throttle_ms),
        "llm_calls": len(llm),
        "api_calls": sum(1 for e in llm if not e["replayed"]),
        "tool_calls": len(tools),
        "recorder_self_ms": round(ctx.self_ms, 3),
        "divergences": sum(1 for e in ctx.events if e["type"] == "divergence"),
        "outputs": outputs,
    }


async def _run_once(ctx, *, rec, prompts, model, temperature, tools, query, employee_id, max_calls) -> dict:
    pipeline = build_pipeline(rec, prompts, model, temperature, tools)
    svc = InMemorySessionService()
    runner = Runner(agent=pipeline, app_name=APP, session_service=svc)
    session = await svc.create_session(app_name=APP, user_id=employee_id)
    msg = types.Content(role="user", parts=[types.Part(text=f"[{employee_id}] {query}")])
    async for _ in runner.run_async(user_id=employee_id, session_id=session.id, new_message=msg,
                                    run_config=RunConfig(max_llm_calls=max_calls)):
        pass
    sess = await svc.get_session(app_name=APP, user_id=employee_id, session_id=session.id)
    return {k: sess.state.get(k) for k in ("plan", "evidence", "action_result", "draft", "final")}


async def execute(query: str | None, employee_id: str | None, *, mode: str = "live", label: str | None = None,
                  case_id: str | None = None, source_run_id: str | None = None, branch_seq: int | None = None,
                  overrides: dict | None = None, fault: str | None = None, record: bool = True,
                  prompt_version: str | None = None, model: str | None = None, temperature: float | None = None,
                  source_run: dict | None = None, source_events: list | None = None, tools: dict | None = None,
                  limiter=None, chunk_sampler=None, retry_waits=RETRY_WAITS, max_llm_calls: int | None = None,
                  save=None) -> RunResult:
    from flightrec.recorder import store
    s = settings()
    overrides = overrides or {}
    if mode in ("replay", "branch"):
        source_run = source_run or store.get_run(source_run_id)
        if source_run is None:
            raise SystemExit(f"run {source_run_id} not found")
        source_run_id = source_run["run_id"]
        if source_events is None:
            source_events = store.get_events(source_run_id)
        scfg = source_run["config"]
        model = model or scfg["agent_model"]
        prompt_version = prompt_version or scfg.get("prompt_version", "v1")
        temperature = scfg.get("temperature", 0.0) if temperature is None else temperature
        query = query or source_run["user_query"]
        employee_id = employee_id or source_run["employee_id"]
        case_id = case_id or source_run.get("case_id")
        fault = fault or source_run.get("fault")
        if mode == "branch" and branch_seq is None:
            raise ValueError("branch needs branch_seq")
        if not os.environ.get("GOOGLE_API_KEY"):
            os.environ["GOOGLE_API_KEY"] = "dummy"  # cached calls never reach the API (spike g)
    if mode == "chaos" and not fault:
        raise ValueError("chaos mode needs a fault")
    model = model or s.agent_model
    prompt_version = prompt_version or s.prompt_version
    temperature = 0.0 if temperature is None else temperature
    max_calls = max_llm_calls or s.max_llm_calls_per_run
    if model in ("", "TBD") or model is None:
        raise SystemExit("AGENT_MODEL is not set: run scripts/model_probe.py (Phase 0)")
    if is_fake(model):
        from flightrec.testing.fake_llm import register
        register()
    prompts = get_prompts(prompt_version)
    tools = tools or get_tools(prompt_version)
    if limiter is None:
        from flightrec.runtime import limiter as _lim
        limiter = _lim()
    if chunk_sampler is None:
        from flightrec.corpus.search import sample_other_chunks
        chunk_sampler = sample_other_chunks
    rec = Recorder(limiter, chunk_sampler)
    run_id = str(uuid.uuid4())
    config = {"agent_model": model, "judge_model": s.judge_model, "embed_model": s.embed_model,
              "temperature": temperature, "prompt_version": prompt_version, "overrides": overrides,
              "tier": s.scale_tier, "max_llm_calls": max_calls, "source_run_id": source_run_id}
    started = dt.datetime.now(dt.UTC)
    status, final, error, outputs, ctx = "crash", None, None, {}, None
    quota_exc: QuotaExhausted | None = None
    attempts = len(retry_waits) + 1
    t_start = time.perf_counter()
    for attempt in range(attempts):
        ctx = RunContext(run_id=run_id, mode=mode, source_events=source_events or [], branch_seq=branch_seq,
                         overrides=overrides if mode == "branch" else {},
                         fault={"name": fault} if (mode == "chaos" and fault) else None,
                         case_seed=case_id or run_id)
        token = _current.set(ctx)
        t_start = time.perf_counter()
        try:
            outputs = await _run_once(ctx, rec=rec, prompts=prompts, model=model, temperature=temperature,
                                      tools=tools, query=query, employee_id=employee_id, max_calls=max_calls)
            final = outputs.get("final")
            status = "diverged" if any(e["type"] == "divergence" for e in ctx.events) else "ok"
            error = None
            break
        except Exception as exc:  # noqa: BLE001 - never raise out of eval/chaos (except QuotaExhausted)
            q = find_exc(exc, QuotaExhausted)
            if q is not None:
                status, error, quota_exc = "paused", str(q), q
                break
            if find_exc(exc, ReplayMiss) is not None:
                status, error = "diverged", str(find_exc(exc, ReplayMiss))
                break
            if is_budget(exc):
                status, error = "budget_exceeded", f"max_llm_calls={max_calls} exceeded"
                final = BUDGET_APOLOGY if prompt_version == "v2" else None  # v2 hardening #5
                break
            if is_rate_limit(exc) and not is_fake(model):
                if attempt < attempts - 1:
                    await asyncio.sleep(retry_waits[attempt])
                    continue
                status, error = "rate_limited", f"{type(exc).__name__}: {str(exc)[:500]}"
                break
            status, error = "crash", f"{type(exc).__name__}: {str(exc)[:1000]}"
            break
        finally:
            _current.reset(token)
    wall_ms = (time.perf_counter() - t_start) * 1000
    ctx.events.sort(key=lambda e: e["seq"])
    if error:
        outputs = {**outputs, "error": error}
    res = RunResult(run_id=run_id, status=status, final_answer=final, mode=mode, user_query=query,
                    employee_id=employee_id, label=label, case_id=case_id, fault=fault,
                    parent_run_id=source_run_id if mode in ("replay", "branch") else None,
                    branch_seq=branch_seq if mode == "branch" else None, events=ctx.events,
                    totals=compute_totals(ctx, wall_ms, outputs), config=config, error=error,
                    started_at=started.isoformat(), ended_at=dt.datetime.now(dt.UTC).isoformat())
    if record:
        (save or store.save_run)(res.row(), res.events)
    if quota_exc is not None:
        raise quota_exc
    return res
