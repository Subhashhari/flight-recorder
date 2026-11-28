"""`flightrec eval`: sequential, resumable, quota-aware clean evaluation."""

from __future__ import annotations

import asyncio
import datetime as dt
import time

from rich.console import Console

from flightrec.evals.cases import Case, load_cases
from flightrec.evals.judge import judge_clean
from flightrec.evals.metrics import (
    clean_failure_reason,
    clean_success,
    retrieval_metrics,
    retrieved_doc_ids,
    tool_calls,
    tool_match,
)
from flightrec.recorder import store
from flightrec.recorder.ratelimit import IST, PT, QuotaExhausted

console = Console()


def handle_quota(q: QuotaExhausted, wait: bool) -> bool:
    """Returns True if the caller should continue (after sleeping until the reset)."""
    when = q.resume_at.astimezone(IST).strftime("%Y-%m-%d %H:%M")
    if not wait:
        console.print(f"[yellow]quota exhausted for {q.model}; resume after {when} IST[/yellow]")
        return False
    secs = max(0.0, (q.resume_at - dt.datetime.now(PT)).total_seconds()) + 60
    console.print(f"[yellow]quota exhausted for {q.model}; sleeping {secs / 3600:.1f} h until {when} IST[/yellow]")
    time.sleep(secs)
    return True


JUDGE_OUTAGE_WAIT_S = 300   # between scoring attempts while the judge model is overloaded
JUDGE_OUTAGE_TRIES = 25     # 24 waits = 2 h; llm._call already retried 30/60/120 s inside each attempt


def score_patiently(score_fn, *args, wait_s: float = JUDGE_OUTAGE_WAIT_S, tries: int = JUDGE_OUTAGE_TRIES,
                    sleep=time.sleep):
    """Score a stored run; ride out judge outages instead of crashing the whole runner.

    A transient server error (503 "high demand", 5xx) or a per-minute 429 from the *judge* is not a property of the
    agent run, which is already saved. Wait and retry; if the judge stays down, return None and leave the run unscored:
    `--resume` re-scores unscored runs without re-running the agent. QuotaExhausted and any other error propagate.
    """
    from flightrec.agents.executor import is_rate_limit, is_transient
    for k in range(tries):
        try:
            return score_fn(*args)
        except QuotaExhausted:
            raise
        except Exception as e:  # noqa: BLE001
            if not (is_transient(e) or is_rate_limit(e)):
                raise
            if k == tries - 1:
                console.print(f"[yellow]judge still unavailable after {tries} attempts; run kept unscored "
                              f"(re-scored on --resume): {type(e).__name__}[/yellow]")
                return None
            console.print(f"[yellow]judge unavailable ({type(e).__name__}); retry {k + 1}/{tries - 1} in "
                          f"{wait_s / 60:.0f} min[/yellow]")
            sleep(wait_s)
    return None


def score_clean_run(case: Case, run: dict, events: list[dict]) -> dict:
    status, final = run["status"], run.get("final_answer")
    actual = tool_calls(events)
    tools_ok = tool_match([t.model_dump() for t in case.expected_tool_calls], actual)
    retr = retrieval_metrics(retrieved_doc_ids(events), case.gold_doc_ids)
    base = {"category": case.category, "tools_ok": tools_ok, "retrieved_doc_ids": retrieved_doc_ids(events), **retr,
            "status": status}
    if status in ("crash", "budget_exceeded") or not (final or "").strip():
        reason = "budget_exceeded" if status == "budget_exceeded" else "crash"
        metrics = {**base, "success": False}
        store.save_score(run["run_id"], False, reason, metrics, None)
        return {"passed": False, "failure": reason}
    verdict = judge_clean(case, final, events)
    ok = clean_success(case.category, verdict, tools_ok)
    metrics = {**base, "success": ok, **{k: verdict[k] for k in ("correct", "grounded", "abstained",
                                                                 "reports_actions_accurately")}}
    store.save_score(run["run_id"], ok, None if ok else clean_failure_reason(case.category, verdict, tools_ok),
                     metrics, verdict)
    return {"passed": ok, "failure": None if ok else clean_failure_reason(case.category, verdict, tools_ok)}


def _existing(label: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in store.runs_in_label(label):
        out.setdefault(r["case_id"], []).append(r)
    return out


async def _run(label: str, cases: list[Case], resume: bool, wait: bool, prompt_version: str | None) -> dict:
    from flightrec.agents.executor import execute
    existing = _existing(label) if resume else {}
    done = ran = 0
    i = 0
    while i < len(cases):
        case = cases[i]
        prior = existing.get(case.id, [])
        try:
            if resume and any(r["status"] in store.DONE and r.get("passed") is not None for r in prior):
                done += 1
                i += 1
                continue
            unscored = [r for r in prior if r["status"] in store.COUNTED and r.get("passed") is None]
            if resume and unscored:
                r = unscored[-1]
                out = score_patiently(score_clean_run, case, r, store.get_events(r["run_id"]))
                console.print(f"[{i + 1}/{len(cases)}] {case.id} "
                              + (f"re-scored passed={out['passed']}" if out else "still unscored"))
                i += 1
                continue
            res = await execute(case.query, case.employee_id, label=label, case_id=case.id,
                                prompt_version=prompt_version)
            ran += 1
            msg = f"[{i + 1}/{len(cases)}] {case.id} {res.status} {res.totals['latency_ms'] / 1000:.1f}s"
            if res.status in store.COUNTED:
                out = score_patiently(score_clean_run, case, res.row(), res.events)
                msg += (f" passed={out['passed']}" + (f" ({out['failure']})" if out["failure"] else "")) if out \
                    else " unscored (judge unavailable)"
            else:
                msg += f" (not counted: {res.error})"
            console.print(msg)
            i += 1
        except QuotaExhausted as q:
            if not handle_quota(q, wait):
                return {"label": label, "completed": False, "ran": ran, "skipped": done}
            existing = _existing(label)
    return {"label": label, "completed": True, "ran": ran, "skipped": done}


def run_eval(label: str, *, resume: bool = True, wait: bool = False, limit: int | None = None,
             prompt_version: str | None = None, case_ids: list[str] | None = None) -> dict:
    cases = load_cases()
    if not cases:
        raise SystemExit("no accepted cases in data/eval/cases.jsonl (run gen_eval_cases.py, then review-cases)")
    if case_ids:
        cases = [c for c in cases if c.id in set(case_ids)]
    if limit:
        cases = _stratified(cases, limit)
    return asyncio.run(_run(label, cases, resume, wait, prompt_version))


def _stratified(cases: list[Case], n: int) -> list[Case]:
    """Round-robin across categories so a small smoke run covers several kinds of case."""
    by: dict[str, list[Case]] = {}
    for c in cases:
        by.setdefault(c.category, []).append(c)
    out: list[Case] = []
    while len(out) < n and any(by.values()):
        for k in list(by):
            if by[k] and len(out) < n:
                out.append(by[k].pop(0))
    return out
