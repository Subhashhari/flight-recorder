"""Mock internal systems for Northwind Labs (HRIS, IT ticketing, expenses). Synthetic data only."""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass, field

from flightrec.config import load_facts

GRADES = ["L1", "L2", "L3", "L4", "L5"]
TICKET_CATEGORIES = {"hardware", "software", "access", "network"}
EXPENSE_CATEGORIES = {"meals", "lodging", "travel", "equipment"}

FIRST = ["Aarav", "Diya", "Kabir", "Meera", "Rohan", "Ananya", "Vikram", "Isha", "Arjun", "Priya", "Nikhil", "Sara",
         "Dev", "Tara", "Karan", "Leela", "Omar", "Nina", "Rahul", "Zoya", "Aditya", "Kavya", "Samir", "Neha",
         "Farhan", "Riya", "Manav", "Pooja", "Ishaan", "Sana", "Varun", "Anika", "Yash", "Mira", "Kunal", "Asha",
         "Tanvi", "Rehan", "Gauri", "Aryan"]
LAST = ["Sharma", "Iyer", "Menon", "Rao", "Kapoor", "Nair", "Gupta", "Das", "Pillai", "Bose", "Joshi", "Khan",
        "Reddy", "Mehta", "Verma", "Chopra", "Kulkarni", "Banerjee", "Sinha", "Desai"]


def generate_employees(seed: int = 7, n: int = 40) -> list[dict]:
    """Deterministic synthetic employees E1001..E1040 (seed 7)."""
    rng = random.Random(seed)
    firsts = FIRST[:]
    rng.shuffle(firsts)
    grades = ["L5"] * 3 + ["L4"] * 6 + ["L3"] * 9 + ["L2"] * 11 + ["L1"] * (n - 29)
    rng.shuffle(grades)
    emps = []
    for i in range(n):
        emps.append({"employee_id": f"E{1001 + i}", "name": f"{firsts[i % len(firsts)]} {rng.choice(LAST)}",
                     "grade": grades[i], "manager_id": None, "casual": rng.randint(0, 12), "sick": rng.randint(0, 10),
                     "earned": rng.randint(0, 60) / 2})
    by_grade = {g: [e for e in emps if e["grade"] == g] for g in GRADES}
    for e in emps:
        gi = GRADES.index(e["grade"])
        if gi < len(GRADES) - 1:
            e["manager_id"] = rng.choice(by_grade[GRADES[gi + 1]])["employee_id"]
    return emps


def expense_limit(grade: str, category: str) -> int:
    return int(load_facts()["expense_limits_inr_per_day"][category][grade])


# ------------------------------------------------------------------ repositories
@dataclass
class MemoryRepo:
    employees: dict = field(default_factory=lambda: {e["employee_id"]: dict(e) for e in generate_employees()})
    tickets: list = field(default_factory=list)
    claims: list = field(default_factory=list)

    def all_employees(self):
        return list(self.employees.values())

    def get(self, employee_id):
        return self.employees.get(employee_id)

    def add_ticket(self, t):
        self.tickets.append(t)

    def add_claim(self, c):
        self.claims.append(c)


class DbRepo:
    def _q(self, sql, p=None):
        from sqlalchemy import text

        from flightrec.db import engine
        with engine().begin() as c:
            r = c.execute(text(sql), p or {})
            return [dict(x._mapping) for x in r] if r.returns_rows else []

    @staticmethod
    def _norm(e):
        e = dict(e)
        e["earned"] = float(e["earned"])
        return e

    def all_employees(self):
        return [self._norm(e) for e in self._q("SELECT * FROM employees ORDER BY employee_id")]

    def get(self, employee_id):
        rows = self._q("SELECT * FROM employees WHERE employee_id=:e", {"e": employee_id})
        return self._norm(rows[0]) if rows else None

    def add_ticket(self, t):
        self._q("INSERT INTO tickets(ticket_id, employee_id, category, description, status) "
                "VALUES (:ticket_id, :employee_id, :category, :description, :status)", t)

    def add_claim(self, c):
        self._q("INSERT INTO expense_claims(claim_id, employee_id, category, amount_inr, description, status) "
                "VALUES (:claim_id, :employee_id, :category, :amount_inr, :description, :status)", c)


class MockBackend:
    def __init__(self, repo=None):
        self.repo = repo or DbRepo()

    def lookup_employee(self, name: str) -> dict:
        n = (name or "").strip().lower()
        emps = self.repo.all_employees()
        hit = [e for e in emps if e["name"].lower() == n] or [e for e in emps if e["name"].lower().split()[0] == n]
        if len(hit) != 1:
            return {"error": "not_found"}
        e = hit[0]
        mgr = self.repo.get(e["manager_id"]) if e["manager_id"] else None
        return {"employee_id": e["employee_id"], "name": e["name"], "grade": e["grade"],
                "manager": mgr["name"] if mgr else None}

    def get_leave_balance(self, employee_id: str) -> dict:
        e = self.repo.get((employee_id or "").strip().upper())
        if not e:
            return {"error": "not_found"}
        return {"employee_id": e["employee_id"], "casual": e["casual"], "sick": e["sick"], "earned": e["earned"]}

    def create_it_ticket(self, employee_id: str, category: str, description: str) -> dict:
        e = self.repo.get((employee_id or "").strip().upper())
        if not e:
            return {"error": "not_found"}
        category = (category or "").strip().lower()
        if category not in TICKET_CATEGORIES:
            return {"error": "invalid_category"}
        tid = f"IT-{uuid.uuid4().hex[:8].upper()}"
        self.repo.add_ticket({"ticket_id": tid, "employee_id": e["employee_id"], "category": category,
                              "description": description or "", "status": "open"})
        return {"ticket_id": tid, "status": "open"}

    def submit_expense_claim(self, employee_id: str, category: str, amount_inr: float, description: str) -> dict:
        e = self.repo.get((employee_id or "").strip().upper())
        if not e:
            return {"error": "not_found"}
        category = (category or "").strip().lower()
        if category not in EXPENSE_CATEGORIES:
            return {"error": "invalid_category"}
        limit = expense_limit(e["grade"], category)
        if float(amount_inr) > limit:
            return {"error": "over_limit", "limit": limit}
        cid = f"EXP-{uuid.uuid4().hex[:8].upper()}"
        self.repo.add_claim({"claim_id": cid, "employee_id": e["employee_id"], "category": category,
                             "amount_inr": float(amount_inr), "description": description or "", "status": "submitted"})
        return {"claim_id": cid, "status": "submitted"}


_default: MockBackend | None = None


def default_backend() -> MockBackend:
    global _default
    if _default is None:
        _default = MockBackend()
    return _default
