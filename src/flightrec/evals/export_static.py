"""Static demo export (guide 9.1) and the trace archive (9.2). Runs made with fake-* models are never exported."""

from __future__ import annotations

import gzip
import json
import shutil
from pathlib import Path

from sqlalchemy import text

from flightrec.config import DOCS_DIR, is_fake
from flightrec.db import engine
from flightrec.recorder import store

SLIM_KEYS = ("seq", "agent", "type", "name", "latency_ms", "tokens_in", "tokens_out", "cost_list_usd", "fault", "error",
             "replayed")
HEADLINE = ("baseline-v1", "hardened-v2", "chaos-baseline-v1", "chaos-hardened-v2", "repeatability")
MAX_FILE = 5 * 1024 * 1024


def _real(run: dict) -> bool:
    return not is_fake((run.get("config") or {}).get("agent_model"))


def _dump(path: Path, obj) -> int:
    data = json.dumps(obj, default=str, separators=(",", ":"))
    path.write_text(data, encoding="utf-8")
    return len(data)


def _run_summary(r: dict) -> dict:
    t = r.get("totals") or {}
    return {k: r.get(k) for k in ("run_id", "parent_run_id", "branch_seq", "label", "case_id", "mode", "fault",
                                  "status", "showcase", "user_query", "employee_id", "started_at", "passed",
                                  "failure_category")} | {
        "latency_ms": t.get("latency_ms"), "tokens": (t.get("tokens_in") or 0) + (t.get("tokens_out") or 0),
        "cost_list_usd": t.get("cost_list_usd"), "agent_model": (r.get("config") or {}).get("agent_model"),
        "prompt_version": (r.get("config") or {}).get("prompt_version")}


def export_static(out: Path) -> dict:
    from flightrec.evals.chaos import chaos_matrix
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.json"):
        old.unlink()
    labels = [lab for lab in store.labels_summary() if not is_fake(lab.get("agent_model"))]
    sizes, run_ids = {}, set()
    for lab in labels:
        runs = [r for r in store.list_runs(label=lab["label"], limit=100000) if _real(r)]
        sizes[f"runs_{lab['label']}.json"] = _dump(out / f"runs_{lab['label']}.json", [_run_summary(r) for r in runs])
        run_ids |= {r["run_id"] for r in runs}
        if lab["is_chaos"]:
            sizes[f"chaos_{lab['label']}.json"] = _dump(out / f"chaos_{lab['label']}.json", chaos_matrix(lab["label"]))
    with engine().connect() as c:
        showcase = {str(r[0]) for r in c.execute(text("SELECT run_id FROM runs WHERE showcase"))}
        # children of showcase runs (pre-recorded branches) and unlabelled showcase runs are exported too
        kids = {str(r[0]) for r in c.execute(text("SELECT run_id FROM runs WHERE parent_run_id = ANY(CAST(:ids AS uuid[]))"),
                                             {"ids": list(showcase)})} if showcase else set()
    run_ids |= showcase | kids
    unlabelled = []
    for rid in sorted(run_ids):
        r = store.get_run(rid)
        if not r or not _real(r):
            continue
        ev = store.get_events(rid)
        full = rid in showcase or rid in kids
        if not full:
            ev = [{k: e.get(k) for k in SLIM_KEYS} for e in ev]
        r["children"] = store.children_of(rid)
        r["events"] = ev
        r["events_full"] = full
        sizes[f"run_{rid}.json"] = _dump(out / f"run_{rid}.json", r)
        if not r.get("label"):
            unlabelled.append(_run_summary(r))
    sizes["runs__unlabelled.json"] = _dump(out / "runs__unlabelled.json", unlabelled)
    diffs = sorted(p.name for p in DOCS_DIR.glob("diff_*.html"))
    ddir = out.parent / "diffs"
    ddir.mkdir(exist_ok=True)
    for d in diffs:
        shutil.copy(DOCS_DIR / d, ddir / d)
    sizes["labels.json"] = _dump(out / "labels.json", {"labels": labels, "diffs": diffs,
                                                       "showcase": sorted(showcase)})
    too_big = {k: v for k, v in sizes.items() if v > MAX_FILE}
    return {"files": len(sizes), "bytes": sum(sizes.values()), "too_big": too_big, "showcase": len(showcase)}


# ------------------------------------------------------------------ trace archive
def export_traces(path: Path, labels: tuple[str, ...] = HEADLINE) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    with engine().connect() as c:
        ids = [str(r[0]) for r in c.execute(text(
            "SELECT run_id FROM runs WHERE label = ANY(:l) OR showcase OR parent_run_id IN "
            "(SELECT run_id FROM runs WHERE showcase) ORDER BY started_at"), {"l": list(labels)})]
    n = 0
    # parents first so the parent_run_id foreign key resolves on import
    rows = [store.get_run(i) for i in ids]
    rows = [r for r in rows if r and _real(r)]
    order = {r["run_id"]: r for r in rows}
    done, seq = set(), []

    def visit(r):
        if r["run_id"] in done:
            return
        if r.get("parent_run_id") in order:
            visit(order[r["parent_run_id"]])
        done.add(r["run_id"])
        seq.append(r)

    for r in rows:
        visit(r)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for r in seq:
            ev = store.get_events(r["run_id"])
            f.write(json.dumps({"run": r, "events": ev}, default=str) + "\n")
            n += 1
    return {"runs": n, "bytes": path.stat().st_size, "path": str(path)}


def import_traces(path: Path) -> dict:
    n = 0
    known = set()
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            obj = json.loads(line)
            r = obj["run"]
            if r.get("parent_run_id") and r["parent_run_id"] not in known and store.get_run(r["parent_run_id"]) is None:
                r["parent_run_id"] = None
            store.save_run(r, obj["events"])
            if r.get("passed") is not None:
                store.save_score(r["run_id"], r["passed"], r.get("failure_category"), r.get("metrics") or {},
                                 r.get("judge_raw"))
            if r.get("showcase"):
                store.set_showcase(r["run_id"], True)
            known.add(r["run_id"])
            n += 1
    return {"runs": n}
