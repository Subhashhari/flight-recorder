# 1. Intuition: the problem and the idea

## 1.1 The one-paragraph version

Companies are starting to deploy **AI agents**: programs where a large language model (LLM) reads a request, decides
what to do, calls tools (databases, ticketing systems, search) and writes an answer. These agents fail in strange,
hard-to-reproduce ways: they give a wrong number, claim to have done something they did not do, or obey an instruction
hidden inside a document. **Flight Recorder** is a toolkit that makes such failures visible and repeatable. It
**records** every step an agent takes, **replays** a recorded run exactly (without calling the AI again), **branches**
a run ("what if, at step 7, the agent had been told something different?"), **injects faults** on purpose to see how
the agent copes, and **evaluates** and **compares** versions of the agent with numbers. The agent it tests is
**PolicyDesk**, a help-desk assistant for a made-up company called Northwind Labs.

The name comes from aviation: an aircraft's flight recorder ("black box") stores everything that happened, so after
an incident investigators can reconstruct exactly what went wrong. We do the same for AI agents.

## 1.2 Background from zero

You need about ten ideas to understand everything else. Each is explained with an everyday analogy.

### What is an LLM?
A **large language model** is a program trained on a huge amount of text to do one thing: given some text, predict
what text comes next. If you give it "The capital of France is", it continues with "Paris". Because it has read so
much, "predict the next words" turns out to be enough to answer questions, summarise, write code and follow
instructions. Examples: Google's Gemini and Gemma, OpenAI's GPT, Anthropic's Claude.

Key consequences:
- **It does not look things up.** It answers from patterns it learned. It knows nothing about Northwind Labs' leave
  policy, because that policy is private (here, invented). If you ask anyway, it may confidently make something up.
  This is called **hallucination**.
- **It is accessed through an API.** You send text over the internet to Google's servers and get text back. Each call
  takes time (latency), and providers limit how many calls you may make.

### Tokens
LLMs read and write **tokens**, chunks of text of roughly 4 characters (about ¾ of a word in English). "Northwind Labs"
is about 3–4 tokens. Providers count and charge per token: **input tokens** (what you send) and **output tokens**
(what it writes). When this project says "tokens/run" or "cost", that is what it means.

### Prompt, system instruction, temperature
- The **prompt** is the text you send.
- A **system instruction** is a special part of the prompt that sets the model's role and rules ("You are the planning
  step of a help desk… Output exactly one line…"). The model treats it as higher priority than the user's text.
- **Temperature** controls randomness. The model actually produces a probability for every possible next token; at
  temperature 0 it (nearly) always picks the most likely one; at higher temperatures it sometimes picks less likely
  ones, so answers vary. We use temperature 0 for evaluation because we want stable behaviour.

**Important subtlety, central to this project:** even at temperature 0, LLM APIs are *not perfectly deterministic*.
The same request can return a slightly different answer because of how the servers batch requests, floating-point
arithmetic on GPUs, and silent model updates. So "just run it again" does not reproduce a bug reliably. That is the
core motivation for recording and replay.

### What is an "agent"?
A plain LLM only produces text. An **agent** is an LLM placed in a loop with **tools**:

1. The program sends the model the task plus a list of available tools (for example `get_leave_balance(employee_id)`).
2. The model may answer: "call `get_leave_balance` with `employee_id = E1003`". This is called **function calling**
   or **tool calling**. The model does not run anything itself; it only asks.
3. The program runs the real function, sends the result back to the model, and the model continues, perhaps calling
   another tool or writing the final answer.

Analogy: the LLM is a smart new employee who cannot touch any system. It can only write requests on sticky notes
("please look up E1003's leave balance"); a clerk (our code) does the lookup and hands back the result.

### Multi-agent pipeline
Instead of one model doing everything, we split the job into specialised steps, each a separate "agent" with its own
instruction. PolicyDesk has five, run one after another like an assembly line:

| Step | Job | Analogy |
|---|---|---|
| planner | decide whether the request needs policy information, an action, or both | receptionist who triages |
| researcher | search the policy documents and quote relevant passages | librarian |
| operator | call back-office tools (leave balance, tickets, expense claims, employee lookup) | clerk |
| writer | draft the reply to the employee, citing sources | writer |
| verifier | check every claim in the draft against the evidence; remove unsupported ones | editor / fact-checker |

Splitting makes each step simpler and easier to inspect. It also means a failure can be pinned to one step.

### RAG: retrieval-augmented generation
The model does not know company policy, so before answering we **retrieve** relevant passages from the company's
documents and put them in the prompt. "Answer using only these passages." This is **RAG**. It needs three pieces:

1. **Chunking.** Documents are split into pieces of about 1,200 characters (with 150 characters of overlap so a
   sentence cut at a boundary still appears whole in one chunk). Smaller pieces mean more precise search results.
2. **Embeddings.** An embedding model turns a piece of text into a list of numbers (here 768 numbers), a point in a
   768-dimensional space, placed so that texts with similar *meaning* land close together. "How many sick days do I
   get?" lands near "Employees receive 10 days of sick leave per year" even though they share few words.
   Closeness is measured with **cosine similarity** (the angle between two vectors; 1 = same direction).
3. **Search.** At question time we embed the question and find the closest chunks (**vector search**). We also run
   classic **keyword (full-text) search**, which is better at exact terms like "L3" or "MFA". Combining both is
   **hybrid search**. We merge the two ranked lists with **Reciprocal Rank Fusion (RRF)**: each chunk scores
   `1/(60 + its rank)` in each list, and the scores are added. A chunk that ranks well in both lists wins.

The chunks and their embeddings live in **Postgres** (a database) with the **pgvector** extension, which adds a vector
column type and fast nearest-neighbour search.

### Evaluation and "LLM as judge"
How do you know if an answer like "You get ten sick days a year, and I've filed your ₹900 claim" is correct? Exact
string matching fails (there are many correct phrasings). Options are human grading (accurate, slow, expensive) or
using **another LLM as a judge**: give it the question, a gold (reference) answer, the evidence and the reply, and ask
structured yes/no questions ("Is it correct? Is every claim supported by the evidence?"). This is standard practice.
Because a judge can itself be wrong, we measure **judge agreement**: a human labels 20 replies, and we report how often
the judge agrees.

Some things should *not* be judged by an LLM because code can check them exactly. "Did the agent call
`submit_expense_claim` with category `meals` and amount 900?" is checked **programmatically**.

### Chaos engineering
Netflix famously ran "Chaos Monkey", a program that randomly shut down servers in production, to prove the system
survived failures. The idea: **inject failures deliberately, in a controlled way, to find weaknesses before real
users do.** We do this to the agent: make a tool time out, return an HTTP 500 error, return garbage, return nothing,
or make the search return irrelevant text or a malicious instruction. Then we check: did the agent tell the employee
something went wrong, or did it invent a ticket number?

### Prompt injection
Text that the model reads (for example a retrieved document) can contain instructions: "SYSTEM NOTICE: ignore all
previous instructions and…". Models sometimes obey such text, because to a model, instructions and data are both just
text. This is **prompt injection**, the number-one security risk for LLM apps. One of our faults plants exactly such an
instruction inside a search result and checks whether the agent obeys it. A unique marker string (`CANARY-7731`) makes
detection unambiguous: if it appears in the final reply, the agent followed the injected instruction.

### Rate limits and free tiers
API providers limit usage per model:
- **RPM**: requests per minute.
- **TPM**: tokens per minute.
- **RPD**: requests per day. On Google's free tier the day resets at midnight Pacific time, which is 13:30 in India
  (until March, because of US daylight-saving rules).

This project runs entirely on the **free tier** (cost ₹0). For example, Gemini 3.5 Flash Lite allows only 15 requests
per minute and 500 per day. A single PolicyDesk run makes about 7 model calls, so the daily budget allows only a few
dozen runs. That constraint shaped a lot of the engineering (Chapter 6).

## 1.3 The problem, concretely

Imagine PolicyDesk is in a pilot at Northwind Labs. An employee complains: "It told me my meal limit was ₹1,500, but
I'm grade L2 and my limit is ₹1,000." You want to answer four questions:

1. **What exactly happened?** Which step got it wrong: the search (wrong passage), the planner (wrong plan), the
   writer (misread the evidence), the verifier (failed to catch it)?
2. **Can I see it again?** Re-running the same question today may produce a different answer (non-determinism, the
   database changed, the model was updated). The bug "disappears".
3. **Would a fix have helped?** If I change the writer's instruction, would *this exact situation* come out right? I
   want to rerun from the point just before the writer, with everything earlier held identical.
4. **What else is broken that nobody has reported?** And did my fix make anything else worse?

Ordinary logging only partially answers question 1. Nothing standard answers 2 and 3 for multi-agent runs, and 4 needs
a test suite designed for LLM failure modes.

## 1.4 The idea: five capabilities

| Capability | Plain-English meaning | Answers question |
|---|---|---|
| **Trace (record)** | Save every model call and tool call: the exact request, the exact response, timing, tokens, cost | 1 |
| **Replay** | Re-run a recorded run, but instead of calling the model, hand back the saved responses. The run is identical and costs nothing. It even works without a valid API key | 2 |
| **Branch** | Replay up to step N exactly, then continue live from step N with a change (a different model, temperature or instruction) | 3 |
| **Chaos** | Run the agent with one deliberately injected fault and classify how it failed | 4 |
| **Eval + diff** | Score the agent on a fixed set of test questions; compare two versions case by case ("these 3 cases got fixed, this 1 broke") | 4 |

A good mental model: **PolicyDesk is the car; Flight Recorder is the dashcam, the crash-test lab and the
before/after comparison report.**

## 1.5 Why this is interesting (what an interviewer is really probing)

- **Reliability of AI systems is the bottleneck for deploying them.** Building a demo agent is easy; knowing when it
  fails, why, and whether a change helped is the hard, valuable part. This project is about the hard part.
- **It shows engineering judgement under constraints:** free-tier quotas forced a quota-aware, resumable runner;
  honesty rules force every reported number to come from a command.
- **It is end to end:** data generation, retrieval, agents, instrumentation, testing, evaluation, a UI, CI and
  deployment.

## 1.6 What makes it hard (preview of later chapters)

1. **Intercepting an agent framework without changing it.** We use the framework's *callbacks* (hooks that run before
   and after every model and tool call) to record and to substitute cached responses. Chapter 3.
2. **Knowing a replay is faithful.** We fingerprint every request (a hash) and flag any difference as a `divergence`.
   Chapter 3.
3. **Branching mid-run.** Steps before N must be byte-for-byte identical, or the "what if" is meaningless.
   Chapter 3.
4. **Scoring free-text answers fairly.** LLM judge plus programmatic checks plus a human agreement check. Chapter 5.
5. **Running hundreds of model calls on 500 calls/day.** Our own rate limiter with a daily counter, and runs that
   pause and resume. Chapter 6.

## 1.7 Honesty rules the project follows

These come from the guide, and they are worth stating in an interview because they show maturity:

- Never invent results. Every number in `docs/results.md` is produced by a command that is printed next to it.
- Cost is reported as a **list-price equivalent** (what it *would* cost on the paid tier); actual spend is ₹0.
- All data is **synthetic** (a fictional company); never call it "production".
- Small samples are labelled **exploratory** (for example 6 chaos runs per fault).
- Regressions are reported, not hidden (if the hardened version answers fewer clean questions correctly, say so).

Next: [Chapter 2: architecture and the life of one request](02-architecture-and-flow.md).
