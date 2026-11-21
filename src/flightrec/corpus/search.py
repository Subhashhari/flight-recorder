"""Hybrid retrieval: pgvector cosine top-20 + Postgres full-text top-20, fused by RRF (k=60)."""

from __future__ import annotations

from sqlalchemy import text

from flightrec.config import settings
from flightrec.corpus.embed import embed_query
from flightrec.db import engine, vec_literal

RRF_K = 60
CANDIDATES = 20


def _vector(c, q_vec: str, n: int = CANDIDATES):
    return [dict(r._mapping) for r in c.execute(text(
        """SELECT chunk_id, doc_id, text, 1 - (embedding <=> CAST(:q AS vector)) AS sim
           FROM chunks ORDER BY embedding <=> CAST(:q AS vector) LIMIT :n"""), {"q": q_vec, "n": n})]


def _fulltext(c, query: str, n: int = CANDIDATES):
    return [dict(r._mapping) for r in c.execute(text(
        """SELECT chunk_id, doc_id, text, ts_rank(tsv, plainto_tsquery('english', :q)) AS rank
           FROM chunks WHERE tsv @@ plainto_tsquery('english', :q)
           ORDER BY rank DESC LIMIT :n"""), {"q": query, "n": n})]


def rrf(*ranked_lists: list[dict], k: int = RRF_K) -> list[dict]:
    scores: dict[str, float] = {}
    rows: dict[str, dict] = {}
    for lst in ranked_lists:
        for rank, r in enumerate(lst, start=1):
            scores[r["chunk_id"]] = scores.get(r["chunk_id"], 0.0) + 1.0 / (k + rank)
            rows.setdefault(r["chunk_id"], r)
    order = sorted(scores, key=lambda cid: (-scores[cid], cid))
    return [{**rows[cid], "score": scores[cid]} for cid in order]


def search(query: str, mode: str = "hybrid", top_k: int | None = None) -> list[dict]:
    top_k = top_k or settings().retrieve_top_k
    qv = vec_literal(embed_query(query))
    with engine().connect() as c:
        vec = _vector(c, qv)
        if mode == "vector":
            fused = [{**r, "score": r["sim"]} for r in vec]
        elif mode == "hybrid":
            fused = rrf(vec, _fulltext(c, query))
        else:
            raise ValueError(f"mode must be hybrid or vector, not {mode!r}")
    return [{"chunk_id": r["chunk_id"], "doc_id": r["doc_id"], "text": r["text"], "score": round(float(r["score"]), 5)}
            for r in fused[:top_k]]


def max_similarity(query: str) -> tuple[float, str | None]:
    """Highest cosine similarity of any chunk to the query (used to drop answerable 'unanswerable' cases)."""
    with engine().connect() as c:
        rows = _vector(c, vec_literal(embed_query(query)), 1)
    return (float(rows[0]["sim"]), rows[0]["chunk_id"]) if rows else (0.0, None)


def sample_other_chunks(exclude_doc_ids: set, n: int, seed: int) -> list[dict]:
    """n random chunks from documents not in exclude_doc_ids (deterministic by seed)."""
    import random
    with engine().connect() as c:
        rows = [dict(r._mapping) for r in c.execute(text("SELECT chunk_id, doc_id, text FROM chunks ORDER BY chunk_id"))]
    pool = [r for r in rows if r["doc_id"] not in exclude_doc_ids] or rows
    rng = random.Random(seed)
    return rng.sample(pool, min(n, len(pool)))


def chunk_texts(chunk_ids: list[str]) -> dict[str, str]:
    with engine().connect() as c:
        return {r[0]: r[1] for r in c.execute(text("SELECT chunk_id, text FROM chunks WHERE chunk_id = ANY(:ids)"),
                                              {"ids": list(chunk_ids)})}


def doc_chunks(doc_id: str) -> list[dict]:
    with engine().connect() as c:
        return [dict(r._mapping) for r in c.execute(
            text("SELECT chunk_id, doc_id, text FROM chunks WHERE doc_id=:d ORDER BY ordinal"), {"d": doc_id})]
