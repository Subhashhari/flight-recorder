"""Persistence: quota counters, runs, events, scores (Postgres) plus in-memory doubles for tests."""

from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict
from typing import Any

from sqlalchemy import text

from flightrec.db import engine

COUNTED = ("ok", "diverged", "budget_exceeded", "crash")  # statuses included in statistics
DONE = COUNTED  # a scored run with one of these statuses means the case is finished for --resume


# ---------------------------------------------------------------- quota
class MemoryQuotaStore:
    def __init__(self):
        self.c = defaultdict(int)

    def calls(self, day, model) -> int:
        return self.c[(day, model)]

    def increment(self, day, model, n: int = 1) -> None:
        self.c[(day, model)] += n


class DbQuotaStore:
    def calls(self, day, model) -> int:
        with engine().connect() as c:
            r = c.execute(text("SELECT calls FROM quota_usage WHERE day_pt=:d AND model=:m"), {"d": day, "m": model})
            row = r.first()
            return int(row[0]) if row else 0

    def increment(self, day, model, n: int = 1) -> None:
        with engine().begin() as c:
            c.execute(text("""INSERT INTO quota_usage(day_pt, model, calls) VALUES (:d, :m, :n)
                              ON CONFLICT (day_pt, model) DO UPDATE SET calls = quota_usage.calls + :n"""),
                      {"d": day, "m": model, "n": n})


def quota_rows() -> list[dict]:
    with engine().connect() as c:
        return [dict(r._mapping) for r in c.execute(text("SELECT * FROM quota_usage ORDER BY day_pt, model"))]


# ---------------------------------------------------------------- runs / events
EVENT_COLS = ("seq", "ordinal", "type", "agent", "name", "request", "response", "request_hash", "latency_ms",
              "tokens_in", "tokens_out", "cost_list_usd", "replayed", "fault", "error", "ts")
JSON_EVENT_COLS = ("request", "response")


def _j(v):
    return None if v is None else json.dumps(v, default=str)


def save_run(run: dict, events: list[dict]) -> None:
    """Write the run and all its events in one transaction (upsert on run_id, events replaced)."""
    with engine().begin() as c:
        c.execute(text("""
            INSERT INTO runs(run_id, parent_run_id, branch_seq, label, case_id, mode, fault, status, showcase,
                             user_query, employee_id, final_answer, config, totals, started_at, ended_at)
            VALUES (:run_id, :parent_run_id, :branch_seq, :label, :case_id, :mode, :fault, :status, :showcase,
                    :user_query, :employee_id, :final_answer, CAST(:config AS jsonb), CAST(:totals AS jsonb),
                    :started_at, :ended_at)
            ON CONFLICT (run_id) DO UPDATE SET status=EXCLUDED.status, final_answer=EXCLUDED.final_answer,
                totals=EXCLUDED.totals, config=EXCLUDED.config, ended_at=EXCLUDED.ended_at"""),
                  {**{k: run.get(k) for k in ("run_id", "parent_run_id", "branch_seq", "label", "case_id", "mode",
                                              "fault", "status", "user_query", "employee_id", "final_answer",
                                              "started_at", "ended_at")},
                   "showcase": bool(run.get("showcase", False)),
                   "config": _j(run["config"]), "totals": _j(run["totals"])})
        c.execute(text("DELETE FROM events WHERE run_id=:r"), {"r": run["run_id"]})
        if events:
            c.execute(text(f"""INSERT INTO events(run_id, {", ".join(EVENT_COLS)}) VALUES (:run_id, {", ".join(
                f"CAST(:{k} AS json)" if k in JSON_EVENT_COLS else f":{k}" for k in EVENT_COLS)})"""),
                      [{"run_id": run["run_id"], **{k: (_j(e.get(k)) if k in JSON_EVENT_COLS else e.get(k))
                                                    for k in EVENT_COLS}} for e in events])


def _row(r) -> dict:
    d = dict(r._mapping)
    for k, v in list(d.items()):
        if isinstance(v, dt.datetime):
            d[k] = v.isoformat()
        elif k in ("run_id", "parent_run_id") and v is not None:
            d[k] = str(v)
        elif k == "cost_list_usd" and v is not None:
            d[k] = float(v)
    return d


def get_run(run_id: str) -> dict | None:
    with engine().connect() as c:
        r = c.execute(text("""SELECT r.*, s.passed, s.failure_category, s.metrics, s.judge_raw
                              FROM runs r LEFT JOIN scores s USING (run_id) WHERE r.run_id=:r"""), {"r": run_id}).first()
        return _row(r) if r else None


def get_events(run_id: str) -> list[dict]:
    with engine().connect() as c:
        rows = c.execute(text("SELECT * FROM events WHERE run_id=:r ORDER BY seq"), {"r": run_id})
        return [_row(r) for r in rows]


def list_runs(label: str | None = None, status: str | None = None, limit: int = 500,
              failed: bool = False, mode: str | None = None) -> list[dict]:
    q = """SELECT r.run_id, r.parent_run_id, r.branch_seq, r.label, r.case_id, r.mode, r.fault, r.status, r.showcase,
                  r.user_query, r.employee_id, r.final_answer, r.config, r.totals, r.started_at, r.ended_at,
                  s.passed, s.failure_category, s.metrics
           FROM runs r LEFT JOIN scores s USING (run_id) WHERE TRUE"""
    p: dict[str, Any] = {"lim": limit}
    if label:
        q += " AND r.label=:label"
        p["label"] = label
    if status:
        q += " AND r.status=:status"
        p["status"] = status
    if mode:
        q += " AND r.mode=:mode"
        p["mode"] = mode
    if failed:
        q += " AND s.passed IS FALSE"
    q += " ORDER BY r.started_at DESC LIMIT :lim"
    with engine().connect() as c:
        return [_row(r) for r in c.execute(text(q), p)]


def latest_scored_runs(label: str) -> list[dict]:
    """One row per case: the most recent scored, counted run in the label."""
    with engine().connect() as c:
        rows = c.execute(text("""
            SELECT DISTINCT ON (r.case_id) r.*, s.passed, s.failure_category, s.metrics, s.judge_raw
            FROM runs r JOIN scores s USING (run_id)
            WHERE r.label=:l AND r.status = ANY(:st)
            ORDER BY r.case_id, r.fault, r.started_at DESC"""), {"l": label, "st": list(COUNTED)})
        return [_row(r) for r in rows]


def chaos_scored_runs(label: str) -> list[dict]:
    with engine().connect() as c:
        rows = c.execute(text("""
            SELECT DISTINCT ON (r.case_id, r.fault) r.*, s.passed, s.failure_category, s.metrics, s.judge_raw
            FROM runs r JOIN scores s USING (run_id)
            WHERE r.label=:l AND r.status = ANY(:st)
            ORDER BY r.case_id, r.fault, r.started_at DESC"""), {"l": label, "st": list(COUNTED)})
        return [_row(r) for r in rows]


def runs_in_label(label: str) -> list[dict]:
    with engine().connect() as c:
        rows = c.execute(text("""SELECT r.*, s.passed, s.failure_category, s.metrics, s.judge_raw
                                 FROM runs r LEFT JOIN scores s USING (run_id)
                                 WHERE r.label=:l ORDER BY r.started_at"""), {"l": label})
        return [_row(r) for r in rows]


def save_score(run_id: str, passed: bool, failure_category: str | None, metrics: dict, judge_raw: dict | None) -> None:
    with engine().begin() as c:
        c.execute(text("""INSERT INTO scores(run_id, passed, failure_category, metrics, judge_raw)
                          VALUES (:r, :p, :f, CAST(:m AS jsonb), CAST(:j AS jsonb))
                          ON CONFLICT (run_id) DO UPDATE SET passed=EXCLUDED.passed,
                            failure_category=EXCLUDED.failure_category, metrics=EXCLUDED.metrics,
                            judge_raw=EXCLUDED.judge_raw"""),
                  {"r": run_id, "p": passed, "f": failure_category, "m": _j(metrics), "j": _j(judge_raw)})


def set_showcase(run_id: str, value: bool = True) -> None:
    with engine().begin() as c:
        c.execute(text("UPDATE runs SET showcase=:v WHERE run_id=:r"), {"v": value, "r": run_id})


def labels_summary() -> list[dict]:
    with engine().connect() as c:
        rows = c.execute(text("""
            SELECT r.label, count(*) AS runs, count(s.run_id) AS scored,
                   sum(CASE WHEN s.passed THEN 1 ELSE 0 END) AS passed,
                   min(r.started_at) AS first_run, max(r.started_at) AS last_run,
                   bool_or(r.mode='chaos') AS is_chaos,
                   max(r.config->>'agent_model') AS agent_model,
                   max(r.config->>'prompt_version') AS prompt_version
            FROM runs r LEFT JOIN scores s USING (run_id)
            WHERE r.label IS NOT NULL GROUP BY r.label ORDER BY min(r.started_at)"""))
        return [_row(r) for r in rows]


def children_of(run_id: str) -> list[dict]:
    with engine().connect() as c:
        rows = c.execute(text("""SELECT run_id, mode, status, branch_seq, started_at FROM runs
                                 WHERE parent_run_id=:r ORDER BY started_at"""), {"r": run_id})
        return [_row(r) for r in rows]
