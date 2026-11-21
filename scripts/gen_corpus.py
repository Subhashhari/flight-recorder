"""Generate the Northwind Labs corpus (guide 6.1.2): 10 documents by the judge model (through the limiter),
2 CSVs directly from data/facts.yaml. Existing documents are kept unless --force (saves quota).

PDF documents (expense_policy, travel_policy, code_of_conduct) are written as markdown to data/corpus/src/ and
converted by scripts/make_pdfs.py.
"""

from __future__ import annotations

import csv
import json
import sys

import yaml

from flightrec.config import CORPUS_DIR, CORPUS_SRC_DIR, load_facts, settings
from flightrec.corpus.facts import DOC_FACTS, DOC_TITLES, doc_path, facts_subset
from flightrec.llm import generate_text

PROMPT = ("Write the Northwind Labs {title} (700–1100 words, numbered sections, at least one table where natural). "
          "Use ONLY these facts exactly as given and invent no other numbers: {facts_subset}. "
          "Realistic corporate policy in plain language.")
SYSTEM = ("You write internal policy documents in Markdown. Start with a level-1 heading with the document title. "
          "Use level-2 headings for numbered sections like '## 1. Purpose'. Write numbers as digits. Do not add "
          "effective dates, version numbers, phone numbers, or any number not given in the facts.")


def write_csvs(facts: dict) -> None:
    with open(CORPUS_DIR / "holidays_2027.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "holiday"])
        for h in facts["holidays_2027"]:
            d, name = h.split(" ", 1)
            w.writerow([d, name])
    with open(CORPUS_DIR / "expense_limits.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["category", "grade", "limit_inr_per_day"])
        for cat, grades in facts["expense_limits_inr_per_day"].items():
            for g, v in grades.items():
                w.writerow([cat, g, v])


def main() -> None:
    force = "--force" in sys.argv
    only = [a for a in sys.argv[1:] if not a.startswith("--")]
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    CORPUS_SRC_DIR.mkdir(parents=True, exist_ok=True)
    facts = load_facts()
    write_csvs(facts)
    print("wrote holidays_2027.csv, expense_limits.csv")
    model = settings().judge_model
    if model in ("", "TBD"):
        raise SystemExit("JUDGE_MODEL not set: run scripts/model_probe.py first")
    for doc_id in DOC_FACTS:
        if only and doc_id not in only:
            continue
        p = doc_path(doc_id)
        if p.exists() and not force:
            print(f"keep {p.relative_to(CORPUS_DIR.parent.parent)} (use --force to regenerate)")
            continue
        sub = yaml.safe_dump(facts_subset(doc_id, facts), sort_keys=False, allow_unicode=True).strip()
        text = generate_text(model, PROMPT.format(title=DOC_TITLES[doc_id], facts_subset=sub), system=SYSTEM,
                             temperature=0.4)
        text = text.strip().removeprefix("```markdown").removeprefix("```").removesuffix("```").strip()
        p.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {p.name} ({len(text.split())} words)")
    print(json.dumps({"next": "uv run python scripts/make_pdfs.py && uv run flightrec check-facts"}))


if __name__ == "__main__":
    main()
