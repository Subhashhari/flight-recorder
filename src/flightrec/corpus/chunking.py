"""Heading split, then recursive character split with overlap; CSV = one chunk per row."""

from __future__ import annotations

import csv
import io
import re

SEPARATORS = ["\n\n", "\n", ". ", " "]
_HEADING = re.compile(r"^#{1,6}\s", re.M)


def split_headings(text: str) -> list[str]:
    starts = [m.start() for m in _HEADING.finditer(text)]
    if not starts or starts[0] != 0:
        starts = [0] + starts
    parts = [text[a:b].strip() for a, b in zip(starts, starts[1:] + [len(text)], strict=False)]
    return [p for p in parts if p]


def _split(text: str, size: int, seps: list[str]) -> list[str]:
    if len(text) <= size:
        return [text]
    for i, sep in enumerate(seps):
        if sep in text:
            pieces = text.split(sep)
            out, cur = [], ""
            for p in pieces:
                cand = f"{cur}{sep}{p}" if cur else p
                if len(cand) <= size:
                    cur = cand
                    continue
                if cur:
                    out.append(cur)
                if len(p) > size:
                    out.extend(_split(p, size, seps[i + 1:]))
                    cur = ""
                else:
                    cur = p
            if cur:
                out.append(cur)
            return out
    return [text[i:i + size] for i in range(0, len(text), size)]


def recursive_split(text: str, size: int, overlap: int) -> list[str]:
    base = _split(text, size, SEPARATORS)
    if overlap <= 0 or len(base) < 2:
        return base
    out = [base[0]]
    for prev, cur in zip(base, base[1:], strict=False):
        tail = prev[-overlap:]
        sp = tail.find(" ")
        tail = tail[sp + 1:] if 0 <= sp < len(tail) - 1 else tail
        out.append(f"{tail} {cur}".strip())
    return out


def chunk_text(text: str, size: int, overlap: int, *, markdown: bool = True) -> list[str]:
    sections = split_headings(text) if markdown else [text]
    chunks: list[str] = []
    for s in sections:
        chunks.extend(c.strip() for c in recursive_split(s, size, overlap) if c.strip())
    return chunks


def chunk_csv(text: str, title: str = "") -> list[str]:
    rows = list(csv.DictReader(io.StringIO(text)))
    prefix = f"{title}: " if title else ""
    return [prefix + "; ".join(f"{k}: {v}" for k, v in r.items()) for r in rows]
