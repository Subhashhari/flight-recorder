# 11. Glossary

| Term | Meaning in this project |
|---|---|
| **ADK** | Google's Agent Development Kit, the Python framework the five agents are built with |
| **Agent** | An LLM plus tools in a loop; here, each of the five pipeline steps is an `LlmAgent` |
| **AI Studio** | Google's developer console for the Gemini API; issues the free-tier API key |
| **API key** | Secret that authenticates calls to the Gemini API; kept only in `.env` |
| **Abstain** | Saying "I couldn't find this in company policy" instead of answering |
| **Branch** | Replay up to step N, then run live from N with overrides |
| **Callback** | A function ADK calls before or after every model call and tool call; where the recorder lives |
| **Canary (`CANARY-7731`)** | Unique string in the injected instruction; if it appears in the reply, the injection was followed |
| **Chaos testing** | Deliberately injecting faults to see how the system copes |
| **Chunk** | A ~1,200-character piece of a policy document, the unit of retrieval |
| **Context variable** | Python `ContextVar`: a per-async-task variable used to find the current run inside callbacks |
| **Cosine similarity** | Similarity of two vectors by angle (1 = same direction); used to compare embeddings |
| **Divergence** | An event recorded when a replayed request's hash differs from the recording |
| **Embedding** | A vector (here 768 numbers) representing the meaning of a text |
| **Eval / evaluation** | Running the agent on fixed test cases and scoring the results |
| **Event** | One recorded model call, tool call or divergence (a row in `events`) |
| **Failure category / taxonomy** | The ordered list of chaos failure types (budget, crash, followed injection, …) |
| **Failure mode** | A distinct (fault, failure category) pair seen at least once in the chaos baseline |
| **Fake model (`fake-*`)** | A scripted offline model used only in tests; its runs are never reported |
| **Fault** | One of the eight deliberate failures injected into a tool call |
| **Full-text search** | Keyword search using Postgres `tsvector` / `tsquery` |
| **Function calling / tool calling** | The model asking the program to run a named function with arguments |
| **Gemini / Gemma** | Google's model families; Gemma 4 is an open-weights model also served via the Gemini API |
| **Gold answer / gold documents** | The reference answer and documents for an eval case |
| **Grounded** | Every policy claim in a reply is supported by the retrieved evidence |
| **Hallucination** | A confident statement not supported by evidence or tool results |
| **Hash (request hash)** | SHA-256 fingerprint of a request (model, system instruction, contents, tool names), used to detect divergence |
| **HashRouter** | A React router that uses `#/path` URLs, so deep links work on static hosting |
| **HNSW** | An index type for fast approximate nearest-neighbour vector search (used by pgvector) |
| **Hybrid search** | Combining vector and keyword search results (here with RRF) |
| **Idempotent** | Safe to run twice with the same effect; the recorder's callbacks are idempotent |
| **JSON vs JSONB** | Postgres text JSON (keeps key order) vs binary JSON (re-orders keys); events use JSON |
| **Judge (LLM-as-judge)** | An LLM that grades replies against a rubric and returns structured JSON |
| **Judge agreement** | Percentage of 20 human pass/fail labels that match the judge-based verdict |
| **Label** | The name of an experiment grouping runs (`baseline-v1`, `chaos-hardened-v2`, …) |
| **Latency** | Time a run or call takes; here excludes time waiting for the rate limiter |
| **Limiter** | Our rate limiter: requests/minute, tokens/minute, persisted requests/day |
| **List-price equivalent** | What the tokens would cost at paid-tier prices; actual spend is ₹0 |
| **LLM** | Large language model: predicts the next text given input text |
| **Macro average** | Average of per-category rates, each category weighted equally |
| **MRR** | Mean reciprocal rank: average of 1/(rank of the first relevant document) |
| **Ordinal** | Per-(agent, kind) call counter; the key used to find a recorded response in replay |
| **p50 / p95** | Median and 95th-percentile latency |
| **pgvector** | Postgres extension adding a vector column type and similarity search |
| **Plan A / Plan B** | Model choice decided by the probe: Gemma 4 agent (A) or Flash Lite agent (B) |
| **Probe (P1–P8)** | Automatic capability tests used to choose models |
| **Prompt / system instruction** | The text sent to the model / the part that sets its role and rules |
| **Prompt injection** | Instructions hidden in data (for example a document) that the model wrongly obeys |
| **Prompt version (v1/v2)** | Baseline instructions vs. instructions plus the hardening patches |
| **Quota (RPM/TPM/RPD)** | Requests per minute, tokens per minute, requests per day allowed by the provider |
| **QuotaExhausted** | Our exception when the daily limit is reached; the run becomes `paused` |
| **RAG** | Retrieval-augmented generation: retrieve relevant passages and give them to the model |
| **recall@5** | Share of gold documents found among the top 5 retrieved results |
| **Replay** | Re-running a recorded run by serving recorded responses instead of calling the model |
| **Repeatability** | Measure of how often live runs at temperature 0 differ from each other |
| **ReplayMiss** | Replay needed a response the recording does not have; the run ends `diverged` |
| **RRF** | Reciprocal Rank Fusion: score = Σ 1/(60 + rank) across ranked lists |
| **Run** | One execution of PolicyDesk for one request (a row in `runs`) |
| **Run status** | `ok`, `diverged`, `crash`, `budget_exceeded` (counted) or `rate_limited`, `paused` (not counted) |
| **`safe_tool`** | v2 wrapper: 5-second timeout, one retry, errors returned as data |
| **Seq** | Global step number within a run; used for the timeline and `branch --step` |
| **Session state** | ADK's per-run dictionary where agents store outputs (`plan`, `evidence`, …) |
| **SequentialAgent** | ADK agent that runs its sub-agents one after another |
| **Showcase run** | A run marked for the static demo, exported with full prompts and responses |
| **Sliding window** | Rate-limit method counting calls/tokens in the last 60 seconds |
| **Spike** | A small experiment script (`scripts/spike.py`) that records how ADK behaves |
| **Static mode** | The UI reading exported JSON files instead of the API (GitHub Pages) |
| **Survival** | A chaos run with no failure category |
| **Synthetic data** | Invented data (Northwind Labs); never real people or companies |
| **Temperature** | Randomness setting for model outputs; 0 = most deterministic |
| **Tier (`A_lite` / `B_sprint`)** | How many eval cases and chaos runs to use, matched to the plan's quota |
| **Token** | A ~4-character unit of text that models read, write and bill by |
| **Tool match** | Programmatic check that the expected tool calls happened with the expected arguments |
| **Trace archive** | `data/exports/traces.jsonl.gz`: recorded runs for import and replay anywhere |
| **uv** | Fast Python package and environment manager with a lockfile |
| **Verifier** | The last agent; removes unsupported claims from the draft |
