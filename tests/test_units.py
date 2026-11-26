"""Unit tests: backend, chunking, fact checker, metrics, chaos selection, RRF, prompts, pricing."""

import pytest

from flightrec.agents.prompts import V1, V2, get_prompts
from flightrec.agents.tools import safe_tool
from flightrec.backend.mock_backend import MemoryRepo, MockBackend, generate_employees
from flightrec.corpus.chunking import chunk_csv, chunk_text, recursive_split
from flightrec.corpus.facts import check_document
from flightrec.corpus.search import rrf
from flightrec.evals.cases import Case, ToolCall
from flightrec.evals.chaos import select_cases
from flightrec.evals.metrics import clean_success, failure_category, percentile, retrieval_metrics, tool_match
from flightrec.recorder.core import request_hash
from flightrec.recorder.pricing import list_cost


# ---------------------------------------------------------------- backend
def test_employees_deterministic_and_well_formed():
    a, b = generate_employees(), generate_employees()
    assert a == b and len(a) == 40
    assert a[0]["employee_id"] == "E1001" and a[-1]["employee_id"] == "E1040"
    assert len({e["name"] for e in a}) == 40
    for e in a:
        assert e["grade"] in ("L1", "L2", "L3", "L4", "L5")
        assert 0 <= e["casual"] <= 12 and 0 <= e["sick"] <= 10 and 0 <= e["earned"] <= 30
        assert (e["manager_id"] is None) == (e["grade"] == "L5")


def test_backend_functions():
    be = MockBackend(MemoryRepo())
    emps = generate_employees()
    e = next(x for x in emps if x["grade"] == "L2")
    assert be.get_leave_balance(e["employee_id"]) == {"employee_id": e["employee_id"], "casual": e["casual"],
                                                      "sick": e["sick"], "earned": e["earned"]}
    assert be.get_leave_balance("E9999") == {"error": "not_found"}
    found = be.lookup_employee(e["name"].upper())
    assert found["employee_id"] == e["employee_id"] and found["manager"]
    assert be.lookup_employee("Nobody Here") == {"error": "not_found"}
    t = be.create_it_ticket(e["employee_id"], "Hardware", "broken")
    assert t["status"] == "open" and t["ticket_id"].startswith("IT-")
    assert be.create_it_ticket(e["employee_id"], "plumbing", "x") == {"error": "invalid_category"}
    ok = be.submit_expense_claim(e["employee_id"], "meals", 900, "lunch")  # L2 meals limit 1000
    assert ok["status"] == "submitted"
    assert be.submit_expense_claim(e["employee_id"], "meals", 1001, "lunch") == {"error": "over_limit", "limit": 1000}
    assert be.submit_expense_claim(e["employee_id"], "toys", 1, "x") == {"error": "invalid_category"}


# ---------------------------------------------------------------- chunking
def test_chunking_heading_split_and_overlap():
    md = "# Title\nintro\n## 1. Purpose\n" + ("word " * 400) + "\n## 2. Scope\nshort"
    chunks = chunk_text(md, 300, 50)
    assert all(len(c) <= 360 for c in chunks)
    assert any(c.startswith("## 2. Scope") for c in chunks)
    parts = recursive_split("a " * 500, 100, 20)
    assert len(parts) > 5 and all(len(p) <= 125 for p in parts)


def test_chunk_csv_prefixes_columns():
    rows = chunk_csv("date,holiday\n2027-01-01,New Year's Day\n", "holidays 2027")
    assert rows == ["holidays 2027: date: 2027-01-01; holiday: New Year's Day"]


# ---------------------------------------------------------------- facts
def test_check_facts_missing_and_extra():
    text = "# Leave\n## 1. Entitlement\nYou get 12 casual and 10 sick days, 18 earned days, accruing 1.5 per month." \
           " Carry forward up to 30 days. Certificate after 3 days. Call 555 for help. Since 2026."
    issues = check_document("leave_policy", text, ignores={})
    assert [i for i in issues if i["issue"].startswith("missing")] == []
    extra = [i["issue"] for i in issues if i["issue"].startswith("extra")]
    assert extra == ["extra number 555"]
    issues2 = check_document("leave_policy", "12 casual days", ignores={})
    assert any("sick_per_year=10" in i["issue"] for i in issues2)


def test_check_facts_thousands_separator_and_strings():
    text = ("Remote work up to 3 days per week. Core hours are 11:00–16:00 IST. Approval by your line manager.")
    assert check_document("remote_work", text, ignores={}) == []
    exp = "Meals L1 ₹800, L2 1,000, L3 1,500, L4 2,500, L5 4,000. Lodging 4,000 5,000 7,000 10,000 15,000. " \
          "Travel 3,000 4,000 6,000 9,000 15,000. Equipment 5,000 5,000 10,000 15,000 25,000."
    assert check_document("expense_policy", exp, ignores={}) == []


# ---------------------------------------------------------------- metrics
def test_retrieval_metrics():
    assert retrieval_metrics(["a", "b", "c"], ["b"]) == {"recall_at_5": 1.0, "mrr": 0.5}
    assert retrieval_metrics(["a"], ["z"]) == {"recall_at_5": 0.0, "mrr": 0.0}
    assert retrieval_metrics(["a"], []) == {"recall_at_5": None, "mrr": None}


def test_tool_match_subset_and_order_insensitive():
    exp = [{"name": "submit_expense_claim", "args": {"employee_id": "E1007", "category": "meals", "amount_inr": 900}},
           {"name": "get_leave_balance", "args": {"employee_id": "E1007"}}]
    act = [{"name": "get_leave_balance", "args": {"employee_id": "e1007"}},
           {"name": "submit_expense_claim", "args": {"employee_id": "E1007", "category": "Meals", "amount_inr": 900.0,
                                                     "description": "dinner"}}]
    assert tool_match(exp, act)
    assert not tool_match(exp, act[:1])
    assert not tool_match([{"name": "get_leave_balance", "args": {"employee_id": "E1"}}], act)
    assert tool_match([], act)


def test_clean_success_rules():
    v = {"correct": True, "grounded": True, "abstained": False, "reports_actions_accurately": True}
    assert clean_success("qa", v, False)
    assert not clean_success("qa", {**v, "grounded": False}, True)
    assert clean_success("unanswerable", {**v, "abstained": True}, False)
    assert not clean_success("action", v, False) and clean_success("action", v, True)
    assert not clean_success("multi", {**v, "correct": False}, True)


def test_failure_category_order():
    ev = []
    assert failure_category("crash", None, ev, "E1003", None, True) == "crash"
    assert failure_category("budget_exceeded", "sorry", ev, "E1003", None, True) == "budget_exceeded"
    assert failure_category("ok", "done CANARY-7731", ev, "E1003", {"claims_unsupported_result": True}, True) == \
        "followed_injection"
    tick = [{"seq": 0, "type": "tool_call", "name": "create_it_ticket", "request": {"args": {"employee_id": "E1001"}},
             "response": {}}]
    assert failure_category("ok", "done", tick, "E1003", {}, True) == "followed_injection"
    assert failure_category("ok", "done", tick, "E1001", {"acknowledges_failure": True}, True) is None
    assert failure_category("ok", "x", ev, "E1003", {"claims_unsupported_result": True}, True) == "hallucinated_result"
    assert failure_category("ok", "x", ev, "E1003", {"hallucinated_policy": True}, True) == "hallucinated_policy"
    assert failure_category("ok", "x", ev, "E1003", {"acknowledges_failure": False}, True) == "ungraceful"
    assert failure_category("ok", "x", ev, "E1003", {"acknowledges_failure": False}, False) is None


def test_percentile():
    assert percentile([1, 2, 3, 4], 50) == 2.5
    assert percentile([5], 95) == 5
    assert percentile([], 50) is None


# ---------------------------------------------------------------- chaos selection
def _case(i, cat):
    return Case(id=f"{cat}-{i}", category=cat, employee_id="E1003", query="q", gold_answer="g",
                expected_tool_calls=[ToolCall(name="get_leave_balance", args={})] if cat != "qa" else [])


def test_select_cases_deterministic_and_applicable():
    cases = [_case(i, c) for i in range(10) for c in ("qa", "action", "multi", "unanswerable")]
    a = select_cases(cases, "tool_http_500", 6)
    assert a == select_cases(list(reversed(cases)), "tool_http_500", 6)
    assert len(a) == 6 and {c.category for c in a} <= {"action", "multi"}
    r = select_cases(cases, "retrieval_empty", 6)
    assert {c.category for c in r} <= {"qa", "multi"}
    assert [c.id for c in a] != [c.id for c in select_cases(cases, "tool_timeout", 6)]


# ---------------------------------------------------------------- misc
def test_rrf_fuses_ranks():
    v = [{"chunk_id": "a"}, {"chunk_id": "b"}, {"chunk_id": "c"}]
    t = [{"chunk_id": "c"}, {"chunk_id": "a"}]
    assert [r["chunk_id"] for r in rrf(v, t)] == ["a", "c", "b"]


def test_request_hash_ignores_volatile_ids():
    c1 = [{"parts": [{"function_call": {"name": "x", "args": {}, "id": "adk-1"}}]}]
    c2 = [{"parts": [{"function_call": {"name": "x", "args": {}, "id": "adk-2"}}]}]
    assert request_hash("m", "s", c1, ["x"]) == request_hash("m", "s", c2, ["x"])
    assert request_hash("m", "s", c1, ["x"]) != request_hash("m", "s2", c1, ["x"])


def test_prompts_have_no_stray_braces_and_v2_appends():
    import re
    allowed = {"plan", "evidence", "action_result", "draft"}
    for p in (V1, V2):
        for k in ("PLANNER", "RESEARCHER", "OPERATOR", "WRITER", "VERIFIER"):
            assert set(re.findall(r"\{(\w+)\}", getattr(p, k))) <= allowed
            assert getattr(p, k).count("{") == getattr(p, k).count("}")
    assert V2.WRITER.startswith(V1.WRITER) and "NO_EVIDENCE" in V2.WRITER
    assert V2.PLANNER == V1.PLANNER
    with pytest.raises(ValueError):
        get_prompts("v3")


def test_safe_tool_converts_errors_and_keeps_signature():
    import inspect

    def boom(employee_id: str) -> dict:
        """Doc."""
        raise RuntimeError("db down")

    w = safe_tool(boom)
    assert w("E1") == {"error": "RuntimeError", "message": "db down", "retryable": False}
    assert w.__name__ == "boom" and str(inspect.signature(w)) == "(employee_id: str) -> dict"


def test_list_cost():
    assert list_cost("gemini-3.5-flash-lite", 1_000_000, 1_000_000) == pytest.approx(2.80)
    assert list_cost("gemma-4-31b-it", 10**6, 10**6) == 0.0
    assert list_cost("unknown-model", 10**6, 10**6) == 0.0


def test_ticket_and_claim_ids_are_stable_and_idempotent():
    repo = MemoryRepo()
    be = MockBackend(repo)
    a = be.create_it_ticket("E1007", "hardware", "laptop screen flickers")
    b = be.create_it_ticket("e1007 ", "Hardware", "laptop screen flickers ")  # same request, different spelling
    c = be.create_it_ticket("E1007", "hardware", "keyboard broken")
    assert a == b and a["ticket_id"] != c["ticket_id"]
    assert len(repo.tickets) == 2  # the retried request did not create a second ticket
    assert MockBackend(MemoryRepo()).create_it_ticket("E1007", "hardware", "laptop screen flickers") == a
    e = next(x for x in generate_employees() if x["grade"] == "L2")
    x = be.submit_expense_claim(e["employee_id"], "meals", 900, "lunch")
    y = be.submit_expense_claim(e["employee_id"], "meals", 900.0, "lunch")
    z = be.submit_expense_claim(e["employee_id"], "meals", 800, "lunch")
    assert x == y and x["claim_id"] != z["claim_id"] and len(repo.claims) == 2


def test_repeatability_attempt_cap(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    import flightrec.agents.executor as ex
    from flightrec.evals import repro

    rows: list[dict] = []
    monkeypatch.setattr(repro.store, "runs_in_label", lambda label: list(rows))
    calls = {"n": 0}

    async def always_crash(query, employee_id, **kw):
        calls["n"] += 1
        row = {"run_id": f"r{calls['n']}", "case_id": kw["case_id"], "status": "crash", "final_answer": None}
        rows.append(row)
        return SimpleNamespace(status="crash", row=lambda: row)

    monkeypatch.setattr(ex, "execute", always_crash)
    case = SimpleNamespace(id="C1", category="policy_qa", query="q", employee_id="E1001")
    out = asyncio.run(repro._repeatability([case], repeats=3, wait=False))
    assert calls["n"] == 3 + repro.EXTRA_ATTEMPTS
    assert out["cases"] == 0 and out["skipped"][0]["attempts"] == 5
    # a restart does not spend more: attempts already in the database count towards the cap
    asyncio.run(repro._repeatability([case], repeats=3, wait=False))
    assert calls["n"] == 5
