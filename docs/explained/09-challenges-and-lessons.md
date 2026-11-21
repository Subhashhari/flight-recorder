# 9. Challenges, bugs and lessons

These all actually happened during the build (2026-11-21). Each has the symptom, the root cause, the fix and the
lesson. Interviewers love "tell me about a bug you found"; the first three are the best stories.

## 9.1 The JSONB bug: replays from the database were not faithful (best story)
- **Symptom:** in-memory replay tests passed, but the first replay of a run *loaded from Postgres* came back
  `diverged`, with two divergences, at the writer and the verifier.
- **Investigation:** diffed the source and replay request contents for those agents. The only difference was the order
  of keys in a tool result: `{'employee_id': 'E1003', 'casual': 5, …}` versus `{'sick': 5, 'casual': 5, …}`.
- **Root cause:** Postgres JSONB does not preserve object key order. ADK renders a tool result into later agents'
  context as Python `str(dict)`, which is order-sensitive. So the stored-and-reloaded cached result produced a
  different prompt for downstream agents.
- **Why it mattered:** in replay it was a false alarm; in **branch** mode the live part would have run on a different
  prompt than the original, silently invalidating "what if" experiments.
- **Fix:** `events.request` and `events.response` became `JSON` (text-preserving), with an idempotent migration; the
  integration test now asserts zero divergences after a DB round-trip.
- **Lessons:** (1) a self-check (the request hash) is what found it, so build verification into the system, not just
  into tests; (2) "equal as data" is not "equal as text" once a framework turns data into prompt text; (3) test the
  real storage path, not only the in-memory one.

## 9.2 Building and verifying without an API key
- **Challenge:** no Gemini key was available while building, yet almost every feature involves model calls.
- **Approach:** (1) read the installed ADK source to confirm the real API instead of trusting older docs; (2) write a
  scripted fake model as a real ADK `BaseLlm`, so the actual framework, callbacks and tool calling run in tests;
  (3) make the spike answer framework-behaviour questions offline with a recording model, and leave only the
  questions that truly need the API (real token counts, the exact 429 error) marked pending; (4) tag fake-model runs
  so they can never leak into results.
- **Lesson:** separate "is my code correct?" (testable offline, deterministically) from "is the model good?"
  (measurable only with the real model). Do not let the second block the first.

## 9.3 Discovering ADK 2.x behaviour (versions move fast)
- **Facts found by inspection and the spike:**
  - Callback signatures: `before_model(callback_context, llm_request)`, `after_model(callback_context, llm_response)`,
    `before_tool(tool, args, tool_context)`, `after_tool(tool, args, tool_context, tool_response)`.
  - A short-circuited model call skips `after_model`; a short-circuited tool call still triggers `after_tool`. This
    asymmetry led to the idempotent `pending` design.
  - Mutating `llm_request.model`, the system instruction and the temperature in `before_model` changes the real
    request, which is what makes branch overrides work.
  - Gemma 4 model names are routed to the same Gemini client natively (no special adapter).
  - ADK 2.15 wraps other agents' outputs in a "quoted data, never instructions" block, visible in recorded requests.
    It affects token counts and prompt-injection results, so it is documented in `docs/feature-requests.md`.
- **Lesson:** for fast-moving libraries, verify against the installed version and record the facts with the evidence.

## 9.4 The fake model that read its own instructions
- **Symptom:** the first offline pipeline test showed no search call; the researcher always answered `NOT_NEEDED`.
- **Root cause:** the fake checked whether the text `needs_policy=no` appeared anywhere in the system instruction,
  but the instruction itself says "If needs_policy=no, output exactly NOT_NEEDED". The rule matched its own text.
- **Fix:** extract only the plan portion (between `Plan:` and `. If needs_`) before checking.
- **Lesson:** when parsing text that is embedded in instructions, scope the parse. This is the same class of problem
  as prompt injection: instructions and data mixed in one string.

## 9.5 A 265-second test suite that should take 3 seconds
- **Symptom:** the integration tests passed but took 4.5 minutes.
- **Investigation:** timed raw connections: `127.0.0.1` connected in ~15 ms; `localhost` stalled for ~20 s per
  connection (on Windows it tries IPv6 `::1` first, which hung against Docker Desktop's port relay).
- **Fix:** all connection strings use `127.0.0.1`. The suite went from 265 s to 2.8 s.
- **Lesson:** measure before guessing; a slow test is a bug report.

## 9.6 Port 5432 already in use
- **Symptom:** `docker compose up` failed: port already allocated. Another project on the machine (its own Postgres)
  used 5432.
- **Fix:** do not touch the other project; make the host port configurable (`FLIGHTREC_DB_PORT`, default 5432), and use
  5433 on that machine via `.env`.
- **Lesson:** never hard-code shared resources; never "fix" a conflict by stopping someone else's service.

## 9.7 Windows-specific traps
- The guide was written for macOS; the build machine was Windows 11. Added `tasks.ps1` with the same targets as the
  Makefile, and `.gitattributes` to normalise line endings.
- PowerShell 5.1's `-Encoding utf8` writes a byte-order mark (BOM). In `.env` that would have turned the first key into
  `﻿GOOGLE_API_KEY`, silently breaking the API key. Caught and stripped immediately.
- An empty `GOOGLE_API_KEY=` line was treated as "set", which stopped replay from installing a dummy key. Now empty
  values count as unset.

## 9.8 Smaller correctness bugs caught by tests and lint
- `make_pdfs.py`: `out += [...]` inside a nested function made `out` a local variable, so any document with a table
  would have crashed. The linter flagged it (F841) and a PDF round-trip test now covers it.
- `check-facts` did not recognise `16` inside `11:00–16:00` written with an en dash, and reported it as an "extra
  number". Fixed the number extraction for string facts and added a test.
- Failure taxonomy: implementing the guide's order literally (crash before budget) would have made `budget_exceeded`
  unreachable, because a budget overrun also has a non-`ok` status. Budget is checked first.
- Spike (g) showed `diverged` because the test relabelled the model name, which is part of every request hash. That is
  the expected result, and the spike's message now says so explicitly, so nobody misreads it.

## 9.9 Designing for 500 requests per day (planned challenge)
- Not a bug but the dominant constraint: quota math, the three-dimensional limiter, persisted daily counters, pause and
  resume, re-scoring without re-running, cached embeddings, zero-cost replay. See Chapter 6.

## 9.10 Things still ahead (likely challenges once the key is in)
- Whether the chosen agent model follows the planner format and tool-calling reliably (probes P5/P6 decide Plan A/B).
- Gemma's 16,000 tokens/minute with growing prompts may make Plan A slow; the limiter will throttle rather than fail.
- Generated policies will need `check-facts` fixes; generated qa gold answers will need human review.
- The exact text of the free-tier 429 error must be confirmed by the spike (f).
- GitHub Pages has to be enabled once in the repository settings before the deploy workflow can succeed.

## 9.11 Lessons in one list
1. Verify replay with a fingerprint; do not assume it.
2. Test the real storage path; serialisation can change semantics.
3. Separate testing your code from evaluating the model.
4. Read the installed library, record behaviour as evidence.
5. Make limits and resources configurable; measure performance problems.
6. Keep every reported number traceable to a command; exclude test-double runs by construction.
7. Change one thing at a time (five named hardening changes) so results are attributable.

Next: [Chapter 10: interview preparation](10-interview-prep.md).
