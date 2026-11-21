"""Eval cases: data/eval/candidates.jsonl (generated) -> review -> data/eval/cases.jsonl (accepted only)."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from flightrec.config import EVAL_DIR

CANDIDATES = EVAL_DIR / "candidates.jsonl"
ACCEPTED = EVAL_DIR / "cases.jsonl"
CATEGORIES = ("qa", "unanswerable", "action", "multi")


class ToolCall(BaseModel):
    name: str
    args: dict = Field(default_factory=dict)


class Case(BaseModel):
    id: str
    category: str
    employee_id: str
    query: str
    gold_answer: str
    gold_doc_ids: list[str] = Field(default_factory=list)
    expected_tool_calls: list[ToolCall] = Field(default_factory=list)
    must_abstain: bool = False
    status: str = "candidate"  # candidate | accepted | rejected


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def load_cases(path: Path = ACCEPTED, status: str | None = "accepted") -> list[Case]:
    cases = [Case.model_validate(r) for r in read_jsonl(path)]
    return [c for c in cases if status is None or c.status == status]


def save_cases(cases: list[Case], path: Path) -> None:
    write_jsonl(path, [c.model_dump() for c in cases])


def case_map(path: Path = ACCEPTED) -> dict[str, Case]:
    return {c.id: c for c in load_cases(path, status=None)}
