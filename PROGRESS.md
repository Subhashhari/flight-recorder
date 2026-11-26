# Progress

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
