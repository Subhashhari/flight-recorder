# Quota log

## Model probe (2026-11-26T23:14)

Console quotas (AI Studio rate-limit page, read 2026-11-18):

| Console name | Resolved ID | RPM | TPM | RPD |
|---|---|---|---|---|
| Gemma 4 31B | gemma-4-31b-it | 30 | 16000 | 14400 |
| Gemma 4 26B | gemma-4-26b-a4b-it | 30 | 16000 | 14400 |
| Gemini 3.5 Flash Lite | gemini-3.5-flash-lite | 15 | 250000 | 500 |
| Gemini 3.1 Flash Lite | gemini-3.1-flash-lite | 15 | 250000 | 500 |
| Gemini Embedding | gemini-embedding-001 | 100 | 30000 | 1000 |

### Probe results

```json
{
 "Gemma 4 31B": {
  "P1": true,
  "P4": true,
  "P2": false,
  "P2_error": "ServerError: 503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later.', 'status': 'UNAVAILABLE'}}",
  "probe_attempts": 4,
  "passes_agent": false
 },
 "Gemma 4 26B": {
  "P1": false,
  "P4": false,
  "P1_error": "ServerError: 503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later.', 'status': 'UNAVAILABLE'}}",
  "P2": true,
  "probe_attempts": 4,
  "passes_agent": false
 },
 "Gemini 3.5 Flash Lite": {
  "P1": true,
  "P4": true,
  "P2": true,
  "P3": true,
  "P5": true,
  "P5_score": "5/5",
  "P5_samples": [
   "needs_policy=yes; needs_action=yes; employee_id=E1003; task=The employee wants to know their annual sick leave entitlement.",
   "needs_policy=no; needs_action=yes; employee_id=E1012; task=The employee wants to check their current leave balance.",
   "needs_policy=no; needs_action=yes; employee_id=E1020; task=The employee wants to raise an IT ticket because their laptop screen is cracked.",
   "needs_policy=yes; needs_action=yes; employee_id=E1007; task=The employee wants to know their meal limit and file an expense claim of Rs 900 for dinner.",
   "needs_policy=yes; needs_action=no; employee_id=E1031; task=The employee wants to know if they are allowed to work from home on Fridays according to company poli"
  ],
  "P6": true,
  "P6_score": "5/5",
  "P6_calls": [
   [
    "get_leave_balance"
   ],
   [
    "create_it_ticket"
   ],
   [
    "lookup_employee"
   ],
   [
    "submit_expense_claim"
   ],
   [
    "create_it_ticket"
   ]
  ],
  "passes_agent": true
 },
 "Gemini 3.1 Flash Lite": {
  "P7": true,
  "P7_score": "5/5"
 },
 "embedding:gemini-embedding-001": {
  "P8": true,
  "P8_dims": 768
 }
}
```

**Decision (automatic):** Plan B · agent `gemini-3.5-flash-lite` · judge `gemini-3.1-flash-lite` · embeddings `gemini-embedding-001` · tier `B_sprint`

## Per-day calls

Dump with `uv run python scripts/quota_dump.py` (reads the `quota_usage` table).
