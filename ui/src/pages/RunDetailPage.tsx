import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { RunDetail, RunEvent, STATIC, api } from "../api";
import { ErrorBox, StatusPill, sec, usd, useLoad } from "../util";

const LANES = ["planner", "researcher", "operator", "writer", "verifier"];

export default function RunDetailPage() {
  const { id = "" } = useParams();
  const run = useLoad(() => api.run(id), [id]);
  if (run.error) return <ErrorBox error={run.error} />;
  if (!run.data) return <div className="empty">Loading…</div>;
  return <Detail key={id} r={run.data} />;
}

function Detail({ r }: { r: RunDetail }) {
  const nav = useNavigate();
  const events = useMemo(() => [...r.events].sort((a, b) => a.seq - b.seq), [r.events]);
  const [sel, setSel] = useState<RunEvent | null>(events.find((e) => e.fault || e.type === "divergence") ?? events[0] ?? null);
  const [busy, setBusy] = useState("");
  const [append, setAppend] = useState("");
  const [msg, setMsg] = useState("");

  // timeline: the pipeline is sequential, so bars are laid end-to-end in seq order, sized by latency
  const layout = useMemo(() => {
    let t = 0;
    const MIN = 40;
    return events
      .filter((e) => e.type !== "divergence")
      .map((e) => {
        const w = Math.max(e.latency_ms ?? 0, MIN);
        const x = t;
        t += w;
        return { e, x, w };
      })
      .map((b, _i, all) => ({ ...b, total: all.length ? all[all.length - 1].x + all[all.length - 1].w : 1 }));
  }, [events]);
  const divergent = new Set(events.filter((e) => e.type === "divergence").map((e) => e.agent));
  const total = layout[0]?.total ?? 1;

  async function act(kind: "replay" | "branch") {
    if (!sel) return;
    setBusy(kind);
    setMsg("");
    try {
      const res =
        kind === "replay"
          ? await api.replay(r.run_id)
          : await api.branch(r.run_id, sel.seq, append.trim() ? { instruction_append: { [sel.agent]: append.trim() } } : {});
      nav(`/runs/${res.run_id}`);
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy("");
    }
  }

  const branchChild = r.children.find((c) => c.mode === "branch");
  const outputs = r.totals.outputs ?? {};
  return (
    <section>
      <p className="crumbs">
        <Link to={r.label ? `/?label=${encodeURIComponent(r.label)}` : "/"}>← {r.label ?? "runs"}</Link>
      </p>
      <div className="pagehead">
        <div>
          <h1 className="query-title">[{r.employee_id}] {r.user_query}</h1>
          <p className="muted">
            {r.case_id && <>{r.case_id} · </>}
            {r.mode}
            {r.fault && <> · fault <span className="tag fault">{r.fault}</span></>} · {r.config.agent_model} · prompts{" "}
            {r.config.prompt_version} · temp {String(r.config.temperature ?? 0)}
          </p>
        </div>
        <StatusPill status={r.status} passed={r.passed} category={r.failure_category} />
      </div>

      <div className="stats row">
        <div><b>{sec(r.totals.latency_ms)}</b><span>latency (excl. throttle)</span></div>
        <div><b>{r.totals.llm_calls}</b><span>LLM calls</span></div>
        <div><b>{r.totals.tool_calls}</b><span>tool calls</span></div>
        <div><b>{(r.totals.tokens_in + r.totals.tokens_out).toLocaleString()}</b><span>tokens</span></div>
        <div><b>{usd(r.totals.cost_list_usd)}</b><span>list-price eq.</span></div>
        <div><b>{r.totals.recorder_self_ms.toFixed(1)} ms</b><span>recorder overhead</span></div>
      </div>

      {(r.parent_run_id || branchChild || r.children.length > 0) && (
        <div className="lineage">
          {r.parent_run_id && (
            <span>
              {r.mode === "branch" ? `Branched at step ${r.branch_seq} from ` : "Replay of "}
              <Link to={`/runs/${r.parent_run_id}`}>{r.parent_run_id.slice(0, 8)}</Link>
            </span>
          )}
          {branchChild && (
            <span>
              Pre-recorded branch: <Link to={`/runs/${branchChild.run_id}`}>{branchChild.run_id.slice(0, 8)}</Link> ({branchChild.status}, from step{" "}
              {branchChild.branch_seq})
            </span>
          )}
          {r.children.filter((c) => c.mode !== "branch").map((c) => (
            <span key={c.run_id}>
              {c.mode}: <Link to={`/runs/${c.run_id}`}>{c.run_id.slice(0, 8)}</Link> ({c.status})
            </span>
          ))}
        </div>
      )}

      <h2>Timeline</h2>
      <div className="timeline" role="list">
        {LANES.map((lane) => (
          <div className="lane" key={lane}>
            <div className={`lanename ${divergent.has(lane) ? "div" : ""}`}>{lane}</div>
            <div className="track">
              {layout
                .filter((b) => b.e.agent === lane)
                .map(({ e, x, w }) => (
                  <button
                    key={e.seq}
                    role="listitem"
                    className={`bar ${e.type} ${e.fault || e.error ? "faulted" : ""} ${sel?.seq === e.seq ? "sel" : ""} ${e.replayed ? "replayed" : ""}`}
                    style={{ left: `${(x / total) * 100}%`, width: `max(${(w / total) * 100}%, 6px)` }}
                    title={`#${e.seq} ${e.type === "tool_call" ? e.name : "LLM"} · ${e.latency_ms ?? 0} ms${e.fault ? ` · fault ${e.fault}` : ""}`}
                    onClick={() => setSel(e)}
                  />
                ))}
            </div>
          </div>
        ))}
        <div className="legend">
          <span><i className="sw llm" /> LLM call</span>
          <span><i className="sw tool" /> tool call</span>
          <span><i className="sw faulted" /> fault / error / divergence</span>
          <span><i className="sw replayed" /> served from cache</span>
        </div>
      </div>

      <div className="split">
        <div className="panel">
          <h2>Inspector {sel && <span className="muted">· step #{sel.seq}</span>}</h2>
          {sel ? <Inspector e={sel} full={r.events_full} /> : <p className="muted">Select a bar.</p>}
          <div className="actions">
            <button disabled={STATIC || !!busy} title={STATIC ? "run locally" : "Re-run from cache, zero API calls"} onClick={() => act("replay")}>
              {busy === "replay" ? "Replaying…" : "Replay"}
            </button>
            <input
              disabled={STATIC}
              value={append}
              onChange={(e) => setAppend(e.target.value)}
              placeholder={sel ? `text appended to ${sel.agent}'s instruction (optional)` : ""}
              title={STATIC ? "run locally" : ""}
            />
            <button disabled={STATIC || !!busy || !sel} title={STATIC ? "run locally" : "Cache before this step, live from here"} onClick={() => act("branch")}>
              {busy === "branch" ? "Branching…" : "Branch from here"}
            </button>
          </div>
          {msg && <p className="error small">{msg}</p>}
        </div>
        <div className="panel">
          <h2>Final answer</h2>
          <p className="answer">{r.final_answer ?? <span className="muted">(none)</span>}</p>
          {r.judge_raw && (
            <>
              <h3>Judge</h3>
              <dl className="kv">
                {Object.entries(r.judge_raw).map(([k, v]) => (
                  <div key={k}><dt>{k}</dt><dd>{String(v)}</dd></div>
                ))}
              </dl>
            </>
          )}
          {Object.keys(outputs).length > 0 && (
            <details>
              <summary>Agent outputs (session state)</summary>
              <dl className="kv">
                {Object.entries(outputs).map(([k, v]) => (
                  <div key={k}><dt>{k}</dt><dd className="pre">{v ?? "—"}</dd></div>
                ))}
              </dl>
            </details>
          )}
        </div>
      </div>
    </section>
  );
}

function Inspector({ e, full }: { e: RunEvent; full: boolean }) {
  return (
    <div>
      <dl className="kv">
        <div><dt>agent</dt><dd>{e.agent}</dd></div>
        <div><dt>type</dt><dd>{e.type}{e.name ? ` · ${e.name}` : ""}</dd></div>
        <div><dt>latency</dt><dd>{e.latency_ms ?? 0} ms{e.replayed ? " (cached)" : ""}</dd></div>
        {e.tokens_in != null && <div><dt>tokens</dt><dd>{e.tokens_in} in / {e.tokens_out} out</dd></div>}
        {e.fault && <div><dt>fault</dt><dd className="error">{e.fault}</dd></div>}
        {e.error && <div><dt>error</dt><dd className="error">{e.error}</dd></div>}
      </dl>
      {full ? (
        <>
          <details open={e.type !== "llm_call"}>
            <summary>Request</summary>
            <pre>{JSON.stringify(e.request, null, 2)}</pre>
          </details>
          <details open>
            <summary>Response</summary>
            <pre>{JSON.stringify(e.response, null, 2)}</pre>
          </details>
        </>
      ) : (
        <p className="muted small">Prompts and responses are included for showcase runs only in the static demo.</p>
      )}
    </div>
  );
}
