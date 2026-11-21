"""Chunk + embed the corpus into `chunks` (truncate and reload: idempotent)."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from flightrec.config import CORPUS_DIR, settings
from flightrec.corpus.chunking import chunk_csv, chunk_text
from flightrec.corpus.embed import embed_texts
from flightrec.db import engine, vec_literal


def pdf_text(path: Path) -> str:
    import pymupdf
    with pymupdf.open(path) as doc:
        return "\n".join(page.get_text() for page in doc)


def corpus_files(corpus_dir: Path = CORPUS_DIR) -> list[Path]:
    return sorted(p for p in corpus_dir.iterdir() if p.is_file() and p.suffix.lower() in (".md", ".pdf", ".csv"))


def load_document(path: Path) -> tuple[str, str]:
    """Returns (kind, text) as ingest sees it."""
    suf = path.suffix.lower()
    if suf == ".pdf":
        return "pdf", pdf_text(path)
    return suf[1:], path.read_text(encoding="utf-8")


def build_chunks(corpus_dir: Path = CORPUS_DIR) -> list[dict]:
    s = settings()
    out = []
    for p in corpus_files(corpus_dir):
        kind, body = load_document(p)
        if kind == "csv":
            pieces = chunk_csv(body, p.stem.replace("_", " "))
        else:
            pieces = chunk_text(body, s.chunk_chars, s.chunk_overlap, markdown=(kind == "md"))
        out += [{"chunk_id": f"{p.stem}#{i}", "doc_id": p.stem, "ordinal": i, "text": t} for i, t in enumerate(pieces)]
    return out


def ingest(corpus_dir: Path = CORPUS_DIR) -> dict:
    chunks = build_chunks(corpus_dir)
    if not chunks:
        raise SystemExit(f"no corpus files in {corpus_dir} (run scripts/gen_corpus.py and scripts/make_pdfs.py)")
    vecs = embed_texts([c["text"] for c in chunks], "RETRIEVAL_DOCUMENT")
    with engine().begin() as c:
        c.execute(text("TRUNCATE chunks"))
        c.execute(text("""INSERT INTO chunks(chunk_id, doc_id, ordinal, text, embedding)
                          VALUES (:chunk_id, :doc_id, :ordinal, :text, CAST(:emb AS vector))"""),
                  [{**ch, "emb": vec_literal(v)} for ch, v in zip(chunks, vecs, strict=True)])
    docs = sorted({c["doc_id"] for c in chunks})
    return {"documents": len(docs), "chunks": len(chunks), "doc_ids": docs}
