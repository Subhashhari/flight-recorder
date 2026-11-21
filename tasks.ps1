# Windows equivalent of the Makefile.  Usage:  .\tasks.ps1 <target> [LABEL]
#   .\tasks.ps1 db-up ; .\tasks.ps1 eval baseline-v1 ; .\tasks.ps1 test
param([Parameter(Mandatory = $true)][string]$Target, [string]$Label = "")
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
function Need-Label { if (-not $Label) { throw "usage: .\tasks.ps1 $Target <LABEL>" } }
switch ($Target) {
  "db-up"   { docker compose up -d db }
  "db-init" { uv run flightrec db-init }
  "seed"    { uv run python scripts/seed_employees.py }
  "ingest"  { uv run flightrec ingest }
  "probe"   { uv run python scripts/model_probe.py }
  "spike"   { uv run python scripts/spike.py }
  "corpus"  { uv run python scripts/gen_corpus.py; if ($?) { uv run python scripts/make_pdfs.py } }
  "pdfs"    { uv run python scripts/make_pdfs.py }
  "cases"   { uv run python scripts/gen_eval_cases.py }
  "eval"    { Need-Label; uv run flightrec eval --label $Label --resume --wait }
  "chaos"   { Need-Label; uv run flightrec chaos --label $Label --faults all --resume --wait }
  "api"     { uv run uvicorn flightrec.api.main:app --reload --host 127.0.0.1 --port 8000 }
  "ui"      { Set-Location ui; npm run dev }
  "test"    { uv run pytest -q -m "not integration" }
  "lint"    { uv run ruff check src tests }
  "backup"  {
    New-Item -ItemType Directory -Force backups | Out-Null
    $f = "backups/flightrec-$(Get-Date -Format yyyy-MM-dd).sql"
    docker compose exec -T db pg_dump -U flightrec flightrec | Out-File -Encoding utf8 $f
    Write-Host "wrote $f"
  }
  "demo"    { docker compose up -d db; uv run flightrec db-init; uv run flightrec import data/exports/traces.jsonl.gz }
  default   { throw "unknown target '$Target'" }
}
