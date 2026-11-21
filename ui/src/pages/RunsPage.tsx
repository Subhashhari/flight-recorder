import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { LabelsFile, STATIC, api } from "../api";
import { ErrorBox, StatusPill, pct, sec, usd, useLoad, when } from "../util";

type LabelsState = { data: LabelsFile | null; error: Error | null; loading: boolean };

export default function RunsPage({ labelsState }: { labelsState: LabelsState }) {
  const [params, setParams] = useSearchParams();
  const labels = labelsState.data?.labels ?? [];
  const label = params.get("label") ?? (STATIC ? labels[0]?.label ?? null : "");
  const status = params.get("status") ?? "";
  const onlyShowcase = params.get("showcase") === "1";
  const runs = useLoad(() => (label === null ? Promise.resolve([]) : api.runs(label || null)), [label]);
  const [q, setQ] = useState("");
  useEffect(() => setQ(""), [label]);

  const rows = useMemo(() => {
    const showcase = new Set(labelsState.data?.showcase ?? []);
    return (runs.data ?? []).filter(
      (r) =>
        (!status || r.status === status || (status === "failed" && r.passed === false)) &&
        (!onlyShowcase || showcase.has(r.run_id) || r.showcase) &&
        (!q || `${r.case_id} ${r.user_query} ${r.fault ?? ""}`.toLowerCase().includes(q.toLowerCase())),
    );
  }, [runs.data, status, onlyShowcase, q, labelsState.data]);

  const set = (k: string, v: string) => {
    const p = new URLSearchParams(params);
    if (v) p.set(k, v);
    else p.delete(k);
    setParams(p, { replace: true });
  };

  if (labelsState.error) return <ErrorBox error={labelsState.error} />;
  const current = labels.find((l) => l.label === label);
  const scored = rows.filter((r) => r.passed !== null);
  return (
    <section>
      <div className="pagehead">
        <div>
          <h1>Runs</h1>
          <p className="muted">Every PolicyDesk run: five agents, each LLM and tool call recorded.</p>
        </div>
        {current && (
          <div className="stats">
            <div><b>{current.runs}</b><span>runs</span></div>
            <div><b>{pct(current.scored ? (current.passed ?? 0) / current.scored : null)}</b><span>{current.is_chaos ? "survived" : "passed"}</span></div>
            <div><b>{current.prompt_version ?? "—"}</b><span>prompts</span></div>
          </div>
        )}
      </div>
      <div className="filters">
        <label>
          Label
          <select value={label ?? ""} onChange={(e) => set("label", e.target.value)}>
            {!STATIC && <option value="">all labels</option>}
            {labels.map((l) => (
              <option key={l.label} value={l.label}>{l.label}</option>
            ))}
            {STATIC && <option value="_unlabelled">(unlabelled: branches)</option>}
          </select>
        </label>
        <label>
          Status
          <select value={status} onChange={(e) => set("status", e.target.value)}>
            <option value="">any</option>
            {["ok", "diverged", "crash", "budget_exceeded", "rate_limited", "paused", "failed"].map((s) => (
              <option key={s} value={s}>{s === "failed" ? "failed (scored)" : s}</option>
            ))}
          </select>
        </label>
        <label className="grow">
          Search
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="case id, query, fault…" />
        </label>
        <label className="check">
          <input type="checkbox" checked={onlyShowcase} onChange={(e) => set("showcase", e.target.checked ? "1" : "")} />
          showcase only
        </label>
      </div>
      {runs.error ? (
        <ErrorBox error={runs.error} />
      ) : runs.loading || labelsState.loading ? (
        <div className="empty">Loading…</div>
      ) : rows.length === 0 ? (
        <div className="empty">
          <h3>No runs</h3>
          <p>{labels.length === 0 ? <>Nothing recorded yet. Run <code>flightrec eval --label smoke-1 --limit 3</code>.</> : "No runs match these filters."}</p>
        </div>
      ) : (
        <>
          <p className="muted small">{rows.length} runs{scored.length ? ` · ${scored.filter((r) => r.passed).length}/${scored.length} passed` : ""}</p>
          <div className="tablewrap">
            <table className="runs">
              <thead>
                <tr>
                  <th>Time</th><th>Label</th><th>Case</th><th>Query</th><th>Result</th>
                  <th className="num">Latency</th><th className="num">Tokens</th><th className="num">List $</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.run_id}>
                    <td className="nowrap">{when(r.started_at)}</td>
                    <td className="nowrap">{r.label ?? <span className="muted">{r.mode}</span>}</td>
                    <td className="nowrap">
                      <Link to={`/runs/${r.run_id}`}>{r.case_id ?? r.run_id.slice(0, 8)}</Link>
                      {r.fault && <div className="tag fault">{r.fault}</div>}
                      {r.mode !== "live" && r.mode !== "chaos" && <div className="tag">{r.mode}</div>}
                    </td>
                    <td className="query"><Link to={`/runs/${r.run_id}`}>{r.user_query}</Link></td>
                    <td><StatusPill status={r.status} passed={r.passed} category={r.failure_category} /></td>
                    <td className="num">{sec(r.latency_ms)}</td>
                    <td className="num">{r.tokens.toLocaleString()}</td>
                    <td className="num">{usd(r.cost_list_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
