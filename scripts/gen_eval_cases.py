"""Generate eval-case candidates (guide 6.1.8): 120 % of each category target from config/scale.yaml.

qa: the judge model proposes question / gold answer per document (through the limiter).
unanswerable: the judge model proposes out-of-corpus questions; any with a chunk similarity > 0.8 is dropped.
action, multi: templated in code (seed 11), expected tool calls computed programmatically from facts + employees.
Requires: model_probe (models), gen_corpus + make_pdfs, db-init + seed + ingest.  Output: data/eval/candidates.jsonl
"""

from __future__ import annotations

import math
import random
import sys

from pydantic import BaseModel

from flightrec.backend.mock_backend import expense_limit, generate_employees
from flightrec.config import load_facts, load_scale, settings
from flightrec.corpus.facts import DOC_FACTS, DOC_TITLES, doc_path
from flightrec.evals.cases import CANDIDATES, Case, ToolCall, load_cases, save_cases
from flightrec.llm import generate_json

ABSTAIN_GOLD = "Not covered by Northwind Labs policy: the assistant should say it could not find this in company " \
               "policy (and may suggest contacting HR/IT) rather than invent an answer."


class QA(BaseModel):
    question: str
    answer: str


class QAList(BaseModel):
    items: list[QA]


class QList(BaseModel):
    questions: list[str]


def _n(target: int) -> int:
    return math.ceil(target * 1.2)


def gen_qa(n_total: int, rng: random.Random, emps: list[dict]) -> list[Case]:
    model = settings().judge_model
    docs = list(DOC_FACTS)
    per = math.ceil(n_total / len(docs))
    out: list[Case] = []
    for doc_id in docs:
        p = doc_path(doc_id)
        if not p.exists():
            print(f"skip {doc_id}: missing")
            continue
        text = p.read_text(encoding="utf-8")
        prompt = (f"Here is the Northwind Labs {DOC_TITLES[doc_id]}:\n\n<document>\n{text}\n</document>\n\n"
                  f"Write {per} distinct questions an employee might realistically ask that this document answers "
                  "precisely and unambiguously. Each gold answer must be one short sentence stating the exact fact "
                  "(numbers as digits) from the document. Do not mention the document in the question. Prefer facts "
                  "with numbers, durations, approvers or conditions.")
        items = generate_json(model, prompt, QAList, temperature=0.3)["items"][:per]
        for it in items:
            out.append(Case(id=f"qa-{len(out) + 1:03d}", category="qa", employee_id=rng.choice(emps)["employee_id"],
                            query=it["question"].strip(), gold_answer=it["answer"].strip(), gold_doc_ids=[doc_id]))
    facts = load_facts()
    for h in rng.sample(facts["holidays_2027"], 2):  # 2 templated CSV questions
        d, name = h.split(" ", 1)
        out.append(Case(id=f"qa-{len(out) + 1:03d}", category="qa", employee_id=rng.choice(emps)["employee_id"],
                        query=f"On what date is the {name} holiday in 2027?", gold_answer=f"{name} is on {d}.",
                        gold_doc_ids=["holidays_2027"]))
    return out


def gen_unanswerable(n: int, rng: random.Random, emps: list[dict]) -> list[Case]:
    from flightrec.corpus.search import max_similarity
    titles = ", ".join(DOC_TITLES.values()) + ", Holiday calendar 2027, Expense limits table"
    prompt = (f"Northwind Labs has internal documents on exactly these topics: {titles}. Write {n + 6} plausible "
              "questions an employee might ask the HR/IT help desk that these documents would NOT answer (for example "
              "topics like stock options, parental-leave pay, cafeteria menus, parking, pension contributions, "
              "relocation bonuses). One sentence each, varied, no numbering.")
    qs = generate_json(settings().judge_model, prompt, QList, temperature=0.7)["questions"]
    out: list[Case] = []
    for q in qs:
        sim, chunk = max_similarity(q)
        if sim > 0.8:
            print(f"drop (similarity {sim:.2f} to {chunk}): {q}")
            continue
        out.append(Case(id=f"unans-{len(out) + 1:03d}", category="unanswerable",
                        employee_id=rng.choice(emps)["employee_id"], query=q.strip(), gold_answer=ABSTAIN_GOLD,
                        must_abstain=True))
        if len(out) >= n:
            break
    return out


SYSTEMS = ["finance shared drive", "HR analytics dashboard", "GitHub organisation", "design team Figma workspace",
           "sales CRM", "production database read replica"]
HW = ["My laptop battery no longer charges", "My laptop keyboard has stopped working", "My monitor keeps flickering",
      "My laptop's trackpad is broken", "My headset microphone does not work"]
CITIES = ["Pune", "Mumbai", "Bengaluru", "Hyderabad", "Chennai", "Delhi"]


def _amount(rng, limit, under=True) -> int:
    x = limit * rng.uniform(0.45, 0.9) if under else limit * rng.uniform(1.15, 1.6)
    return int(round(x / 10) * 10)


def gen_action(n: int, rng: random.Random, emps: list[dict]) -> list[Case]:
    by_id = {e["employee_id"]: e for e in emps}
    out: list[Case] = []
    for i in range(n):
        e = rng.choice(emps)
        eid, t = e["employee_id"], i % 6
        if t == 0:
            q, calls = "What is my leave balance?", [ToolCall(name="get_leave_balance", args={"employee_id": eid})]
            gold = f"Leave balance: casual {e['casual']}, sick {e['sick']}, earned {e['earned']:g} days."
        elif t == 1:
            q = f"{rng.choice(HW)}. Please raise an IT ticket."
            calls = [ToolCall(name="create_it_ticket", args={"employee_id": eid, "category": "hardware"})]
            gold = "A hardware IT ticket was opened; the reply gives the ticket id returned by the system."
        elif t == 2:
            q = f"I need access to the {rng.choice(SYSTEMS)}. Please open a ticket for it."
            calls = [ToolCall(name="create_it_ticket", args={"employee_id": eid, "category": "access"})]
            gold = "An access IT ticket was opened; the reply gives the ticket id returned by the system."
        elif t == 3:
            x = _amount(rng, expense_limit(e["grade"], "meals"))
            q = f"Please file a meals expense of ₹{x} for a team lunch today."
            calls = [ToolCall(name="submit_expense_claim", args={"employee_id": eid, "category": "meals",
                                                                 "amount_inr": x})]
            gold = f"The ₹{x} meals claim was submitted; the reply gives the claim id."
        elif t == 4:
            target = rng.choice([x for x in emps if x["manager_id"] and x["employee_id"] != eid])
            q = f"Who is {target['name']}'s manager?"
            calls = [ToolCall(name="lookup_employee", args={"name": target["name"]})]
            gold = f"{target['name']}'s manager is {by_id[target['manager_id']]['name']}."
        else:
            x = _amount(rng, expense_limit(e["grade"], "lodging"))
            q = f"Submit a lodging claim of ₹{x} for my hotel stay in {rng.choice(CITIES)} last night."
            calls = [ToolCall(name="submit_expense_claim", args={"employee_id": eid, "category": "lodging",
                                                                 "amount_inr": x})]
            gold = f"The ₹{x} lodging claim was submitted; the reply gives the claim id."
        out.append(Case(id=f"act-{i + 1:03d}", category="action", employee_id=eid, query=q, gold_answer=gold,
                        expected_tool_calls=calls))
    return out


def gen_multi(n: int, rng: random.Random, emps: list[dict]) -> list[Case]:
    facts = load_facts()
    out: list[Case] = []
    for i in range(n):
        e = rng.choice(emps)
        eid, g, t = e["employee_id"], e["grade"], i % 5
        if t in (0, 1, 2):
            cat, phrase, what = [("meals", "meal limit", "dinner with a client"),
                                 ("lodging", "hotel (lodging) limit", f"my hotel stay in {rng.choice(CITIES)}"),
                                 ("travel", "daily travel limit", "cab fares to the client site")][t]
            lim = expense_limit(g, cat)
            under = rng.random() < 0.5
            x = _amount(rng, lim, under)
            q = f"What's my {phrase}, and please file ₹{x} for {what}."
            calls = [ToolCall(name="submit_expense_claim", args={"employee_id": eid, "category": cat, "amount_inr": x})]
            outcome = "the claim was submitted (claim id given)" if under else \
                f"the claim was rejected as over the ₹{lim} limit"
            gold = f"The {cat} limit for grade {g} is ₹{lim} per day; for ₹{x} {outcome}."
            docs = ["expense_policy"]
        elif t == 3:
            q = "How many sick leave days do I get per year, and how many do I have left?"
            calls = [ToolCall(name="get_leave_balance", args={"employee_id": eid})]
            gold = f"Employees get {facts['leave']['sick_per_year']} sick leave days per year; you have {e['sick']} left."
            docs = ["leave_policy"]
        else:
            q = "What's the minimum password length, and please raise an access ticket because I'm locked out."
            calls = [ToolCall(name="create_it_ticket", args={"employee_id": eid, "category": "access"})]
            gold = (f"Passwords must be at least {facts['it_security']['password_min_chars']} characters; an access "
                    "ticket was opened (ticket id given).")
            docs = ["it_security"]
        out.append(Case(id=f"multi-{i + 1:03d}", category="multi", employee_id=eid, query=q, gold_answer=gold,
                        gold_doc_ids=docs, expected_tool_calls=calls))
    return out


def main() -> None:
    only = set(sys.argv[1:])  # optional: subset of qa unanswerable action multi
    t = load_scale()["eval"]
    rng = random.Random(11)
    emps = generate_employees()
    for d in DOC_FACTS:
        if not doc_path(d).exists():
            raise SystemExit(f"corpus document {d} missing: run gen_corpus.py first")
    existing = load_cases(CANDIDATES, status=None)
    keep = [c for c in existing if only and c.category not in only]
    new: list[Case] = []
    if not only or "action" in only:
        new += gen_action(_n(t["action"]), rng, emps)
    if not only or "multi" in only:
        new += gen_multi(_n(t["multi"]), rng, emps)
    if not only or "qa" in only:
        new += gen_qa(_n(t["qa"]), rng, emps)
    if not only or "unanswerable" in only:
        new += gen_unanswerable(_n(t["unanswerable"]), rng, emps)
    allc = keep + new
    save_cases(allc, CANDIDATES)
    counts = {k: sum(1 for c in allc if c.category == k) for k in ("qa", "unanswerable", "action", "multi")}
    print(f"wrote {CANDIDATES} {counts} (targets {t}); next: uv run flightrec review-cases")


if __name__ == "__main__":
    main()
