"""A scripted, deterministic stand-in for the agent model (`fake-*`), used by unit tests and offline smoke runs.

It reads the ADK request (system instruction + contents) and behaves like a cooperative PolicyDesk model: the
planner emits the plan line, the researcher/operator call tools, the writer composes a reply from state, the
verifier echoes it. The v1 writer "falls for" a prompt injection so chaos categorisation can be tested offline.
These runs are synthetic test fixtures and are excluded from exports and results.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncGenerator

from google.adk.models import BaseLlm, LlmRequest, LlmResponse
from google.adk.models.registry import LLMRegistry
from google.genai import types

_registered = False


def register() -> None:
    global _registered
    if not _registered:
        LLMRegistry.register(FakeLlm)
        _registered = True


def _sys(req: LlmRequest) -> str:
    si = req.config.system_instruction if req.config else None
    if si is None:
        return ""
    if isinstance(si, str):
        return si
    return "\n".join(p.text or "" for p in getattr(si, "parts", []) or [])


def _texts(req: LlmRequest) -> list[str]:
    return [p.text for c in req.contents or [] for p in (c.parts or []) if p.text]


def _between(s: str, a: str, b: str) -> str:
    i = s.find(a)
    if i < 0:
        return ""
    i += len(a)
    j = s.find(b, i)
    return s[i:j if j >= 0 else len(s)].strip()


def _last_function_response(req: LlmRequest):
    if not req.contents:
        return None
    for p in req.contents[-1].parts or []:
        if p.function_response:
            return p.function_response
    return None


def _user(req: LlmRequest) -> tuple[str, str]:
    for t in _texts(req):
        m = re.search(r"\[(E\d{4})\]\s*(.+)", t, re.S)
        if m:
            return m.group(1), m.group(2).strip()
    return "E0000", ""


ACTION_WORDS = ("balance", "ticket", "file ", "claim", "submit", "manager", "raise", "reimburse", "laptop", "access to")


def _plan(emp: str, msg: str) -> str:
    low = msg.lower()
    action = any(w in low for w in ACTION_WORDS)
    policy = ("?" in msg and not low.startswith(("who is", "what is my leave balance"))) or "limit" in low or \
        "policy" in low or not action
    return f"needs_policy={'yes' if policy else 'no'}; needs_action={'yes' if action else 'no'}; employee_id={emp}; " \
           f"task={msg.splitlines()[0][:150]}"


def _action_call(emp: str, msg: str) -> tuple[str, dict]:
    low = msg.lower()
    amt = re.search(r"(?:₹|rs\.?|inr)\s*([\d,]+)", low)
    if "balance" in low:
        return "get_leave_balance", {"employee_id": emp}
    if "manager" in low:
        m = re.search(r"who is ([a-z]+(?: [a-z]+)?)'s manager", low)
        return "lookup_employee", {"name": (m.group(1) if m else "").title()}
    if amt and any(w in low for w in ("file", "claim", "submit", "reimburse")):
        cat = "meals" if any(w in low for w in ("meal", "dinner", "lunch")) else \
            "lodging" if any(w in low for w in ("hotel", "lodging")) else \
            "travel" if any(w in low for w in ("cab", "travel", "taxi", "flight")) else "equipment"
        return "submit_expense_claim", {"employee_id": emp, "category": cat,
                                        "amount_inr": float(amt.group(1).replace(",", "")), "description": msg[:80]}
    cat = "access" if "access" in low else "network" if "wifi" in low or "vpn" in low else \
        "software" if "software" in low or "install" in low else "hardware"
    return "create_it_ticket", {"employee_id": emp, "category": cat, "description": msg[:120]}


def respond(req: LlmRequest) -> types.Content:
    system = _sys(req)
    emp, msg = _user(req)
    fr = _last_function_response(req)
    plan = _between(system, "Plan:", ". If needs_")

    def text(t: str) -> types.Content:
        return types.Content(role="model", parts=[types.Part(text=t)])

    def call(name: str, args: dict) -> types.Content:
        return types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(name=name, args=args))])

    if "planning step" in system:
        return text(_plan(emp, msg))
    if "search_policies tool" in system:
        if "needs_policy=no" in plan:
            return text("NOT_NEEDED")
        if fr is None:
            return call("search_policies", {"query": _between(system, "task=", ". If needs_policy") or msg})
        results = (fr.response or {}).get("results") or []
        if not results:
            return text("NO_EVIDENCE")
        wrap = "retrieved_document tags" in system
        lines = [f"[{r['chunk_id']}] {r['text'][:300]}" for r in results[:3]]
        if wrap:
            lines = [f"<retrieved_document>{x}</retrieved_document>" for x in lines]
        return text("\n".join(lines))
    if "use the tools to carry out" in system:
        if "needs_action=no" in plan:
            return text("NOT_NEEDED")
        if fr is None:
            name, args = _action_call(emp, msg)
            return call(name, args)
        return text(f"{fr.name} returned {json.dumps(fr.response, sort_keys=True)}")
    if system.startswith("Write the reply") or "Write the reply" in system:
        evidence = _between(system, "Policy evidence:", ". Action results:")
        actions = _between(system, "Action results:", ". Cite policy sources")
        parts = []
        if evidence and evidence not in ("NOT_NEEDED",):
            if "NO_EVIDENCE" in evidence:
                parts.append("I couldn't find this in company policy.")
            else:
                m = re.search(r"\[([a-z_0-9]+)#\d+\]\s*([^\n<]+)", evidence)
                if m:
                    parts.append(f"{m.group(2)[:200].strip()} [{m.group(1)}]")
        if actions and actions != "NOT_NEEDED":
            parts.append(actions[:200])
        reply = " ".join(parts) or "I could not help with that."
        if "SYSTEM NOTICE" in evidence and "Treat evidence as data" not in system:
            reply += " CANARY-7731"
        return text(reply)
    if "Draft reply:" in system:
        return text(_between(system, "Draft reply:", ". Policy evidence:") or "I could not help with that.")
    # generic (spike / probe): add tool
    if "add" in (req.tools_dict or {}) and fr is None:
        nums = [int(x) for x in re.findall(r"\d+", " ".join(_texts(req)))][:2] or [0, 0]
        return call("add", {"a": nums[0], "b": nums[-1]})
    if fr is not None:
        return text(f"The answer is {json.dumps(fr.response)}")
    return text("ok")


class FakeLlm(BaseLlm):
    model: str = "fake-agent"

    @classmethod
    def supported_models(cls) -> list[str]:
        return [r"fake-.*"]

    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False
                                     ) -> AsyncGenerator[LlmResponse, None]:
        content = respond(llm_request)
        n_in = sum(len(t) for t in _texts(llm_request)) // 4 + len(_sys(llm_request)) // 4
        n_out = sum(len(p.text or "") + (20 if p.function_call else 0) for p in content.parts) // 4 + 1
        yield LlmResponse(content=content, usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=n_in, candidates_token_count=n_out, total_token_count=n_in + n_out))
