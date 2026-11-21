# Project rules (read every session)
- The full specification is in docs/GUIDE.md. Follow it exactly. Do not redesign.
- Read PROGRESS.md first to see where you stopped; append to it after every phase.
- Never print, log, echo or commit the value of GOOGLE_API_KEY or the contents of .env.
- Never run `git push`. Commit locally after each phase (`git add -A && git commit -m "phase N: ..."`).
- Never invent results. Numbers in docs/results.md must come from commands you ran; if you cannot run something, say so in PROGRESS.md.
- All LLM and embedding calls must go through the limiter (recorder/ratelimit.py). Never run bulk jobs except via `flightrec eval|chaos --resume`.
- Do not enable billing, add paid services, or change models/limits/tier once chosen in Phase 0.
- Prefer writing whole files in one step; avoid long exploratory chatter (the agent has a daily request limit).
- Stop at each Gate, show the evidence (command output), and wait for the next instruction.
