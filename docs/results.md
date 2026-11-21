# Results (all numbers produced by the commands shown)
Plan: ? · Agent model: TBD · Judge model: TBD · Embedding model: TBD · Tier: TBD · Commit: unknown · Date: 2026-11-21

Synthetic data (Northwind Labs). Costs are list-price equivalents (config/pricing.yaml); actual spend Rs 0. Statistics exclude `rate_limited` and `paused` runs.

Regenerate with `uv run flightrec report`.

## Clean eval
Command: `flightrec eval --label <label>`

| Label | Cases | Success % | qa | unanswerable | action | multi | Halluc. % | p50 s | p95 s | tokens/run | list-price $/run |
|---|---|---|---|---|---|---|---|---|---|---|---|
| (no clean eval completed yet) |||||||||||| 

Success % = mean of per-category success rates. Per-category n: 

## Retrieval
Command: `flightrec eval-retrieval --mode hybrid|vector` (qa + multi cases with gold docs)

| Mode | n | recall@5 | MRR |
|---|---|---|---|
| hybrid | — | not run yet | — |
| vector | — | not run yet | — |

## Chaos
Command: `flightrec chaos --label <label> --faults all`. Per-fault rates from small samples are exploratory.

(no chaos run completed yet)

## Reproducibility
Commands: `flightrec repeatability`, `flightrec replay-check --label L`, `flightrec stats --label L`

| live runs differing | replay identical | tracing overhead |
|---|---|---|
| — | — | — |

## Judge agreement
Command: `flightrec label` then `flightrec judge-agreement`

| labels n | agreement % |
|---|---|
| — | not labelled yet |

