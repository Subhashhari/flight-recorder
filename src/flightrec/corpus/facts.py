"""check-facts: every assigned fact must appear in its document; every other number is flagged."""

from __future__ import annotations

import re
from pathlib import Path

from flightrec.config import CORPUS_DIR, CORPUS_SRC_DIR, load_facts

# document id -> facts.yaml sections (guide 6.1.2)
DOC_FACTS: dict[str, list[str]] = {
    "leave_policy": ["leave"], "remote_work": ["remote_work"], "it_security": ["it_security"],
    "device_policy": ["devices"], "onboarding": ["onboarding"], "data_handling": ["data_handling"],
    "support_escalation": ["escalation"], "expense_policy": ["expense_limits_inr_per_day"],
    "travel_policy": ["travel", "expense_limits_inr_per_day"], "code_of_conduct": ["code_of_conduct"],
}
PDF_DOCS = {"expense_policy", "travel_policy", "code_of_conduct"}
DOC_TITLES = {
    "leave_policy": "Leave Policy", "remote_work": "Remote Work Policy", "it_security": "IT Security Policy",
    "device_policy": "Device Policy", "onboarding": "Onboarding Guide", "data_handling": "Data Handling Policy",
    "support_escalation": "IT Support Escalation Policy", "expense_policy": "Expense Policy",
    "travel_policy": "Travel Policy", "code_of_conduct": "Code of Conduct",
}

NUM = re.compile(r"(?<![\w.:/-])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(?![\w])")
YEARS = {2025, 2026, 2027}


def doc_path(doc_id: str) -> Path:
    return (CORPUS_SRC_DIR if doc_id in PDF_DOCS else CORPUS_DIR) / f"{doc_id}.md"


def facts_subset(doc_id: str, facts: dict | None = None) -> dict:
    facts = facts or load_facts()
    return {sec: facts[sec] for sec in DOC_FACTS[doc_id]}


def _leaves(d, prefix=""):
    if isinstance(d, dict):
        for k, v in d.items():
            yield from _leaves(v, f"{prefix}.{k}" if prefix else str(k))
    elif isinstance(d, list):
        for i, v in enumerate(d):
            yield from _leaves(v, f"{prefix}[{i}]")
    else:
        yield prefix, d


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def _norm_text(t: str) -> str:
    return re.sub(r"\s+", " ", t.replace("–", "-").replace("—", "-").replace("₹", "Rs ")).lower()


def numbers_in(text: str) -> list[tuple[float, int]]:
    return [(_num(m.group(1) + (m.group(2) or "")), m.start()) for m in NUM.finditer(text)]


def _strip_structure(text: str) -> str:
    """Blank out heading numbering and list indices so they are not reported as extra numbers."""
    out = []
    for line in text.splitlines():
        line = re.sub(r"^(\s*#{1,6}\s*)(\d+(\.\d+)*\.?)", lambda m: m.group(1) + " " * len(m.group(2)), line)
        line = re.sub(r"^(\s*)(\d+(\.\d+)*[.)])(\s)", lambda m: m.group(1) + " " * len(m.group(2)) + m.group(4), line)
        out.append(line)
    return "\n".join(out)


def load_ignores(path: Path | None = None) -> dict[str, set[float]]:
    """data/corpus/.factignore lines: `doc_id: 42` or `*: 42` (comments with #)."""
    path = path or CORPUS_DIR / ".factignore"
    ign: dict[str, set[float]] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if ":" in line:
                d, n = line.split(":", 1)
                try:
                    ign.setdefault(d.strip(), set()).add(_num(n.strip()))
                except ValueError:
                    pass
    return ign


def check_document(doc_id: str, text: str, facts: dict | None = None, ignores: dict | None = None) -> list[dict]:
    sub = facts_subset(doc_id, facts)
    ignores = ignores if ignores is not None else load_ignores()
    issues: list[dict] = []
    norm = _norm_text(text)
    present = {n for n, _ in numbers_in(text)}
    allowed: set[float] = set()
    for key, val in _leaves(sub):
        if isinstance(val, bool) or key.endswith("_source"):
            continue
        if isinstance(val, int | float):
            allowed.add(float(val))
            if float(val) not in present:
                issues.append({"doc": doc_id, "issue": f"missing fact {key}={val}", "snippet": ""})
        else:
            s = str(val)
            allowed |= {float(x) for x in re.findall(r"\d+(?:\.\d+)?", s)}
            if _norm_text(s).replace(" ", "") not in norm.replace(" ", ""):
                issues.append({"doc": doc_id, "issue": f"missing fact {key}={s!r}", "snippet": ""})
    skip = allowed | YEARS | ignores.get(doc_id, set()) | ignores.get("*", set())
    stripped = _strip_structure(text)
    seen = set()
    for n, pos in numbers_in(stripped):
        if n in skip or n in seen:
            continue
        seen.add(n)
        snippet = text[max(0, pos - 40):pos + 40].replace("\n", " ")
        issues.append({"doc": doc_id, "issue": f"extra number {n:g}", "snippet": snippet})
    return issues


def check_all() -> tuple[list[dict], list[str]]:
    facts, ignores = load_facts(), load_ignores()
    issues, missing_docs = [], []
    for doc_id in DOC_FACTS:
        p = doc_path(doc_id)
        if not p.exists():
            missing_docs.append(doc_id)
            continue
        issues += check_document(doc_id, p.read_text(encoding="utf-8"), facts, ignores)
    return issues, missing_docs
