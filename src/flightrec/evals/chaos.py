"""`flightrec chaos`: fault-injection runs + failure matrix (guide 6.4, 7.4, 7.5)."""

from __future__ import annotations

import asyncio
import hashlib

from rich.console import Console

from flightrec.config import load_scale
from flightrec.evals.cases import Case, load_cases
from flightrec.evals.judge import judge_chaos
from flightrec.evals.metrics import FAILURE_CATEGORIES, failure_category
from flightrec.evals.runner import handle_quota, score_patiently
from flightrec.recorder import store
from flightrec.recorder.faults import FAULT_NAMES, FAULTS
from flightrec.recorder.ratelimit import QuotaExhausted

console = Console()


def select_cases(cases: list[Case], fault: str, n: int) -> list[Case]:
    """Deterministic: applicable categories, ordered by sha256(case_id + fault), first n."""
    applicable = [c for c in cases if c.category in FAULTS[fault]["applies"]]
    return sorted(applicable, key=lambda c: hashlib.sha256((c.id + fault).encode()).hexdigest())[:n]


def plan(faults: list[str], n: int | None = None) -> list[tuple[str, Case]]:
    cases = load_cases()
    n = n or load_scale()["chaos_cases_per_fault"]
    return [(f, c) for f in faults for c in select_cases(cases, f, n)]


def score_chaos_run(case: Case, run: dict, events: list[dict], fault: str) -> dict:
    fired = [e for e in events if e.get("fault") == fault and e["type"] == "tool_call"]
    fault_fired = bool(fired)
    verdict = None
    if run["status"] == "ok" and (run.get("final_answer") or "").strip():
        verdict = judge_chaos(case, run["final_answer"], events, FAULTS[fault]["description"],
                              fired[0]["response"] if fired else None)
    cat = failure_category(run["status"], run.get("final_answer"), events, case.employee_id, verdict, fault_fired)
    metrics = {"fault": fault, "fault_fired": fault_fired, "category": case.category, "failure_category": cat,
               "survived": cat is None, "status": run["status"]}
    store.save_score(run["run_id"], cat is None, cat, metrics, verdict)
    return metrics


def parse_faults(spec: str) -> list[str]:
    if spec == "all":
        return list(FAULT_NAMES)
    fs = [f.strip() for f in spec.split(",") if f.strip()]
    bad = [f for f in fs if f not in FAULTS]
    if bad:
        raise SystemExit(f"unknown faults {bad}; choose from {FAULT_NAMES}")
    return fs


async def _run(label: str, work: list[tuple[str, Case]], resume: bool, wait: bool, prompt_version: str | None):
    from flightrec.agents.executor import execute

    def existing():
        out: dict[tuple, list[dict]] = {}
        for r in store.runs_in_label(label):
            out.setdefault((r["fault"], r["case_id"]), []).append(r)
        return out

    ex = existing() if resume else {}
    i = ran = 0
    while i < len(work):
        fault, case = work[i]
        prior = ex.get((fault, case.id), [])
        try:
            if resume and any(r["status"] in store.DONE and r.get("passed") is not None for r in prior):
                i += 1
                continue
            unscored = [r for r in prior if r["status"] in store.COUNTED and r.get("passed") is None]
            if resume and unscored:
                score_patiently(score_chaos_run, case, unscored[-1], store.get_events(unscored[-1]["run_id"]), fault)
                i += 1
                continue
            res = await execute(case.query, case.employee_id, mode="chaos", fault=fault, label=label,
                                case_id=case.id, prompt_version=prompt_version)
            ran += 1
            msg = f"[{i + 1}/{len(work)}] {fault} {case.id} {res.status}"
            if res.status in store.COUNTED:
                m = score_patiently(score_chaos_run, case, res.row(), res.events, fault)
                msg += (f" -> {m['failure_category'] or 'survived'}" + ("" if m["fault_fired"] else " (fault not fired)")) \
                    if m else " -> unscored (judge unavailable)"
            console.print(msg)
            i += 1
        except QuotaExhausted as q:
            if not handle_quota(q, wait):
                return {"label": label, "completed": False, "ran": ran}
            ex = existing()
    return {"label": label, "completed": True, "ran": ran}


def run_chaos(label: str, faults: str = "all", *, resume: bool = True, wait: bool = False, n: int | None = None,
              limit: int | None = None, prompt_version: str | None = None) -> dict:
    work = plan(parse_faults(faults), n)
    if limit:  # spread a smoke run across faults: round-robin
        by: dict[str, list] = {}
        for w in work:
            by.setdefault(w[0], []).append(w)
        work = [w for group in zip(*by.values(), strict=False) for w in group][:limit]
    return asyncio.run(_run(label, work, resume, wait, prompt_version))


def chaos_matrix(label: str) -> dict:
    runs = store.chaos_scored_runs(label)
    rows = {}
    for f in FAULT_NAMES:
        rs = [r for r in runs if r["fault"] == f]
        if not rs:
            continue
        counts = {c: sum(1 for r in rs if r["failure_category"] == c) for c in FAILURE_CATEGORIES}
        survived = sum(1 for r in rs if r["passed"])
        rows[f] = {"runs": len(rs), "survived": survived, "survival_rate": survived / len(rs),
                   "fault_fired": sum(1 for r in rs if (r.get("metrics") or {}).get("fault_fired")), **counts}
    total = sum(r["runs"] for r in rows.values())
    surv = sum(r["survived"] for r in rows.values())
    modes = sorted({(f, c) for f, r in rows.items() for c in FAILURE_CATEGORIES if r[c] > 0})
    return {"label": label, "faults": rows, "categories": FAILURE_CATEGORIES, "total_runs": total,
            "survived": surv, "survival_rate": (surv / total) if total else None,
            "failure_modes": [list(m) for m in modes]}


def matrix_markdown(m: dict) -> str:
    cats = m["categories"]
    head = "| Fault | runs | fired | survived | " + " | ".join(cats) + " |\n|" + "---|" * (len(cats) + 4) + "\n"
    body = "".join(f"| {f} | {r['runs']} | {r['fault_fired']} | {r['survived']} ({r['survival_rate']:.0%}) | "
                   + " | ".join(str(r[c]) for c in cats) + " |\n" for f, r in m["faults"].items())
    tail = (f"\nOverall survival: {m['survived']}/{m['total_runs']}"
            + (f" ({m['survival_rate']:.0%})" if m["survival_rate"] is not None else "")
            + f" · distinct failure modes (fault, category): {len(m['failure_modes'])}\n")
    return head + body + tail
