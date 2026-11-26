"""Automated stand-in for `flightrec review-cases` (used 2026-11-27, see DEEPDIVE 11.2).

Accepts candidates in file order up to each category's tier target, skipping the ids in REJECT, and keeps any
decisions already made by a human in data/eval/cases.jsonl. Writes data/eval/cases.jsonl (accepted only),
data/eval/rejected.jsonl and data/eval/validation.json (which cases a human reviewed and which were auto-validated).

The automated checks behind REJECT (gold numbers vs facts.yaml and the gold document, expense limits and over/under
verdicts, leave balances and managers vs the seeded employees, duplicates) are described in DEEPDIVE 11.2.
"""

from __future__ import annotations

import json

from flightrec.config import EVAL_DIR, load_scale
from flightrec.evals.cases import ACCEPTED, CANDIDATES, CATEGORIES, load_cases, save_cases

REJECT = {
    "act-007": "exact duplicate of act-001 (same employee and query)",
    "qa-014": "gold answer ('notify the IT Manager') is not in data/facts.yaml; invented by the document generator",
    "qa-018": "same fact as qa-015 (L3 meal limit)",
    # coverage: in file order the 15 qa slots filled before travel_policy, code_of_conduct and holidays_2027 had a
    # case, so one case of each same-document pair (or one whose fact multi cases already test) is dropped
    "qa-005": "coverage: password length is already tested by multi-005 / multi-010",
    "qa-008": "coverage: device_policy keeps qa-007",
    "qa-010": "coverage: onboarding keeps qa-009",
    "qa-012": "coverage: data_handling keeps qa-011",
    "qa-016": "coverage: expense_policy keeps qa-015 (multi cases also test expense limits)",
}
HUMAN_ACCEPTED = {"act-001", "act-002"}  # accepted by a human in `flightrec review-cases` on 2026-11-27


def main() -> None:
    targets = load_scale()["eval"]
    human = {c.id: c for c in load_cases(CANDIDATES, status=None) if c.id in HUMAN_ACCEPTED}
    for c in human.values():
        c.status = "accepted"
    counts = {k: sum(1 for c in human.values() if c.category == k and c.status == "accepted") for k in CATEGORIES}
    decided = dict(human)
    method = {cid: "human" for cid in human}
    for c in load_cases(CANDIDATES, status=None):
        if c.id in decided or counts[c.category] >= targets[c.category]:
            continue
        c.status = "rejected" if c.id in REJECT else "accepted"
        decided[c.id] = c
        method[c.id] = "auto"
        if c.status == "accepted":
            counts[c.category] += 1
    save_cases([c for c in decided.values() if c.status == "accepted"], ACCEPTED)
    save_cases([c for c in decided.values() if c.status == "rejected"], EVAL_DIR / "rejected.jsonl")
    out = {"method": method, "reject_reasons": {k: v for k, v in REJECT.items() if k in decided},
           "accepted_counts": counts, "targets": targets,
           "note": "auto = validated by automated checks, not read by a human (DEEPDIVE 11.2)"}
    (EVAL_DIR / "validation.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps({"accepted": counts, "targets": targets,
                      "human": sum(v == "human" for v in method.values()),
                      "auto": sum(v == "auto" for v in method.values())}))


if __name__ == "__main__":
    main()
