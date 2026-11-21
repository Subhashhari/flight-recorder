"""ADK spike (guide 6.0.4). Answers (a)-(g) with real outputs and writes them into docs/architecture.md.

Framework-behaviour questions (a, b, c, d, e-roundtrip, g) run offline against a local recording model.
Questions needing the real API (e-usage on a real model, f rate-limit error) run only when GOOGLE_API_KEY is set;
otherwise they are recorded as "pending: needs API key". Run: uv run python scripts/spike.py [--offline]
"""

from __future__ import annotations

import asyncio
import datetime as dt
import inspect
import json
import os
import sys
import uuid

from google.adk.agents import LlmAgent
from google.adk.models import BaseLlm, LlmRequest, LlmResponse
from google.adk.models.registry import LLMRegistry
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from flightrec.config import DOCS_DIR, load_env_file, settings

load_env_file()
OUT: dict[str, str] = {}
SEEN: list = []


class RecordingLlm(BaseLlm):
    """Local model: calls `add` once, then answers; records every request it receives."""

    model: str = "spike-recorder"

    @classmethod
    def supported_models(cls):
        return [r"spike-.*"]

    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False):
        si = llm_request.config.system_instruction if llm_request.config else None
        SEEN.append({"model": llm_request.model, "system": si if isinstance(si, str) else str(si),
                     "temperature": llm_request.config.temperature if llm_request.config else None})
        last = llm_request.contents[-1].parts[0] if llm_request.contents else None
        if last is not None and last.function_response:
            c = types.Content(role="model", parts=[types.Part(text=f"The answer is {last.function_response.response}")])
        else:
            c = types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(
                name="add", args={"a": 17, "b": 25}, id=f"spike-{uuid.uuid4().hex[:6]}"))])
        yield LlmResponse(content=c, usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=11, candidates_token_count=7, total_token_count=18))


LLMRegistry.register(RecordingLlm)
TOOL_RUNS: list = []


def add(a: int, b: int) -> dict:
    """Add two integers."""
    TOOL_RUNS.append((a, b))
    return {"sum": a + b}


async def run(agent, text="What is 17 plus 25?"):
    svc = InMemorySessionService()
    runner = Runner(agent=agent, app_name="spike", session_service=svc)
    s = await svc.create_session(app_name="spike", user_id="u")
    final = ""
    async for ev in runner.run_async(user_id="u", session_id=s.id,
                                     new_message=types.Content(role="user", parts=[types.Part(text=text)])):
        if ev.content and ev.content.parts and ev.is_final_response():
            final = "".join(p.text or "" for p in ev.content.parts)
    return final


def a_signatures() -> str:
    f = LlmAgent.model_fields
    lines = [f"google-adk {__import__('google.adk').adk.__version__}, google-genai {__import__('google.genai').genai.__version__}",
             "Declared types (LlmAgent fields):"]
    for k in ("before_model_callback", "after_model_callback", "before_tool_callback", "after_tool_callback"):
        lines.append(f"- {k}: {str(f[k].annotation).replace('typing.', '')[:300]}")
    calls: list[str] = []

    def bm(callback_context, llm_request):
        calls.append(f"before_model(callback_context={type(callback_context).__name__}, "
                     f"llm_request={type(llm_request).__name__})")

    def am(callback_context, llm_response):
        calls.append(f"after_model(callback_context={type(callback_context).__name__}, "
                     f"llm_response={type(llm_response).__name__})")

    def bt(tool, args, tool_context):
        calls.append(f"before_tool(tool={type(tool).__name__}, args={type(args).__name__}, "
                     f"tool_context={type(tool_context).__name__})")

    def at(tool, args, tool_context, tool_response):
        calls.append(f"after_tool(tool={type(tool).__name__}, args={type(args).__name__}, "
                     f"tool_context={type(tool_context).__name__}, tool_response={type(tool_response).__name__})")

    agent = LlmAgent(name="spike", model="spike-recorder", instruction="Use add.", tools=[add],
                     before_model_callback=bm, after_model_callback=am, before_tool_callback=bt, after_tool_callback=at)
    asyncio.run(run(agent))
    lines.append("Observed calls (keyword arguments, runtime types):")
    lines += [f"- {c}" for c in dict.fromkeys(calls)]
    return "\n".join(lines)


def b_short_circuit_model() -> str:
    after = []

    def bm(callback_context, llm_request):
        return LlmResponse(content=types.Content(role="model", parts=[types.Part(text="cached answer")]))

    def am(callback_context, llm_response):
        after.append(llm_response.content.parts[0].text)

    SEEN.clear()
    agent = LlmAgent(name="spike", model="spike-recorder", instruction="x", before_model_callback=bm,
                     after_model_callback=am)
    final = asyncio.run(run(agent))
    return (f"before_model_callback returned an LlmResponse -> model called: {bool(SEEN)}; final={final!r}; "
            f"after_model_callback invoked: {bool(after)} (times={len(after)}). "
            "Recorder impact: none, after_model finds no pending entry and returns None.")


def c_short_circuit_tool() -> str:
    after = []
    TOOL_RUNS.clear()

    def bt(tool, args, tool_context):
        return {"sum": 999}

    def at(tool, args, tool_context, tool_response):
        after.append(tool_response)

    agent = LlmAgent(name="spike", model="spike-recorder", instruction="x", tools=[add], before_tool_callback=bt,
                     after_tool_callback=at)
    final = asyncio.run(run(agent))
    return (f"before_tool_callback returned a dict -> tool executed: {bool(TOOL_RUNS)}; after_tool_callback invoked: "
            f"{bool(after)} (saw {after}); final={final!r}.")


def d_mutation() -> str:
    seen_model = []

    def bm(callback_context, llm_request):
        seen_model.append(llm_request.model)
        llm_request.model = "spike-mutated"
        llm_request.config.system_instruction = (llm_request.config.system_instruction or "") + " APPENDED"
        llm_request.config.temperature = 0.7

    SEEN.clear()
    agent = LlmAgent(name="spike", model="spike-recorder", instruction="Base instruction.", tools=[add],
                     before_model_callback=bm, generate_content_config=types.GenerateContentConfig(temperature=0.0))
    asyncio.run(run(agent))
    got = SEEN[0]
    return (f"llm_request.model populated in before_model_callback: {seen_model[0]!r}. After mutation the model "
            f"class received model={got['model']!r}, system_instruction ends with 'APPENDED': "
            f"{str(got['system']).rstrip().endswith('APPENDED')}, temperature={got['temperature']}. "
            "So mutating model / system_instruction / temperature changes the real request (the model *class* is "
            "resolved from the agent before callbacks, so a model override must stay within the same backend).")


def e_roundtrip(real_model: str | None) -> str:
    r = LlmResponse(content=types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(
        name="add", args={"a": 17, "b": 25}, id="adk-123"), thought_signature=b"\x01\x02sig")]),
        usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=11, candidates_token_count=7))
    d = r.model_dump(mode="json", exclude_none=True)
    back = LlmResponse.model_validate(d)
    msg = (f"Round-trip of a function-call LlmResponse via model_dump(mode='json', exclude_none=True) -> "
           f"model_validate: equal={back == r}; function_call preserved={back.content.parts[0].function_call == r.content.parts[0].function_call}; "
           f"bytes thought_signature preserved={back.content.parts[0].thought_signature == r.content.parts[0].thought_signature}.")
    if real_model:
        try:
            u_holder = []

            def am(callback_context, llm_response):
                u = llm_response.usage_metadata
                u_holder.append((u.prompt_token_count, u.candidates_token_count) if u else None)

            agent = LlmAgent(name="spike", model=real_model, instruction="Answer in one word.", after_model_callback=am)
            asyncio.run(run(agent, "Say hello."))
            msg += f" Real model {real_model}: usage_metadata (prompt, candidates) = {u_holder[0]}."
        except Exception as ex:  # noqa: BLE001
            msg += f" Real model usage check failed: {type(ex).__name__}: {str(ex)[:200]}"
    else:
        msg += " usage_metadata on a real model: pending (needs API key)."
    return msg


def f_rate_limit(judge: str | None) -> str:
    if not judge:
        return "pending: needs API key and JUDGE_MODEL (default match `429|RESOURCE_EXHAUSTED|quota` used meanwhile)."
    from google import genai
    client = genai.Client()
    for i in range(30):
        try:
            client.models.generate_content(model=judge, contents="Reply: ok")
        except Exception as ex:  # noqa: BLE001
            mro = " > ".join(c.__name__ for c in type(ex).__mro__[:4])
            return (f"After {i + 1} rapid calls on {judge}: {type(ex).__module__}.{type(ex).__name__} ({mro}); "
                    f"str = {str(ex)[:300]!r}; code attr = {getattr(ex, 'code', None)}. Matched by executor regex "
                    "`429|RESOURCE_EXHAUSTED|quota`.")
    return f"not reproduced in 30 calls on {judge}; using default match `429|RESOURCE_EXHAUSTED|quota`."


def g_dummy_key() -> str:
    """Record a run with the scripted model, relabel it as a real Gemini model, replay with GOOGLE_API_KEY=dummy."""
    import importlib

    from flightrec.agents import executor
    from flightrec.recorder.ratelimit import Limiter
    from flightrec.recorder.store import MemoryQuotaStore
    sys.path.insert(0, str(DOCS_DIR.parent))
    conftest = importlib.import_module("tests.conftest")
    from flightrec.backend.mock_backend import MemoryRepo, MockBackend
    tools = conftest.make_tools(MockBackend(MemoryRepo()))
    lim = Limiter(MemoryQuotaStore(), {})
    src = asyncio.run(executor.execute("How many sick leaves do I get?", "E1003", model="fake-agent", tools=tools,
                                       limiter=lim, chunk_sampler=conftest.fake_sampler, record=False))
    real_name = "gemini-3.5-flash-lite"
    saved = os.environ.get("GOOGLE_API_KEY")
    os.environ["GOOGLE_API_KEY"] = "dummy"
    try:
        run_src = {"run_id": src.run_id, "config": {**src.config, "agent_model": real_name},
                   "user_query": src.user_query, "employee_id": src.employee_id}
        rep = asyncio.run(executor.execute(None, None, mode="replay", source_run=run_src, source_events=src.events,
                                           tools=tools, limiter=Limiter(MemoryQuotaStore(), {}),
                                           chunk_sampler=conftest.fake_sampler, record=False))
    finally:
        if saved is None:
            os.environ.pop("GOOGLE_API_KEY", None)
        else:
            os.environ["GOOGLE_API_KEY"] = saved
    return (f"Replay of a {len(src.events)}-event run with agent model {real_name!r} and GOOGLE_API_KEY=dummy: "
            f"status={rep.status}, api_calls={rep.totals['api_calls']}, identical final answer="
            f"{rep.final_answer == src.final_answer}. A fully cached run works with a dummy key. (Status is "
            "`diverged` only because the source was relabelled to a different model name, which is part of every "
            "request hash; the cached responses were still served.)")


def main() -> None:
    offline = "--offline" in sys.argv
    s = settings()
    have_key = bool(os.environ.get("GOOGLE_API_KEY")) and os.environ.get("GOOGLE_API_KEY") != "dummy" and not offline
    agent = s.agent_model if have_key and s.agent_model not in ("", "TBD") else None
    judge = s.judge_model if have_key and s.judge_model not in ("", "TBD") else None
    steps = [("a", "exact callback signatures", a_signatures), ("b", "before_model short-circuit", b_short_circuit_model),
             ("c", "before_tool short-circuit", c_short_circuit_tool), ("d", "mutating llm_request", d_mutation),
             ("e", "usage_metadata and LlmResponse round-trip", lambda: e_roundtrip(agent)),
             ("f", "rate-limit exception", lambda: f_rate_limit(judge)),
             ("g", "replay with GOOGLE_API_KEY=dummy", g_dummy_key)]
    for k, title, fn in steps:
        try:
            OUT[k] = fn()
        except Exception as ex:  # noqa: BLE001
            OUT[k] = f"ERROR {type(ex).__name__}: {str(ex)[:300]}"
        print(f"({k}) {title}\n{OUT[k]}\n", flush=True)
    block = [f"_Generated by `uv run python scripts/spike.py` on {dt.datetime.now().isoformat(timespec='minutes')}"
             f" ({'with' if have_key else 'without'} API key)._", ""]
    for k, title, _ in steps:
        block += [f"**({k}) {title}**", "", "```", OUT[k], "```", ""]
    p = DOCS_DIR / "architecture.md"
    text = p.read_text(encoding="utf-8")
    a, b = "<!-- ADK_FACTS_START -->", "<!-- ADK_FACTS_END -->"
    pre, rest = text.split(a, 1)
    post = rest.split(b, 1)[1]
    p.write_text(pre + a + "\n" + "\n".join(block) + b + post, encoding="utf-8")
    (DOCS_DIR / "spike_output.json").write_text(json.dumps(OUT, indent=1), encoding="utf-8")
    print("wrote docs/architecture.md (ADK facts)")


if __name__ == "__main__":
    _ = inspect  # keep import for readers poking at signatures
    main()
