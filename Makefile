# On Windows without make, use the equivalent PowerShell wrapper: .\tasks.ps1 <target> [LABEL]
.PHONY: db-up db-init seed ingest probe spike corpus pdfs cases eval chaos api ui test lint backup demo

db-up:     ; docker compose up -d db
db-init:   ; uv run flightrec db-init
seed:      ; uv run python scripts/seed_employees.py
ingest:    ; uv run flightrec ingest
probe:     ; uv run python scripts/model_probe.py
spike:     ; uv run python scripts/spike.py
corpus:    ; uv run python scripts/gen_corpus.py && uv run python scripts/make_pdfs.py
pdfs:      ; uv run python scripts/make_pdfs.py
cases:     ; uv run python scripts/gen_eval_cases.py
eval:      ; uv run flightrec eval --label $(LABEL) --resume --wait
chaos:     ; uv run flightrec chaos --label $(LABEL) --faults all --resume --wait
api:       ; uv run uvicorn flightrec.api.main:app --reload --host 127.0.0.1 --port 8000
ui:        ; cd ui && npm run dev
test:      ; uv run pytest -q -m "not integration"
lint:      ; uv run ruff check src tests
backup:    ; mkdir -p backups && docker compose exec -T db pg_dump -U flightrec flightrec | gzip > backups/flightrec-$$(date +%F).sql.gz
demo:      ; docker compose up -d db && uv run flightrec db-init && uv run flightrec import data/exports/traces.jsonl.gz
