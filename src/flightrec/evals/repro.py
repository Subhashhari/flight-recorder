"""Reproducibility studies: live repeatability at temperature 0 and replay-check (guide 6.3.3, 6.3.4)."""

from __future__ import annotations

import asyncio
import random

from rich.console import Console

from flightrec.config import is_fake, load_scale, settings
from flightrec.evals.cases import load_cases
from flightrec.evals.report import save_export
from flightrec.evals.runner import handle_quota
from flightrec.recorder import store
from flightrec.recorder.ratelimit import QuotaExhausted
from flightrec.recorder.replay import replay, same_outcome

console = Console()
LABEL = "repeatability"


def pick_cases(n: int, seed: int = 5):
    cases = load_cases()
    rng = random.Random(seed)
    by: dict[str, list] = {}
    for c in cases:
        by.setdefault(c.category, []).append(c)
    for v in by.values():
        rng.shuffle(v)
    out = []
    while len(out) < n and any(by.values()):
        for k in sorted(by):
            if by[k] and len(out) < n:
                out.append(by[k].pop())
    return out


async def _repeatability(cases, repeats: int, wait: bool) -> dict | None:
    from flightrec.agents.executor import execute
    per_case = []
    for i, c in enumerate(cases):
        while True:
            prior = [r for r in store.runs_in_label(LABEL) if r["case_id"] == c.id and r["status"] in ("ok", "diverged")]
            try:
                while len(prior) < repeats:
                    res = await execute(c.query, c.employee_id, label=LABEL, case_id=c.id, temperature=0.0)
                    if res.status in ("ok", "diverged"):
                        prior.append(res.row())
                break
            except QuotaExhausted as q:
                if not handle_quota(q, wait):
                    return None
        runs = prior[:repeats]
        evs = [store.get_events(r["run_id"]) for r in runs]
        differ = any(not same_outcome(evs[0], runs[0]["final_answer"], evs[j], runs[j]["final_answer"])
                     for j in range(1, len(runs)))
        per_case.append({"case_id": c.id, "category": c.category, "differs": differ,
                         "run_ids": [r["run_id"] for r in runs]})
        console.print(f"[{i + 1}/{len(cases)}] {c.id} differs={differ}")
    # replay one recorded run `repeats` times: all must be identical (zero API calls)
    src = per_case[0]["run_ids"][0]
    src_run, src_ev = store.get_run(src), store.get_events(src)
    identical = 0
    for _ in range(repeats):
        rep = await replay(src, record=False)
        identical += same_outcome(src_ev, src_run["final_answer"], rep.events, rep.final_answer) and \
            rep.totals["api_calls"] == 0
    return {"cases": len(per_case), "repeats": repeats, "temperature": 0.0,
            "live_differ_rate": sum(p["differs"] for p in per_case) / len(per_case),
            "replay_source_run": src, "replay_identical": f"{identical}/{repeats}", "per_case": per_case}


def repeatability(n: int | None = None, repeats: int | None = None, wait: bool = False) -> dict | None:
    cfg = load_scale()["repeatability"]
    cases = pick_cases(n or cfg["cases"])
    out = asyncio.run(_repeatability(cases, repeats or cfg["repeats"], wait))
    if out and not is_fake(settings().agent_model):
        save_export("repeatability.json", out)
    return out


async def _replay_check(label: str) -> dict:
    runs = [r for r in store.runs_in_label(label) if r["status"] in ("ok", "diverged") and r["mode"] in ("live", "chaos")]
    same = 0
    bad = []
    for r in runs:
        ev = store.get_events(r["run_id"])
        rep = await replay(r["run_id"], record=False)
        ok = same_outcome(ev, r["final_answer"], rep.events, rep.final_answer) and rep.totals["api_calls"] == 0
        same += ok
        if not ok:
            bad.append(r["run_id"])
    return {"label": label, "n": len(runs), "identical": same, "identical_rate": (same / len(runs)) if runs else None,
            "not_identical": bad}


def replay_check(label: str) -> dict:
    out = asyncio.run(_replay_check(label))
    runs = store.runs_in_label(label)
    if runs and not any(is_fake(r["config"].get("agent_model")) for r in runs):
        save_export(f"replay_check_{label}.json", out)
    return out
