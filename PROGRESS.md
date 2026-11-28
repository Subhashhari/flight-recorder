# Progress

## Current state (updated 2026-11-28 15:40 IST)

The unattended chain `scripts/run_chain.ps1` is running (log: `logs/chain.log`, UTF-16; read with
`Get-Content logs\chain.log -Tail 20`). Plan B: agent `gemini-3.5-flash-lite`, judge `gemini-3.1-flash-lite`,
embeddings `gemini-embedding-001`, tier `B_sprint` (40 cases).

| Step (DEEPDIVE 19) | Status |
|---|---|
| 1-5 setup, probe, spike, corpus, check-facts, ingest, cases | done |
| 6 smoke eval (`smoke-1`, 3 runs), `baseline-v1` (40 runs) | done |
| 7 `eval-retrieval` hybrid + vector | done |
| 7 `chaos-baseline-v1` (48 runs) | done 15:35 |
| 7 `hardened-v2` (40) | running (started 15:35) |
| 7 `chaos-hardened-v2` (48) | queued |
| 8 diffs, `repeatability` (8 x 3), `replay-check` | queued |
| 8 `label` (**human**, ~25 min), `judge-agreement` | after the chain |
| 9 showcase runs, `report`, `export-static`, `export-traces`, README/SUMMARY numbers | after `label` |
| 10 GitHub Pages, demo video, rotate the key (**human**) | last |

Measured (stored runs, 2026-11-28): 7.4 LLM calls per clean run, 9.1 per chaos run; 450 usable agent calls per quota
day (reset 13:30 IST). Remaining ~1,020 agent calls -> chain expected to finish Mon 2026-11-30 evening IST, later if
Gemini has long 503 outages.

Numbers so far, as printed by the commands (final figures come from `flightrec report`, not from here):
- `eval --label baseline-v1`: 40 cases, success 0.925; qa 15/15, unanswerable 5/5, action 10/10, multi 7/10;
  hallucination rate 0.0 (n=25); p50 8.4 s, p95 31.1 s; 13,028 tokens/run; list-price $0.0047/run; 40 ok, 0 crash.
  All 3 multi failures: the claim is filed but the reply quotes the limit range instead of the employee's own limit.
- `eval-retrieval`: hybrid recall@5 0.92, MRR 0.88; vector recall@5 0.92, MRR 0.86 (n=25).
- `chaos --label chaos-baseline-v1` matrix (6 runs per fault, all faults fired; exploratory sample sizes): overall
  survival 31/48 (65%), 7 distinct (fault, category) failure modes. tool_timeout 6/6 survived; tool_http_500 4/6
  (2 ungraceful); tool_malformed_payload 3/6 (3 hallucinated_result); tool_empty_result 0/6 (6 hallucinated_result);
  tool_missing_fields 2/6 (3 hallucinated_result, 1 ungraceful); retrieval_empty 5/6 (1 ungraceful);
  retrieval_irrelevant 5/6 (1 ungraceful); retrieval_prompt_injection 6/6 (0 followed_injection).

If the chain stops (reboot, VS Code closed, error): `powershell -ExecutionPolicy Bypass -File scripts\run_chain.ps1`
continues where it stopped. `scripts\schedule_chain.ps1` (run by the human once) makes it a scheduled task that
survives VS Code exits and restarts at logon.

Incidents: 2026-11-27 00:50 the chain process died with no error (most likely killed with its parent VS Code process
tree); resumed 15:10. 2026-11-28 13:37 a judge 503 stopped it (DEEPDIVE 16.6, fixed); resumed 15:19.

## 2026-11-26 (evening, new laptop): probe, spike, corpus, ingest, candidates done

- New laptop set up: uv 0.13.10 installed, `uv sync`, Docker DB on host port 5433 (from `.env`), `db-init`, 40
  employees seeded, `pytest -m "not integration"` 42 passed, ruff clean.
- Probe re-run with 503 retries: Gemma 4 31B and 26B still `503 UNAVAILABLE` "high demand" on all 4 attempts each.
  3.5 Flash Lite P1-P6 pass (P5 5/5, P6 5/5), 3.1 Flash Lite P7 5/5, embedding P8 768-d. **Plan B, `B_sprint`** again.
- Spike re-run with the key: (e) real usage_metadata on gemini-3.5-flash-lite = (23, 2). (f) no longer bursts raw
  calls past the limiter to provoke a 429 (project rule: every call through the limiter).
- Corpus: 10 docs generated + 2 CSVs, 3 PDFs rendered. check-facts flagged 3 extra numbers, none contradicting
  facts.yaml (two true counts whitelisted in `.factignore`, one "Table 1" caption removed). Now 0 issues.
- Ingest: 124 chunks from 12 documents. Gate passes (`how many sick leaves` -> leave_policy top 5; scores show the
  keyword side matched nothing for this query, see DEEPDIVE 17 item 9).
- `gen_eval_cases.py`: `data/eval/candidates.jsonl` with qa 22, unanswerable 6, action 12, multi 12.
- 2026-11-27: reading the candidates showed `support_escalation.md` section 4 turning the facts' P1/P2 *response*
  times into *resolution* deadlines (check-facts cannot see this: the numbers are right). Section 4 now says "does not
  receive a response within"; re-ingested. Pre-check of all 52 candidates against facts.yaml, the corpus and the
  seeded employees: all gold numbers, limits, over/under verdicts, balances and managers correct.
- 2026-11-27: limiter bug, embedding batches counted as 1 request instead of 1 per text (DEEPDIVE 16.5). Fixed + test.
- 2026-11-27: eval set fixed, 40 cases (qa 15, unanswerable 5, action 10, multi 10), every policy document covered
  by at least one qa case. Gold answers verified automatically; selection reviewed and approved by the human (2 cases
  accepted in review-cases, the rest via the approved list in `scripts/auto_accept_cases.py`). DEEPDIVE 11.2,
  `data/eval/validation.json`.
- Next: smoke eval, then baseline-v1 and the rest of DEEPDIVE 19, unattended with `--resume --wait`.

## 2026-11-26: key added, first probe run, moving to another laptop

### State
- First real model probe: both Gemma 4 models returned `503 UNAVAILABLE: high demand` on every attempt (with 30/60/120 s
  retries); a direct test got 7 of 8 calls failing and one success after 87 s. Gemini 3.5 Flash Lite passed P1-P6 5/5,
  3.1 Flash Lite passed P7 5/5, gemini-embedding-001 passed P8 (768-d). **Automatic decision: Plan B** (`B_sprint`).
  Output: `docs/quota-log.md`, `docs/probe_output.txt`, `config/limits.yaml`.
- Not yet generated: corpus, PDFs, eval cases, any eval/chaos/repeatability runs. The database on the old laptop holds
  only the schema and the 40 seeded employees (both reproducible), so nothing needs to be copied across.

### Setting up the new laptop (Windows)
1. Install Git, Docker Desktop, uv (`winget install astral-sh.uv`) and Node 24 (only needed for the UI build).
2. `git clone https://github.com/Subhashhari/flight-recorder.git` and `cd flight-recorder`, then `uv sync`.
3. Copy `.env.example` to `.env`, put the API key in `GOOGLE_API_KEY` yourself (never paste it into a chat). Keep
   `FLIGHTREC_DB_PORT=5432` and the `:5432` DSN unless that port is taken (the old laptop needed 5433).
4. Start Docker Desktop, then `docker compose up -d db`, `uv run flightrec db-init`,
   `uv run python scripts/seed_employees.py`, `uv run pytest -q -m "not integration"` (expect 42 passed).
5. `uv run python scripts/model_probe.py`: re-runs the plan choice. If Gemma has recovered it picks Plan A, otherwise
   Plan B again. It writes the four `TBD` values in `.env`.
6. Continue with `docs/DEEPDIVE.md` section 19 (remaining steps): spike, corpus, PDFs, check-facts, ingest, cases,
   review-cases, ...
7. Power settings: the machine only needs to be on while a job runs. Jobs stop when the day's quota is spent and resume
   from the database on the next run (reset 13:30 IST).

## 2026-11-21: initial build (all phases' code), no API key yet

Environment actually used: Windows 11 (the guide assumes macOS), uv 0.13.9, Python 3.12, Node 24, Docker Desktop,
google-adk 2.15.0, google-genai 2.34.0. Windows equivalents of the Makefile targets live in `tasks.ps1`.

### Done and verified (commands run)
- **Phase 0 (partial):** uv project, dependencies, `docker-compose.yml`, Makefile, ruff + pytest config.
  `scripts/model_probe.py` written (P1–P8 + automatic Plan A/B) but **not run: no API key**.
  `scripts/spike.py` run offline: ADK facts (a), (b), (c), (d), (e: round-trip), (g) answered with real outputs in
  `docs/architecture.md`; (e: real usage_metadata) and (f: 429 error text) **pending the key**.
  `docker compose up -d db` works (host port 5433 on this machine, because another project uses 5432).
- **Phase 1 (code):** facts.yaml, check-facts, corpus generator, PDF converter, chunking, ingest, hybrid search (RRF),
  mock backend + seeding (40 employees seeded), eval-case generator, review-cases.
  Corpus and cases **not generated: needs the judge model (key)**.
- **Phase 2 (code):** tools, prompts v1/v2, pipeline, executor (429 retries, paused, crash, budget), limiter with
  RPM/TPM/RPD, recorder callbacks, judge, metrics, eval runner (resume/wait), eval-retrieval, label, judge-agreement.
- **Phase 3 (code + tests):** replay, branch, repeatability, replay-check, overhead stats.
- **Phase 4 (code + tests):** 8 faults, chaos runner + matrix, v2 hardening (exactly the 5 changes), showcase, diff.
- **Phase 5 (code):** FastAPI routes, 3-page UI (api + static mode), export-static, export-traces, import.
  `npm run build` succeeds in static mode.
- **Phase 6 (code):** Dockerfile, CI and Pages workflows, README, docs.
- Tests: `uv run pytest` → 41 passed (38 offline unit/pipeline tests using real ADK with a scripted local model +
  3 DB integration tests in a separate `flightrec_test` database). `ruff check` clean.

### Bugs found and fixed while verifying
- JSONB re-orders keys → DB-loaded replays were `diverged` (prompts changed). Event request/response now `JSON`.
  See docs/feature-requests.md #3.
- 2026-11-26: random `uuid4` ticket/claim ids would have inflated the live repeatability differ rate → ids are now
  derived from the request (idempotent inserts). Repeatability now caps attempts per case at `repeats + 2`. Two
  offline tests added. See docs/DEEPDIVE.md section 17, items 1, 5 and 7.
- 2026-11-26: a 503 "high demand" made the first probe reject Gemma and pick Plan B. Transient 5xx errors are now
  retried in the probe, the executor and `llm._call`, and a run that still fails is `rate_limited` (excluded), not
  `crash`. See docs/DEEPDIVE.md section 16.4.
- `localhost` DB connections ~20 s each on Windows → DSNs use `127.0.0.1`.
- `make_pdfs.py` table rendering crashed (`out +=` in a closure); check-facts mis-read en-dash time ranges.

### Not done (needs the human or the API key)
1. Put the AI Studio key in `.env` (`GOOGLE_API_KEY=`), then `uv run python scripts/model_probe.py`.
2. `uv run python scripts/spike.py` again (fills (e) usage and (f) rate-limit facts).
3. `gen_corpus.py` → `make_pdfs.py` → `check-facts` (human fixes) → `ingest` → `gen_eval_cases.py` →
   `review-cases` (human) → smoke eval → baseline / chaos / hardened runs → diff, repeatability, label (human).
4. `flightrec report`, `export-static`, `export-traces`, showcase runs, commit + push.
5. GitHub → Settings → Pages → Source: GitHub Actions. Record the demo video.

`docs/results.md` currently contains only empty tables: no result has been produced yet.
