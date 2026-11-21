"""PDF conversion round-trip: markdown -> reportlab PDF -> pymupdf text (what ingest reads)."""

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate

from flightrec.corpus.ingest import pdf_text
from scripts.make_pdfs import md_to_flowables


def test_markdown_to_pdf_roundtrip(tmp_path):
    md = ("# Expense Policy\n\n## 1. Limits\n\nDaily limits are below.\n\n| Category | L1 | L2 |\n|---|---|---|\n"
          "| Meals | ₹800 | ₹1,000 |\n\n- Keep **receipts**\n- Submit within *30* days\n")
    p = tmp_path / "x.pdf"
    SimpleDocTemplate(str(p), pagesize=A4).build(md_to_flowables(md))
    text = pdf_text(p)
    for s in ("Expense Policy", "1. Limits", "Meals", "800", "1,000", "receipts"):
        assert s in text
