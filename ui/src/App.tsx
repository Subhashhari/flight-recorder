import { NavLink, Route, Routes } from "react-router-dom";
import { STATIC, api } from "./api";
import { useLoad } from "./util";
import RunsPage from "./pages/RunsPage";
import RunDetailPage from "./pages/RunDetailPage";
import ChaosPage from "./pages/ChaosPage";

export default function App() {
  const labels = useLoad(() => api.labels(), []);
  const diffs = labels.data?.diffs ?? [];
  return (
    <div className="shell">
      <header className="top">
        <div className="brand">
          <svg viewBox="0 0 32 32" width="22" height="22" aria-hidden>
            <rect width="32" height="32" rx="7" fill="var(--accent)" />
            <path d="M7 20h5l3-9 4 13 3-7h3" stroke="white" strokeWidth="2.4" fill="none" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <span>Flight Recorder</span>
          <span className={`mode ${STATIC ? "static" : "live"}`}>{STATIC ? "static demo" : "local API"}</span>
        </div>
        <nav>
          <NavLink to="/" end>Runs</NavLink>
          <NavLink to="/chaos">Chaos</NavLink>
          {diffs.length > 0 && (
            <details className="diffs">
              <summary>Diffs</summary>
              <div className="menu">
                {diffs.map((d) => (
                  <a key={d} href={api.diffUrl(d)} target="_blank" rel="noreferrer">
                    {d.replace(/^diff_/, "").replace(/\.html$/, "").replace("__", " → ")}
                  </a>
                ))}
              </div>
            </details>
          )}
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<RunsPage labelsState={labels} />} />
          <Route path="/runs/:id" element={<RunDetailPage />} />
          <Route path="/chaos" element={<ChaosPage labelsState={labels} />} />
        </Routes>
      </main>
      <footer>
        Synthetic data (Northwind Labs) · Gemini API free tier · costs are list-price equivalents, actual spend ₹0
      </footer>
    </div>
  );
}
