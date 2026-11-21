# 6. Quotas, infrastructure, testing and delivery

## 6.1 Living on the free tier

The whole project costs ₹0. The price is strict limits (AI Studio console, read 2026-11-18):

| Model | RPM | TPM | RPD | Role |
|---|---|---|---|---|
| Gemma 4 31B / 26B | 30 | 16,000 | 14,400 | candidate agent (Plan A) |
| Gemini 3.5 / 3.1 Flash Lite | 15 | 250,000 | 500 | judge (Plan A) or agent + judge (Plan B) |
| Gemini Embedding | 100 | 30,000 | 1,000 | embeddings |
| other Flash / Pro models | 5–10 or 0 | | 20 or 0 | unusable |

Quotas are **per model**, so agent, judge and embedding calls draw from separate pools. That is why the agent and judge
are different models in both plans.

**The arithmetic that shaped the design (Plan B):** about 7 agent calls per run; (40 eval + 48 chaos) runs × 2
versions × 7 + repeatability 8 × 3 × 7 + ~500 for development ≈ 1,900 agent calls. At 90 % of 500 per day that is
about 4.2 days of quota. Plan A has a generous daily limit but only 16,000 tokens per minute; with the conversation
growing at each agent, that means roughly 5–10 calls a minute and 10–15 hours of runtime. Either way, runs **must**
survive interruptions, wait for limits, and resume the next day.

## 6.2 Choosing the models automatically: the probe

`scripts/model_probe.py` lists the available models, matches console names to real model IDs (preferring
non-preview, shortest names), then tests each candidate:

| Probe | Checks | Why it matters |
|---|---|---|
| P1 | a plain text call works | basic access |
| P2 | a call with a system instruction works | some open models reject system instructions |
| P3 | an ADK agent with an `add(a, b)` tool answers "17 + 25" by actually calling the tool and saying 42 | tool calling through ADK |
| P4 | `usage_metadata` has non-zero token counts | needed for token/cost accounting |
| P5 | the real v1 PLANNER prompt yields the exact one-line format on ≥ 4 of 5 queries | instruction-following reliability |
| P6 | 5 action requests with the real OPERATOR prompt trigger the right tool on ≥ 4 of 5 | tool-choice reliability |
| P7 | JSON mode with a pydantic schema returns valid JSON 5 of 5 times (judge candidates) | the judge depends on it |
| P8 | the embedding model returns exactly 768 numbers with `output_dimensionality=768` | the vector column is 768-d |

**Decision rule (no human judgement):** Gemma 4 31B passes P1–P6 → Plan A with 31B; else 26B passes → Plan A with
26B; else Plan B (agent 3.5 Flash Lite, judge 3.1 Flash Lite). The judge in Plan A is 3.5 Flash Lite if it passes P7,
otherwise 3.1. The script writes the IDs and tier into `.env`, `config/limits.yaml` and `docs/quota-log.md`.
Automating the choice makes it reproducible and removes the temptation to pick whichever model "looks better".

## 6.3 The limiter (`recorder/ratelimit.py`)

Every model, judge and embedding call goes through `Limiter.acquire(model, est_tokens)` first.

**How it works:**
1. Effective limits are 90 % of the published ones (`SAFETY = 0.9`): 15 RPM → 13, 250,000 TPM → 225,000, 500 RPD → 450.
   The margin absorbs clock skew and calls we cannot see.
2. **Daily (RPD):** a counter per (Pacific date, model) lives in the Postgres table `quota_usage`. If it has reached the
   daily limit, raise `QuotaExhausted(model, resume_at = next midnight Pacific)`. It is persisted (not in memory) so
   that restarting the program mid-day does not forget what was already spent.
3. **Per minute (RPM and TPM):** a **sliding window**: a queue of `(timestamp, tokens)` for the last 60 seconds. Drop
   entries older than 60 s. If adding this call would exceed the request count or the token sum, sleep until the
   oldest entry expires, then check again.
4. Record the call in the window and **increment the daily counter before the call** (a call that then fails still
   used quota, and retries count too).
5. Return the seconds spent waiting, which the recorder adds to `throttle_ms`.

**Worked example (TPM):** limit 1,000 TPM → 900 effective. At t=0 a 500-token call goes through. At t=10 s another
500-token call would make 1,000 > 900, so the limiter sleeps 50.05 s (until the first entry is 60 s old), then
proceeds. A unit test with a fake clock checks exactly this.

**Token estimate:** `len(json(contents + system)) / 4 + 512`, about 4 characters per token plus headroom for the
reply. A single request larger than the per-minute budget raises `ValueError` immediately (it could never succeed).

**Other details:** models not in `limits.yaml` are refused (`KeyError`), so a typo cannot bypass the limits; `fake-*` and
`ollama*` models are free and bypass it; a lock makes it safe if tools run in worker threads.

**Why a sliding window and not a token bucket?** A sliding log is exact for "at most N per rolling minute", which is
how the provider's limits behave, and at our volume (≤ 30 calls/min) storing timestamps costs nothing. A token bucket
allows bursts that could still trip the provider's per-minute check.

## 6.4 When the API pushes back anyway

- **HTTP 429 / `RESOURCE_EXHAUSTED`** (the provider's rate-limit error): the executor retries the **whole run** after
  30, 60 and 120 seconds. Retrying the whole run (not just the call) keeps the recording clean: a run is either a
  complete, coherent trace or it is not stored as successful. After three failures the run is stored as `rate_limited`
  (excluded from statistics, retried on the next resume). The error text is matched with
  `429|RESOURCE_EXHAUSTED|quota` (to be confirmed by the spike's question (f) once a key is available).
- **Daily quota reached** (`QuotaExhausted`): the run is stored as `paused` and the error propagates to the
  eval/chaos loop, which either exits with "resume after HH:MM IST" or sleeps until the reset (`--wait`).
  Midnight Pacific is 13:30 IST until March.
- **Anything else**: `crash`, with the error text stored on the run. The eval/chaos loops never die on a crash.

## 6.5 Saving quota elsewhere

- Query embeddings are cached in Postgres (`query_embeddings`), so repeated searches (replay checks, retrieval evals,
  the same question in v1 and v2) cost nothing.
- Embeddings are sent in batches of 50 chunks.
- Corpus generation skips documents that already exist unless `--force`.
- Re-scoring an unscored run does not re-run the agent.
- Replay costs zero calls, so demos and repeatability checks are free after recording.

## 6.6 Testing strategy

The hard problem: the system's core behaviour involves a paid, rate-limited, non-deterministic external model. Testing
against it would be slow, flaky and quota-hungry, and there was no key during the build. The solution has three layers:

1. **A scripted fake model, run through the real framework** (`src/flightrec/testing/fake_llm.py`). It is a genuine ADK
   `BaseLlm` subclass, registered for model names `fake-*`. ADK runs the real pipeline, real callbacks and real
   tool-calling machinery; only the "brain" is replaced by deterministic rules (the planner emits the plan line, the
   researcher calls `search_policies` then quotes the results, the v1 writer "falls for" an injection so chaos
   classification can be tested). This tests *our code and its integration with ADK*, which is what we can test
   without a model. A mock that bypassed ADK would have missed real integration bugs.
2. **Offline unit tests** for pure logic: backend rules, chunking, fact checking, retrieval metrics, tool matching,
   success rules, the failure-category order, chaos case selection, RRF, hashing, prompts (no stray braces, v2 =
   v1 + patch), `safe_tool`, pricing, the PDF round-trip, and the limiter under a **fake clock** (RPM, TPM, RPD with the
   midnight-Pacific reset). No network, no database: 39 tests in about 2 seconds, run in CI.
3. **Database integration tests** (`tests/integration/`, marker `integration`): a separate `<db>_test` database, so
   real data is never touched, plus a hashed bag-of-words fake embedder. They run ingest → hybrid search → a recorded
   run with the DB-backed mock backend → scoring → **replay loaded from Postgres** (must be `ok` with zero
   divergences) → a chaos run classified `followed_injection` → export filters → trace archive round-trip.

Runs made with fake models are tagged by their model name and are **never** exported or reported.

## 6.7 Containers and local services

- **`docker-compose.yml`**: the `db` service is `pgvector/pgvector:pg16` (Postgres with the vector extension,
  multi-architecture, so it runs on Apple Silicon too), bound to `127.0.0.1` only, with a named volume for the data.
  The host port is `${FLIGHTREC_DB_PORT:-5432}`, configurable because another project on the development PC already
  used 5432. The optional `app` service (profile `app`) runs the API and UI container.
- **`Dockerfile`**: two stages. Stage 1 (`node:lts`) builds the React UI; stage 2 (`python:3.12-slim`) installs the
  locked Python dependencies with uv (dependencies first, then the project, so Docker's layer cache avoids
  reinstalling everything after a code change), copies the built UI and serves everything with uvicorn. Verified
  locally: the container answers `/healthz` and serves the UI.
- The API binds to `127.0.0.1` because the `POST` routes spend your quota; it is not meant to be exposed.

## 6.8 Continuous integration and the public demo

- **`ci.yml`** (every push and pull request): install with `uv sync --frozen` (fails if `uv.lock` is stale), lint with
  ruff, run the offline tests, build the Docker image. It is green on GitHub.
- **`pages.yml`** (push to `main`): builds the UI with `VITE_DEMO_MODE=static` and `VITE_BASE=/<repo-name>/`, then
  deploys to GitHub Pages. In static mode `ui/src/api.ts` maps every GET to a JSON file under `demo-data/`
  (`labels.json`, `runs_<label>.json`, `run_<id>.json`, `chaos_<label>.json`) and disables the Replay/Branch buttons
  with the tooltip "run locally". The router is a **HashRouter** (`/#/runs/<id>`), because GitHub Pages cannot rewrite
  deep URLs to `index.html`; with a normal router, refreshing a deep link would 404. (Pages must be enabled once in
  the repository settings: Source = GitHub Actions.)
- **`flightrec export-static`** writes those JSON files. Full prompts and responses are included only for showcase
  runs; other runs keep slim events (step, agent, type, latency, tokens, fault), to keep each file under 5 MB and
  the site small.
- **Trace archive** (`flightrec export-traces` → `data/exports/traces.jsonl.gz`, `flightrec import`): the headline
  labels plus showcase runs, one JSON line per run with its events, parents written before children so lineage
  links survive import. `make demo` = start the DB, create the schema, import the archive. Because replay works with a
  dummy key, a reviewer can replay real recorded runs without any account.

## 6.9 Configuration and secrets

- `.env` holds the API key and settings; it is git-ignored (and Docker-ignored). `.env.example` is the template.
  The key is never printed, logged or committed. `config.load_env_file()` reads `.env` into the environment without
  overriding variables already set, and treats an empty value as unset.
- `config/limits.yaml` (rate limits), `config/pricing.yaml` (list prices with source and date),
  `config/scale.yaml` (case and run counts per tier) are committed, so experiments are reproducible.
- Free-tier prompts may be used by Google to improve its products, which is one more reason all data is synthetic.

## 6.10 Developer workflow

- `uv` manages Python and dependencies; `uv.lock` pins every version, so CI, Docker and every laptop install the same
  thing.
- `Makefile` targets (`db-up`, `ingest`, `eval`, `chaos`, `test`, `lint`, `backup`, `demo`, …) for macOS/Linux;
  `tasks.ps1` provides the same targets on Windows.
- `make backup` dumps the database nightly (long experiments live in it).
- `GEMINI.md` and `docs/prompts/phaseN.txt` are the operating rules and per-phase prompts from the original plan for
  running a coding agent on the project phase by phase.

Next: [Chapter 7: code tour](07-code-tour.md).
