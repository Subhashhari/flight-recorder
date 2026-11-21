"""PolicyDesk tools: plain functions with docstrings and type hints (ADK builds declarations from them)."""

from __future__ import annotations

import concurrent.futures as cf
import functools

from flightrec.backend.mock_backend import default_backend

TOOL_TIMEOUT_S = 5.0
_pool = cf.ThreadPoolExecutor(max_workers=4, thread_name_prefix="safe_tool")


def search_policies(query: str) -> dict:
    """Search the Northwind Labs company policy documents.

    Args:
        query: what to look for, in plain words.

    Returns:
        {"results": [{"chunk_id", "doc_id", "text"}, ...]} with the most relevant passages first.
    """
    from flightrec.corpus.search import search
    rows = search(query, mode="hybrid")
    return {"results": [{"chunk_id": r["chunk_id"], "doc_id": r["doc_id"], "text": r["text"]} for r in rows]}


def lookup_employee(name: str) -> dict:
    """Look up an employee by full name or first name.

    Args:
        name: the employee's name.

    Returns:
        {"employee_id", "name", "grade", "manager"} or {"error": "not_found"}.
    """
    return default_backend().lookup_employee(name)


def get_leave_balance(employee_id: str) -> dict:
    """Get an employee's remaining leave balance in days.

    Args:
        employee_id: id like E1003.

    Returns:
        {"employee_id", "casual", "sick", "earned"} or {"error": "not_found"}.
    """
    return default_backend().get_leave_balance(employee_id)


def create_it_ticket(employee_id: str, category: str, description: str) -> dict:
    """Open an IT support ticket.

    Args:
        employee_id: id like E1003.
        category: one of hardware, software, access, network.
        description: short description of the problem or request.

    Returns:
        {"ticket_id", "status": "open"} or {"error": "invalid_category"}.
    """
    return default_backend().create_it_ticket(employee_id, category, description)


def submit_expense_claim(employee_id: str, category: str, amount_inr: float, description: str) -> dict:
    """Submit an expense claim. The amount is checked against the per-day limit for the employee's grade.

    Args:
        employee_id: id like E1003.
        category: one of meals, lodging, travel, equipment.
        amount_inr: amount in Indian rupees.
        description: what the expense was for.

    Returns:
        {"claim_id", "status": "submitted"}, or {"error": "over_limit", "limit": N} when above the grade limit.
    """
    return default_backend().submit_expense_claim(employee_id, category, amount_inr, description)


def safe_tool(fn):
    """v2 hardening: catch exceptions, 5 s timeout, one retry; return an error dict instead of raising."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        last: dict = {}
        for attempt in range(2):
            fut = _pool.submit(fn, *args, **kwargs)
            try:
                return fut.result(timeout=TOOL_TIMEOUT_S)
            except cf.TimeoutError:
                last = {"error": "TimeoutError", "message": f"tool did not respond within {TOOL_TIMEOUT_S:g}s",
                        "retryable": True}
            except Exception as e:  # noqa: BLE001 - converting any tool failure into data is the point
                last = {"error": type(e).__name__, "message": str(e)[:300], "retryable": attempt == 0}
        return last

    return wrapper


SEARCH_TOOLS = {"search_policies": search_policies}
ACTION_TOOLS = {"lookup_employee": lookup_employee, "get_leave_balance": get_leave_balance,
                "create_it_ticket": create_it_ticket, "submit_expense_claim": submit_expense_claim}


def get_tools(prompt_version: str = "v1", overrides: dict | None = None) -> dict:
    """name -> callable. `overrides` swaps implementations (tests); v2 wraps every tool in safe_tool()."""
    tools = {**SEARCH_TOOLS, **ACTION_TOOLS, **(overrides or {})}
    if prompt_version == "v2":
        tools = {k: safe_tool(v) for k, v in tools.items()}
    return tools
