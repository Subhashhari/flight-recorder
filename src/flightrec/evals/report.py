"""Summaries computed only from stored runs/scores: label summary, retrieval eval, stats, docs/results.md."""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from statistics import mean

from sqlalchemy import text

from flightrec.config import DATA_DIR, DOCS_DIR, ROOT, is_fake, settings
from flightrec.db import engine
from flightrec.evals.cases import CATEGORIES, load_cases
from flightrec.evals.metrics import percentile, retrieval_metrics
from flightrec.recorder import store

EXPORTS = DATA_DIR / "exports"


def save_export(name: str, obj) -> None:
    EXPORTS.mkdir(parents=True, exist_ok=True)
    (EXPORTS / name).write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")


def load_export(name: str):
    p = EXPORTS / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def clean_summary(label: str) -> dict:
    runs = store.latest_scored_runs(label)
    by_cat = {c: [r for r in runs if (r.get("metrics") or {}).get("category") == c] for c in CATEGORIES}
    cat_rate = {c: (sum(1 for r in rs if r["passed"]) / len(rs)) if rs else None for c, rs in by_cat.items()}
    present = [v for v in cat_rate.values() if v is not None]
    judged_qm = [r for r in runs if (r.get("metrics") or {}).get("category") in ("qa", "multi")
                 and (r.get("metrics") or {}).get("grounded") is not None]
    lat = [r["totals"]["latency_ms"] / 1000 for r in runs]
    toks = [r["totals"]["tokens_in"] + r["totals"]["tokens_out"] for r in runs]
    cost = [r["totals"]["cost_list_usd"] for r in runs]
    with engine().connect() as c:
        excluded = c.execute(text("SELECT count(*) FROM runs WHERE label=:l AND status IN ('rate_limited','paused')"),
                             {"l": label}).scalar()
    return {
        "label": label, "cases": len(runs), "success": mean(present) if present else None,
        "per_category": cat_rate, "per_category_n": {c: len(rs) for c, rs in by_cat.items()},
        "hallucination_rate": (sum(1 for r in judged_qm if not r["metrics"]["grounded"]) / len(judged_qm))
        if judged_qm else None,
        "hallucination_n": len(judged_qm),
        "p50_s": percentile(lat, 50), "p95_s": percentile(lat, 95),
        "tokens_per_run": mean(toks) if toks else None, "cost_per_run_usd": mean(cost) if cost else None,
        "statuses": {s: sum(1 for r in runs if r["status"] == s) for s in store.COUNTED},
        "excluded_rate_limited_or_paused": excluded,
        "agent_model": runs[0]["config"]["agent_model"] if runs else None,
        "prompt_version": runs[0]["config"].get("prompt_version") if runs else None,
    }


def retrieval_eval(mode: str) -> dict:
    from flightrec.corpus.search import search
    cases = [c for c in load_cases() if c.category in ("qa", "multi") and c.gold_doc_ids]
    rows = []
    for c in cases:
        hits = search(c.query, mode=mode, top_k=5)
        docs = list(dict.fromkeys(h["doc_id"] for h in hits))
        rows.append({"case_id": c.id, **retrieval_metrics(docs, c.gold_doc_ids), "docs": docs})
    out = {"mode": mode, "n": len(rows), "embed_model": settings().embed_model,
           "recall_at_5": mean(r["recall_at_5"] for r in rows) if rows else None,
           "mrr": mean(r["mrr"] for r in rows) if rows else None, "date": dt.date.today().isoformat(), "rows": rows}
    if not is_fake(settings().embed_model):
        save_export(f"retrieval_{mode}.json", out)
    return out


def stats(label: str | None = None) -> dict:
    with engine().connect() as c:
        corpus = c.execute(text("SELECT count(*), count(DISTINCT doc_id) FROM chunks")).first()
        q = "SELECT status, mode, totals FROM runs" + (" WHERE label=:l" if label else "")
        runs = [dict(r._mapping) for r in c.execute(text(q), {"l": label} if label else {})]
    counted = [r for r in runs if r["status"] in store.COUNTED and r["mode"] != "replay"]
    self_ms = sum(r["totals"].get("recorder_self_ms", 0) for r in counted)
    lat_ms = sum(r["totals"].get("latency_ms", 0) for r in counted)
    by_status: dict[str, int] = {}
    for r in runs:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    calls = [r["totals"].get("api_calls", r["totals"].get("llm_calls", 0)) for r in counted]
    return {"label": label, "runs": len(runs), "by_status": by_status, "corpus_chunks": corpus[0],
            "corpus_documents": corpus[1], "eval_cases": len(load_cases()),
            "avg_llm_calls_per_run": mean(calls) if calls else None,
            "avg_tokens_per_run": mean(r["totals"]["tokens_in"] + r["totals"]["tokens_out"] for r in counted)
            if counted else None,
            "tracing_overhead": (self_ms / lat_ms) if lat_ms else None, "recorder_self_ms": self_ms,
            "latency_ms": lat_ms}


# ------------------------------------------------------------------ results.md
def _pct(x):
    return "—" if x is None else f"{x * 100:.1f}"


def _f(x, nd=2):
    return "—" if x is None else f"{x:.{nd}f}"


def _commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                              check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def write_results_md() -> str:
    """Regenerate docs/results.md purely from the DB and data/exports/*.json produced by commands."""
    from flightrec.evals.chaos import chaos_matrix, matrix_markdown
    s = settings()
    labels = [lab for lab in store.labels_summary() if not is_fake(lab.get("agent_model"))]
    clean = [lab["label"] for lab in labels if not lab["is_chaos"] and lab["scored"]
             and not lab["label"].startswith(("smoke", "repeatability"))]
    chaos = [lab["label"] for lab in labels if lab["is_chaos"] and lab["scored"] and not lab["label"].startswith("smoke")]
    plan = {"A_lite": "A", "B_sprint": "B"}.get(s.scale_tier, "?")
    md = ["# Results (all numbers produced by the commands shown)",
          f"Plan: {plan} · Agent model: {s.agent_model} · Judge model: {s.judge_model} · Embedding model: "
          f"{s.embed_model} · Tier: {s.scale_tier} · Commit: {_commit()} · Date: {dt.date.today().isoformat()}",
          "", "Synthetic data (Northwind Labs). Costs are list-price equivalents (config/pricing.yaml); actual spend Rs 0."
          " Statistics exclude `rate_limited` and `paused` runs.", "",
          "Regenerate with `uv run flightrec report`.", "", "## Clean eval", "Command: `flightrec eval --label <label>`", "",
          "| Label | Cases | Success % | qa | unanswerable | action | multi | Halluc. % | p50 s | p95 s | tokens/run | list-price $/run |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for lab in clean:
        x = clean_summary(lab)
        pc = x["per_category"]
        md.append(f"| {lab} | {x['cases']} | {_pct(x['success'])} | {_pct(pc['qa'])} | {_pct(pc['unanswerable'])} | "
                  f"{_pct(pc['action'])} | {_pct(pc['multi'])} | {_pct(x['hallucination_rate'])} | {_f(x['p50_s'])} | "
                  f"{_f(x['p95_s'])} | {_f(x['tokens_per_run'], 0)} | {_f(x['cost_per_run_usd'], 5)} |")
    if not clean:
        md.append("| (no clean eval completed yet) |||||||||||| ")
    md += ["", "Success % = mean of per-category success rates. Per-category n: "
           + "; ".join(f"{lab}: {clean_summary(lab)['per_category_n']}" for lab in clean), ""]
    md += ["## Retrieval", "Command: `flightrec eval-retrieval --mode hybrid|vector` (qa + multi cases with gold docs)",
           "", "| Mode | n | recall@5 | MRR |", "|---|---|---|---|"]
    for mode in ("hybrid", "vector"):
        r = load_export(f"retrieval_{mode}.json")
        md.append(f"| {mode} | {r['n']} | {_f(r['recall_at_5'], 3)} | {_f(r['mrr'], 3)} |" if r
                  else f"| {mode} | — | not run yet | — |")
    md += ["", "## Chaos", "Command: `flightrec chaos --label <label> --faults all`. Per-fault rates from small "
           "samples are exploratory.", ""]
    for lab in chaos:
        md += [f"### {lab}", "", matrix_markdown(chaos_matrix(lab)), ""]
    if not chaos:
        md += ["(no chaos run completed yet)", ""]
    rep, overhead = load_export("repeatability.json"), None
    base = next((lab for lab in clean if "baseline" in lab), clean[0] if clean else None)
    if base:
        overhead = stats(base)["tracing_overhead"]
    rc = [load_export(f"replay_check_{lab}.json") for lab in clean]
    rc = [r for r in rc if r]
    live_cell = (f"{_pct(rep['live_differ_rate'])} % of {rep['cases']} cases × {rep['repeats']} runs "
                 f"(recorded-run replays identical: {rep['replay_identical']}"
                 f"{'; skipped after attempt cap: ' + str(len(rep['skipped'])) if rep.get('skipped') else ''})"
                 ) if rep else "—"
    replay_cell = "; ".join(f"{r['label']}: {_pct(r['identical_rate'])} % of {r['n']}" for r in rc) or "—"
    overhead_cell = f"{_pct(overhead)} % ({base})" if overhead is not None else "—"
    md += ["## Reproducibility", "Commands: `flightrec repeatability`, `flightrec replay-check --label L`, "
           "`flightrec stats --label L`", "", "| live runs differing | replay identical | tracing overhead |",
           "|---|---|---|", f"| {live_cell} | {replay_cell} | {overhead_cell} |", ""]
    ja = load_export("judge_agreement.json")
    md += ["## Judge agreement", "Command: `flightrec label` then `flightrec judge-agreement`", "",
           "| labels n | agreement % |", "|---|---|",
           f"| {ja['n']} | {_pct(ja['agreement'])} |" if ja else "| — | not labelled yet |", ""]
    out = "\n".join(md) + "\n"
    (DOCS_DIR / "results.md").write_text(out, encoding="utf-8")
    return out
