"""
VoiceGateway2 Latency Dashboard Generator
==========================================
Reads a CSV produced by vg2_latency_report.py and generates a self-contained
HTML dashboard file that can be opened directly in any browser — no server,
no internet connection, no additional installs required.

Latency tiers:
  Green  — under 2,500ms   (acceptable)
  Yellow — 2,500ms–5,000ms (degraded)
  Red    — over 5,000ms    (unacceptable)

Dashboard behaviour:
  - Acceptable sessions shown as flat summary cards (no turn detail)
  - Degraded / unacceptable sessions auto-expand showing only flagged turns
  - Flagged turns are highlighted in the tier colour

Usage:
  # Generate from the most recent CSV in reports/
  python generate_dashboard.py

  # Generate from a specific CSV
  python generate_dashboard.py --input reports/JP_Sandbox_20260314_182435.csv

  # Custom output path
  python generate_dashboard.py --output my_report.html
"""

import csv
import json
import os
import sys
import argparse
from datetime import datetime
from collections import defaultdict


# ── Tier config ───────────────────────────────────────────────────────────────

GREEN_MAX  = 2500
YELLOW_MAX = 5000

def get_tier(ms: int) -> str:
    if ms < GREEN_MAX:   return "green"
    if ms < YELLOW_MAX:  return "yellow"
    return "red"

def tier_label(ms: int) -> str:
    return {"green": "Acceptable", "yellow": "Degraded", "red": "Unacceptable"}[get_tier(ms)]


# ── CSV loading ───────────────────────────────────────────────────────────────

def find_latest_csv(reports_dir: str = "reports") -> str:
    if not os.path.isdir(reports_dir):
        print(f"[error] Reports directory '{reports_dir}' not found.")
        print("        Run vg2_latency_report.py --csv first.")
        sys.exit(1)
    csvs = [f for f in os.listdir(reports_dir) if f.endswith(".csv")]
    if not csvs:
        print(f"[error] No CSV files found in '{reports_dir}'.")
        print("        Run vg2_latency_report.py --csv first.")
        sys.exit(1)
    latest = max(csvs, key=lambda f: os.path.getmtime(os.path.join(reports_dir, f)))
    return os.path.join(reports_dir, latest)


def load_csv(path: str) -> list:
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        print(f"[error] CSV '{path}' is empty.")
        sys.exit(1)
    return rows


def build_data(rows: list) -> dict:
    sessions_map = defaultdict(list)
    for row in rows:
        sessions_map[row["session_id"]].append(row)

    sorted_sessions = sorted(
        sessions_map.items(),
        key=lambda kv: kv[1][0]["session_start"]
    )

    all_latencies = [int(r["first_token_latency_ms"]) for r in rows]
    tier_counts   = {"green": 0, "yellow": 0, "red": 0}

    session_data = []
    for s_num, (session_id, s_rows) in enumerate(sorted_sessions, 1):
        s_lats = []
        turns  = []
        for t_num, row in enumerate(s_rows, 1):
            ms   = int(row["first_token_latency_ms"])
            tier = get_tier(ms)
            tier_counts[tier] += 1
            s_lats.append(ms)
            turns.append({
                "turn_number":         t_num,
                "first_token_ms":      ms,
                "full_response_ms":    int(row["full_response_latency_ms"]),
                "tier":                tier,
                "tier_label":          tier_label(ms),
                "user_text":           row.get("user_text", ""),
                "first_bot_text":      row.get("first_bot_text", ""),
                "user_text_length":    int(row.get("user_text_length", 0)),
                "bot_output_segments": int(row.get("bot_output_segments", 0)),
            })

        s_avg      = int(sum(s_lats) / len(s_lats))
        s_max      = max(s_lats)
        sess_tier  = get_tier(s_max)   # session tier driven by peak turn

        # Only include flagged turns in the detail view
        flagged_turns = [t for t in turns if t["tier"] != "green"]

        session_data.append({
            "session_number":  s_num,
            "session_id":      session_id,
            "session_start":   s_rows[0]["session_start"],
            "turn_count":      len(turns),
            "avg_latency_ms":  s_avg,
            "peak_latency_ms": s_max,
            "tier":            sess_tier,
            "tier_label":      tier_label(s_max),
            "flagged_turns":   flagged_turns,
            "has_flags":       len(flagged_turns) > 0,
        })

    # Date range for header
    timestamps = [r["inbound_time"] for r in rows if r.get("inbound_time")]
    date_str = ""
    if timestamps:
        timestamps.sort()
        start = timestamps[0][:10]
        end   = timestamps[-1][:10]
        date_str = start if start == end else f"{start} – {end}"

    total = len(all_latencies)
    return {
        "project":          rows[0].get("project", ""),
        "generated_at":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "date_range":       date_str,
        "total_turns":      total,
        "total_sessions":   len(session_data),
        "avg_latency_ms":   int(sum(all_latencies) / total),
        "min_latency_ms":   min(all_latencies),
        "max_latency_ms":   max(all_latencies),
        "tier_counts":      tier_counts,
        "tier_pct": {
            k: round(v / total * 100) for k, v in tier_counts.items()
        },
        "green_max_ms":     GREEN_MAX,
        "yellow_max_ms":    YELLOW_MAX,
        "sessions":         session_data,
    }


# ── HTML ──────────────────────────────────────────────────────────────────────

def generate_html(data: dict) -> str:
    data_json = json.dumps(data, indent=2)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>VG2 Latency Report — {data['project']}</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  :root {{
    --g: #27500A; --g-bg: #EAF3DE; --g-bd: #97C459;
    --y: #633806; --y-bg: #FAEEDA; --y-bd: #EF9F27;
    --r: #791F1F; --r-bg: #FCEBEB; --r-bd: #F09595;
    --bg:      #f7f6f3;
    --surface: #ffffff;
    --border:  #e2e0da;
    --text:    #1a1917;
    --text-2:  #6b6860;
    --text-3:  #9b9890;
    --mono: 'IBM Plex Mono', 'Courier New', monospace;
    --sans: 'IBM Plex Sans', system-ui, sans-serif;
    --rad: 8px;
    --rad-lg: 12px;
  }}
  body {{ font-family: var(--sans); background: var(--bg); color: var(--text); padding-bottom: 60px; }}

  /* header */
  .db-head {{ background: var(--text); padding: 20px 28px 16px; }}
  .db-head h1 {{ font-size: 16px; font-weight: 500; color: #fff; margin: 0 0 3px; letter-spacing: -0.2px; }}
  .db-head p  {{ font-size: 11px; color: rgba(255,255,255,0.4); margin: 0; font-family: var(--mono); }}

  /* stat strip */
  .stat-row {{
    display: grid;
    grid-template-columns: repeat(5, minmax(0,1fr));
    gap: 8px; padding: 14px;
    background: #eeece8;
    border-bottom: 1px solid var(--border);
  }}
  .stat {{ background: var(--surface); border-radius: var(--rad); padding: 10px 12px; }}
  .stat-lbl {{ font-size: 10px; color: var(--text-3); margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.06em; }}
  .stat-val {{ font-size: 20px; font-weight: 500; font-family: var(--mono); color: var(--text); }}

  /* tier breakdown */
  .tier-section {{ padding: 16px 20px; border-bottom: 1px solid var(--border); background: var(--surface); }}
  .sec-lbl {{ font-size: 10px; color: var(--text-3); text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 10px; }}
  .tier-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap: 8px; margin-bottom: 12px; }}
  .tc {{ border-radius: var(--rad); padding: 10px 14px; border: 1px solid; }}
  .tc.g {{ background: var(--g-bg); border-color: var(--g-bd); }}
  .tc.y {{ background: var(--y-bg); border-color: var(--y-bd); }}
  .tc.r {{ background: var(--r-bg); border-color: var(--r-bd); }}
  .tc-top {{ display: flex; align-items: center; gap: 6px; margin-bottom: 1px; }}
  .tdot {{ width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }}
  .tdot.g {{ background: var(--g-bd); }}
  .tdot.y {{ background: var(--y-bd); }}
  .tdot.r {{ background: var(--r-bd); }}
  .tc-name {{ font-size: 11px; font-weight: 500; }}
  .tc.g .tc-name {{ color: var(--g); }}
  .tc.y .tc-name {{ color: var(--y); }}
  .tc.r .tc-name {{ color: var(--r); }}
  .tc-range {{ font-size: 10px; font-family: var(--mono); opacity: 0.7; }}
  .tc.g .tc-range {{ color: var(--g); }}
  .tc.y .tc-range {{ color: var(--y); }}
  .tc.r .tc-range {{ color: var(--r); }}
  .tc-count {{ font-size: 24px; font-weight: 500; font-family: var(--mono); margin-top: 4px; }}
  .tc.g .tc-count {{ color: var(--g); }}
  .tc.y .tc-count {{ color: var(--y); }}
  .tc.r .tc-count {{ color: var(--r); }}
  .tc-sub {{ font-size: 11px; opacity: 0.8; }}
  .tc.g .tc-sub {{ color: var(--g); }}
  .tc.y .tc-sub {{ color: var(--y); }}
  .tc.r .tc-sub {{ color: var(--r); }}
  .prop-track {{ height: 6px; background: var(--border); border-radius: 3px; overflow: hidden; display: flex; }}
  .ps {{ height: 100%; }}
  .ps.g {{ background: var(--g-bd); }}
  .ps.y {{ background: var(--y-bd); }}
  .ps.r {{ background: var(--r-bd); }}

  /* sessions */
  .sess-section {{ padding: 16px 20px; }}
  .sess-card {{ border: 1px solid var(--border); border-radius: var(--rad-lg); overflow: hidden; margin-bottom: 8px; background: var(--surface); }}
  .sess-head {{ display: flex; justify-content: space-between; align-items: center; padding: 11px 14px; gap: 8px; flex-wrap: wrap; }}
  .sess-head.clickable {{ cursor: pointer; }}
  .sess-head.clickable:hover {{ background: #fafaf8; }}
  .sess-left {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap; min-width: 0; }}
  .sess-num {{ font-size: 11px; font-weight: 500; color: var(--text-3); text-transform: uppercase; letter-spacing: 0.05em; white-space: nowrap; }}
  .sess-id {{ font-size: 11px; font-family: var(--mono); color: var(--text-2); white-space: nowrap; }}
  .tpill {{ font-size: 10px; font-weight: 500; padding: 2px 8px; border-radius: 20px; border: 1px solid; display: inline-flex; align-items: center; gap: 4px; white-space: nowrap; }}
  .tpill.g {{ background: var(--g-bg); color: var(--g); border-color: var(--g-bd); }}
  .tpill.y {{ background: var(--y-bg); color: var(--y); border-color: var(--y-bd); }}
  .tpill.r {{ background: var(--r-bg); color: var(--r); border-color: var(--r-bd); }}
  .sess-right {{ display: flex; align-items: center; gap: 16px; flex-shrink: 0; }}
  .sm {{ text-align: right; }}
  .sm-lbl {{ font-size: 10px; color: var(--text-3); text-transform: uppercase; letter-spacing: 0.04em; }}
  .sm-val {{ font-size: 13px; font-weight: 500; font-family: var(--mono); color: var(--text); }}
  .sm-val.y {{ color: var(--y); }}
  .sm-val.r {{ color: var(--r); }}
  .chev {{ font-size: 10px; color: var(--text-3); transition: transform 0.2s; margin-left: 4px; display: inline-block; }}
  .chev.open {{ transform: rotate(180deg); }}

  /* turns table */
  .turns-wrap {{ display: none; border-top: 1px solid var(--border); }}
  .turns-wrap.open {{ display: block; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 12px; table-layout: fixed; }}
  th {{ font-size: 10px; font-weight: 500; color: var(--text-3); text-align: left; padding: 6px 14px; background: #fafaf8; text-transform: uppercase; letter-spacing: 0.05em; }}
  td {{ padding: 9px 14px; border-top: 1px solid var(--border); vertical-align: top; }}
  tr.fy td {{ background: var(--y-bg); }}
  tr.fr td {{ background: var(--r-bg); }}
  .tnum {{ font-family: var(--mono); font-size: 11px; color: var(--text-3); white-space: nowrap; }}
  .lv {{ font-family: var(--mono); font-weight: 500; font-size: 13px; white-space: nowrap; }}
  .lv.y {{ color: var(--y); }}
  .lv.r {{ color: var(--r); }}
  .bt {{ height: 4px; background: var(--border); border-radius: 2px; margin-top: 5px; }}
  .bf {{ height: 100%; border-radius: 2px; }}
  .bf.y {{ background: var(--y-bd); }}
  .bf.r {{ background: var(--r-bd); }}
  .txu {{ font-size: 11px; color: var(--text-3); margin-bottom: 2px; }}
  .txu b {{ color: var(--text-2); font-weight: 500; }}
  .txb {{ font-size: 11px; color: var(--text-2); }}
  .txb b {{ color: var(--text); font-weight: 500; }}
  .fms {{ font-size: 10px; font-family: var(--mono); color: var(--text-3); white-space: nowrap; text-align: right; }}

  /* footer */
  .footer {{ text-align: center; padding: 28px; font-size: 11px; color: var(--text-3); font-family: var(--mono); }}
</style>
</head>
<body>

<div id="root"></div>

<script>
const D = {data_json};

function fmt(ms) {{
  return ms >= 1000 ? (ms/1000).toFixed(2)+'s' : ms.toLocaleString()+'ms';
}}

function tierClass(tier) {{
  return {{green:'g', yellow:'y', red:'r'}}[tier];
}}

function build() {{
  const root = document.getElementById('root');
  const tc   = D.tier_counts;
  const pct  = D.tier_pct;
  const total = D.total_turns;

  root.innerHTML = `
  <div style="max-width:960px;margin:0 auto;">

    <div class="db-head">
      <h1>VoiceGateway2 — Latency Report</h1>
      <p>${{D.project}} &middot; ${{D.total_sessions}} session${{D.total_sessions!==1?'s':''}} &middot; ${{D.total_turns}} turns &middot; ${{D.date_range}}</p>
    </div>

    <div class="stat-row">
      <div class="stat"><div class="stat-lbl">Avg latency</div><div class="stat-val">${{fmt(D.avg_latency_ms)}}</div></div>
      <div class="stat"><div class="stat-lbl">Min latency</div><div class="stat-val">${{fmt(D.min_latency_ms)}}</div></div>
      <div class="stat"><div class="stat-lbl">Max latency</div><div class="stat-val">${{fmt(D.max_latency_ms)}}</div></div>
      <div class="stat"><div class="stat-lbl">Sessions</div><div class="stat-val">${{D.total_sessions}}</div></div>
      <div class="stat"><div class="stat-lbl">Total turns</div><div class="stat-val">${{D.total_turns}}</div></div>
    </div>

    <div class="tier-section">
      <div class="sec-lbl">Turn breakdown by tier</div>
      <div class="tier-grid">
        <div class="tc g">
          <div class="tc-top"><span class="tdot g"></span><span class="tc-name">Acceptable</span></div>
          <div class="tc-range">&lt; ${{D.green_max_ms.toLocaleString()}}ms</div>
          <div class="tc-count">${{tc.green}}</div>
          <div class="tc-sub">turn${{tc.green!==1?'s':''}} (${{pct.green}}%)</div>
        </div>
        <div class="tc y">
          <div class="tc-top"><span class="tdot y"></span><span class="tc-name">Degraded</span></div>
          <div class="tc-range">${{D.green_max_ms.toLocaleString()}} – ${{D.yellow_max_ms.toLocaleString()}}ms</div>
          <div class="tc-count">${{tc.yellow}}</div>
          <div class="tc-sub">turn${{tc.yellow!==1?'s':''}} (${{pct.yellow}}%)</div>
        </div>
        <div class="tc r">
          <div class="tc-top"><span class="tdot r"></span><span class="tc-name">Unacceptable</span></div>
          <div class="tc-range">&gt; ${{D.yellow_max_ms.toLocaleString()}}ms</div>
          <div class="tc-count">${{tc.red}}</div>
          <div class="tc-sub">turn${{tc.red!==1?'s':''}} (${{pct.red}}%)</div>
        </div>
      </div>
      <div class="prop-track">
        <div class="ps g" style="width:${{pct.green}}%"></div>
        <div class="ps y" style="width:${{pct.yellow}}%"></div>
        <div class="ps r" style="width:${{pct.red}}%"></div>
      </div>
    </div>

    <div class="sess-section">
      <div class="sec-lbl">Sessions</div>
      ${{D.sessions.map(s => buildSession(s)).join('')}}
    </div>

    <div class="footer">VoiceGateway2 Latency Report &middot; ${{D.project}} &middot; Generated ${{D.generated_at}}</div>

  </div>`;
}}

function buildSession(s) {{
  const tc  = tierClass(s.tier);
  const peakClass = s.tier === 'green' ? '' : ` ${{tc}}`;
  const isGreen   = s.tier === 'green';
  const maxMs     = D.max_latency_ms;

  const headClass = isGreen ? 'sess-head' : 'sess-head clickable';
  const chevron   = isGreen ? '' : `<span class="chev open" id="chev-${{s.session_number}}">&#9660;</span>`;
  const onclick   = isGreen ? '' : `onclick="tog(${{s.session_number}})"`;

  const turnsHtml = isGreen ? '' : `
    <div class="turns-wrap open" id="body-${{s.session_number}}">
      <table>
        <thead><tr>
          <th style="width:36px;">#</th>
          <th style="width:160px;">Latency</th>
          <th>Transcript</th>
          <th style="width:88px;">Full resp.</th>
        </tr></thead>
        <tbody>
          ${{s.flagged_turns.map(t => buildTurnRow(t, maxMs)).join('')}}
        </tbody>
      </table>
    </div>`;

  return `
    <div class="sess-card">
      <div class="${{headClass}}" ${{onclick}}>
        <div class="sess-left">
          <span class="sess-num">Session ${{s.session_number}}</span>
          <span class="sess-id">${{s.session_id}}</span>
          <span class="tpill ${{tc}}"><span class="tdot ${{tc}}"></span>${{s.tier_label}}</span>
        </div>
        <div class="sess-right">
          <div class="sm"><div class="sm-lbl">Avg</div><div class="sm-val">${{fmt(s.avg_latency_ms)}}</div></div>
          <div class="sm"><div class="sm-lbl">Peak</div><div class="sm-val${{peakClass}}">${{fmt(s.peak_latency_ms)}}</div></div>
          <div class="sm"><div class="sm-lbl">Turns</div><div class="sm-val">${{s.turn_count}}</div></div>
          ${{chevron}}
        </div>
      </div>
      ${{turnsHtml}}
    </div>`;
}}

function buildTurnRow(t, maxMs) {{
  const tc  = tierClass(t.tier);
  const pct = Math.round((t.first_token_ms / maxMs) * 100);
  const rowClass = tc === 'y' ? 'fy' : 'fr';
  const userText = t.user_text
    ? t.user_text.slice(0, 90) + (t.user_text.length > 90 ? '&hellip;' : '')
    : '<em style="color:#9b9890">— call connected —</em>';
  const botText  = t.first_bot_text
    ? t.first_bot_text.slice(0, 90) + (t.first_bot_text.length > 90 ? '&hellip;' : '')
    : '';
  return `
    <tr class="${{rowClass}}">
      <td class="tnum">T${{t.turn_number}}</td>
      <td>
        <div class="lv ${{tc}}">${{fmt(t.first_token_ms)}}</div>
        <div class="bt"><div class="bf ${{tc}}" style="width:${{pct}}%"></div></div>
      </td>
      <td>
        <div class="txu"><b>User</b>&nbsp; ${{userText}}</div>
        <div class="txb"><b>Bot&nbsp;</b>&nbsp; ${{botText}}</div>
      </td>
      <td class="fms">${{fmt(t.full_response_ms)}}</td>
    </tr>`;
}}

function tog(num) {{
  const body  = document.getElementById('body-' + num);
  const chev  = document.getElementById('chev-' + num);
  const isOpen = body.classList.contains('open');
  body.classList.toggle('open', !isOpen);
  chev.classList.toggle('open', !isOpen);
}}

build();
</script>
</body>
</html>"""


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Generate an HTML latency dashboard from a VG2 CSV report",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--input",  metavar="FILE", default=None,
                        help="CSV to read (default: most recent in reports/)")
    parser.add_argument("--output", metavar="FILE", default="dashboard.html",
                        help="Output HTML file (default: dashboard.html)")
    args = parser.parse_args()

    csv_path = args.input or find_latest_csv()
    print(f"Reading : {csv_path}")

    rows = load_csv(csv_path)
    data = build_data(rows)

    print(f"  {data['total_sessions']} session(s) · {data['total_turns']} turn(s)")
    print(f"  Tier counts — green: {data['tier_counts']['green']}  "
          f"yellow: {data['tier_counts']['yellow']}  "
          f"red: {data['tier_counts']['red']}")

    html = generate_html(data)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\nDashboard saved → {args.output}")
    print("Open it in any browser — no internet connection required.")


if __name__ == "__main__":
    main()
