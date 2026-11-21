"""API routes. Response shapes match the static demo export so the UI is identical in api and static mode."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from flightrec.config import DOCS_DIR
from flightrec.evals.export_static import _run_summary
from flightrec.recorder import store

router = APIRouter(prefix="/api")


@router.get("/runs")
def runs(label: str | None = None, status: str | None = None, limit: int = 500):
    return [_run_summary(r) for r in store.list_runs(label=label, status=status, limit=limit)]


@router.get("/runs/{run_id}")
def run(run_id: str):
    r = store.get_run(run_id)
    if r is None:
        raise HTTPException(404, "run not found")
    r["events"] = store.get_events(run_id)
    r["events_full"] = True
    r["children"] = store.children_of(run_id)
    return r


@router.get("/labels")
def labels():
    return {"labels": store.labels_summary(), "diffs": sorted(p.name for p in DOCS_DIR.glob("diff_*.html")),
            "showcase": [r["run_id"] for r in store.list_runs(limit=100000) if r["showcase"]]}


@router.get("/chaos")
def chaos(label: str):
    from flightrec.evals.chaos import chaos_matrix
    return chaos_matrix(label)


class ChatIn(BaseModel):
    query: str
    employee_id: str = "E1003"
    prompt_version: str | None = None
    label: str | None = None


class ReplayIn(BaseModel):
    run_id: str


class BranchIn(BaseModel):
    run_id: str
    step: int
    overrides: dict = Field(default_factory=dict)


def _out(res):
    return {"run_id": res.run_id, "status": res.status, "final_answer": res.final_answer, "error": res.error,
            "totals": res.totals}


@router.post("/chat")
async def chat(body: ChatIn):
    """Local only: uses your quota."""
    from flightrec.agents.executor import execute
    return _out(await execute(body.query, body.employee_id, label=body.label, prompt_version=body.prompt_version))


@router.post("/replay")
async def replay(body: ReplayIn):
    from flightrec.recorder.replay import replay as _replay
    return _out(await _replay(body.run_id))


@router.post("/branch")
async def branch(body: BranchIn):
    from flightrec.recorder.replay import branch as _branch
    try:
        return _out(await _branch(body.run_id, body.step, body.overrides))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
