# Discovery session (SIMULATED)

> **This is a simulated discovery session**, written to frame the project the way a forward-deployed engineer would
> with a real customer. The persona and quotes are invented; Northwind Labs is a synthetic company.

## Persona
**Priya, IT & HR Operations Lead, Northwind Labs** (~400 employees). Owns the internal help desk: policy questions
(leave, expenses, travel, security), and simple actions (leave balance, IT tickets, expense claims).

## What she told us (simulated)
- "Half our tickets are questions already answered in a policy PDF nobody can find."
- "When the pilot bot gave a wrong expense limit, I couldn't tell *why*. I couldn't re-run what it saw."
- "I need to know it fails *safely*: if the ticketing system is down, it must not tell someone their ticket exists."
- "Before we change the prompt or the model, show me what gets better and what gets worse."

## Pain points → what Flight Recorder does
| Pain point | Capability |
|---|---|
| Can't explain a wrong answer | Trace every LLM / tool / retrieval call with latency, tokens, list-price cost |
| Can't reproduce it | Deterministic replay from the recording (zero API calls) |
| "What if we had changed X at that step?" | Branch from step N with a changed model / temperature / instruction |
| Unknown behaviour when systems fail | Chaos suite: 8 injected faults with a failure taxonomy |
| Risky prompt/model changes | Eval harness + `diff` of two runs (flipped cases, metric deltas) |

## Success targets (proposed, to be checked against `docs/results.md`)
- Wrong-answer rate on policy questions under 5 %.
- Never claims an action succeeded without an id from the system (chaos category `hallucinated_result` = 0).
- Prompt-injection in retrieved documents is not followed (`followed_injection` = 0).
- p95 latency under 15 s per request (excluding free-tier throttling).
- Every change ships with a before/after diff.

## Data-readiness issues actually hit
- Policy numbers had to be pinned in a single `data/facts.yaml`; generated documents are checked against it with
  `flightrec check-facts` (missing facts and extra, unsupported numbers are flagged for human fixing).
- Three documents are PDFs; text extraction (pymupdf) flattens tables, so chunking falls back to character splits.
- Expense limits live in a table (CSV) and in prose; both are indexed, which affects retrieval metrics.
- Eval cases need human review (`flightrec review-cases`) because generated gold answers can be wrong.
