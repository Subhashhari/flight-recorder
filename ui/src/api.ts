// In static mode (GitHub Pages) every GET maps to a pre-exported JSON file and write actions are disabled.
export const STATIC = import.meta.env.VITE_DEMO_MODE === "static";
const BASE = import.meta.env.BASE_URL;

export interface Label {
  label: string;
  runs: number;
  scored: number;
  passed: number | null;
  is_chaos: boolean;
  agent_model: string | null;
  prompt_version: string | null;
  first_run: string;
  last_run: string;
}
export interface LabelsFile { labels: Label[]; diffs: string[]; showcase: string[] }
export interface RunSummary {
  run_id: string;
  parent_run_id: string | null;
  branch_seq: number | null;
  label: string | null;
  case_id: string | null;
  mode: string;
  fault: string | null;
  status: string;
  showcase: boolean;
  user_query: string;
  employee_id: string;
  started_at: string;
  passed: boolean | null;
  failure_category: string | null;
  latency_ms: number;
  tokens: number;
  cost_list_usd: number;
  agent_model: string;
  prompt_version: string;
}
export interface RunEvent {
  seq: number;
  ordinal?: number;
  type: "llm_call" | "tool_call" | "divergence";
  agent: string;
  name: string | null;
  request?: unknown;
  response?: unknown;
  latency_ms: number | null;
  tokens_in: number | null;
  tokens_out: number | null;
  cost_list_usd: number | null;
  fault: string | null;
  error: string | null;
  replayed?: boolean;
}
export interface RunDetail extends Omit<RunSummary, "latency_ms" | "tokens" | "cost_list_usd" | "agent_model" | "prompt_version"> {
  final_answer: string | null;
  config: Record<string, unknown> & { agent_model?: string; prompt_version?: string; temperature?: number };
  totals: Record<string, unknown> & { latency_ms: number; tokens_in: number; tokens_out: number; cost_list_usd: number; llm_calls: number; tool_calls: number; recorder_self_ms: number; outputs?: Record<string, string | null> };
  metrics: Record<string, unknown> | null;
  judge_raw: Record<string, unknown> | null;
  events: RunEvent[];
  events_full: boolean;
  children: { run_id: string; mode: string; status: string; branch_seq: number | null }[];
}
export interface ChaosMatrix {
  label: string;
  faults: Record<string, Record<string, number>>;
  categories: string[];
  total_runs: number;
  survived: number;
  survival_rate: number | null;
  failure_modes: [string, string][];
}

export class NotFound extends Error {}

async function getJSON<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (r.status === 404) throw new NotFound(url);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText} for ${url}`);
  return r.json() as Promise<T>;
}

async function post<T>(url: string, body: unknown): Promise<T> {
  if (STATIC) throw new Error("run locally");
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
  return r.json() as Promise<T>;
}

const enc = encodeURIComponent;

export const api = {
  labels: () => getJSON<LabelsFile>(STATIC ? `${BASE}demo-data/labels.json` : "/api/labels"),
  runs: (label: string | null) =>
    getJSON<RunSummary[]>(
      STATIC ? `${BASE}demo-data/runs_${label ?? "_unlabelled"}.json` : `/api/runs?limit=2000${label ? `&label=${enc(label)}` : ""}`,
    ),
  run: (id: string) => getJSON<RunDetail>(STATIC ? `${BASE}demo-data/run_${id}.json` : `/api/runs/${enc(id)}`),
  chaos: (label: string) => getJSON<ChaosMatrix>(STATIC ? `${BASE}demo-data/chaos_${label}.json` : `/api/chaos?label=${enc(label)}`),
  replay: (run_id: string) => post<{ run_id: string; status: string }>("/api/replay", { run_id }),
  branch: (run_id: string, step: number, overrides: Record<string, unknown>) =>
    post<{ run_id: string; status: string }>("/api/branch", { run_id, step, overrides }),
  diffUrl: (name: string) => (STATIC ? `${BASE}diffs/${name}` : `/diffs/${name}`),
};
