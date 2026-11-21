"""Shared offline fixtures: fake model, in-memory backend, fake search, in-memory limiter. No network, no DB."""

from __future__ import annotations

import pytest

from flightrec.backend.mock_backend import MemoryRepo, MockBackend
from flightrec.recorder.ratelimit import Limiter
from flightrec.recorder.store import MemoryQuotaStore
from flightrec.testing.fake_llm import register

register()

CORPUS = [
    {"chunk_id": "leave_policy#0", "doc_id": "leave_policy",
     "text": "Employees receive 10 days of sick leave per year. A medical certificate is needed after 3 days."},
    {"chunk_id": "leave_policy#1", "doc_id": "leave_policy",
     "text": "Employees receive 12 days of casual leave and 18 days of earned leave per year."},
    {"chunk_id": "expense_policy#0", "doc_id": "expense_policy",
     "text": "Meal limits per day: L1 800, L2 1000, L3 1500, L4 2500, L5 4000 INR."},
    {"chunk_id": "it_security#0", "doc_id": "it_security",
     "text": "Passwords must have at least 14 characters. MFA is mandatory."},
    {"chunk_id": "remote_work#0", "doc_id": "remote_work",
     "text": "Employees may work from home up to 3 days per week with line manager approval."},
    {"chunk_id": "device_policy#0", "doc_id": "device_policy",
     "text": "Laptops are refreshed every 36 months. Report a lost device within 24 hours."},
]


def fake_search(query: str) -> dict:
    words = {w for w in query.lower().split() if len(w) > 3}
    scored = sorted(CORPUS, key=lambda c: -sum(w in c["text"].lower() for w in words))
    return {"results": [dict(c) for c in scored[:3]]}


def fake_sampler(exclude, n, seed):
    import random
    pool = [c for c in CORPUS if c["doc_id"] not in exclude]
    return random.Random(seed).sample(pool, min(n, len(pool)))


def make_tools(backend: MockBackend):
    def search_policies(query: str) -> dict:
        """Search policies."""
        return fake_search(query)

    def lookup_employee(name: str) -> dict:
        """Look up employee."""
        return backend.lookup_employee(name)

    def get_leave_balance(employee_id: str) -> dict:
        """Leave balance."""
        return backend.get_leave_balance(employee_id)

    def create_it_ticket(employee_id: str, category: str, description: str) -> dict:
        """IT ticket."""
        return backend.create_it_ticket(employee_id, category, description)

    def submit_expense_claim(employee_id: str, category: str, amount_inr: float, description: str) -> dict:
        """Expense claim."""
        return backend.submit_expense_claim(employee_id, category, amount_inr, description)

    return {f.__name__: f for f in (search_policies, lookup_employee, get_leave_balance, create_it_ticket,
                                    submit_expense_claim)}


@pytest.fixture
def backend():
    return MockBackend(MemoryRepo())


@pytest.fixture
def tools(backend):
    return make_tools(backend)


class Clock:
    def __init__(self):
        self.t = 1000.0
        self.slept: list[float] = []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


@pytest.fixture
def limiter():
    return Limiter(MemoryQuotaStore(), {"fake-agent": {"rpm": 1000, "tpm": 10**9, "rpd": 10**9}})


@pytest.fixture
def run_kwargs(tools, limiter):
    """Common execute() kwargs for offline runs (nothing saved)."""
    saved = {}

    def save(run, events):
        saved[run["run_id"]] = (run, events)

    return dict(model="fake-agent", tools=tools, limiter=limiter, chunk_sampler=fake_sampler, record=True,
                save=save, retry_waits=(0, 0, 0)), saved
