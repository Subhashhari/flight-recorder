"""Append/refresh the per-day call table (from quota_usage) in docs/quota-log.md."""

from flightrec.config import DOCS_DIR
from flightrec.recorder.store import quota_rows

MARK = "## Per-day calls"


def main() -> None:
    rows = quota_rows()
    table = ["| Day (Pacific) | Model | Calls |", "|---|---|---|"] + [
        f"| {r['day_pt']} | {r['model']} | {r['calls']} |" for r in rows]
    p = DOCS_DIR / "quota-log.md"
    text = p.read_text(encoding="utf-8") if p.exists() else "# Quota log\n\n"
    head = text.split(MARK)[0].rstrip()
    p.write_text(f"{head}\n\n{MARK}\n\nFrom the `quota_usage` table (calls counted by the limiter before each request;"
                 f" retries count).\n\n" + "\n".join(table) + "\n", encoding="utf-8")
    print("\n".join(table))


if __name__ == "__main__":
    main()
