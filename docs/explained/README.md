# Flight Recorder, explained from zero

This folder explains the whole project for someone who has never worked with LLMs, agents or retrieval. Read it in
order: each chapter builds on the previous one. Intuition comes first; code comes last.

| # | Chapter | What you will be able to answer after reading it |
|---|---|---|
| 1 | [Intuition: the problem and the idea](01-intuition.md) | "Why does this project exist? What is an agent, RAG, a judge, chaos testing?" |
| 2 | [Architecture and the life of one request](02-architecture-and-flow.md) | "Walk me through what happens when an employee asks a question." |
| 3 | [Recording, replay and branching](03-recorder-replay-branch.md) | "How do you replay a non-deterministic LLM run exactly?" |
| 4 | [Chaos testing and hardening](04-chaos-and-hardening.md) | "How do you find failure modes before a customer does?" |
| 5 | [Evaluation: how we measure quality](05-evaluation.md) | "How do you know it works? How do you score an LLM's answer?" |
| 6 | [Quotas, infrastructure, testing, delivery](06-quotas-infra-testing.md) | "How did you run this for free? How is it tested and shipped?" |
| 7 | [Code tour, file by file](07-code-tour.md) | "Show me where X happens in the code." |
| 8 | [Decisions and alternatives](08-decisions-and-alternatives.md) | "Why X and not Y?" for every major choice |
| 9 | [Challenges, bugs and lessons](09-challenges-and-lessons.md) | "What went wrong and what did you learn?" |
| 10 | [Interview preparation](10-interview-prep.md) | Pitches, a whiteboard script, ~70 likely questions with answers |
| 11 | [Glossary](11-glossary.md) | Every term used anywhere in these files |

## Where the project stands right now (2026-11-21)

Be precise about this in an interview: it is the single most important honesty point.

- **Built and verified:** all the code for every phase in [`docs/GUIDE.md`](../GUIDE.md): the 5-agent pipeline,
  the recorder, replay, branch, the rate limiter, 8 fault types, the eval and chaos runners, the LLM judge, diff,
  reports, the API, the 3-page UI, static export, the trace archive, Docker, CI. 39 offline tests and 2 database
  integration tests pass; CI is green on GitHub; the Docker image builds and serves the UI.
- **Not yet done:** anything that needs a Gemini API key: choosing the models (probe), generating the policy
  documents, generating eval cases, and every eval/chaos run. So **there are no result numbers yet**.
  `docs/results.md` contains only empty tables, on purpose. Every number you put on a resume must come from
  `docs/results.md` after you run the commands in the main [README](../../README.md).

When a chapter says "the result will show…", it describes what the measurement is, not a measured value.
