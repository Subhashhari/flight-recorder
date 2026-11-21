"""Phase 0 model probe (guide 6.0.3): resolve model IDs, run probes P1-P8, choose Plan A/B automatically.

Writes AGENT_MODEL / JUDGE_MODEL / EMBED_MODEL / SCALE_TIER into .env (values edited in place, file never printed),
config/limits.yaml and docs/quota-log.md. Uses the raw client (no limiter) with a polite per-model pause.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path

import yaml
from pydantic import BaseModel

from flightrec.config import CONFIG_DIR, DOCS_DIR, ROOT, load_env_file

load_env_file()

CONSOLE = {  # console name -> (lowercase substring, rpm, tpm, rpd)
    "Gemma 4 31B": ("gemma-4-31b", 30, 16000, 14400),
    "Gemma 4 26B": ("gemma-4-26b", 30, 16000, 14400),
    "Gemini 3.5 Flash Lite": ("gemini-3.5-flash-lite", 15, 250000, 500),
    "Gemini 3.1 Flash Lite": ("gemini-3.1-flash-lite", 15, 250000, 500),
    "Gemini Embedding": ("embedding", 100, 30000, 1000),
}
PLAN_RE = re.compile(r"^needs_policy=(yes|no); needs_action=(yes|no); employee_id=E\d{4}; task=.+$")
P5_QUERIES = ["[E1003] How many sick leave days do I get per year?", "[E1012] What is my leave balance?",
              "[E1020] My laptop screen is cracked, please raise a ticket.",
              "[E1007] What's my meal limit, and file Rs 900 for dinner.", "[E1031] Can I work from home on Fridays?"]
P6_QUERIES = [("[E1003] What is my leave balance?", "get_leave_balance"),
              ("[E1012] My laptop keyboard is broken, please raise a hardware ticket.", "create_it_ticket"),
              ("[E1020] Who is Meera Iyer's manager?", "lookup_employee"),
              ("[E1007] File a meals expense of Rs 600 for a client lunch.", "submit_expense_claim"),
              ("[E1031] I need access to the finance shared drive, please open a ticket.", "create_it_ticket")]

_last: dict[str, float] = {}
LOG: list[str] = []


def say(msg: str) -> None:
    print(msg, flush=True)
    LOG.append(msg)


def pause(model: str, rpm: int) -> None:
    gap = 60 / rpm * 1.15
    dt_ = time.monotonic() - _last.get(model, 0)
    if dt_ < gap:
        time.sleep(gap - dt_)
    _last[model] = time.monotonic()


def resolve(names: list[str], sub: str) -> str | None:
    hits = [n for n in names if sub in n.lower()]
    if not hits:
        return None
    clean = [n for n in hits if not re.search(r"-(preview|exp)", n)] or hits
    choice = min(clean, key=len)
    if len(hits) > 1:
        say(f"  '{sub}' matched {hits}; chose {choice}")
    return choice


def err(e: Exception) -> str:
    return f"{type(e).__name__}: {str(e)[:200]}"


# ------------------------------------------------------------------ probes
def p1_p2_p4(client, model, rpm):
    from google.genai import types
    out = {}
    try:
        pause(model, rpm)
        r = client.models.generate_content(model=model, contents="Reply with the single word: ready")
        out["P1"] = bool(r.text and r.text.strip())
        u = r.usage_metadata
        out["P4"] = bool(u and (u.prompt_token_count or 0) > 0 and (u.candidates_token_count or 0) > 0)
    except Exception as e:  # noqa: BLE001
        out["P1"], out["P4"], out["P1_error"] = False, False, err(e)
    try:
        pause(model, rpm)
        r = client.models.generate_content(model=model, contents="What are you?", config=types.GenerateContentConfig(
            system_instruction="You are a terse assistant. Answer in at most five words."))
        out["P2"] = bool(r.text and r.text.strip())
    except Exception as e:  # noqa: BLE001
        out["P2"], out["P2_error"] = False, err(e)
    return out


async def _adk_run(agent, text, state=None):
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types
    svc = InMemorySessionService()
    runner = Runner(agent=agent, app_name="probe", session_service=svc)
    s = await svc.create_session(app_name="probe", user_id="u", state=state or {})
    final, calls = "", []
    async for ev in runner.run_async(user_id="u", session_id=s.id,
                                     new_message=types.Content(role="user", parts=[types.Part(text=text)])):
        for fc in ev.get_function_calls() or []:
            calls.append(fc.name)
        if ev.content and ev.content.parts and ev.is_final_response():
            final = "".join(p.text or "" for p in ev.content.parts)
    return final, calls


def p3(model, rpm):
    from google.adk.agents import LlmAgent
    executed = []

    def add(a: int, b: int) -> dict:
        """Add two integers and return the sum."""
        executed.append((a, b))
        return {"sum": a + b}

    def before(callback_context, llm_request):
        pause(model, rpm)

    try:
        agent = LlmAgent(name="calc", model=model, instruction="Use the add tool for arithmetic, then state the result.",
                         tools=[add], before_model_callback=before)
        final, _ = asyncio.run(_adk_run(agent, "What is 17 plus 25?"))
        return {"P3": bool(executed) and "42" in final}
    except Exception as e:  # noqa: BLE001
        return {"P3": False, "P3_error": err(e)}


def p5(client, model, rpm):
    from google.genai import types

    from flightrec.agents.prompts import PLANNER
    ok, samples = 0, []
    for q in P5_QUERIES:
        try:
            pause(model, rpm)
            r = client.models.generate_content(model=model, contents=q, config=types.GenerateContentConfig(
                system_instruction=PLANNER, temperature=0.0))
            line = (r.text or "").strip()
            samples.append(line[:160])
            ok += bool(PLAN_RE.match(line))
        except Exception as e:  # noqa: BLE001
            samples.append(err(e))
    return {"P5": ok >= 4, "P5_score": f"{ok}/5", "P5_samples": samples}


def p6(model, rpm):
    from google.adk.agents import LlmAgent

    from flightrec.agents.prompts import OPERATOR

    def lookup_employee(name: str) -> dict:
        """Look up an employee by name. Returns employee_id, name, grade, manager."""
        return {"employee_id": "E1009", "name": name, "grade": "L3", "manager": "Kabir Rao"}

    def get_leave_balance(employee_id: str) -> dict:
        """Get an employee's remaining leave balance in days."""
        return {"employee_id": employee_id, "casual": 4, "sick": 6, "earned": 12.5}

    def create_it_ticket(employee_id: str, category: str, description: str) -> dict:
        """Open an IT ticket. category is one of hardware, software, access, network."""
        return {"ticket_id": "IT-PROBE01", "status": "open"}

    def submit_expense_claim(employee_id: str, category: str, amount_inr: float, description: str) -> dict:
        """Submit an expense claim. category is one of meals, lodging, travel, equipment."""
        return {"claim_id": "EXP-PROBE01", "status": "submitted"}

    def before(callback_context, llm_request):
        pause(model, rpm)

    ok, got = 0, []
    for q, expected in P6_QUERIES:
        emp = q[1:6]
        plan = f"needs_policy=no; needs_action=yes; employee_id={emp}; task={q[8:]}"
        try:
            agent = LlmAgent(name="operator", model=model, instruction=OPERATOR, before_model_callback=before,
                             tools=[lookup_employee, get_leave_balance, create_it_ticket, submit_expense_claim])
            _, calls = asyncio.run(_adk_run(agent, q, state={"plan": plan}))
            got.append(calls)
            ok += expected in calls
        except Exception as e:  # noqa: BLE001
            got.append(err(e))
    return {"P6": ok >= 4, "P6_score": f"{ok}/5", "P6_calls": got}


class _J(BaseModel):
    correct: bool
    grounded: bool
    notes: str


def p7(client, model, rpm):
    from google.genai import types
    ok, errs = 0, []
    for i in range(5):
        try:
            pause(model, rpm)
            r = client.models.generate_content(
                model=model, contents=f"Gold answer: 10 days. Reply: 'You get {8 + i} days of sick leave.' Grade it.",
                config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=_J,
                                                   temperature=0.0))
            _J.model_validate_json(r.text)
            ok += 1
        except Exception as e:  # noqa: BLE001
            errs.append(err(e))
    return {"P7": ok == 5, "P7_score": f"{ok}/5", **({"P7_errors": errs[:2]} if errs else {})}


def p8(client, model, rpm):
    from google.genai import types
    try:
        pause(model, rpm)
        r = client.models.embed_content(model=model, contents=["sick leave policy"],
                                        config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY",
                                                                        output_dimensionality=768))
        n = len(r.embeddings[0].values)
        return {"P8": n == 768, "P8_dims": n}
    except Exception as e:  # noqa: BLE001
        return {"P8": False, "P8_error": err(e)}


# ------------------------------------------------------------------ writers
def set_env(values: dict) -> None:
    p = ROOT / ".env"
    lines = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
    seen = set()
    for i, line in enumerate(lines):
        k = line.split("=", 1)[0].strip()
        if k in values:
            lines[i] = f"{k}={values[k]}"
            seen.add(k)
    lines += [f"{k}={v}" for k, v in values.items() if k not in seen]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_limits(ids: dict) -> None:
    p = CONFIG_DIR / "limits.yaml"
    lines = ["# AI Studio rate-limit page, read 2026-11-18. tpm in tokens/minute.",
             f"# Model IDs resolved by scripts/model_probe.py on {dt.date.today().isoformat()}.",
             "# The limiter refuses any model not listed. fake-* are local test doubles (never reported)."]
    for console_name, mid in ids.items():
        if mid:
            _, rpm, tpm, rpd = CONSOLE[console_name]
            lines.append(f"{mid}: {{rpm: {rpm}, tpm: {tpm}, rpd: {rpd}}}   # {console_name}")
    lines += ["fake-agent: {rpm: 100000, tpm: 100000000, rpd: 100000000}",
              "fake-judge: {rpm: 100000, tpm: 100000000, rpd: 100000000}",
              "fake-embed: {rpm: 100000, tpm: 100000000, rpd: 100000000}"]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    yaml.safe_load(p.read_text(encoding="utf-8"))


def main() -> int:
    import os

    from google import genai
    if not os.environ.get("GOOGLE_API_KEY") or os.environ["GOOGLE_API_KEY"] == "dummy":
        say("GOOGLE_API_KEY is not set in .env; add your AI Studio key first (see README).")
        return 2
    client = genai.Client()
    names = sorted(m.name.removeprefix("models/") for m in client.models.list())
    say(f"{len(names)} models listed")
    ids = {}
    for console_name, (sub, *_rest) in CONSOLE.items():
        if console_name == "Gemini Embedding":
            continue
        ids[console_name] = resolve(names, sub)
    emb_candidates = (["gemini-embedding-001"] if "gemini-embedding-001" in names else []) + \
        [n for n in names if "embedding" in n and n != "gemini-embedding-001"]
    say("\n| Console name | Resolved ID |\n|---|---|")
    for k, v in ids.items():
        say(f"| {k} | {v or '(not found)'} |")
    say(f"| Gemini Embedding (candidates) | {', '.join(emb_candidates[:4]) or '(not found)'} |")

    results: dict[str, dict] = {}

    def agent_probes(name):
        mid, rpm = ids[name], CONSOLE[name][1]
        if not mid:
            return {"available": False}
        say(f"\nprobing {name} = {mid} (P1-P6)")
        r = p1_p2_p4(client, mid, rpm)
        if r.get("P1") and r.get("P2"):
            r |= p3(mid, rpm)
            r |= p5(client, mid, rpm) if r.get("P3") else {"P5": False}
            r |= p6(mid, rpm) if r.get("P3") else {"P6": False}
        r["passes_agent"] = all(r.get(f"P{i}") for i in range(1, 7))
        say(json.dumps(r, indent=1))
        return r

    def judge_probe(name):
        mid = ids[name]
        if not mid:
            return {"available": False, "P7": False}
        say(f"\nprobing {name} = {mid} (P7)")
        r = p7(client, mid, CONSOLE[name][1])
        say(json.dumps(r))
        return r

    agent = judge = tier = plan = None
    for g in ("Gemma 4 31B", "Gemma 4 26B"):
        results[g] = agent_probes(g)
        if results[g].get("passes_agent"):
            agent, plan, tier = ids[g], "A", "A_lite"
            break
    if plan == "A":
        results["Gemini 3.5 Flash Lite"] = judge_probe("Gemini 3.5 Flash Lite")
        if results["Gemini 3.5 Flash Lite"].get("P7"):
            judge = ids["Gemini 3.5 Flash Lite"]
        else:
            results["Gemini 3.1 Flash Lite"] = judge_probe("Gemini 3.1 Flash Lite")
            judge = ids["Gemini 3.1 Flash Lite"] if results["Gemini 3.1 Flash Lite"].get("P7") else None
    else:
        results["Gemini 3.5 Flash Lite"] = agent_probes("Gemini 3.5 Flash Lite")
        results["Gemini 3.1 Flash Lite"] = judge_probe("Gemini 3.1 Flash Lite")
        if results["Gemini 3.5 Flash Lite"].get("passes_agent") and results["Gemini 3.1 Flash Lite"].get("P7"):
            agent, judge, plan, tier = ids["Gemini 3.5 Flash Lite"], ids["Gemini 3.1 Flash Lite"], "B", "B_sprint"
    embed = None
    for cand in emb_candidates:
        r = p8(client, cand, 100)
        results[f"embedding:{cand}"] = r
        say(f"\nprobing embedding {cand} (P8): {json.dumps(r)}")
        if r.get("P8"):
            embed = cand
            break
    if not (agent and judge and embed):
        say(f"\nSTOP: a required probe failed for every option (agent={agent}, judge={judge}, embed={embed}). "
            "Nothing written. Paste this output into a chat for help.")
        return 1
    write_limits({k: v for k, v in {**ids, "Gemini Embedding": embed}.items() if v})
    set_env({"AGENT_MODEL": agent, "JUDGE_MODEL": judge, "EMBED_MODEL": embed, "SCALE_TIER": tier})
    say(f"\nDECISION: Plan {plan} · agent={agent} · judge={judge} · embed={embed} · tier={tier}")
    md = ["# Quota log", "", f"## Model probe ({dt.datetime.now().isoformat(timespec='minutes')})", "",
          "Console quotas (AI Studio rate-limit page, read 2026-11-18):", "",
          "| Console name | Resolved ID | RPM | TPM | RPD |", "|---|---|---|---|---|"]
    for k, (_s, rpm, tpm, rpd) in CONSOLE.items():
        md.append(f"| {k} | {embed if k == 'Gemini Embedding' else ids.get(k) or '(not found)'} | {rpm} | {tpm} | {rpd} |")
    md += ["", "### Probe results", "", "```json", json.dumps(results, indent=1), "```", "",
           f"**Decision (automatic):** Plan {plan} · agent `{agent}` · judge `{judge}` · embeddings `{embed}` · "
           f"tier `{tier}`", "", "## Per-day calls", "", "Dump with `uv run python scripts/quota_dump.py` "
           "(reads the `quota_usage` table).", ""]
    (DOCS_DIR / "quota-log.md").write_text("\n".join(md), encoding="utf-8")
    Path(DOCS_DIR / "probe_output.txt").write_text("\n".join(LOG) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
