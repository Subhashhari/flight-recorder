# 10. Interview preparation

## 10.1 Ground rules for talking about this project

1. **State the status precisely.** "All the tooling is built and tested; the evaluation runs on the real model are
   [in progress / done, here are the numbers]." Before the runs exist, do not quote any result. After they exist, every
   number must match `docs/results.md`, with its denominator ("on a 40-case eval set").
2. **Be honest about how it was built.** If it was built with an AI coding assistant from a written specification,
   say so plainly when asked: "I wrote the specification and design constraints, used an AI coding agent to implement
   it, and verified, debugged and own every part." Interviewers increasingly expect this; what they test is whether
   you understand every decision. That is what these chapters are for.
3. **Name the cost of every choice** (Chapter 8). "We chose X; the downside is Y; we mitigated it with Z."
4. **Say "synthetic", "list-price equivalent", "exploratory (small sample)"**, and never "production" or "Vertex AI".

## 10.2 Pitches

**30 seconds.** "Agents fail in ways that are hard to reproduce, so I built a flight recorder for them. It records
every model and tool call of a five-agent Google ADK pipeline, replays any run deterministically from the recording
with zero API calls, can branch a run at any step with a changed prompt or model, injects eight kinds of faults to
find failure modes, and diffs behaviour between versions. It all runs on free-tier quotas, so I also built a
quota-aware, resumable runner."

**2 minutes.** Add: the subject is PolicyDesk, a help-desk agent for a synthetic company: planner, researcher with hybrid
retrieval over Postgres/pgvector, operator with mock HR/IT/finance tools, writer, verifier. Recording happens in ADK
callbacks, with a request fingerprint so a replay *proves* it is identical (a mismatch is logged as a divergence). That
check caught a real bug: Postgres JSONB re-ordered tool results, which changed downstream prompts. Evaluation covers
four question types with an LLM judge plus exact tool-call checks, retrieval recall and MRR, latency percentiles and
list-price cost, and a 20-label human check on the judge. Chaos testing runs v1 under each fault, then a v2 with
exactly five hardening changes, and compares survival fault by fault. There is a React UI with a five-lane timeline,
deployed as a static demo on GitHub Pages, plus Docker and CI.

## 10.3 Whiteboard script (about 10 minutes)

1. Draw the five agents in a row; write the state keys between them (`plan`, `evidence`, `action_result`, `draft`,
   `final`).
2. Under the researcher, draw Postgres with two arrows (vector top-20, full-text top-20) merging into RRF → top 5.
3. Under the operator, draw four tools → mock backend tables.
4. Draw a box around every model and tool call labelled "Recorder callbacks", and inside it: limiter → live / replay /
   branch / chaos → buffered events → one transaction.
5. Show an event row: `seq, ordinal, agent, type, request, response, request_hash, latency, tokens, fault`.
6. Explain replay (lookup by agent + kind + ordinal, hash check, divergence) and branch (cache below step N, live from N).
7. Draw the eval loop: cases → run → programmatic checks + judge → scores → report/diff; and the chaos loop with the
   failure taxonomy.
8. Finish with the delivery path: export → static JSON → GitHub Pages; archive → `make demo`.

## 10.4 Demo script (3 minutes, from the guide)
1. Demo site: a run's five-lane timeline; click bars to show prompts, latency, tokens.
2. A v1 chaos run with `retrieval_prompt_injection` classified `followed_injection`; show the injected text in the search
   result and the canary in the reply.
3. Its pre-recorded **branch** child with the v2 patch: same cached prefix (faded bars), live from the writer, passes.
4. The chaos page: heatmap and v1 vs v2 survival.
5. The README results table and a diff page (flipped cases).

## 10.5 Likely questions with answers

### Motivation and product
1. **Why build this?** Building agents is easy; knowing *when and why* they fail is hard. Reproducing a failure,
   testing a fix on that exact failure and preventing regressions are the bottlenecks to deploying agents.
2. **Who is the user?** The engineer or "forward-deployed" engineer responsible for an agent in a customer
   deployment, and the operations lead who needs evidence that it is safe.
3. **How is it different from Langfuse or LangSmith?** They observe and evaluate; this also *controls execution*:
   deterministic replay, branching at step N, fault injection with a taxonomy, all quota-aware. In production I would
   send the traces to such a tool and keep the replay and chaos engine.
4. **Why a synthetic company?** Known ground truth, no privacy risk (free-tier prompts may be used for training),
   reproducible anywhere. The cost: cleaner than real data.

### LLM and agent basics
5. **What is an agent here?** An LLM plus tools in a loop: the model requests a function call, our code executes it and
   returns the result, the model continues.
6. **Why five agents instead of one?** Single responsibility, checkable intermediate outputs, failure attribution, a
   meaningful timeline. Cost: ~7 calls per run.
7. **How do agents share information?** ADK session state: each agent's output is saved under its `output_key`;
   later instructions reference `{plan}`, `{evidence}`, and so on, and ADK fills them in.
8. **Why temperature 0?** To minimise variance for evaluation. It does not guarantee determinism (server batching,
   floating-point, model updates), which is why replay exists and repeatability is measured.
9. **What does the verifier do, and could it hurt?** It removes claims not supported by evidence or action results. It
   can also wrongly remove or alter correct content; the eval measures the net effect.
10. **What happens if the model loops?** `max_llm_calls = 25` stops it; the run is `budget_exceeded`; v2 returns a fixed
    apology instead of an empty answer.

### Retrieval
11. **Explain embeddings to a non-expert.** A list of numbers that places text in a space where similar meanings are
    close; we compare with cosine similarity.
12. **Why hybrid search?** Vectors capture meaning but can miss exact tokens (L3, MFA, P1); keywords capture tokens but
    not paraphrase. Fusing both is more robust.
13. **What is RRF and why k = 60?** Score = Σ 1/(k + rank) across lists; it uses ranks, so no score normalisation is
    needed between cosine and `ts_rank`; 60 is the standard default from the original paper, which damps the influence of
    the very top ranks.
14. **Any weakness in your hybrid search?** Yes: `plainto_tsquery` ANDs all words, so long questions often match
    nothing in full-text and hybrid ≈ vector. `websearch_to_tsquery` or an OR query is the next experiment;
    `eval-retrieval` will quantify it.
15. **Why 1,200-character chunks with 150 overlap?** About one rule or one table per chunk; overlap protects facts that
    straddle boundaries; heading-aware splitting keeps sections intact.
16. **Why pgvector and not Pinecone?** One database for vectors, full-text, mock data and runs; HNSW is fast enough; no
    extra service. A dedicated store matters at much larger scale or with heavy filtering.
17. **How do you evaluate retrieval separately?** recall@5 and MRR against gold documents, computed by `eval-retrieval`
    without running the agent (cheap, cached embeddings).

### Recording, replay, branch
18. **How do you record without modifying ADK?** Its four callbacks (before/after model and tool) attached to every
    agent; `callbacks.py` is the only ADK-aware file.
19. **How does replay work?** `before_model` and `before_tool` return the recorded response for the same
    (agent, kind, ordinal) instead of letting the call happen. The model is never contacted, so it is free and works with
    a dummy key.
20. **How do you know a replay is faithful?** Every request is hashed (model, system instruction, contents, tool names,
    with volatile ids stripped); a mismatch with the recording emits a `divergence` event and marks the run `diverged`.
    `replay-check` measures identity across a whole label.
21. **Why look up by ordinal and not by hash?** A hash miss would stop the replay; we want to continue and *report* the
    difference. Global `seq` would misalign after any extra call.
22. **Why strip ids from the hash?** ADK assigns random function-call ids; without stripping, every replay would look
    divergent.
23. **What is branching for?** A controlled experiment on one real incident: identical prefix (including the injected
    fault), then a change from step N. If the outcome changes, the change caused it.
24. **What can you override in a branch?** Model (same backend), temperature, text appended to a specific agent's
    instruction.
25. **Does replay have side effects?** No: tools are served from the recording. A branch *does* execute tools after step N,
    which in a real system would need sandboxing.
26. **Why buffer events and write once?** No DB latency in the measured path, no half-written runs, atomicity.
27. **Tell me about a bug you found.** The JSONB key-order bug (Chapter 9.1): found by the hash check, root cause in how
    ADK renders tool results, fixed with JSON columns and a regression test.
28. **What are the limits of replay?** It reproduces the agent given recorded inputs, not the model; ADK upgrades could
    change call order (visible as divergences); temperature is not in the hash.
29. **How is overhead measured?** Time inside recorder code excluding limiter waits, divided by run latency;
    `flightrec stats`.
30. **Why context variables?** Callbacks receive ADK's context, not ours; a `ContextVar` gives each async task its own
    current run, so concurrent runs cannot mix.

### Chaos
31. **What is chaos engineering?** Injecting failures deliberately and in a controlled way to find weaknesses before users do.
32. **Which faults and why those?** Four ways a back-office call fails (timeout, 500, malformed, empty), partial data
    (missing fields), and three retrieval failures (empty, irrelevant, poisoned). Together they cover the failure modes that lead to
    invented results, invented policy and injection.
33. **How is a fault injected?** In the recorder callbacks: pre-execution faults are returned by `before_tool` (the tool
    never runs); result faults mutate the real result in `after_tool`, keeping the original.
34. **How do you classify failures?** An ordered taxonomy: budget, crash, followed injection (code-checked canary or
    E1001 ticket), hallucinated result, hallucinated policy, ungraceful (judge-assisted), otherwise survived.
35. **Why a canary string?** It is unambiguous and code-checkable; it does not depend on a judge that might itself be
    affected by the injection.
36. **What did v2 change?** Exactly five things (Chapter 4.5). Asked "why only five": attribution.
37. **Does `safe_tool` handle injected timeouts?** No: injected faults are returned before the tool runs; `safe_tool`
    protects against *real* exceptions. The prompt patches handle injected faults. (Shows you know the code.)
38. **Is a 6-runs-per-fault sample meaningful?** Per fault it is exploratory (one run is about 17 points); the overall
    survival rate and the v1 vs v2 direction across faults are more informative. With more quota, increase N.
39. **What if the fault never fires?** Recorded as `fault_fired = false`; the matrix shows fired counts, so a "survival"
    without a fault is not mistaken for robustness.
40. **Do you defend against prompt injection completely?** No. Delimiting untrusted text and telling the model it is data
    reduces risk; real defences add privilege separation (tools that cannot be triggered by retrieved text),
    allow-lists, and output filtering. Also note ADK 2.15 already quotes other agents' output as data.

### Evaluation and statistics
41. **How do you score free-text answers?** An LLM judge with a JSON schema for meaning; code for exact things (tool
    calls); 20 human labels to measure judge agreement.
42. **Why not exact match or embedding similarity?** Many correct phrasings; similarity cannot distinguish ₹1,000 from
    ₹1,500.
43. **What are the four categories and their success rules?** Chapter 5.3.
44. **Why macro-average success?** Each category counts equally; otherwise the largest category dominates.
45. **What is hallucination rate here?** Share of qa + multi runs judged `grounded = false`.
46. **p50 vs p95?** Median vs tail; p95 is what users notice; latency excludes limiter waits.
47. **What is MRR?** Mean of 1/rank of the first relevant document; it rewards ranking it first.
48. **How were test cases created?** LLM-proposed qa and unanswerable (reviewed by a human; unanswerable filtered by
    similarity ≤ 0.8), templated action and multi with expected calls computed from data.
49. **How do you know the judge is right?** You do not fully; judge agreement on 20 hand labels quantifies it. If
    low, say so and weigh the numbers accordingly.
50. **How would you make the numbers statistically solid?** Larger eval sets, repeated runs with confidence intervals
    (for example bootstrap), paired comparisons on the same cases, multiple judges or a stronger judge.
51. **What does `diff` add over two averages?** Flipped cases: an average can hide fixes and regressions cancelling out.
52. **How do you avoid cherry-picking?** `docs/results.md` is generated from the DB by a command; fake-model runs are
    excluded by construction; rate-limited and paused runs are excluded by rule; regressions are reported.

### Quotas, operations, infrastructure
53. **How did you run hundreds of calls on 500/day?** A limiter for requests/minute, tokens/minute and a persisted daily counter
    (90 % safety), resumable runs that pause at the daily limit and continue after midnight Pacific, cached embeddings,
    zero-cost replay, re-scoring without re-running.
54. **Why not just retry on 429?** Rejected calls still waste daily quota, and backoff cannot know when the day resets.
55. **Sliding window vs token bucket?** A sliding log enforces "at most N in any 60 s" exactly, matching how the
    provider counts; the volume is tiny, so storing timestamps is free.
56. **How were models chosen?** An automatic probe (P1–P8) and a fixed decision rule; Plan A Gemma 4 if it passes, else Plan B
    Flash Lite.
57. **Why is the agent model different from the judge model?** Quotas are per model, and a judge should ideally not be
    the same model it grades.
58. **What does Docker do here?** Runs the exact Postgres+pgvector image anywhere; a multi-stage image bundles the API and
    built UI for reviewers.
59. **What does CI check?** Locked install, lint, offline tests, Docker build, on every push.
60. **How is the public demo hosted for free?** A static export of runs to JSON, the same React UI in static mode on
    GitHub Pages, with a HashRouter for deep links.
61. **How is the API key protected?** Only in `.env` (git- and Docker-ignored), never printed; API bound to
    127.0.0.1.

### Testing
62. **How do you test code that depends on an LLM?** A scripted fake model registered in ADK, so the real framework and
    callbacks run deterministically; unit tests for pure logic; a fake clock for the limiter; DB integration tests in a
    separate database.
63. **Why not mock ADK?** The risky part is the integration with ADK (callback semantics, short-circuits, state
    templating); mocking it away would hide exactly those bugs.
64. **What do the tests not cover?** The real model's quality and the exact provider errors; those come from the probe,
    the spike and the eval runs.

### Scaling and production
65. **How would you run this in production?** Export events as OpenTelemetry spans; record continuously with sampling;
    store payloads in object storage with PII redaction; replay incidents from production traces in a sandbox; run
    chaos and evals in CI on every prompt or model change, with gates on regressions.
66. **What about concurrency?** Context variables already isolate runs; the limiter has a lock; you would add an
    async-aware limiter and parallel workers per model pool.
67. **What about privacy?** Redact or tokenise PII before storing prompts; access control on traces; retention limits.
68. **How would this generalise to other frameworks?** The core is framework-agnostic; write one adapter per framework
    (LangGraph callbacks, OpenAI Agents SDK hooks) mapping to the same events.

### Behavioural
69. **What was the hardest part?** Making replay provably faithful (idempotent callbacks across ADK's asymmetric
    short-circuits, volatile-id stripping, the JSONB bug).
70. **What would you do differently?** Put the generation config in the hash; consider ADK runner plugins for single
    registration; start retrieval with `websearch_to_tsquery`; plan the eval budget per category earlier.
71. **What are you most proud of?** That every number is traceable to a command and the system checks its own replay
    fidelity.

## 10.6 Hard or trap questions

- **"Temperature 0 is deterministic, so why replay?"** It is not deterministic in practice (batching, floating-point,
  model updates), and replay also freezes the tools and data, which change. The repeatability study measures the
  live variance.
- **"Your judge grades its own family of models; isn't that circular?"** Partly: a known bias. Mitigations: structured
  rubric, code checks where possible, human agreement check; better: a different or stronger judge.
- **"40 cases is tiny."** Yes; it is sized to a free-tier quota; numbers are reported with denominators and small
  samples marked exploratory; the harness scales with quota.
- **"Isn't a fake LLM test meaningless?"** It tests the machinery (recording, replay, faults, scoring) through the real
  framework, which is exactly what can be tested deterministically; model quality is measured separately.
- **"Could v2 just be refusing more?"** Possibly; that is why clean success is re-measured on v2 and flipped cases are
  inspected; a drop of more than 3 points is reported as a trade-off.

## 10.7 What I would do next
1. Run the full experiment plan and publish the numbers.
2. Retrieval: `websearch_to_tsquery`, a re-ranker, the chunk-size ablation.
3. Add generation config to the request hash; a replay "strict mode" that stops at the first divergence.
4. OpenTelemetry export; CI gate that runs a small eval and chaos suite on every prompt change.
5. Privilege separation for tools (retrieved text can never trigger `create_it_ticket`), a stronger injection
   defence than prompt wording.
6. Bigger eval set with confidence intervals; a second judge model.

## 10.8 Numbers to fill in after the runs (copy from `docs/results.md`)

| Claim | Where it comes from | Value |
|---|---|---|
| Eval size, corpus size | `flightrec stats` | ___ cases, ___ chunks / 12 documents |
| Task success v1 → v2 | Clean eval table | ___ % → ___ % |
| Hallucination rate v1 → v2 | Clean eval table | ___ % → ___ % |
| recall@5, MRR hybrid vs vector | Retrieval table | ___ / ___ vs ___ / ___ |
| Chaos survival v1 → v2 | Chaos tables | ___ % → ___ % (exploratory) |
| Failure modes found | `failure_modes` in the v1 chaos matrix | ___ |
| p50 / p95 latency, tokens/run, list-price $/run | Clean eval table | ___ |
| Tracing overhead | Reproducibility table | ___ % |
| Live runs differing at temperature 0; replay identical | Reproducibility table | ___ % of ___ cases; 100 % |
| Judge agreement | Judge agreement table | ___ % on 20 labels |

## 10.9 Never claim
- Any number not in `docs/results.md`.
- "Production", "real users", "deployed on GCP/Cloud Run", "Vertex AI".
- That prompt changes "solve" prompt injection.
- That per-fault rates from 6 runs are significant.

## 10.10 How a 2-hour interview might go
| Time | Likely focus | Prepare with |
|---|---|---|
| 0–15 min | pitch, motivation, product framing | 10.2, Chapter 1 |
| 15–45 min | architecture whiteboard, request walkthrough | 10.3, Chapter 2 |
| 45–75 min | deep dive: replay/branch or chaos or eval | Chapters 3–5 |
| 75–100 min | trade-offs, alternatives, scaling, production | Chapter 8, 10.5 (65–68), 10.7 |
| 100–120 min | bugs, lessons, behavioural, your questions | Chapter 9, 10.5 (69–71) |
