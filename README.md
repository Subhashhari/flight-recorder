# Flight Recorder

**A flight recorder for LLM agents: it traces every step of a 5-agent Google ADK pipeline, replays runs
deterministically, branches them at any step, injects faults to find failure modes, and diffs behaviour across prompt
or model changes.**

- **Live demo (static, read-only):** https://subhashhari.github.io/flight-recorder/
- **Demo video:** _coming soon_
- **Results:** [`docs/results.md`](docs/results.md) (every number there is produced by a command shown next to it)
- **New to agents, RAG or evals?** [`docs/explained/`](docs/explained/README.md) explains the whole project from zero:
  motivation, architecture, how replay works, chaos, evaluation, every design decision and its alternatives, the
  bugs we hit, and interview preparation.

Built on the Gemini API free tier (and Gemma if used). Costs are list-price equivalents; actual spend ₹0.

## What it does

| Capability | What it does |
|---|---|
| Trace | Every LLM call, tool call and retrieval with tokens, latency, list-price-equivalent cost |
| Replay | Re-executes a recorded run from cache: zero LLM calls, works with `GOOGLE_API_KEY=dummy` |
| Branch | Replays up to step N, then runs live with a changed model / temperature / instruction |
| Chaos | Injects 8 fault types (tool timeouts, HTTP 500, malformed payloads, empty or irrelevant retrieval, prompt injection…) and classifies failures |
| Eval | LLM judge + programmatic scoring, retrieval recall@5 / MRR, latency/token/cost percentiles |
| Diff | Compares two eval labels: flipped cases and metric deltas (CLI + static HTML) |
| UI | Runs list, five-lane run timeline with inspector, chaos heatmap |

The subject under test, **PolicyDesk**, is an internal help-desk assistant for a synthetic company (Northwind Labs):
`planner → researcher → operator → writer → verifier`, with hybrid retrieval (pgvector + Postgres full-text, RRF) and
four mock back-office tools (employee lookup, leave balance, IT tickets, expense claims).

## Results

See [`docs/results.md`](docs/results.md). It is regenerated from stored runs with `uv run flightrec report` and
stays empty until the eval and chaos runs below are done. No number is written by hand.

## Architecture

```
Local machine (Docker Postgres + uv)                               GitHub Pages (static)
┌──────────────────────────────────────────────────────────┐      ┌──────────────────────┐
│ CLI → executor.execute() → ADK Runner → SequentialAgent  │      │ React UI + demo-data │
│   planner → researcher → operator → writer → verifier    │      └───────────▲──────────┘
│   every LlmAgent has Recorder callbacks                  │                  │ export-static
│     ├─ Limiter.acquire(model, est_tokens)  RPM/TPM/RPD   │                  │
│     ├─ live / replay / branch / chaos behaviour          │──────────────────┘
│     └─ buffered events → Postgres (runs, events, scores) │
│ FastAPI on 127.0.0.1:8000 serves the same UI (api mode)  │
└───────────────┬──────────────────────────────────────────┘
                ▼
        Gemini API (free tier)
```

Details, replay semantics and the verified ADK callback behaviour: [`docs/architecture.md`](docs/architecture.md).

## Run it in 5 commands (replay works with a dummy key)

```bash
git clone https://github.com/Subhashhari/flight-recorder.git && cd flight-recorder
cp .env.example .env                 # GOOGLE_API_KEY=dummy is enough for replaying the archive
make db-up                           # Postgres 16 + pgvector in Docker
make demo                            # schema + import data/exports/traces.jsonl.gz
make api   # and in a second terminal: make ui   → http://localhost:5173
```

Windows without `make`: `.\tasks.ps1 db-up`, `.\tasks.ps1 demo`, `.\tasks.ps1 api`, `.\tasks.ps1 ui`.
If port 5432 is already taken, set `FLIGHTREC_DB_PORT=5433` in `.env` and use `:5433` in `DATABASE_URL`.
Requirements: Docker, [uv](https://docs.astral.sh/uv/), Node ≥ 20.

## Reproduce everything (needs a free AI Studio key)

```bash
make probe                           # resolves model IDs, runs probes P1–P8, picks Plan A/B and the tier
make spike                           # records ADK facts (a)–(g) into docs/architecture.md
make db-up db-init seed
make corpus                          # 10 policy docs via the judge model + 2 CSVs, then PDFs
uv run flightrec check-facts         # fix flagged numbers in data/corpus/*.md, re-run until clean
make ingest
make cases                           # eval-case candidates
uv run flightrec review-cases        # human accept / reject / edit
uv run flightrec eval --label smoke-1 --limit 3
make eval LABEL=baseline-v1          # resumable; sleeps until the quota reset with --wait
uv run flightrec eval-retrieval --mode hybrid && uv run flightrec eval-retrieval --mode vector
make chaos LABEL=chaos-baseline-v1
PROMPT_VERSION=v2 make eval LABEL=hardened-v2
PROMPT_VERSION=v2 make chaos LABEL=chaos-hardened-v2
uv run flightrec diff baseline-v1 hardened-v2
uv run flightrec diff chaos-baseline-v1 chaos-hardened-v2
uv run flightrec repeatability && uv run flightrec replay-check --label baseline-v1
uv run flightrec label && uv run flightrec judge-agreement
uv run flightrec report              # regenerates docs/results.md
uv run flightrec export-static && uv run flightrec export-traces
```

All CLI commands: `uv run flightrec --help`. Tests: `make test` (offline; no network, no DB) and
`uv run pytest -m integration` (needs the Docker DB, still no API key).

## What I built vs existing tools (Langfuse, LangSmith)

Langfuse and LangSmith are excellent hosted observability products: tracing, prompt management, datasets and LLM-judge
evals. Flight Recorder overlaps on tracing and evals, but focuses on three things they don't centre:
**deterministic replay** of a whole multi-agent run from its recording (zero API calls, verifiable via request hashes
and `divergence` events), **branching** a recorded run at step N with a changed model, temperature or instruction, and a
**fault-injection suite** with an automatic failure taxonomy, all under a quota-aware, resumable runner built for
free-tier rate limits. It is a self-contained tool over one pipeline, not a general platform. In production I would export
the same spans to an observability backend rather than replace it.

## Honesty notes

Synthetic data only (Northwind Labs); not production. Costs are list-price equivalents from
[`config/pricing.yaml`](config/pricing.yaml) (Gemma has no paid list price and is recorded as $0). Per-fault chaos rates
come from small samples and are exploratory. "Gemini API" means the Gemini Developer API (AI Studio), not Vertex AI.
