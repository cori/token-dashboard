#!/usr/bin/env python3
"""Token Analysis Dashboard — static HTML generator.

Reads ~/.hermes/token_calls.db and ~/.hermes/rate_table.yaml, produces
a self-contained HTML file with the two headline metrics (§6) plus
provider breakdown, latency distribution, and a 5h burn timeline chart.

Plain HTML + inline CSS + vanilla JS. No frameworks, no build step.
Output: ~/.hermes/token_dashboard.html
"""

import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import yaml

DB_PATH = Path.home() / ".hermes" / "token_calls.db"
RATE_TABLE = Path.home() / ".hermes" / "rate_table.yaml"
OUTPUT = Path.home() / ".hermes" / "token_dashboard.html"

# Model Picker Watch — separate skill, separate files. We read its
# append-only JSONL event log here to surface drift / unhealthy models
# on this dashboard. Read-only: we don't write to it.
PICKER_WATCH_JSONL = Path.home() / ".hermes" / "cache" / "model-picker-watch.jsonl"

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Token Analysis — Hermes</title>
<style>
  :root {
    --bg: #11100E;
    --surface: #22333B;
    --surface2: #1a2a32;
    --border: #3B4A50;
    --ink: #EAE0D5;
    --muted: #8899a0;
    --accent: #C6AC8F;
    --success: #86C08B;
    --warning: #E0B15D;
    --error: #F87171;
    --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, system-ui, sans-serif;
    --mono: "SF Mono", "Fira Code", "Cascadia Code", Menlo, monospace;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { background: var(--bg); color: var(--ink); font-family: var(--font); padding: 1.5rem; line-height: 1.6; }
  h1 { font-size: 1.4rem; font-weight: 600; margin-bottom: 0.25rem; }
  .subtitle { color: var(--muted); font-size: 0.85rem; margin-bottom: 1.5rem; }
  .grid { display: grid; gap: 1rem; max-width: 1200px; margin: 0 auto; }
  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 1rem; margin-bottom: 1rem; }
  .card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 1.25rem; }
  .card h2 { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); margin-bottom: 0.5rem; }
  .card .value { font-size: 1.8rem; font-weight: 700; font-family: var(--mono); }
  .card .unit { font-size: 0.8rem; color: var(--muted); margin-left: 0.25rem; }
  .card .sub { font-size: 0.8rem; color: var(--muted); margin-top: 0.25rem; }
  .section { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 1.25rem; margin-bottom: 1rem; }
  .section h2 { font-size: 0.9rem; font-weight: 600; margin-bottom: 1rem; }
  table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
  th { text-align: left; color: var(--muted); font-weight: 500; padding: 0.5rem 0.75rem; border-bottom: 1px solid var(--border); }
  td { padding: 0.5rem 0.75rem; border-bottom: 1px solid var(--surface2); font-family: var(--mono); }
  td.text { font-family: var(--font); }
  .num { text-align: right; }
  .chart-container { position: relative; height: 200px; margin-top: 0.5rem; }
  canvas { width: 100%; height: 100%; }
  .badge { display: inline-block; padding: 0.1rem 0.5rem; border-radius: 4px; font-size: 0.7rem; font-weight: 600; text-transform: uppercase; }
  .badge-sub { background: #2a4a3a; color: var(--success); }
  .badge-free { background: #3a3a2a; color: var(--warning); }
  .badge-metered { background: #2a3a4a; color: #8ab4f8; }
  .footer { color: var(--muted); font-size: 0.75rem; text-align: center; margin-top: 1rem; }
</style>
</head>
<body>
<div class="grid">
  <h1>Token Analysis</h1>
  <p class="subtitle">__SUBTITLE__</p>

  <div class="cards" id="cards"></div>

  <div class="section">
    <h2>Provider / Model Breakdown</h2>
    <div id="breakdown"></div>
  </div>

  <div class="section">
    <h2>Peak Rolling 5-Hour Burn by Tier</h2>
    <div id="burn"></div>
  </div>

  <div class="section">
    <h2>5-Hour Burn Timeline</h2>
    <div class="chart-container"><canvas id="chart"></canvas></div>
  </div>

  <div class="section" id="errors-section" style="display:none">
    <h2>Error Timeline (429s, 5xx, Timeouts)</h2>
    <div id="errors"></div>
  </div>

  <div class="section" id="picker-watch-section" style="display:none">
    <h2>Model Picker Watch — Tracked Models <span id="picker-watch-meta" class="subtitle" style="margin-left:0.5rem"></span></h2>
    <div id="picker-watch-banner" style="display:none; padding: 0.75rem 1rem; margin-bottom: 0.75rem; border-radius: 6px;"></div>
    <div id="picker-watch"></div>
  </div>

  <div class="section">
    <h2>Latency Distribution</h2>
    <div id="latency"></div>
  </div>

  <p class="footer">Generated __TIMESTAMP__ · <a href="#" onclick="location.reload();return false;">refresh</a></p>
</div>

<script>
const data = __DATA__;

// Render summary cards
function fmt(n) { return n.toLocaleString(); }
function fmtMoney(n) { return '$' + n.toFixed(4); }

const cards = document.getElementById('cards');
const totalTokens = data.summary.total_tokens;
const totalCalls = data.summary.total_calls;
const totalCost = data.summary.total_cost;
const peakBurn = data.peak_burn_all.max;
const p95Burn = data.peak_burn_all.p95;

cards.innerHTML = [
  {label:'Total Calls', value: fmt(totalCalls), sub: `${data.summary.providers} providers`},
  {label:'Total Tokens', value: fmt(totalTokens), sub: `${data.summary.span_hours.toFixed(1)}h span`},
  {label:'Derived Cost', value: fmtMoney(totalCost), sub: data.summary.estimated + ' estimated rows'},
  {label:'Peak 5h Burn', value: fmt(peakBurn), sub: 'P95: ' + fmt(p95Burn) + ' tokens'},
  {label:'Tracked Models', value: fmt(data.picker_watch.tracked.length), sub: data.picker_watch.drift_count + ' drift events logged'},
].map(c => `
  <div class="card">
    <h2>${c.label}</h2>
    <div class="value">${c.value}<span class="unit">${c.unit||''}</span></div>
    <div class="sub">${c.sub}</div>
  </div>
`).join('');

// Provider breakdown table
const bd = document.getElementById('breakdown');
let bdHtml = '<table><tr><th>Provider</th><th>Model</th><th>Tier</th><th class="num">Calls</th><th class="num">Tokens</th><th class="num">Cost</th><th class="num">Eff $/M</th></tr>';
data.breakdown.forEach(r => {
  const badge = `<span class="badge badge-${r.tier}">${r.tier}</span>`;
  bdHtml += `<tr><td class="text">${r.provider}</td><td class="text">${r.model}</td><td>${badge}</td><td class="num">${fmt(r.calls)}</td><td class="num">${fmt(r.tokens)}</td><td class="num">${fmtMoney(r.cost)}</td><td class="num">${r.eff_per_m.toFixed(4)}</td></tr>`;
});
bdHtml += '</table>';
bd.innerHTML = bdHtml;

// Peak burn by tier
const burn = document.getElementById('burn');
let burnHtml = '<table><tr><th>Tier</th><th class="num">Max</th><th class="num">P95</th><th class="num">Calls</th></tr>';
data.peak_burn.forEach(r => {
  burnHtml += `<tr><td class="text">${r.tier}</td><td class="num">${fmt(r.max)}</td><td class="num">${fmt(r.p95)}</td><td class="num">${r.calls}</td></tr>`;
});
burnHtml += '</table>';
burn.innerHTML = burnHtml;

// Latency stats
const lat = document.getElementById('latency');
let latHtml = '<table><tr><th>Provider</th><th>Model</th><th class="num">p50</th><th class="num">p95</th><th class="num">max</th></tr>';
data.latency.forEach(r => {
  latHtml += `<tr><td class="text">${r.provider}</td><td class="text">${r.model}</td><td class="num">${r.p50}ms</td><td class="num">${r.p95}ms</td><td class="num">${r.max}ms</td></tr>`;
});
latHtml += '</table>';
lat.innerHTML = latHtml;

// Model Picker Watch — tracked models, drift banner, swap recommendations
const VERDICT_COLOR = {
  HEALTHY: '#86C08B', DEGRADED: '#E0B15D', DEAD: '#F87171',
  AUTH_FAILED: '#c084e0', RATE_LIMITED: '#E0B15D', PROVIDER_DOWN: '#a14a4a',
  UNREACHABLE: '#888888', MODEL_NOT_FOUND: '#E0B15D',
  UNKNOWN: '#888888', DRIFT: '#8ab4f8', SKIP: '#666666',
};
const VERDICT_GLYPH = {
  HEALTHY: '✓', DEGRADED: '⚠', DEAD: '✗',
  AUTH_FAILED: '🔑', RATE_LIMITED: '⏱', PROVIDER_DOWN: '💥',
  UNREACHABLE: '📡', MODEL_NOT_FOUND: '🚫',
  UNKNOWN: '?', DRIFT: '↻', SKIP: '—',
};
const pw = data.picker_watch;
if (pw.tracked.length > 0 || pw.drift.length > 0 || pw.swap_recommendations.length > 0) {
  document.getElementById('picker-watch-section').style.display = 'block';
  // Meta line under the heading
  const meta = `last refresh ${pw.last_refresh || '—'} · last probe ${pw.last_probe || '—'}`;
  document.getElementById('picker-watch-meta').textContent = meta;
  // Drift banner
  const banner = document.getElementById('picker-watch-banner');
  if (pw.drift.length > 0 || pw.swap_recommendations.length > 0) {
    let html = '';
    if (pw.drift.length > 0) {
      html += `<strong>${pw.drift_count} drift event(s):</strong><ul style="margin: 0.25rem 0 0 1.25rem; padding: 0;">`;
      pw.drift.slice().reverse().forEach(d => {
        html += `<li style="font-family: var(--mono); font-size: 0.8rem;">${d.ts || ''} · ${d.provider}/${d.model}: ${d.detail}</li>`;
      });
      html += '</ul>';
    }
    if (pw.swap_recommendations.length > 0) {
      html += `<strong style="display:block; margin-top: 0.5rem;">Swap recommendations:</strong><ul style="margin: 0.25rem 0 0 1.25rem; padding: 0;">`;
      pw.swap_recommendations.forEach(s => {
        const repl = s.replacement ? ` → ${s.replacement}` : ' (no replacement available)';
        html += `<li style="font-family: var(--mono); font-size: 0.8rem;">${s.ts || ''} · ${s.provider}/${s.broken_model}${repl}</li>`;
      });
      html += '</ul>';
    }
    banner.style.background = 'rgba(224, 177, 93, 0.15)';
    banner.style.border = '1px solid var(--warning)';
    banner.style.color = 'var(--ink)';
    banner.innerHTML = html;
    banner.style.display = 'block';
  }
  // Tracked models table
  const pwEl = document.getElementById('picker-watch');
  let pwHtml = '<table><tr><th>Provider</th><th>Model</th><th>Verdict</th><th>Last Probe</th></tr>';
  pw.tracked.forEach(r => {
    const color = VERDICT_COLOR[r.verdict] || '#888';
    const glyph = VERDICT_GLYPH[r.verdict] || '?';
    pwHtml += `<tr><td class="text">${r.provider}</td><td class="text">${r.model}</td><td style="color:${color}">${glyph} ${r.verdict}${r.reason ? ` — ${r.reason}` : ''}</td><td class="text">${r.ts || ''}</td></tr>`;
  });
  pwHtml += '</table>';
  pwEl.innerHTML = pwHtml;
}

// Error timeline
const errorRows = data.errors || [];
if (errorRows.length > 0) {
  document.getElementById('errors-section').style.display = 'block';
  const errEl = document.getElementById('errors');
  let errHtml = '<table><tr><th>Time</th><th>Provider</th><th>Model</th><th class="num">Status</th><th>Reason</th><th class="num">Latency</th></tr>';
  errorRows.forEach(r => {
    const statusColor = r.status === 429 ? 'var(--warning)' : 'var(--error)';
    errHtml += `<tr><td class="text">${r.ts}</td><td class="text">${r.provider}</td><td class="text">${r.model}</td><td class="num" style="color:${statusColor}">${r.status}</td><td class="text">${r.reason}</td><td class="num">${r.latency_ms}ms</td></tr>`;
  });
  errHtml += '</table>';
  errEl.innerHTML = errHtml;
}

// Burn timeline canvas chart
const canvas = document.getElementById('chart');
const ctx = canvas.getContext('2d');
const points = data.timeline;
if (points.length > 1) {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth, h = canvas.clientHeight;
  canvas.width = w * dpr; canvas.height = h * dpr;
  ctx.scale(dpr, dpr);

  const padding = {top: 10, right: 10, bottom: 25, left: 50};
  const cw = w - padding.left - padding.right;
  const ch = h - padding.top - padding.bottom;

  const maxBurn = Math.max(...points.map(p => p.burn));
  const minT = points[0].t, maxT = points[points.length-1].t;

  // Grid lines
  ctx.strokeStyle = '#3B4A50';
  ctx.fillStyle = '#8899a0';
  ctx.font = '10px monospace';
  for (let i = 0; i <= 4; i++) {
    const y = padding.top + ch * (1 - i/4);
    ctx.beginPath(); ctx.moveTo(padding.left, y); ctx.lineTo(w - padding.right, y); ctx.stroke();
    const val = Math.round(maxBurn * i / 4);
    ctx.fillText(fmt(val), 2, y + 3);
  }

  // Area chart
  ctx.beginPath();
  ctx.moveTo(padding.left, padding.top + ch);
  points.forEach((p, i) => {
    const x = padding.left + cw * (p.t - minT) / (maxT - minT || 1);
    const y = padding.top + ch * (1 - p.burn / maxBurn);
    if (i === 0) ctx.lineTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.lineTo(padding.left + cw, padding.top + ch);
  ctx.closePath();
  ctx.fillStyle = 'rgba(198, 172, 143, 0.15)';
  ctx.fill();

  // Line
  ctx.beginPath();
  points.forEach((p, i) => {
    const x = padding.left + cw * (p.t - minT) / (maxT - minT || 1);
    const y = padding.top + ch * (1 - p.burn / maxBurn);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.strokeStyle = '#C6AC8F';
  ctx.lineWidth = 1.5;
  ctx.stroke();
}
</script>
</body>
</html>
"""


def _load_picker_watch() -> dict:
    """Read the model-picker-watch JSONL log and return a structured
    summary suitable for surfacing on this dashboard.

    Returns a dict with:
      tracked:           list of {provider, model, verdict, ts}
                         — the most-recent probe verdict per (provider, model)
      drift_count:       int — number of drift events in the log
      drift:            list of {provider, model, detail, ts} (last 10)
      swap_recommendations: list of {provider, broken_model, replacement, ts}
      last_refresh:     ISO timestamp of the most recent refresh event, or null
      last_probe:       ISO timestamp of the most recent probe event, or null

    Returns an empty structure (not an error) if the JSONL doesn't
    exist yet — the watcher is a sibling skill, not a hard dependency
    of this dashboard.
    """
    empty = {
        "tracked": [],
        "drift_count": 0,
        "drift": [],
        "swap_recommendations": [],
        "last_refresh": None,
        "last_probe": None,
    }
    if not PICKER_WATCH_JSONL.is_file():
        return empty
    events: list[dict] = []
    with open(PICKER_WATCH_JSONL) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if not events:
        return empty
    # Per-(provider, model) latest probe verdict
    latest: dict[tuple[str, str], dict] = {}
    drift: list[dict] = []
    swaps: list[dict] = []
    last_refresh = None
    last_probe = None
    for ev in events:
        ts = ev.get("ts")
        kind = ev.get("event")
        if kind == "refresh" and (last_refresh is None or (ts and ts > last_refresh)):
            last_refresh = ts
        elif kind == "probe" and (last_probe is None or (ts and ts > last_probe)):
            last_probe = ts
        elif kind == "drift":
            drift.append({
                "provider": ev.get("provider", ""),
                "model": ev.get("model", ""),
                "detail": ev.get("detail", ""),
                "ts": ts,
            })
        elif kind == "swap_recommendation":
            swaps.append({
                "provider": ev.get("provider", ""),
                "broken_model": ev.get("broken_model", ""),
                "replacement": ev.get("replacement"),
                "ts": ts,
            })
        if kind == "probe":
            key = (ev.get("provider", ""), ev.get("model", ""))
            prev = latest.get(key)
            if prev is None or (ts and (prev.get("ts") or "") < ts):
                latest[key] = {
                    "provider": key[0],
                    "model": key[1],
                    "verdict": ev.get("verdict", ""),
                    "reason": ev.get("reason", ""),
                    "ts": ts,
                }
    tracked = sorted(
        latest.values(),
        key=lambda r: (r["provider"], r["model"]),
    )
    return {
        "tracked": tracked,
        "drift_count": len(drift),
        "drift": drift[-10:],  # most recent 10
        "swap_recommendations": swaps,
        "last_refresh": last_refresh,
        "last_probe": last_probe,
    }


def generate():
    conn = sqlite3.connect(str(DB_PATH))

    # Load rate table for tier info
    with open(RATE_TABLE) as f:
        rates = yaml.safe_load(f) or []
    tier_map = {(r["provider"], r["model"]): r.get("tier", "?") for r in rates}

    # Summary
    total_calls = conn.execute("SELECT COUNT(*) FROM calls").fetchone()[0]
    total_tokens = conn.execute(
        "SELECT COALESCE(SUM(prompt_uncached + prompt_cached + completion + reasoning), 0) FROM calls"
    ).fetchone()[0]
    total_cost = conn.execute("SELECT COALESCE(SUM(cost_derived), 0) FROM calls").fetchone()[0]
    estimated = conn.execute("SELECT COUNT(*) FROM calls WHERE estimated = 1").fetchone()[0]
    first_ts = conn.execute("SELECT ts FROM calls ORDER BY id LIMIT 1").fetchone()
    last_ts = conn.execute("SELECT ts FROM calls ORDER BY id DESC LIMIT 1").fetchone()
    span_hours = 0
    if first_ts and last_ts:
        t1 = datetime.fromisoformat(first_ts[0])
        t2 = datetime.fromisoformat(last_ts[0])
        span_hours = (t2 - t1).total_seconds() / 3600
    providers = len(conn.execute("SELECT DISTINCT provider FROM calls").fetchall())

    # Provider breakdown
    breakdown = []
    for prov, model, calls, tokens, cost in conn.execute("""
        SELECT provider, model, COUNT(*),
               COALESCE(SUM(prompt_uncached + prompt_cached + completion + reasoning), 0),
               COALESCE(SUM(cost_derived), 0)
        FROM calls GROUP BY provider, model
    """).fetchall():
        tier = tier_map.get((prov, model), tier_map.get((prov, ""), "?"))
        eff = (cost * 1e6 / tokens) if tokens > 0 and cost else 0
        breakdown.append({
            "provider": prov, "model": model, "tier": tier or "?",
            "calls": calls, "tokens": tokens, "cost": cost, "eff_per_m": eff,
        })

    # Peak burn by tier (all + per-tier)
    burn_by_tier = []
    # Note: ISO8601 strings sort lexicographically (the 'T' separator
    # and trailing offset are both sortable), so ORDER BY ts works.
    all_rows = conn.execute("""
        SELECT ts, prompt_uncached + prompt_cached + completion + reasoning
        FROM calls WHERE estimated = 0 ORDER BY ts
    """).fetchall()

    def compute_burn(rows, label):
        if not rows:
            return {"tier": label, "max": 0, "p95": 0, "calls": 0}
        tokens = [(r[0], r[1] or 0) for r in rows]
        burns = []
        max_burn, max_end = 0, ""
        for i, (ts_i, _) in enumerate(tokens):
            t_i = datetime.fromisoformat(ts_i).timestamp()
            w_sum = 0
            for j in range(i, len(tokens)):
                t_j = datetime.fromisoformat(tokens[j][0]).timestamp()
                if t_j - t_i > 18000:
                    break
                w_sum += tokens[j][1]
            burns.append(w_sum)
            if w_sum > max_burn:
                max_burn, max_end = w_sum, ts_i
        burns.sort()
        p95 = burns[int(len(burns) * 0.95)] if burns else 0
        return {"tier": label, "max": max_burn, "p95": p95, "calls": len(rows)}

    burn_by_tier.append(compute_burn(all_rows, "all"))
    for tier_name in sorted(set(tier_map.values())):
        tier_provs = {r["provider"] for r in rates if r.get("tier") == tier_name}
        tier_rows = [r for r in all_rows if r[0] and any(
            r[0].startswith(t) for t in [f"{p}" for p in tier_provs]
        )]
        # Simpler: filter by provider
        tier_rows = conn.execute("""
            SELECT ts, prompt_uncached + prompt_cached + completion + reasoning
            FROM calls WHERE estimated = 0 AND provider IN ({})
            ORDER BY ts
        """.format(",".join("?" * len(tier_provs))), list(tier_provs)).fetchall()
        burn_by_tier.append(compute_burn(tier_rows, tier_name))

    # Latency stats
    latency = []
    for prov, model in conn.execute("SELECT DISTINCT provider, model FROM calls").fetchall():
        lats = [r[0] for r in conn.execute(
            "SELECT latency_ms FROM calls WHERE provider=? AND model=? AND latency_ms IS NOT NULL ORDER BY latency_ms",
            (prov, model)
        ).fetchall()]
        if not lats:
            continue
        n = len(lats)
        latency.append({
            "provider": prov, "model": model,
            "p50": lats[n // 2],
            "p95": lats[int(n * 0.95)],
            "max": lats[-1],
        })

    # Timeline data for chart (5h rolling burn, sampled every call)
    timeline = []
    ts_tokens = [(r[0], r[1] or 0) for r in conn.execute("""
        SELECT ts, prompt_uncached + prompt_cached + completion + reasoning
        FROM calls WHERE estimated = 0 ORDER BY ts
    """).fetchall()]
    for i, (ts_i, _) in enumerate(ts_tokens):
        t_i = datetime.fromisoformat(ts_i).timestamp()
        w_sum = 0
        for j in range(i, len(ts_tokens)):
            t_j = datetime.fromisoformat(ts_tokens[j][0]).timestamp()
            if t_j - t_i > 18000:
                break
            w_sum += ts_tokens[j][1]
        timeline.append({"t": t_i, "burn": w_sum})

    conn.close()

    # Error calls
    conn2 = sqlite3.connect(str(DB_PATH))
    error_rows = conn2.execute("""
        SELECT ts, provider, model, status, fallback_reason, latency_ms
        FROM calls WHERE status != 200 ORDER BY id DESC LIMIT 50
    """).fetchall()
    errors = [
        {"ts": r[0], "provider": r[1], "model": r[2], "status": r[3],
         "reason": r[4] or "", "latency_ms": r[5] or 0}
        for r in error_rows
    ]
    conn2.close()

    data = {
        "summary": {
            "total_calls": total_calls,
            "total_tokens": total_tokens,
            "total_cost": total_cost,
            "estimated": estimated,
            "providers": providers,
            "span_hours": span_hours,
        },
        "breakdown": breakdown,
        "peak_burn_all": burn_by_tier[0],
        "peak_burn": burn_by_tier,
        "latency": latency,
        "timeline": timeline,
        "errors": errors,
        "picker_watch": _load_picker_watch(),
    }

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    subtitle = f"{total_calls} calls · {providers} providers · {span_hours:.1f}h span"
    html = HTML_TEMPLATE.replace("__DATA__", json.dumps(data, default=str))
    html = html.replace("__SUBTITLE__", subtitle)
    html = html.replace("__TIMESTAMP__", now)

    OUTPUT.write_text(html)
    print(f"Dashboard written to {OUTPUT}")
    print(f"  {total_calls} calls, {total_tokens:,} tokens, ${total_cost:.4f} derived cost")
    print(f"  Open: file://{OUTPUT}")


if __name__ == "__main__":
    generate()