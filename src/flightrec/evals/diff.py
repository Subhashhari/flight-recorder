"""`flightrec diff A B`: metric deltas + flipped cases (markdown on stdout, HTML in docs/)."""

from __future__ import annotations

import html

from flightrec.config import DOCS_DIR
from flightrec.recorder import store


def _is_chaos(label: str) -> bool:
    runs = store.runs_in_label(label)
    return any(r["mode"] == "chaos" for r in runs)


def _results(label: str, chaos: bool) -> dict:
    rows = store.chaos_scored_runs(label) if chaos else store.latest_scored_runs(label)
    return {((r["fault"], r["case_id"]) if chaos else r["case_id"]): r for r in rows}


def _metrics(label: str, chaos: bool) -> dict:
    if chaos:
        from flightrec.evals.chaos import chaos_matrix
        m = chaos_matrix(label)
        out = {"runs": m["total_runs"], "survival %": m["survival_rate"], "failure modes": len(m["failure_modes"])}
        out.update({f"survival {f} %": r["survival_rate"] for f, r in m["faults"].items()})
        return out
    from flightrec.evals.report import clean_summary
    s = clean_summary(label)
    out = {"cases": s["cases"], "success %": s["success"]}
    out.update({f"{c} %": v for c, v in s["per_category"].items()})
    out.update({"hallucination %": s["hallucination_rate"], "p50 s": s["p50_s"], "p95 s": s["p95_s"],
                "tokens/run": s["tokens_per_run"], "list-price $/run": s["cost_per_run_usd"]})
    return out


def _fmt(k: str, v) -> str:
    if v is None:
        return "—"
    if k.endswith("%"):
        return f"{v * 100:.1f}"
    if isinstance(v, float):
        return f"{v:.5f}" if "$" in k else f"{v:.2f}"
    return str(v)


def diff(a: str, b: str) -> dict:
    chaos = _is_chaos(a) or _is_chaos(b)
    ma, mb = _metrics(a, chaos), _metrics(b, chaos)
    rows = []
    for k in dict.fromkeys(list(ma) + list(mb)):
        va, vb = ma.get(k), mb.get(k)
        d = (vb - va) if isinstance(va, int | float) and isinstance(vb, int | float) else None
        rows.append((k, _fmt(k, va), _fmt(k, vb), "—" if d is None else (f"{d * 100:+.1f}" if k.endswith("%")
                                                                        else f"{d:+.4g}")))
    ra, rb = _results(a, chaos), _results(b, chaos)
    flips = []
    for key in sorted(set(ra) & set(rb), key=str):
        pa, pb = bool(ra[key]["passed"]), bool(rb[key]["passed"])
        if pa != pb:
            flips.append({"key": key if isinstance(key, str) else f"{key[0]} / {key[1]}",
                          "a": "pass" if pa else (ra[key]["failure_category"] or "fail"),
                          "b": "pass" if pb else (rb[key]["failure_category"] or "fail"),
                          "direction": "fixed" if pb else "regressed", "a_run": ra[key]["run_id"],
                          "b_run": rb[key]["run_id"]})
    md = [f"## diff {a} → {b}", "", f"| metric | {a} | {b} | Δ |", "|---|---|---|---|"]
    md += [f"| {k} | {x} | {y} | {d} |" for k, x, y, d in rows]
    md += ["", f"Compared on {len(set(ra) & set(rb))} shared {'(fault, case) pairs' if chaos else 'cases'}. "
           f"Fixed: {sum(f['direction'] == 'fixed' for f in flips)} · Regressed: "
           f"{sum(f['direction'] == 'regressed' for f in flips)}", "", "| case | " + a + " | " + b + " | direction |",
           "|---|---|---|---|"]
    md += [f"| {f['key']} | {f['a']} | {f['b']} | {f['direction']} |" for f in flips] or ["| (no flipped cases) ||||"]
    markdown = "\n".join(md) + "\n"
    out = DOCS_DIR / f"diff_{a}__{b}.html"
    out.write_text(_html(a, b, rows, flips, chaos), encoding="utf-8")
    return {"markdown": markdown, "html_path": str(out), "flips": flips, "rows": rows}


def _html(a, b, rows, flips, chaos) -> str:
    e = html.escape
    tr = "".join(f"<tr><td>{e(k)}</td><td>{e(x)}</td><td>{e(y)}</td><td class='{'pos' if d.startswith('+') else 'neg' if d.startswith('-') else ''}'>{e(d)}</td></tr>"
                 for k, x, y, d in rows)
    fl = "".join(f"<tr class='{f['direction']}'><td>{e(f['key'])}</td><td>{e(f['a'])}</td><td>{e(f['b'])}</td>"
                 f"<td>{e(f['direction'])}</td></tr>" for f in flips) or "<tr><td colspan=4>No flipped cases</td></tr>"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Diff {e(a)} vs {e(b)}</title><style>
:root{{--bg:#fbfaf8;--fg:#1d1d1f;--muted:#6b6b70;--line:#e4e2dd;--pos:#1f7a4d;--neg:#b3261e;--card:#fff}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151517;--fg:#ececee;--muted:#9a9aa1;--line:#2c2c30;--pos:#5fcf95;--neg:#ff8a80;--card:#1d1d20}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}}
main{{max-width:900px;margin:0 auto;padding:24px 16px}}h1{{font-size:22px;margin:0 0 4px}}p{{color:var(--muted);margin:0 0 20px}}
table{{width:100%;border-collapse:collapse;background:var(--card);margin-bottom:28px;font-variant-numeric:tabular-nums}}
th,td{{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line)}}th{{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}}
.pos{{color:var(--pos)}}.neg{{color:var(--neg)}}tr.fixed td:last-child{{color:var(--pos)}}tr.regressed td:last-child{{color:var(--neg)}}
.wrap{{overflow-x:auto}}</style></head><body><main>
<h1>{e(a)} → {e(b)}</h1><p>{"Chaos labels: keyed by (fault, case)." if chaos else "Clean eval labels: keyed by case."} Generated by <code>flightrec diff</code>.</p>
<h2>Metrics</h2><div class="wrap"><table><tr><th>Metric</th><th>{e(a)}</th><th>{e(b)}</th><th>Δ</th></tr>{tr}</table></div>
<h2>Flipped cases ({len(flips)})</h2><div class="wrap"><table><tr><th>Case</th><th>{e(a)}</th><th>{e(b)}</th><th>Direction</th></tr>{fl}</table></div>
</main></body></html>"""
