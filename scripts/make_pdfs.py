"""Convert data/corpus/src/{expense_policy,travel_policy,code_of_conduct}.md to PDF (reportlab Platypus)."""

from __future__ import annotations

import re
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from flightrec.config import CORPUS_DIR, CORPUS_SRC_DIR
from flightrec.corpus.facts import PDF_DOCS

STYLES = getSampleStyleSheet()


def inline(s: str) -> str:
    s = escape(s.replace("₹", "Rs "))
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    return re.sub(r"(?<!\*)\*(?!\*)(.+?)\*", r"<i>\1</i>", s)


def md_to_flowables(md: str) -> list:
    out, table, para = [], [], []

    def flush_para():
        if para:
            out.append(Paragraph(inline(" ".join(para)), STYLES["BodyText"]))
            para.clear()

    def flush_table():
        if table:
            rows = [r for r in table if not re.match(r"^\s*\|?\s*:?-{2,}", r)]
            data = [[Paragraph(inline(c.strip()), STYLES["BodyText"]) for c in r.strip().strip("|").split("|")]
                    for r in rows]
            t = Table(data, repeatRows=1)
            t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                                   ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
                                   ("VALIGN", (0, 0), (-1, -1), "TOP")]))
            out.extend([t, Spacer(1, 8)])
            table.clear()

    for line in md.splitlines():
        s = line.rstrip()
        if s.strip().startswith("|"):
            flush_para()
            table.append(s)
            continue
        flush_table()
        if not s.strip():
            flush_para()
            continue
        m = re.match(r"^(#{1,6})\s+(.*)", s)
        if m:
            flush_para()
            style = {1: "Title", 2: "Heading2"}.get(len(m.group(1)), "Heading3")
            out.append(Paragraph(inline(m.group(2)), STYLES[style]))
            continue
        m = re.match(r"^\s*([-*]|\d+[.)])\s+(.*)", s)
        if m:
            flush_para()
            bullet = "•" if m.group(1) in "-*" else m.group(1)
            out.append(Paragraph(f"{escape(bullet)} {inline(m.group(2))}", STYLES["BodyText"]))
            continue
        para.append(s.strip())
    flush_para()
    flush_table()
    return out


def main() -> None:
    for doc_id in sorted(PDF_DOCS):
        src = CORPUS_SRC_DIR / f"{doc_id}.md"
        if not src.exists():
            print(f"skip {doc_id}: {src} missing (run gen_corpus.py)")
            continue
        dst = CORPUS_DIR / f"{doc_id}.pdf"
        doc = SimpleDocTemplate(str(dst), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, title=doc_id,
                                author="Northwind Labs (synthetic)", invariant=1)
        doc.build(md_to_flowables(src.read_text(encoding="utf-8")))
        print(f"wrote {dst.name}")


if __name__ == "__main__":
    main()
