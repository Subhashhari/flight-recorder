import { useEffect, useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Link } from "react-router-dom";
import { ChaosMatrix, LabelsFile, api } from "../api";
import { ErrorBox, pct } from "../util";

type LabelsState = { data: LabelsFile | null; error: Error | null; loading: boolean };
const SERIES = ["var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)"];

export default function ChaosPage({ labelsState }: { labelsState: LabelsState }) {
  const chaosLabels = (labelsState.data?.labels ?? []).filter((l) => l.is_chaos).map((l) => l.label);
  const [mats, setMats] = useState<Record<string, ChaosMatrix>>({});
  const [err, setErr] = useState<Error | null>(null);
  const [active, setActive] = useState<string | null>(null);
  const key = chaosLabels.join("|");

  useEffect(() => {
    Promise.all(chaosLabels.map((l) => api.chaos(l).then((m) => [l, m] as const)))
      .then((pairs) => {
        setMats(Object.fromEntries(pairs));
        setActive((a) => a ?? chaosLabels[0] ?? null);
      })
      .catch(setErr);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const faults = useMemo(() => Array.from(new Set(Object.values(mats).flatMap((m) => Object.keys(m.faults)))), [mats]);
  const chart = faults.map((f) => ({
    fault: f.replace(/^(tool|retrieval)_/, ""),
    ...Object.fromEntries(Object.entries(mats).map(([l, m]) => [l, m.faults[f] ? Math.round((m.faults[f].survival_rate as number) * 100) : null])),
  }));

  if (labelsState.error) return <ErrorBox error={labelsState.error} />;
  if (err) return <ErrorBox error={err} />;
  if (!labelsState.loading && chaosLabels.length === 0)
    return (
      <div className="empty">
        <h3>No chaos runs yet</h3>
        <p>Run <code>flightrec chaos --label chaos-baseline-v1 --faults all --resume</code>.</p>
      </div>
    );
  const m = active ? mats[active] : null;
  const maxCell = m ? Math.max(1, ...Object.values(m.faults).flatMap((r) => m.categories.map((c) => r[c] ?? 0))) : 1;
  return (
    <section>
      <div className="pagehead">
        <div>
          <h1>Chaos</h1>
          <p className="muted">8 injected faults × failure categories. Small samples per fault are exploratory.</p>
        </div>
        <div className="stats">
          {Object.entries(mats).map(([l, x]) => (
            <div key={l}><b>{pct(x.survival_rate)}</b><span>{l} survival ({x.survived}/{x.total_runs})</span></div>
          ))}
        </div>
      </div>

      <h2>Survival rate by fault</h2>
      <div className="panel chart">
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={chart} margin={{ top: 8, right: 8, bottom: 40, left: 0 }}>
            <CartesianGrid vertical={false} stroke="var(--line)" />
            <XAxis dataKey="fault" angle={-25} textAnchor="end" interval={0} tick={{ fill: "var(--muted)", fontSize: 12 }} />
            <YAxis unit="%" domain={[0, 100]} tick={{ fill: "var(--muted)", fontSize: 12 }} width={44} />
            <Tooltip contentStyle={{ background: "var(--card)", border: "1px solid var(--line)", color: "var(--fg)" }} formatter={(v) => `${v}%`} />
            <Legend verticalAlign="top" height={28} />
            {Object.keys(mats).map((l, i) => (
              <Bar key={l} dataKey={l} fill={SERIES[i % SERIES.length]} radius={[3, 3, 0, 0]} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="heathead">
        <h2>Failure matrix</h2>
        <div className="seg">
          {chaosLabels.map((l) => (
            <button key={l} className={l === active ? "on" : ""} onClick={() => setActive(l)}>{l}</button>
          ))}
        </div>
      </div>
      {m && (
        <div className="tablewrap">
          <table className="heat">
            <thead>
              <tr>
                <th>Fault</th><th className="num">runs</th><th className="num">survived</th>
                {m.categories.map((c) => <th key={c} className="num">{c.replace(/_/g, " ")}</th>)}
              </tr>
            </thead>
            <tbody>
              {Object.entries(m.faults).map(([f, r]) => (
                <tr key={f}>
                  <td><Link to={`/?label=${encodeURIComponent(m.label)}`}>{f}</Link></td>
                  <td className="num">{r.runs}</td>
                  <td className="num">{r.survived} <span className="muted">({pct(r.survival_rate)})</span></td>
                  {m.categories.map((c) => {
                    const v = r[c] ?? 0;
                    return (
                      <td key={c} className="num cell" style={{ background: v ? `color-mix(in srgb, var(--bad) ${12 + (v / maxCell) * 58}%, transparent)` : undefined }}>
                        {v || ""}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {m && <p className="muted small">{m.failure_modes.length} distinct failure modes (fault, category) in {m.label}.</p>}
    </section>
  );
}
