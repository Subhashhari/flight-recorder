# 7. Code tour, file by file

About 4,300 lines of Python (source, scripts, tests) and 800 lines of TypeScript/CSS. Files are listed in the
order a request touches them, then the evaluation layer, then the edges (API, UI, scripts, tests).

## 7.1 Configuration and plumbing

**`src/flightrec/config.py`**
- `ROOT`, `CONFIG_DIR`, `DATA_DIR`, `CORPUS_DIR`, `CORPUS_SRC_DIR`, `EVAL_DIR`, `DOCS_DIR`: paths, overridable with
  `FLIGHTREC_ROOT` (the Docker image sets it to `/app`).
- `load_env_file()`: reads `.env` into `os.environ` without overriding existing variables (so `PROMPT_VERSION=v2 make
  eval` wins), skipping empty values. Runs at import time because google-genai and ADK read `GOOGLE_API_KEY` from the
  environment.
- `Settings` (pydantic-settings): `agent_model`, `judge_model`, `embed_model`, `database_url`, `scale_tier`,
  `max_llm_calls_per_run` (25), `chunk_chars` (1200), `chunk_overlap` (150), `retrieve_top_k` (5),
  `prompt_version`. `settings()` builds a fresh object each call, so CLI flags that set environment variables take
  effect.
- `load_limits()`, `load_pricing()`, `load_scale(tier)`, `load_facts()`, `norm_model()` (strips `models/`),
  `is_fake()`.

**`src/flightrec/db.py`**: a lazily created SQLAlchemy engine; `init_db()` runs `schema.sql` through the raw psycopg
connection (needed because the file contains many statements); `vec_literal()` formats a vector as `'[0.1,…]'`,
inserted with `CAST(:emb AS vector)`.

**`src/flightrec/schema.sql`**: the tables from Chapter 2.7, the HNSW index on embeddings (fast approximate
nearest-neighbour search) and a GIN index on the full-text column, plus the JSONB→JSON migration block for `events`.

**`src/flightrec/runtime.py`**: process-wide singletons: `limiter()` (DB-backed daily counter + `limits.yaml`) and
`genai_client()` (the Gemini Developer API client, never Vertex).

## 7.2 Running the agent

**`agents/prompts.py`**: the five v1 instructions, verbatim from the guide; `V2_PATCH` (four appended sentences);
`V1`/`V2` namespaces; `BUDGET_APOLOGY`; `get_prompts(version)`. A test checks that the only `{…}` placeholders are the
state keys ADK should fill (`plan`, `evidence`, `action_result`, `draft`), because a stray brace makes ADK look for a
non-existent state variable and fail.

**`agents/tools.py`**: the five tools as plain functions with docstrings and type hints (ADK builds the function
declarations the model sees from these). `search_policies` calls hybrid search; the four action tools call the mock
backend. `safe_tool()` is the v2 wrapper (worker thread, 5 s timeout, one retry, error dict; `functools.wraps` keeps
the name, signature and docstring so the model sees the same tool). `get_tools(prompt_version, overrides)` returns the
tool set (tests pass in-memory replacements).

**`agents/pipeline.py`**: `build_pipeline(rec, prompts, model, temperature, tools)` creates five `LlmAgent`s with the
recorder's four callbacks and the same `GenerateContentConfig(temperature=…)`, inside
`SequentialAgent(name="policydesk")`.

**`agents/executor.py`**: `execute(query, employee_id, *, mode, label, case_id, source_run_id, branch_seq, overrides,
fault, record, prompt_version, …) -> RunResult`.
1. For replay/branch: load the source run and events, inherit its model, prompt version, temperature, query and
   employee, and set a dummy key if none exists.
2. Create a `Recorder(limiter, chunk_sampler)` and a `run_id`.
3. Up to 4 attempts: create a `RunContext`, set the context variable, `_run_once()` (build the pipeline, create an
   ADK `Runner` + `InMemorySessionService`, send `"[E…] query"`, iterate `run_async` with
   `RunConfig(max_llm_calls=25)`, read the final session state).
4. Classify exceptions by walking the exception chain (`_chain`, which also looks inside exception groups):
   `QuotaExhausted` → `paused` (re-raised after saving); `ReplayMiss` → `diverged`; ADK's
   `LlmCallsLimitExceededError` → `budget_exceeded` (+ apology in v2); a 429 → wait 30/60/120 s and retry, then
   `rate_limited`; anything else → `crash`.
5. Sort events by `seq`, `compute_totals()`, save via `store.save_run` (one transaction).
`RunResult.row()` gives the `runs` row as a dict.

## 7.3 The recorder

**`recorder/core.py`**: `RunContext` (with `next_ordinal`, `from_cache(seq)`, `find_source(agent, type, ordinal)`),
the `_current` context variable, `request_hash()` with volatile-key stripping (`_strip`), `estimate_tokens()`,
`jsonable()`, `add_event()` (builds an event dict, auto-assigns `seq`/`ordinal` if not given, rejects unknown fields),
and `ReplayMiss`.

**`recorder/callbacks.py`**: `serialize_request()` (model, system text, contents dumped to JSON, tool names,
temperature), `apply_overrides()`, and `Recorder` with `before_model` / `after_model` / `before_tool` / `after_tool`
(Chapter 3.6). Tool events key their `pending` entry by `(agent, "tool", function_call_id)` so parallel tool calls in
one model response cannot collide.

**`recorder/faults.py`**: `FAULTS` (the eight definitions: target, stage, applicable categories, description, fixed
response, simulated latency), `pre_tool_fault()`, `post_tool_fault()`, `INJECTION`, `CANARY`, `MAIN_KEYS`.

**`recorder/replay.py`**: `replay()`, `branch()` (validates override names), `parse_overrides()` (turns
`--set temperature=0.7 --append writer="…"` into a dict), `tool_sequence()` and `same_outcome()` (same tool calls with
the same arguments in the same order, and the same final text).

**`recorder/ratelimit.py`**: `Limiter`, `QuotaExhausted`, `next_reset()`, time zones `PT` and `IST` (Chapter 6.3).
Clock, sleep and "now" are injectable for tests.

**`recorder/pricing.py`**: `price_for(model)` (exact key, else the longest key that is a prefix of the model id, so
`gemma-4` prices `gemma-4-31b-it`), `list_cost(model, tokens_in, tokens_out)`.

**`recorder/store.py`**: all database reads and writes: `MemoryQuotaStore` / `DbQuotaStore`; `save_run` (upsert the
run, replace its events), `get_run`, `get_events`, `list_runs`, `runs_in_label`, `latest_scored_runs` (one row per case
via `DISTINCT ON`), `chaos_scored_runs` (one per (case, fault)), `save_score`, `set_showcase`, `labels_summary`,
`children_of`, `quota_rows`. `COUNTED` = the statuses included in statistics.

## 7.4 Retrieval and data

**`corpus/chunking.py`**: `split_headings()` (split Markdown at `#` headings), `recursive_split()` (try paragraph
breaks, then line breaks, then sentence ends, then spaces, until each piece fits 1,200 characters, then prepend ~150
characters from the previous piece, starting at a word boundary), `chunk_text()`, `chunk_csv()` (one chunk per row:
`"holidays 2027: date: 2027-01-01; holiday: New Year's Day"`).

**`corpus/embed.py`**: `embed_texts(texts, task_type)` (batches of 50 through the limiter, `output_dimensionality=768`,
asserts 768 dimensions; `RETRIEVAL_DOCUMENT` for chunks), `embed_query()` (`RETRIEVAL_QUERY`, cached in
`query_embeddings` by SHA-256 of the text), `fake_embed()` (hashed bag of words, offline tests only).

**`corpus/ingest.py`**: `pdf_text()` (pymupdf, page by page), `corpus_files()`, `build_chunks()` (Markdown → heading +
recursive split; PDF → recursive split; CSV → rows), `ingest()` (embed all, `TRUNCATE chunks`, insert: idempotent).

**`corpus/search.py`**: `_vector()` (`ORDER BY embedding <=> :q LIMIT 20`, where `<=>` is pgvector's cosine
distance), `_fulltext()` (`tsv @@ plainto_tsquery('english', :q)` ranked by `ts_rank`), `rrf()` (k = 60, ties broken by
chunk id for determinism), `search(query, mode)`, `max_similarity()`, `sample_other_chunks()` (for the
`retrieval_irrelevant` fault, seeded), `doc_chunks()`.

**`corpus/facts.py`**: `DOC_FACTS` (which `facts.yaml` sections each document must contain), `PDF_DOCS`,
`DOC_TITLES`, `check_document()` (missing facts: every number must appear, with or without thousands separators;
every string must appear, ignoring case, dashes and spacing. Extra numbers: every number in the text that is not a
fact, a year 2025–2027, a heading number or a list index, or listed in `data/corpus/.factignore`), `check_all()`.

**`backend/mock_backend.py`**: `generate_employees(seed=7)` (40 employees, grade quotas shuffled, managers one grade
up), `expense_limit(grade, category)` from `facts.yaml`, `MemoryRepo` (tests) and `DbRepo` (Postgres), and
`MockBackend` with the four business functions and their error contracts (`not_found`, `invalid_category`,
`over_limit` with the limit).

## 7.5 Evaluation layer

**`evals/cases.py`**: pydantic `Case` and `ToolCall`, JSONL read/write, `load_cases(path, status)`.

**`evals/metrics.py`**: `search_results()`, `retrieved_doc_ids()`, `retrieval_metrics()`, `tool_calls()`,
`args_match()`, `tool_match()`, `clean_success()`, `clean_failure_reason()`, `followed_injection()`,
`failure_category()` (the ordered taxonomy), `percentile()`.

**`evals/judge.py`**: `CleanVerdict` and `ChaosVerdict` schemas, the rubrics, `clean_prompt()` / `chaos_prompt()`
(they assemble evidence and tool results from the recorded events), `judge_clean()` / `judge_chaos()` (real judge via
`llm.generate_json`, or the offline heuristic for `fake-judge`).

**`llm.py`**: `generate_text()` and `generate_json()` for non-agent calls (judge, corpus, case generation), always
through the limiter, with the same 429 retry policy.

**`evals/runner.py`**: `run_eval()` → `_run()` (the resumable loop of Chapter 5.5), `score_clean_run()`,
`handle_quota()` (print or sleep until reset), `_stratified()` (round-robin across categories for `--limit` smoke runs).

**`evals/chaos.py`**: `select_cases()` (sha256 ordering), `plan()`, `score_chaos_run()`, `run_chaos()`,
`chaos_matrix()`, `matrix_markdown()`.

**`evals/repro.py`**: `pick_cases(n, seed=5)`, `repeatability()`, `replay_check()`.

**`evals/report.py`**: `clean_summary(label)`, `retrieval_eval(mode)`, `stats(label)`, `write_results_md()`,
`save_export()` / `load_export()` for `data/exports/*.json`.

**`evals/diff.py`**: `diff(a, b)` → markdown, HTML file, flipped cases.

**`evals/review.py`**: the interactive `review_cases()`, `label()`, `judge_agreement()`.

**`evals/export_static.py`**: `export_static(out)`, `export_traces(path, labels)`, `import_traces(path)`; `_real()`
filters out fake-model runs.

## 7.6 Interfaces

**`cli.py`** (Typer): `db-init`, `ingest`, `search`, `check-facts`, `review-cases`, `eval`, `eval-retrieval`,
`chaos`, `chaos-matrix`, `runs`, `run`, `replay`, `branch`, `showcase add|remove|list`, `diff`, `label`,
`judge-agreement`, `repeatability`, `replay-check`, `stats`, `report`, `export-static`, `export-traces`, `import`.
Heavy imports happen inside each command so `flightrec --help` is fast.

**`api/routes.py`** (FastAPI): `GET /api/runs`, `GET /api/runs/{id}` (run + events + children), `GET /api/labels`,
`GET /api/chaos?label=`, `POST /api/chat|replay|branch`. The response shapes are identical to the static export files,
so the UI code does not care which mode it is in. **`api/main.py`**: the app, `/healthz`, CORS for the Vite dev
server, `/diffs` (the diff HTML files), and the built UI at `/` when `UI_DIST` is set (Docker).

**`ui/src/api.ts`**: types (`RunSummary`, `RunDetail`, `RunEvent`, `ChaosMatrix`, …), `STATIC` flag, `api.*`
functions mapping to `/api/...` or `demo-data/*.json`. **`ui/src/App.tsx`**: header (mode badge, nav, Diffs menu),
routes. **`pages/RunsPage.tsx`**: filters (label, status, search, showcase only) in the URL query string; the runs
table. **`pages/RunDetailPage.tsx`**: summary tiles, lineage ("Branched at step N from …", "Pre-recorded branch"), the
**five-lane timeline** (one lane per agent; bars laid end to end in `seq` order, sized by latency, with a 40 ms minimum
so instant cached calls stay clickable; red outline for faults, errors or divergences; faded for cached), the
inspector (request/response JSON), Replay and Branch-from-here buttons (with optional text appended to the selected
agent's instruction), the final answer, the judge verdict and the agents' outputs. **`pages/ChaosPage.tsx`**: survival
bar chart for every chaos label (recharts) and the fault × category heatmap. **`styles.css`**: colour tokens with
light/dark themes, responsive layout down to phone width.

## 7.7 Scripts

| Script | What it does |
|---|---|
| `model_probe.py` | Phase 0 probes P1–P8 and the automatic Plan A/B decision (Chapter 6.2) |
| `spike.py` | Answers ADK questions (a)–(g) with real outputs and writes them into `docs/architecture.md`; offline parts use a recording fake model |
| `gen_corpus.py` | 10 documents via the judge model using only their facts subset; 2 CSVs directly from `facts.yaml` |
| `make_pdfs.py` | Markdown (headings, paragraphs, bullets, pipe tables) → PDF with reportlab Platypus |
| `gen_eval_cases.py` | Candidates for the four categories (Chapter 5.2) |
| `seed_employees.py` | Inserts the 40 deterministic employees |
| `quota_dump.py` | Writes the per-day call table from `quota_usage` into `docs/quota-log.md` |

## 7.8 Tests

| File | Covers |
|---|---|
| `tests/conftest.py` | fake corpus and search, in-memory backend, fake tools with the real names, a fake clock, run helpers |
| `tests/test_pipeline_offline.py` | a full live run through real ADK records all five agents, the right tool, contiguous `seq` |
| `tests/test_replay.py` | replay identity with zero limiter calls; divergence on a changed hash; branch switches to live exactly at N with overrides applied; injection fault followed by v1 and fixed by a branch; each action and retrieval fault; v2 budget apology; quota → `paused`; limiter RPM/TPM/RPD/unknown-model/free-model with a fake clock |
| `tests/test_units.py` | backend, chunking, fact checker, metrics, success rules, failure order, chaos selection, RRF, hash stripping, prompts, `safe_tool`, pricing |
| `tests/test_pdf.py` | Markdown → PDF → pymupdf text still contains headings, table cells and numbers |
| `tests/integration/test_db_smoke.py` | the DB path end to end in a separate test database (Chapter 6.6) |

Next: [Chapter 8: decisions and alternatives](08-decisions-and-alternatives.md).
