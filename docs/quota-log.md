# Quota log

## Model probe

Not run yet: needs a Gemini API key in `.env`. Run `uv run python scripts/model_probe.py`; it overwrites this file
with the resolved model IDs, the probe results (P1–P8), the automatic Plan A/B decision and the tier.

Console quotas (AI Studio rate-limit page, read 2026-11-18):

| Console name | RPM | TPM | RPD |
|---|---|---|---|
| Gemma 4 31B / 26B | 30 | 16,000 | 14,400 |
| Gemini 3.5 / 3.1 Flash Lite | 15 | 250,000 | 500 |
| Gemini Embedding | 100 | 30,000 | 1,000 |

## Per-day calls

Dump with `uv run python scripts/quota_dump.py` (reads the `quota_usage` table).
