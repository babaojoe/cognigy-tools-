"""
VoiceGateway2 Latency Report
============================
Fetches logs directly from the Cognigy API (or reads a local file) and
computes per-turn latency (inbound user message → first bot output) for
the voiceGateway2 channel. Results are grouped by session.

Setup:
    1. Edit config.json — add your project name, API key, project ID, and base URL.
    2. Install the one dependency:  pip install requests
    3. Run it.

Usage examples:

  # Fetch live from API for one project
  python vg2_latency_report.py --project "JP Sandbox"

  # Fetch for all projects in config.json
  python vg2_latency_report.py --all

  # Fetch and save a timestamped CSV to reports/
  python vg2_latency_report.py --project "JP Sandbox" --csv

  # Use a previously saved JSON file instead of calling the API
  python vg2_latency_report.py --input logs.json

  # Override the log entry fetch limit
  python vg2_latency_report.py --project "JP Sandbox" --limit 5000
"""

import json
import argparse
import csv
import os
import sys
from datetime import datetime
from collections import defaultdict
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

try:
    import requests
except ImportError:
    requests = None


# ── Constants ─────────────────────────────────────────────────────────────────

INBOUND_MSG       = "Received message from user"
OUTBOUND_MSG      = "Sent output to Endpoint"
TARGET_CHANNEL    = "voiceGateway2"
CONFIG_FILE       = "config.json"
LATENCY_THRESHOLD = 5000   # ms — turns above this are flagged


# ── Config ────────────────────────────────────────────────────────────────────

def load_config(path: str = CONFIG_FILE) -> dict:
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), path)
    if not os.path.exists(config_path):
        print(f"[error] Config file not found: {config_path}")
        print("        Copy config.json to the same folder as this script.")
        sys.exit(1)
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_project(config: dict, name: str) -> dict:
    for p in config.get("projects", []):
        if p.get("name", "").lower() == name.lower():
            return p
    available = [p.get("name") for p in config.get("projects", [])]
    print(f"[error] Project '{name}' not found in config.json.")
    print(f"        Available: {available}")
    sys.exit(1)


# ── API fetching ───────────────────────────────────────────────────────────────

def fetch_logs_from_api(project: dict, limit: int = 2000) -> list:
    """
    Fetch log entries from the Cognigy Logs API.
    Paginates automatically until all entries are retrieved or limit is hit.
    If limit is 0, fetches ALL available entries with no cap.
    """
    if requests is None:
        print("[error] Install requests first:  pip install requests")
        sys.exit(1)

    base_url   = project.get("base_url", "https://api-app.cognigy.ai").rstrip("/").removesuffix("/openapi")
    api_key    = project["api_key"]
    project_id = project["project_id"]

    if api_key == "YOUR_API_KEY_HERE":
        print(f"[error] API key not set for '{project['name']}' in config.json.")
        sys.exit(1)
    if project_id == "YOUR_PROJECT_ID_HERE":
        print(f"[error] Project ID not set for '{project['name']}' in config.json.")
        sys.exit(1)

    headers   = {"X-API-Key": api_key}
    all_items = []
    next_id   = None
    page      = 1
    page_size = 25    # Cognigy returns 25 per page
    unlimited = (limit == 0)

    print(f"  Fetching logs for '{project['name']}' from {base_url} ...")
    if unlimited:
        print("  (No limit set — fetching all available entries)")

    current_url    = f"{base_url}/v2.0/projects/{project_id}/logs"
    current_params = {"limit": page_size}

    while True:
        try:
            resp = requests.get(
                current_url,
                headers=headers,
                params=current_params,
                timeout=30,
            )
        except requests.exceptions.ConnectionError:
            print(f"[error] Could not connect to {base_url}. Check base_url in config.json.")
            sys.exit(1)
        except requests.exceptions.Timeout:
            print("[error] Request timed out.")
            sys.exit(1)

        if resp.status_code == 401:
            print("[error] Authentication failed (401). Check api_key in config.json.")
            sys.exit(1)
        if resp.status_code == 404:
            print("[error] Not found (404). Check project_id in config.json.")
            sys.exit(1)
        if not resp.ok:
            print(f"[error] API returned {resp.status_code}: {resp.text[:200]}")
            sys.exit(1)

        data     = resp.json()

        # Cognigy embeds items under _embedded.logEntry
        embedded  = data.get("_embedded", {})
        items     = embedded.get("logEntry", [])
        all_items.extend(items)

        # Use the full next href directly for subsequent pages
        next_href = data.get("_links", {}).get("next", {}).get("href", "")
        if next_href:
            # Clean up the URL: force https, strip empty previous= param
            parsed     = urlparse(next_href)
            params_qs  = parse_qs(parsed.query, keep_blank_values=False)
            params_qs.pop("previous", None)
            clean_query    = urlencode({k: v[0] for k, v in params_qs.items()})
            next_href      = urlunparse(parsed._replace(scheme="https", query=clean_query))
            current_url    = next_href
            current_params = None
        else:
            next_href = None

        print(f"    Page {page}: {len(items)} entries (total so far: {len(all_items)})")
        page += 1

        # Stop if: no more pages, page was empty, or we hit the limit
        if not next_href or not items:
            break
        if not unlimited and len(all_items) >= limit:
            break

    if not unlimited:
        all_items = all_items[:limit]

    all_items.sort(key=lambda x: x.get("timestamp", ""))
    print(f"  Done. {len(all_items)} entries retrieved.")
    return all_items


# ── Local file ─────────────────────────────────────────────────────────────────

def load_logs_from_file(path: str) -> list:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    items = data.get("items", [])
    items.sort(key=lambda x: x.get("timestamp", ""))
    return items


# ── Filtering & grouping ───────────────────────────────────────────────────────

def filter_vg2(items: list) -> list:
    """Keep only voiceGateway2 entries (by channel field or traceId prefix)."""
    out = []
    for item in items:
        meta     = item.get("meta", {})
        ch       = meta.get("channel", "")
        trace_id = item.get("traceId", "")
        if ch == TARGET_CHANNEL or trace_id.startswith("endpoint-vg2client-"):
            out.append(item)
    return out


def group_by_trace(items: list) -> dict:
    """Group entries by traceId — each traceId = one conversational turn."""
    groups = defaultdict(list)
    for item in items:
        groups[item.get("traceId", "unknown")].append(item)
    return groups


# ── Latency calculation ────────────────────────────────────────────────────────

def parse_ts(ts_str: str) -> datetime:
    return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))


def compute_turn_latency(entries: list) -> dict | None:
    """
    Compute latency for a single turn (entries sharing a traceId).

    Metrics:
      first_token_latency_ms   — user msg received → first non-empty bot output
      full_response_latency_ms — user msg received → last bot output
      user_text_length         — character count of user utterance (longer = more NLU work)
      bot_output_segments      — number of output events (more = longer response)
    """
    inbound   = None
    outbounds = []

    for e in sorted(entries, key=lambda x: x.get("timestamp", "")):
        msg  = e.get("msg", "")
        meta = e.get("meta", {})
        if msg == INBOUND_MSG and inbound is None:
            inbound = e
        if msg == OUTBOUND_MSG and meta.get("text", ""):
            outbounds.append(e)

    if inbound is None or not outbounds:
        return None

    inbound_ts   = parse_ts(inbound["timestamp"])
    first_out_ts = parse_ts(outbounds[0]["timestamp"])
    last_out_ts  = parse_ts(outbounds[-1]["timestamp"])
    user_text    = inbound.get("meta", {}).get("text", "") or ""

    first_ms = int((first_out_ts - inbound_ts).total_seconds() * 1000)
    full_ms  = int((last_out_ts  - inbound_ts).total_seconds() * 1000)

    return {
        "session_id":                inbound.get("meta", {}).get("sessionId", "unknown"),
        "trace_id":                  inbound.get("traceId", ""),
        "inbound_time":              inbound["timestamp"],
        "first_output_time":         outbounds[0]["timestamp"],
        "last_output_time":          outbounds[-1]["timestamp"],
        "first_token_latency_ms":    first_ms,
        "full_response_latency_ms":  full_ms,
        "exceeds_threshold":         first_ms > LATENCY_THRESHOLD,
        "user_text":                 user_text,
        "user_text_length":          len(user_text),
        "first_bot_text":            outbounds[0].get("meta", {}).get("text", ""),
        "bot_output_segments":       len(outbounds),
    }


def analyze_turns(items: list) -> list:
    """Filter → group by trace → compute latency for each turn."""
    vg2_items = filter_vg2(items)
    groups    = group_by_trace(vg2_items)
    turns     = []
    for _, entries in sorted(
        groups.items(),
        key=lambda kv: min(e["timestamp"] for e in kv[1])
    ):
        result = compute_turn_latency(entries)
        if result:
            turns.append(result)
    return turns


def group_turns_by_session(turns: list) -> dict:
    """
    Group turns by session_id, preserving turn order within each session.
    Returns an ordered dict: { session_id: [turn, turn, ...] }
    """
    sessions = defaultdict(list)
    for turn in turns:
        sessions[turn["session_id"]].append(turn)
    # Sort sessions by their first turn's inbound time
    return dict(sorted(sessions.items(), key=lambda kv: kv[1][0]["inbound_time"]))


def session_summary(turns: list) -> dict:
    """Compute aggregate stats for a list of turns belonging to one session."""
    latencies     = [t["first_token_latency_ms"] for t in turns]
    flagged_turns = [t for t in turns if t["exceeds_threshold"]]
    return {
        "turn_count":        len(turns),
        "avg_latency_ms":    int(sum(latencies) / len(latencies)),
        "min_latency_ms":    min(latencies),
        "max_latency_ms":    max(latencies),
        "flagged_count":     len(flagged_turns),
        "session_flagged":   len(flagged_turns) > 0,
        "start_time":        turns[0]["inbound_time"],
        "end_time":          turns[-1]["last_output_time"],
    }


# ── Console output ─────────────────────────────────────────────────────────────

def print_report(turns: list, project_name: str = ""):
    """Print a session-grouped latency report to the console."""
    header = "VoiceGateway2 Latency Report"
    if project_name:
        header += f" — {project_name}"

    print("\n" + "=" * 72)
    print(f"  {header}")
    print("=" * 72)

    if not turns:
        print("  No complete turns found in logs.")
        print("=" * 72 + "\n")
        return

    sessions    = group_turns_by_session(turns)
    all_lat     = [t["first_token_latency_ms"] for t in turns]
    all_flagged = [t for t in turns if t["exceeds_threshold"]]

    # ── Overall summary ────────────────────────────────────────────────────────
    print(f"\n  OVERALL  |  {len(sessions)} session(s)  |  {len(turns)} turn(s)  |  threshold: {LATENCY_THRESHOLD:,}ms")
    print(f"  Avg latency : {sum(all_lat)/len(all_lat):>7.0f} ms")
    print(f"  Min latency : {min(all_lat):>7,} ms")
    print(f"  Max latency : {max(all_lat):>7,} ms")
    print(f"  Flagged     : {len(all_flagged)} turn(s) exceeding {LATENCY_THRESHOLD:,}ms")

    # ── Per-session breakdown ──────────────────────────────────────────────────
    for s_idx, (session_id, s_turns) in enumerate(sessions.items(), 1):
        summary = session_summary(s_turns)
        flag    = "  ⚠ HAS SLOW TURNS" if summary["session_flagged"] else ""
        short_id = session_id[:8] + "..." if len(session_id) > 12 else session_id

        print(f"\n  {'─' * 68}")
        print(f"  SESSION {s_idx}  |  {session_id}{flag}")
        print(f"  Started : {summary['start_time']}")
        print(f"  Turns   : {summary['turn_count']}   "
              f"Avg: {summary['avg_latency_ms']:,}ms   "
              f"Min: {summary['min_latency_ms']:,}ms   "
              f"Max: {summary['max_latency_ms']:,}ms")

        for t_idx, t in enumerate(s_turns, 1):
            lat   = t["first_token_latency_ms"]
            tflag = f"  ⚠ SLOW ({lat:,}ms > {LATENCY_THRESHOLD:,}ms threshold)" if t["exceeds_threshold"] else ""
            bar   = build_bar(lat, max(all_lat))

            print(f"\n    Turn {t_idx}{tflag}")
            print(f"      User  : \"{t['user_text'][:70]}\"")
            print(f"      Bot   : \"{t['first_bot_text'][:70]}\"")
            print(f"      Time  : {t['inbound_time']}  →  {t['first_output_time']}")
            print(f"      Latency (first token) : {lat:>6,} ms  {bar}")
            print(f"      Latency (full resp.)  : {t['full_response_latency_ms']:>6,} ms  "
                  f"({t['bot_output_segments']} output segments)")
            print(f"      User text length      : {t['user_text_length']} chars")

    print(f"\n{'=' * 72}\n")


def build_bar(value: int, max_value: int, width: int = 20) -> str:
    """Build a simple ASCII progress bar for visual latency comparison."""
    if max_value == 0:
        return ""
    filled = int((value / max_value) * width)
    return f"[{'█' * filled}{'░' * (width - filled)}]"


# ── CSV output ─────────────────────────────────────────────────────────────────

def write_csv(turns: list, path: str, project_name: str = ""):
    """
    Write turn-level data to CSV, including session position and threshold flag.
    Each row = one turn. Sessions are identified by session_id column.
    Designed to be loaded into Excel / Google Sheets for pivot analysis.
    """
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    sessions = group_turns_by_session(turns)

    # Build rows with session-level context added to each turn
    rows = []
    for s_idx, (session_id, s_turns) in enumerate(sessions.items(), 1):
        summary = session_summary(s_turns)
        for t_idx, t in enumerate(s_turns, 1):
            row = {
                "project":                   project_name,
                "session_number":            s_idx,
                "session_id":                session_id,
                "session_start":             summary["start_time"],
                "session_turn_count":        summary["turn_count"],
                "session_avg_latency_ms":    summary["avg_latency_ms"],
                "session_flagged":           summary["session_flagged"],
                "turn_number":               t_idx,
                "turn_number_in_session":    t_idx,
                "trace_id":                  t["trace_id"],
                "inbound_time":              t["inbound_time"],
                "first_output_time":         t["first_output_time"],
                "last_output_time":          t["last_output_time"],
                "first_token_latency_ms":    t["first_token_latency_ms"],
                "full_response_latency_ms":  t["full_response_latency_ms"],
                "exceeds_threshold":         t["exceeds_threshold"],
                "latency_threshold_ms":      LATENCY_THRESHOLD,
                "user_text_length":          t["user_text_length"],
                "bot_output_segments":       t["bot_output_segments"],
                "user_text":                 t["user_text"],
                "first_bot_text":            t["first_bot_text"],
            }
            rows.append(row)

    fields = list(rows[0].keys()) if rows else []
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    print(f"  CSV saved → {path}  ({len(rows)} rows across {len(sessions)} session(s))")


def make_csv_path(reports_dir: str, project_name: str) -> str:
    safe = project_name.replace(" ", "_").replace("/", "-")
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(reports_dir, f"{safe}_{ts}.csv")


# ── Entry point ────────────────────────────────────────────────────────────────

def run_project(project: dict, config: dict, save_csv: bool, limit: int):
    print(f"\n── Project: {project['name']} {'─' * max(1, 50 - len(project['name']))}")
    items = fetch_logs_from_api(project, limit=limit)
    turns = analyze_turns(items)
    print_report(turns, project_name=project["name"])
    if save_csv and turns:
        reports_dir = config.get("defaults", {}).get("reports_dir", "reports")
        csv_path    = make_csv_path(reports_dir, project["name"])
        write_csv(turns, csv_path, project_name=project["name"])


def main():
    parser = argparse.ArgumentParser(
        description="VoiceGateway2 latency report — session-grouped, threshold-flagged",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    source = parser.add_mutually_exclusive_group()
    source.add_argument("--project", metavar="NAME",
                        help="Project name from config.json")
    source.add_argument("--all",     action="store_true",
                        help="Run for every project in config.json")
    source.add_argument("--input",   metavar="FILE",
                        help="Local log JSON file (skips API call)")

    parser.add_argument("--csv",   action="store_true",
                        help="Save a timestamped CSV to reports/")
    parser.add_argument("--limit", type=int, default=None,
                        help="Max log entries to fetch. Use 0 for no limit. "
                             "(Default: from config.json, fallback 2000)")

    args = parser.parse_args()

    # ── Mode 1: local file ─────────────────────────────────────────────────────
    if args.input:
        print(f"Loading logs from file: {args.input}")
        items = load_logs_from_file(args.input)
        print(f"  Total entries: {len(items)}")
        turns = analyze_turns(items)
        print_report(turns)
        if args.csv and turns:
            config      = load_config() if os.path.exists(CONFIG_FILE) else {}
            reports_dir = config.get("defaults", {}).get("reports_dir", "reports")
            write_csv(turns, make_csv_path(reports_dir, "local_file"))
        return

    # ── Modes 2 & 3: live API ──────────────────────────────────────────────────
    config = load_config()

    # Resolve limit: CLI flag → config.json → default 2000 → 0 means unlimited
    if args.limit is not None:
        limit = args.limit
    else:
        limit = config.get("defaults", {}).get("limit", 2000)

    if args.all:
        projects = config.get("projects", [])
        if not projects:
            print("[error] No projects found in config.json.")
            sys.exit(1)
        for project in projects:
            run_project(project, config, save_csv=args.csv, limit=limit)

    elif args.project:
        project = get_project(config, args.project)
        run_project(project, config, save_csv=args.csv, limit=limit)

    else:
        parser.print_help()
        print("\nTip: edit config.json first, then try:")
        print('  python vg2_latency_report.py --project "JP Sandbox"')


if __name__ == "__main__":
    main()
