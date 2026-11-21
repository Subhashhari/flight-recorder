"""Human-in-the-loop CLIs: review-cases, label, judge-agreement."""

from __future__ import annotations

import random
import textwrap

from rich.console import Console
from rich.panel import Panel

from flightrec.config import EVAL_DIR, load_scale
from flightrec.evals.cases import (
    ACCEPTED,
    CANDIDATES,
    CATEGORIES,
    Case,
    load_cases,
    read_jsonl,
    save_cases,
    write_jsonl,
)
from flightrec.evals.metrics import search_results
from flightrec.recorder import store

console = Console()
LABELS = EVAL_DIR / "judge_labels.jsonl"


def _gold_chunks(case: Case, max_chunks: int = 3) -> str:
    try:
        from flightrec.corpus.search import doc_chunks, search
        hits = [h for h in search(case.query, mode="hybrid", top_k=8) if h["doc_id"] in case.gold_doc_ids][:max_chunks]
        if not hits and case.gold_doc_ids:
            hits = doc_chunks(case.gold_doc_ids[0])[:1]
        return "\n\n".join(f"[{h['chunk_id']}] {textwrap.shorten(h['text'], 700)}" for h in hits) or "(no gold chunks)"
    except Exception as e:  # noqa: BLE001 - review still works without the DB
        return f"(could not load chunks: {type(e).__name__})"


def review_cases() -> dict:
    targets = load_scale()["eval"]
    cands = load_cases(CANDIDATES, status=None)
    accepted = {c.id: c for c in load_cases(ACCEPTED, status=None)}
    counts = {k: sum(1 for c in accepted.values() if c.category == k and c.status == "accepted") for k in CATEGORIES}
    for c in cands:
        if c.id in accepted:
            continue
        if counts[c.category] >= targets[c.category]:
            continue
        body = (f"[b]{c.category}[/b] · {c.id} · employee {c.employee_id}\n\n[b]Query:[/b] {c.query}\n"
                f"[b]Gold answer:[/b] {c.gold_answer}\n[b]Gold docs:[/b] {', '.join(c.gold_doc_ids) or '—'}\n"
                f"[b]Expected tools:[/b] {[t.model_dump() for t in c.expected_tool_calls] or '—'}\n"
                f"[b]Must abstain:[/b] {c.must_abstain}\n\n[dim]{_gold_chunks(c)}[/dim]")
        console.print(Panel(body, title=f"{c.category}: {counts[c.category]}/{targets[c.category]} accepted"))
        while True:
            k = console.input("[a]ccept / [r]eject / [e]dit gold answer / [q]uit > ").strip().lower()
            if k in ("a", "r", "e", "q"):
                break
        if k == "q":
            break
        if k == "e":
            new = console.input("New gold answer: ").strip()
            if new:
                c.gold_answer = new
            k = "a"
        c.status = "accepted" if k == "a" else "rejected"
        accepted[c.id] = c
        if k == "a":
            counts[c.category] += 1
        save_cases(list(accepted.values()), ACCEPTED)
    # cases.jsonl contains only accepted cases
    save_cases([c for c in accepted.values() if c.status == "accepted"], ACCEPTED)
    rejected = [c for c in accepted.values() if c.status == "rejected"]
    if rejected:
        save_cases(rejected, EVAL_DIR / "rejected.jsonl")
    return {"accepted": counts, "targets": targets}


def label(source_label: str = "baseline-v1", n: int = 20, seed: int = 13) -> dict:
    runs = [r for r in store.latest_scored_runs(source_label) if r["status"] == "ok" and r.get("judge_raw")]
    have = {x["run_id"] for x in read_jsonl(LABELS)}
    rng = random.Random(seed)
    rng.shuffle(runs)
    todo = [r for r in runs if r["run_id"] not in have][: max(0, n - len(have))]
    cases = {c.id: c for c in load_cases()}
    rows = read_jsonl(LABELS)
    for r in todo:
        c = cases.get(r["case_id"])
        ev = store.get_events(r["run_id"])
        evid = "\n".join(f"[{x['chunk_id']}] {textwrap.shorten(x['text'], 300)}" for x in search_results(ev)) or "—"
        console.print(Panel(f"[b]Query:[/b] [{r['employee_id']}] {r['user_query']}\n[b]Category:[/b] "
                            f"{c.category if c else '?'}\n[b]Gold:[/b] {c.gold_answer if c else '?'}\n\n"
                            f"[b]Answer:[/b] {r['final_answer']}\n\n[dim]{evid}[/dim]",
                            title=f"label {len(rows) + 1}/{n}"))
        while True:
            k = console.input("Does this reply pass? [p]ass / [f]ail / [q]uit > ").strip().lower()
            if k in ("p", "f", "q"):
                break
        if k == "q":
            break
        rows.append({"run_id": r["run_id"], "case_id": r["case_id"], "human_pass": k == "p",
                     "judge_pass": bool(r["passed"])})
        write_jsonl(LABELS, rows)
    return {"labelled": len(rows)}


def judge_agreement() -> dict:
    rows = read_jsonl(LABELS)
    if not rows:
        raise SystemExit("no labels yet: run `flightrec label` first")
    agree = sum(1 for r in rows if r["human_pass"] == r["judge_pass"])
    out = {"n": len(rows), "agree": agree, "agreement": agree / len(rows),
           "human_pass": sum(r["human_pass"] for r in rows), "judge_pass": sum(r["judge_pass"] for r in rows)}
    from flightrec.evals.report import save_export
    save_export("judge_agreement.json", out)
    return out
