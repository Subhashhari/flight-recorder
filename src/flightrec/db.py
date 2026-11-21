"""SQLAlchemy engine and schema creation."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine

from flightrec.config import settings

_engine: Engine | None = None


def engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(settings().database_url, pool_pre_ping=True)
    return _engine


def init_db() -> None:
    """Run schema.sql (idempotent). Uses the raw psycopg connection so multiple statements are allowed."""
    sql = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
    raw = engine().raw_connection()
    try:
        cur = raw.cursor()
        cur.execute(sql)
        raw.commit()
    finally:
        raw.close()


def vec_literal(v: list[float]) -> str:
    """pgvector text form; inserted as CAST(:emb AS vector)."""
    return "[" + ",".join(f"{x:.7g}" for x in v) + "]"
