# Flight Recorder: one-page summary

**A flight recorder for LLM agents.** It traces every step of a five-agent pipeline, replays any run deterministically
with zero API calls, branches a run at any step with a changed model or prompt, injects faults to find failure modes,
and compares versions before a change ships. Built on the Gemini API free tier for ₹0.

**Repo:** github.com/Subhashhari/flight-recorder · **Status (2026-11-25):** all code built and tested offline; the evaluation runs
that need the API key have not run yet, so no result numbers exist.

## Problem

LLM agents fail in ways that are hard to explain and hard to reproduce. The same question can give a different answer
tomorrow. A tool outage can make an agent claim an action succeeded. A document can contain text that hijacks the
agent. Teams change prompts and models without knowing what got better or worse. The simulated customer is an IT/HR
operations lead running an internal help desk.

## What I built

- **The system under test (PolicyDesk):** a five-agent help-desk assistant for a synthetic company
  (planner → researcher → operator → writer → verifier) on Google ADK. It has hybrid retrieval over 12 policy documents
  (Markdown, PDF, CSV) and 4 tools that act on mock HR, IT and expense systems with 40 synthetic employees.
- **Trace:** every model call, tool call and retrieval is recorded with latency, tokens and list-price-equivalent cost.
  This is done through ADK callbacks and is the only framework-specific code.
- **Deterministic replay:** a recorded run is re-executed from cache with zero API calls and works with a dummy key.
  A request fingerprint (SHA-256, with volatile IDs stripped) reports every step where a replay diverges.
- **Branching:** a run is replayed up to step N, then continues live with a changed model, temperature or instruction.
  This answers "what if we had changed X at that step?".
- **Fault injection:** 8 fault types (tool timeout, HTTP 500, malformed or empty or partial payloads, empty or
  irrelevant retrieval, prompt injection). Each run gets one label from an ordered failure taxonomy, and the results
  form a fault × failure matrix.
- **Hardening:** exactly 5 named fixes (a tool error wrapper and 4 prompt rules), compared before and after on the same
  cases.
- **Evaluation:** an 80-case set (Plan A) or 40-case set (Plan B) in 4 categories: policy Q&A, questions with no
  answer in the documents, actions, and mixed requests. Scoring combines an LLM judge (schema-checked JSON) with code
  checks of tool calls, and 20 human labels measure how far the judge can be trusted. Metrics: macro-averaged success,
  hallucination rate, recall@5 and MRR, p50/p95 latency, tokens and cost per run. A diff lists every case that flipped
  between two versions.
- **Quota-aware runner:** my own rate limiter covers requests/minute, tokens/minute and a stored daily count that
  resets at midnight Pacific. Runs retry on 429 errors, pause when the daily quota is spent and resume after the reset.
  Runs can be re-scored without being re-run.
- **Interfaces:** a 24-command CLI, a FastAPI backend and a 3-page React UI (run timeline with an inspector, a fault
  heatmap). The same UI runs as a free static demo on GitHub Pages, and a trace archive lets anyone replay real runs
  locally.

## Tech stack

Python 3.12 · Google ADK · Gemini API (Gemma 4 / Gemini Flash Lite, Gemini embeddings) · PostgreSQL 16 + pgvector
(HNSW) + full-text search · Reciprocal Rank Fusion · FastAPI · SQLAlchemy 2 · Typer · pydantic · React + TypeScript +
Vite + recharts · Docker / Docker Compose · GitHub Actions (CI + Pages) · uv · pytest · ruff · reportlab / PyMuPDF

## Key engineering decisions (interview talking points)

- **I built the recorder myself instead of using Langfuse or LangSmith.** Replay, branching and fault injection all
  need to *replace* model and tool results mid-run, and observability tools only watch.
- **Cached responses are found by (agent, call number), not by fingerprint.** A changed request is then reported as a
  divergence instead of stopping the replay.
- **The model is picked automatically.** A probe script runs 8 checks (system instructions, tool calling, output
  format, JSON mode, embedding size) and picks the agent and judge models by a fixed rule. The judge is always a
  different model from the agent, which avoids self-grading bias and keeps their quotas separate.
- **All data is synthetic, and every number comes from one facts file.** An automatic checker flags any generated
  document that contradicts that file.
- **Hybrid retrieval with RRF.** Vector search catches meaning and keyword search catches exact codes such as "L3",
  "MFA" and "P1". RRF fuses the two by rank, so the scores need no tuning.
- **Bug I found and fixed:** Postgres JSONB re-orders keys, and ADK puts tool results into later prompts as
  order-sensitive text, so replays loaded from the database were not faithful. The request fingerprint caught it, and
  storing events as JSON fixed it.
- **Honesty by design:** the results file is generated only from stored runs, test-model runs are excluded
  automatically, costs are stated as list-price equivalents, and sample sizes are always shown.

## Facts you can state now

- 5 agents, 4 tools, 12 policy documents, 40 synthetic employees, 8 fault types, 24 CLI commands, 3 UI pages
- Rate limiter covering requests/minute, tokens/minute and requests/day, with pause and resume across quota days
- 43 automated tests: 41 run offline through the real ADK framework with a scripted fake model, and 2 are database
  integration tests. CI runs lint, the offline tests and a Docker build on every push.
- Total spend: ₹0 (Gemini API free tier)

## Resume bullets (fill each placeholder only from `docs/results.md` after the runs)

1. Built a tracing and deterministic replay/branching toolkit for a 5-agent LLM pipeline (Google ADK, Gemini API).
   Recorder overhead was **[X %]** of run time. Live temperature-0 runs differed in **[Y %]** of **[N]** cases, while
   replay reproduced **100 %** with zero API calls.
2. Designed a fault-injection suite (**8** fault types, **[R]** runs) with an automated failure taxonomy and found
   **[M]** failure modes. Five targeted hardening changes raised survival from **[A %]** to **[B %]** (exploratory,
   small samples).
3. Built an **[N]**-case evaluation harness: an LLM judge with **[Z %]** agreement with **20** human labels, retrieval
   recall@5 and MRR, groundedness, tool-call accuracy, p50/p95 latency and cost. Hybrid retrieval changed recall@5 from
   **[P]** to **[Q]**.
4. Engineered a quota-aware, resumable job runner (requests/minute, tokens/minute and requests/day limits) for
   free-tier APIs. Dockerized it, with GitHub Actions CI and a static React demo on GitHub Pages.

**Heading line:** Flight Recorder | Python, Google ADK, Gemini API, Postgres/pgvector, FastAPI, React, Docker, GitHub
Actions | GitHub · Demo

**Wording rules:** say "Gemini API" (add "Gemma 4" if it is the agent), never "Vertex AI" or "deployed on GCP"; say the
data is synthetic; say "list-price-equivalent" cost; state sample sizes. Bullet 1's "[Y %]" can be quoted as
measured: the random ticket/claim ID issue was fixed on 2026-11-26 (`docs/DEEPDIVE.md` §17, item 1).

**One-line pitch:** "Agents fail in ways that are hard to reproduce, so I built a flight recorder: it records runs,
replays them deterministically, injects faults to find weaknesses before a customer does, and diffs behaviour across
prompt or model changes, all quota-aware on a free tier."
