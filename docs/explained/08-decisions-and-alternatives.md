# 8. Decisions and alternatives

Each decision has the same shape: **what we chose**, **what else we could have done**, **why this**, and **what it
costs us**. Interviewers rarely ask "what did you do?"; they ask "why that and not X?". Being able to name the cost of
your own choice is the strongest signal of understanding.

---

## A. Scope and platform

### A1. Build our own recorder instead of using an observability product
- **Chose:** a purpose-built recorder on ADK callbacks, storing runs in our own Postgres.
- **Alternatives:** Langfuse, LangSmith, Arize Phoenix, or OpenTelemetry tracing into Jaeger/Grafana.
- **Why:** those tools excel at *viewing* traces and running evals, but our core features need **control of the
  execution**: serving cached responses (replay), switching to live at step N (branch) and corrupting tool results
  (chaos). Observability tools watch; they do not intercept and substitute. Building it also demonstrates understanding
  rather than configuration.
- **Cost:** we reimplemented trace storage and a UI that those products already do better; no team features. In
  production you would export the same events as OpenTelemetry spans to such a tool and keep the replay/chaos engine.

### A2. Google ADK as the agent framework
- **Chose:** ADK (`google-adk`): `LlmAgent`, `SequentialAgent`, `Runner`, per-agent callbacks.
- **Alternatives:** LangGraph (graph-based state machines), CrewAI or AutoGen (role-based multi-agent), or a
  hand-written loop over the raw `google-genai` SDK.
- **Why:** first-class Gemini support (including Gemma 4 natively), a clean callback API at exactly the four points a
  recorder needs, built-in session state with `{key}` templating, and a model-call cap (`max_llm_calls`). Using a real
  framework (not a toy loop) makes the recorder's design relevant to how agents are actually built.
- **Cost:** we depend on ADK's internals (for example how tool results are rendered into later prompts, which caused
  the JSONB bug); ADK 2.x behaviour differs from 1.x documentation; there is no built-in public record/replay API.

### A3. Gemini API free tier
- **Chose:** AI Studio free tier with an API key; total spend ₹0.
- **Alternatives:** paid OpenAI/Anthropic/Gemini; local open models via Ollama; Vertex AI.
- **Why:** zero cost; Gemma 4 and Flash Lite are capable enough for structured multi-step tasks; one provider for agent,
  judge and embeddings.
- **Cost:** severe rate limits (500 requests/day for Flash Lite), which forced the limiter, resumability and multi-day
  runs; free-tier prompts may be used by Google, so only synthetic data. Local models would remove quotas but need a GPU
  and give weaker tool calling.

### A4. Pick the models with an automatic probe (Plan A / Plan B)
- **Chose:** `model_probe.py` runs P1–P8 and applies a fixed rule.
- **Alternatives:** choose by hand; benchmark extensively.
- **Why:** model availability and capabilities on the free tier change; a probe tests exactly the capabilities the
  pipeline needs (system instructions, tool calling, the planner format, JSON mode, 768-d embeddings) at small cost,
  and a fixed rule removes bias.
- **Cost:** 5-sample probes are coarse; a model could pass and still be weak overall.

### A5. Synthetic company data
- **Chose:** Northwind Labs: invented policies from `facts.yaml`, 40 seeded employees.
- **Alternatives:** real company documents (unavailable, confidential), public policy datasets.
- **Why:** full control of the ground truth (every number is known), no privacy risk on a free tier that may train on
  prompts, and reproducibility on any machine.
- **Cost:** less messy than reality (no contradictory versions, scanned PDFs, ambiguous questions). Never call it
  production data.

## B. The agent design

### B1. A fixed five-step sequential pipeline
- **Chose:** planner → researcher → operator → writer → verifier, always in that order.
- **Alternatives:** one ReAct-style agent with all tools; a router that transfers control dynamically between agents;
  parallel research and action.
- **Why:** each step has one job and a checkable output, failures can be attributed to a step, and the timeline view is
  meaningful. A fixed order also makes replay simpler (no branching control flow to reproduce).
- **Cost:** more model calls (≈ 7 per run, even when a step outputs `NOT_NEEDED`), so more latency and quota; a single
  agent would be cheaper for simple questions.

### B2. A strict planner output format
- **Chose:** one line `needs_policy=…; needs_action=…; employee_id=…; task=…`.
- **Alternatives:** JSON output; free text.
- **Why:** easy for smaller models to follow, easy to check with a regex (probe P5), and easy for later agents to
  apply rules to. JSON mode would be stricter but adds a separate configuration path for one agent.
- **Cost:** a regex-shaped format can be subtly broken (extra words), which P5 measures.

### B3. A separate verifier step
- **Chose:** a final fact-checking agent.
- **Alternatives:** none (trust the writer); constrained decoding; citations-only answers.
- **Why:** a cheap, common mitigation for unsupported details, and a clear place for the v2 rule "never claim success if a
  tool result shows an error".
- **Cost:** one more model call per run, and the verifier can also *introduce* errors; the eval measures the net effect.

### B4. Temperature 0 and a 25-call cap
- **Chose:** temperature 0 for all agents and the judge; `max_llm_calls = 25`.
- **Why:** temperature 0 minimises variation (it does not eliminate it, and the repeatability study measures what
  remains); the cap stops runaway tool loops from burning quota.
- **Cost:** temperature 0 can make outputs repetitive; the cap could cut off a legitimately long run (reported as
  `budget_exceeded`, never hidden).

### B5. Default ADK context (every agent sees the conversation so far)
- **Chose:** ADK's default `include_contents`, as the guide's pipeline specifies.
- **Alternative:** `include_contents="none"` so each agent sees only its instruction (with state injected).
- **Why:** follows the spec and gives each agent full context (the user's exact words), and ADK 2.15 wraps other
  agents' output as quoted data, a free injection defence.
- **Cost:** prompts grow along the pipeline, which uses more tokens and matters for Gemma's 16,000 TPM limit. Trying
  `none` for writer and verifier is a natural optimisation experiment.

## C. Recording and replay

### C1. Intercept via ADK callbacks
- **Chose:** the four agent-level callbacks.
- **Alternatives:** (1) an HTTP-level record/replay proxy, like the VCR "cassette" libraries used in web testing;
  (2) subclassing or monkeypatching the model class; (3) ADK runner-level plugins.
- **Why:** callbacks see *semantic* events (which agent, which tool, which arguments) instead of raw HTTP bodies; they
  can substitute both model responses and tool results; they are a supported public API. An HTTP cassette would not
  see tool calls (they are local Python) and breaks when request bodies contain timestamps or ids.
- **Cost:** tied to ADK; the asymmetric short-circuit behaviour (spike b/c) needed idempotent handling. Plugins would
  have meant one registration instead of five, but per-agent callbacks match the spec and keep the recorder explicit.

### C2. Look up cached responses by (agent, kind, ordinal)
- **Chose:** "the writer's first model call", and so on.
- **Alternatives:** look up by request hash; by global `seq`.
- **Why:** hash lookup turns any change into a hard miss (we want to continue and *report* a divergence); `seq` lookup
  misaligns everything after one extra call. The ordinal is stable per agent.
- **Cost:** if an agent makes calls in a different order between versions, ordinals map to the wrong calls; the hash
  check exposes that as divergences.

### C3. On a divergence, keep serving the cached response
- **Chose:** emit a `divergence` event, serve the recording, mark the run `diverged`.
- **Alternative:** stop the replay at the first mismatch.
- **Why:** you see *all* the places that differ in one pass, and the run still completes for inspection.
- **Cost:** after a divergence, later steps may be logically inconsistent (they answer questions that were not asked).
  The status makes this explicit.

### C4. Strip volatile fields before hashing
- **Chose:** remove function-call `id`, `thought_signature`, `thought`.
- **Why:** they are random per call; without stripping, every faithful replay would look divergent.
- **Cost:** a change that only affected those fields would go unnoticed (harmless by construction). Temperature is
  also not in the hash (a known gap).

### C5. Buffer events and flush once per run
- **Chose:** keep events in memory, write run + events in one transaction at the end.
- **Alternatives:** write each event as it happens; append to a log file.
- **Why:** no database latency inside the measured run (keeps the overhead number honest), no half-written runs, and
  simple atomic semantics.
- **Cost:** if the process is killed mid-run, that run's events are lost (the run is simply re-executed on resume).

### C6. Store events as JSON, not JSONB (deviation from the guide)
- **Chose:** `JSON` columns for `events.request/response`; JSONB elsewhere.
- **Why:** JSONB re-orders keys; ADK renders tool results into later prompts as order-sensitive text, so JSONB broke
  replay fidelity (Chapter 3.11). JSON preserves the exact text.
- **Cost:** no JSONB indexing or containment queries on events (not needed here).

## D. Retrieval

### D1. Postgres + pgvector instead of a dedicated vector database
- **Chose:** one Postgres for vectors, full-text search, mock business data and run storage.
- **Alternatives:** Pinecone (hosted), Qdrant/Weaviate/Milvus, Chroma, FAISS in memory.
- **Why:** one system to run and back up; hybrid search is two SQL queries in the same database; HNSW indexing is
  plenty for ~100 chunks (it scales to millions); joins between runs and data are trivial.
- **Cost:** a dedicated vector DB offers filtering, sharding and managed scaling we do not need at this size.

### D2. Hybrid search with Reciprocal Rank Fusion
- **Chose:** top-20 vector + top-20 full-text, fused with RRF (k = 60), top 5 returned.
- **Alternatives:** vector only; a weighted sum of normalised scores; a cross-encoder re-ranker.
- **Why:** vector search captures meaning but can miss exact tokens (grade codes "L3", "MFA", "P1"); keyword search is
  the reverse. RRF combines *ranks*, so it needs no score normalisation or tuning (cosine similarity and `ts_rank` are on
  different scales), and k = 60 is the widely used default from the original RRF paper.
- **Cost:** the `plainto_tsquery` keyword side requires all words to match, so for long questions it often returns
  nothing and hybrid ≈ vector; `eval-retrieval` measures hybrid against vector, so the effect is quantified, not assumed.
  A re-ranker would likely help more but costs another model call per query.

### D3. Heading-aware chunking at 1,200 characters with 150 overlap
- **Alternatives:** fixed-size windows; sentence-level chunks; "semantic" chunking by embedding similarity.
- **Why:** policy documents are organised by numbered sections, so splitting at headings keeps each rule with its
  context; 1,200 characters (~300 tokens) holds a full rule or small table; overlap protects facts that straddle a
  boundary. CSV rows become one chunk each, prefixed with column names, so "meals, L2, 1000" is self-explanatory.
- **Cost:** PDFs lose their heading markers in text extraction, so they fall back to plain recursive splitting; the
  chunk-size ablation was explicitly cut from scope.

### D4. 768-dimensional embeddings
- **Chose:** `output_dimensionality=768` (the model natively produces more dimensions and supports truncation).
- **Why:** smaller vectors are cheaper to store and search with a negligible quality loss for short policy text; it is a
  fixed column size, and probe P8 verifies the model honours it.
- **Cost:** slight recall loss compared with full-size vectors, irrelevant at this corpus size.

## E. Evaluation

### E1. LLM-as-judge plus programmatic checks plus human agreement
- **Alternatives:** exact or fuzzy string match; embedding similarity to the gold answer; humans grade everything.
- **Why:** free-text answers have many correct phrasings (string match fails); embedding similarity cannot tell
  "₹1,000" from "₹1,500"; humans do not scale. So: the judge for meaning, code for anything exact (tool calls, canary
  string, E1001 ticket), and 20 human labels to quantify trust in the judge.
- **Cost:** judge bias and errors; judge calls use quota.

### E2. Templated action and multi cases
- **Why:** expected tool calls and answers depend on private employee data and exact limits; code computes them with
  certainty, while an LLM could get them wrong. LLMs generate only the open-ended qa and unanswerable questions, where
  variety matters, and a human reviews those.
- **Cost:** templated questions are less varied than real phrasing.

### E3. A single source of truth for facts, with an automatic checker
- **Chose:** `facts.yaml` + `check-facts`.
- **Alternative:** read all twelve documents manually.
- **Why:** a generated policy that silently says 11 sick days would corrupt every qa score. The checker finds missing
  facts and *extra* numbers in minutes, and a human only fixes what is flagged.
- **Cost:** heuristics (it ignores heading numbers and years) can miss or over-flag; `.factignore` handles harmless
  extras.

### E4. Macro-averaged success and the latest scored run per case
- **Why:** each category counts equally (small categories such as unanswerable stay visible), and re-runs never
  double-count.

## F. Chaos

### F1. Inject faults inside the recorder callbacks
- **Alternatives:** mock the backend functions; network-level chaos (for example a fault-injecting proxy).
- **Why:** the recorder already sits at the exact boundary between agent and tools, faults become part of the recording
  (so branches replay the same fault), and the same mechanism covers action tools and retrieval.
- **Cost:** in-process faults do not test real network behaviour (slow responses, partial reads).

### F2. One label per failure, assigned by an ordered taxonomy
- **Alternative:** multiple labels per run.
- **Why:** counts add up to the number of runs, and the matrix stays readable; the order goes from most severe and objective to
  judged.
- **Cost:** secondary failures in the same run are hidden.

### F3. Exactly five hardening changes
- **Why:** a small, named set of changes makes the before/after comparison attributable. Endless prompt tweaking
  would make the improvement unexplainable.
- **Cost:** some failure modes may remain unaddressed by design.

## G. Operations

### G1. Our own rate limiter
- **Alternatives:** rely on provider 429 errors with exponential backoff (for example the `tenacity` library); an
  asyncio rate-limit library.
- **Why:** we need **three** dimensions (requests per minute, tokens per minute, and a *persisted* daily counter with
  the provider's midnight-Pacific reset) plus a clean "pause and resume tomorrow" signal. Backoff alone wastes daily
  quota on rejected calls and cannot know when the day resets.
- **Cost:** the estimates can drift from Google's real accounting, hence the 0.9 safety factor and 429 retries as a
  backstop.

### G2. Retry the whole run on 429
- **Why:** keeps every stored trace complete and coherent; partial runs never mix with successful ones.
- **Cost:** repeats the calls that had already succeeded in that run.

### G3. Resumable, label-based runners
- **Why:** multi-day experiments on a free tier; any interruption (sleep, crash, quota) is recoverable with `--resume`.

### G4. Postgres for run storage (not files or SQLite)
- **Why:** it is already needed for vectors, and SQL makes "latest scored run per case", chaos matrices and label summaries easy.
- **Cost:** requires Docker; SQLite would be lighter but has no pgvector.

## H. Interfaces and delivery

### H1. A React UI with a static mode, deployed to GitHub Pages
- **Alternatives:** Streamlit or Gradio (faster to write, but need a running Python server); a hosted API on Cloud
  Run (costs money, exposes quota).
- **Why:** a static site is free, permanent and safe (no quota, no keys); the same UI works against the local API for
  replay/branch. The API and the export produce identical JSON shapes, so there is one code path in the UI.
- **Cost:** the public demo is read-only, and the data must be re-exported and committed to update it.

### H2. HashRouter
- **Why:** GitHub Pages serves static files only; with `/#/runs/<id>` URLs every deep link loads `index.html`.
- **Cost:** less pretty URLs.

### H3. FastAPI, Typer, uv, Docker for the database
- **FastAPI:** typed request/response models, async (ADK is async), automatic docs.
- **Typer:** a typed CLI with many subcommands at almost no code cost.
- **uv:** very fast installs with a lockfile used identically by laptops, CI and Docker.
- **Docker for Postgres:** one command gives the exact `pgvector/pgvector:pg16` image on any OS, avoiding "works on my
  machine" problems with extensions.

## I. Testing

### I1. A scripted fake model run through real ADK
- **Alternatives:** mock everything with `unittest.mock`; record real API responses and replay them in tests.
- **Why:** mocks that bypass ADK would not test the integration that matters (callbacks, short-circuits, state
  templating). Recorded real responses would need an API key and quota. A deterministic `BaseLlm` registered for
  `fake-*` exercises everything except the model's intelligence.
- **Cost:** it cannot tell you how good the real model is; only the eval runs can.

### I2. A separate integration-test database
- **Why:** ingest truncates the `chunks` table; running tests against your real database would wipe your corpus.
  `<db>_test` isolates them completely.

Next: [Chapter 9: challenges, bugs and lessons](09-challenges-and-lessons.md).
