import { useEffect, useState } from "react";
import { NotFound } from "./api";

export function useLoad<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let live = true;
    setLoading(true);
    setError(null);
    fn()
      .then((d) => live && setData(d))
      .catch((e: Error) => live && setError(e))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return { data, error, loading };
}

export const sec = (ms: number | null | undefined) => (ms == null ? "—" : `${(ms / 1000).toFixed(1)} s`);
export const usd = (x: number | null | undefined) => (x == null ? "—" : x === 0 ? "$0" : `$${x.toFixed(5)}`);
export const pct = (x: number | null | undefined) => (x == null ? "—" : `${Math.round(x * 100)}%`);
export const when = (iso: string) => {
  const d = new Date(iso);
  return isNaN(+d) ? iso : d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
};

export function StatusPill({ status, passed, category }: { status: string; passed?: boolean | null; category?: string | null }) {
  const tone = status !== "ok" && status !== "diverged" ? "bad" : passed === false ? "bad" : passed ? "good" : status === "diverged" ? "warn" : "neutral";
  const text = passed === true ? "pass" : passed === false ? category ?? "fail" : status;
  return <span className={`pill ${tone}`}>{text}</span>;
}

export function ErrorBox({ error }: { error: Error }) {
  if (error instanceof NotFound)
    return (
      <div className="empty">
        <h3>No data here yet</h3>
        <p>
          The demo data has not been exported. Locally: <code>uv run flightrec export-static</code>, commit{" "}
          <code>ui/public/demo-data/</code>, push.
        </p>
      </div>
    );
  return <div className="empty error">Could not load: {error.message}</div>;
}
