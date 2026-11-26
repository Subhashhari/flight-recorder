"""Embeddings (768-d) through the limiter; query embeddings cached in Postgres.

`fake-embed` is a local hashed bag-of-words embedder for offline tests only.
"""

from __future__ import annotations

import hashlib
import math
import re

from flightrec.config import is_fake, settings

DIM = 768
BATCH = 50


def fake_embed(text: str) -> list[float]:
    v = [0.0] * DIM
    for tok in re.findall(r"[a-z0-9]+", text.lower()):
        h = int(hashlib.md5(tok.encode()).hexdigest()[:8], 16)
        v[h % DIM] += 1.0 if (h >> 12) & 1 else -1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def embed_texts(texts: list[str], task_type: str, model: str | None = None) -> list[list[float]]:
    model = model or settings().embed_model
    if is_fake(model):
        return [fake_embed(t) for t in texts]
    from google.genai import types

    from flightrec.runtime import genai_client, limiter
    out: list[list[float]] = []
    for i in range(0, len(texts), BATCH):
        batch = texts[i:i + BATCH]
        # the free tier counts every text in a batch as one request (RPM and RPD), so acquire len(batch) requests
        limiter().acquire(model, int(sum(len(t) for t in batch) / 4) + 64, n=len(batch))
        r = genai_client().models.embed_content(
            model=model, contents=batch,
            config=types.EmbedContentConfig(task_type=task_type, output_dimensionality=DIM))
        for e in r.embeddings:
            if len(e.values) != DIM:
                raise ValueError(f"expected {DIM} dimensions, got {len(e.values)}")
            out.append(list(e.values))
    return out


def embed_query(text_: str, model: str | None = None) -> list[float]:
    """RETRIEVAL_QUERY embedding, cached in query_embeddings."""
    from sqlalchemy import text

    from flightrec.db import engine, vec_literal
    model = model or settings().embed_model
    h = hashlib.sha256(text_.encode()).hexdigest()
    with engine().connect() as c:
        row = c.execute(text("""SELECT embedding::text FROM query_embeddings
                                WHERE model=:m AND task_type='RETRIEVAL_QUERY' AND text_hash=:h"""),
                        {"m": model, "h": h}).first()
    if row:
        return [float(x) for x in row[0].strip("[]").split(",")]
    v = embed_texts([text_], "RETRIEVAL_QUERY", model)[0]
    with engine().begin() as c:
        c.execute(text("""INSERT INTO query_embeddings(model, task_type, text_hash, embedding)
                          VALUES (:m, 'RETRIEVAL_QUERY', :h, CAST(:e AS vector)) ON CONFLICT DO NOTHING"""),
                  {"m": model, "h": h, "e": vec_literal(v)})
    return v
