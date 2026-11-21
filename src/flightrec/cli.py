"""`flightrec` CLI (guide 5.5)."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(add_completion=False, no_args_is_help=True, help="Flight Recorder for the PolicyDesk ADK pipeline.")
showcase_app = typer.Typer(help="Mark runs for the static demo.")
app.add_typer(showcase_app, name="showcase")
console = Console()

PV = typer.Option(None, "--prompt-version", help="v1 (baseline) or v2 (hardened); default from PROMPT_VERSION")


def _pv(v: str | None) -> str | None:
    if v:
        os.environ["PROMPT_VERSION"] = v
    return v


def _table(rows: list[dict], cols: list[str], title: str | None = None) -> None:
    t = Table(title=title)
    for c in cols:
        t.add_column(c)
    for r in rows:
        t.add_row(*["" if r.get(c) is None else str(r.get(c)) for c in cols])
    console.print(t)


@app.command("db-init")
def db_init():
    """Create the schema (idempotent)."""
    from flightrec.db import init_db
    init_db()
    console.print("schema ready")


@app.command()
def ingest():
    """Chunk + embed the corpus (truncate and reload)."""
    from flightrec.corpus.ingest import ingest as _ingest
    console.print(_ingest())


@app.command()
def search(query: str, mode: str = typer.Option("hybrid", help="hybrid | vector"), k: int = 5):
    """Try retrieval."""
    from flightrec.corpus.search import search as _search
    rows = _search(query, mode=mode, top_k=k)
    _table([{**r, "text": r["text"][:110].replace("\n", " ")} for r in rows], ["chunk_id", "score", "text"],
           f"{mode}: {query}")


@app.command("check-facts")
def check_facts():
    """Verify corpus numbers against data/facts.yaml."""
    from flightrec.corpus.facts import check_all
    issues, missing = check_all()
    for d in missing:
        console.print(f"[red]missing document {d}[/red]")
    if issues:
        _table(issues, ["doc", "issue", "snippet"], "check-facts")
    console.print(f"{len(issues)} issue(s), {len(missing)} missing document(s)")
    raise typer.Exit(1 if issues or missing else 0)


@app.command("review-cases")
def review_cases():
    """Interactive accept / reject / edit of eval-case candidates."""
    from flightrec.evals.review import review_cases as _r
    console.print(_r())


@app.command()
def eval(label: str = typer.Option(..., "--label"), resume: bool = typer.Option(False, "--resume"),
         wait: bool = typer.Option(False, "--wait"), limit: int = typer.Option(None, help="smoke: first N (stratified)"),
         prompt_version: str = PV):
    """Clean eval run over accepted cases."""
    from flightrec.evals.runner import run_eval
    console.print(run_eval(label, resume=resume, wait=wait, limit=limit, prompt_version=_pv(prompt_version)))
    from flightrec.evals.report import clean_summary
    console.print_json(json.dumps(clean_summary(label), default=str))


@app.command("eval-retrieval")
def eval_retrieval(mode: str = typer.Option("hybrid", "--mode")):
    """Retrieval-only metrics (recall@5, MRR) over gold questions. No agent calls."""
    from flightrec.evals.report import retrieval_eval
    r = retrieval_eval(mode)
    console.print({k: v for k, v in r.items() if k != "rows"})


@app.command()
def chaos(label: str = typer.Option(..., "--label"), faults: str = typer.Option("all", "--faults"),
          resume: bool = typer.Option(False, "--resume"), wait: bool = typer.Option(False, "--wait"),
          limit: int = typer.Option(None, help="smoke: N runs spread across faults"), prompt_version: str = PV):
    """Fault-injection runs."""
    from flightrec.evals.chaos import chaos_matrix, matrix_markdown, run_chaos
    console.print(run_chaos(label, faults, resume=resume, wait=wait, limit=limit, prompt_version=_pv(prompt_version)))
    console.print(matrix_markdown(chaos_matrix(label)))


@app.command("chaos-matrix")
def chaos_matrix_cmd(label: str = typer.Option(..., "--label"), as_json: bool = typer.Option(False, "--json")):
    """Print the fault x failure-category matrix for a chaos label."""
    from flightrec.evals.chaos import chaos_matrix, matrix_markdown
    m = chaos_matrix(label)
    console.print_json(json.dumps(m)) if as_json else console.print(matrix_markdown(m))


@app.command()
def runs(label: str = typer.Option(None, "--label"), failed: bool = typer.Option(False, "--failed"),
         status: str = typer.Option(None), limit: int = 50):
    """List runs."""
    from flightrec.recorder.store import list_runs
    rows = list_runs(label=label, status=status, failed=failed, limit=limit)
    _table([{**r, "latency_s": f"{r['totals']['latency_ms'] / 1000:.1f}",
             "tokens": r["totals"]["tokens_in"] + r["totals"]["tokens_out"],
             "result": "" if r["passed"] is None else ("pass" if r["passed"] else r["failure_category"] or "fail")}
            for r in rows], ["run_id", "label", "case_id", "mode", "fault", "status", "result", "latency_s", "tokens"])


@app.command()
def run(query: str, employee: str = typer.Option("E1003", "--employee"), label: str = typer.Option(None),
        fault: str = typer.Option(None), prompt_version: str = PV):
    """One live (or chaos, with --fault) run."""
    from flightrec.agents.executor import execute
    res = asyncio.run(execute(query, employee, mode="chaos" if fault else "live", fault=fault, label=label,
                              prompt_version=_pv(prompt_version)))
    console.print(f"run {res.run_id} status={res.status}\n{res.final_answer}")
    if res.error:
        console.print(f"[red]{res.error}[/red]")


def _print_run(res, src_id: str):
    from flightrec.recorder import store
    from flightrec.recorder.replay import same_outcome
    src = store.get_run(src_id)
    same = same_outcome(store.get_events(src_id), src["final_answer"], res.events, res.final_answer)
    console.print(f"{res.mode} run {res.run_id} status={res.status} api_calls={res.totals['api_calls']} "
                  f"identical_to_source={same}")
    console.print(res.final_answer or "")
    if res.error:
        console.print(f"[red]{res.error}[/red]")


@app.command()
def replay(run_id: str, label: str = typer.Option(None), no_record: bool = typer.Option(False, "--no-record")):
    """Re-execute a recorded run from cache (zero LLM calls)."""
    from flightrec.recorder.replay import replay as _replay
    _print_run(asyncio.run(_replay(run_id, label=label, record=not no_record)), run_id)


@app.command()
def branch(run_id: str, step: int = typer.Option(..., "--step"),
           set_: list[str] = typer.Option(None, "--set", help="model=... or temperature=..."),
           append: list[str] = typer.Option(None, "--append", help='agent="text appended to its instruction"'),
           label: str = typer.Option(None)):
    """Replay up to step N, then run live with overrides."""
    from flightrec.recorder.replay import branch as _branch
    from flightrec.recorder.replay import parse_overrides
    _print_run(asyncio.run(_branch(run_id, step, parse_overrides(set_, append), label=label)), run_id)


@showcase_app.command("add")
def showcase_add(run_id: str):
    from flightrec.recorder.store import set_showcase
    set_showcase(run_id, True)
    console.print(f"showcase += {run_id}")


@showcase_app.command("remove")
def showcase_remove(run_id: str):
    from flightrec.recorder.store import set_showcase
    set_showcase(run_id, False)


@showcase_app.command("list")
def showcase_list():
    from flightrec.recorder.store import list_runs
    rows = [r for r in list_runs(limit=100000) if r["showcase"]]
    _table(rows, ["run_id", "label", "case_id", "mode", "fault", "status", "failure_category"])


@app.command()
def diff(a: str, b: str):
    """Metric deltas + flipped cases between two labels (markdown; also writes docs/diff_A__B.html)."""
    from flightrec.evals.diff import diff as _diff
    d = _diff(a, b)
    console.print(d["markdown"])
    console.print(f"wrote {d['html_path']}")


@app.command()
def label(source: str = typer.Option("baseline-v1", "--source"), n: int = 20):
    """Hand-label 20 random clean outputs pass/fail."""
    from flightrec.evals.review import label as _label
    console.print(_label(source, n))


@app.command("judge-agreement")
def judge_agreement():
    from flightrec.evals.review import judge_agreement as _ja
    console.print(_ja())


@app.command()
def repeatability(cases: int = typer.Option(None), repeats: int = typer.Option(None),
                  wait: bool = typer.Option(False, "--wait")):
    """Live temperature-0 repeatability + replay identity."""
    from flightrec.evals.repro import repeatability as _rep
    out = _rep(cases, repeats, wait)
    console.print({k: v for k, v in (out or {}).items() if k != "per_case"})


@app.command("replay-check")
def replay_check(label: str = typer.Option(..., "--label")):
    """Replay every run in a label; % identical (expected 100 %)."""
    from flightrec.evals.repro import replay_check as _rc
    console.print(_rc(label))


@app.command()
def stats(label: str = typer.Option(None, "--label")):
    """Counts, averages, tracing overhead."""
    from flightrec.evals.report import stats as _stats
    console.print(_stats(label))


@app.command()
def report():
    """Regenerate docs/results.md from stored runs and data/exports/*.json."""
    from flightrec.evals.report import write_results_md
    console.print(write_results_md())


@app.command("export-static")
def export_static(out: Path = typer.Option(Path("ui/public/demo-data"), "--out")):
    from flightrec.evals.export_static import export_static as _e
    console.print(_e(out))


@app.command("export-traces")
def export_traces(file: Path = typer.Argument(Path("data/exports/traces.jsonl.gz"))):
    from flightrec.evals.export_static import export_traces as _e
    console.print(_e(file))


@app.command("import")
def import_(file: Path):
    """Load a trace archive into a (fresh) DB."""
    from flightrec.evals.export_static import import_traces
    console.print(import_traces(file))


def main():
    app()


if __name__ == "__main__":
    main()
