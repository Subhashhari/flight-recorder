CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS chunks (
  chunk_id TEXT PRIMARY KEY, doc_id TEXT NOT NULL, ordinal INT NOT NULL, text TEXT NOT NULL,
  embedding vector(768) NOT NULL,
  tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED
);
CREATE INDEX IF NOT EXISTS chunks_emb_idx ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS chunks_tsv_idx ON chunks USING gin (tsv);

CREATE TABLE IF NOT EXISTS query_embeddings (
  model TEXT NOT NULL, task_type TEXT NOT NULL, text_hash TEXT NOT NULL, embedding vector(768) NOT NULL,
  PRIMARY KEY (model, task_type, text_hash)
);
CREATE TABLE IF NOT EXISTS quota_usage (
  day_pt DATE NOT NULL, model TEXT NOT NULL, calls INT NOT NULL DEFAULT 0, PRIMARY KEY (day_pt, model)
);
CREATE TABLE IF NOT EXISTS employees (
  employee_id TEXT PRIMARY KEY, name TEXT NOT NULL, grade TEXT NOT NULL, manager_id TEXT,
  casual INT NOT NULL, sick INT NOT NULL, earned NUMERIC NOT NULL
);
CREATE TABLE IF NOT EXISTS tickets (
  ticket_id TEXT PRIMARY KEY, employee_id TEXT NOT NULL, category TEXT NOT NULL,
  description TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS expense_claims (
  claim_id TEXT PRIMARY KEY, employee_id TEXT NOT NULL, category TEXT NOT NULL,
  amount_inr NUMERIC NOT NULL, description TEXT, status TEXT NOT NULL, created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS runs (
  run_id UUID PRIMARY KEY, parent_run_id UUID REFERENCES runs(run_id), branch_seq INT,
  label TEXT, case_id TEXT,
  mode TEXT NOT NULL,        -- live | replay | branch | chaos
  fault TEXT,
  status TEXT NOT NULL,      -- ok | crash | diverged | budget_exceeded | rate_limited | paused (rate_limited = 429 or 5xx after retries)
  showcase BOOLEAN NOT NULL DEFAULT FALSE,
  user_query TEXT NOT NULL, employee_id TEXT NOT NULL, final_answer TEXT,
  config JSONB NOT NULL,     -- models, temperature, prompt_version, overrides, tier
  totals JSONB NOT NULL,     -- tokens_in, tokens_out, cost_list_usd, latency_ms, throttle_ms, llm_calls, tool_calls, recorder_self_ms
  started_at TIMESTAMPTZ NOT NULL, ended_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS runs_label_idx ON runs(label, case_id);
CREATE TABLE IF NOT EXISTS events (
  event_id BIGSERIAL PRIMARY KEY,
  run_id UUID NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
  seq INT NOT NULL, ordinal INT NOT NULL,
  type TEXT NOT NULL,        -- llm_call | tool_call | divergence
  agent TEXT NOT NULL, name TEXT,
  -- JSON (not JSONB): JSONB re-orders object keys, and ADK renders tool results into later prompts as
  -- order-sensitive text, so a JSONB round-trip makes faithful replays/branches see different prompts.
  request JSON, response JSON, request_hash TEXT,
  latency_ms INT, tokens_in INT, tokens_out INT, cost_list_usd NUMERIC(12,6),
  replayed BOOLEAN NOT NULL DEFAULT FALSE, fault TEXT, error TEXT, ts TIMESTAMPTZ NOT NULL,
  UNIQUE (run_id, seq)
);
DO $$ BEGIN  -- migrate databases created with the original JSONB event columns
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_name='events' AND column_name='response' AND data_type='jsonb') THEN
    ALTER TABLE events ALTER COLUMN request TYPE json USING request::json,
                       ALTER COLUMN response TYPE json USING response::json;
  END IF;
END $$;
CREATE TABLE IF NOT EXISTS scores (
  run_id UUID PRIMARY KEY REFERENCES runs(run_id) ON DELETE CASCADE,
  passed BOOLEAN NOT NULL, failure_category TEXT, metrics JSONB NOT NULL, judge_raw JSONB
);
