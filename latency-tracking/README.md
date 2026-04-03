# VoiceGateway2 Latency QA Tool

A lightweight tool for measuring and reporting response latency in Cognigy VoiceGateway2 voice bot sessions. Designed for QA testing — fetches live logs from the Cognigy API and generates a visual HTML dashboard.

---

## What it measures

**First-token latency** — the time between when a user finishes speaking and when the bot begins responding. This is the latency the caller actually experiences.

Each turn is rated against three tiers:

| Tier | Range | Meaning |
|---|---|---|
| 🟢 Acceptable | Under 2,500ms | Normal performance |
| 🟡 Degraded | 2,500ms – 5,000ms | Noticeable delay, worth investigating |
| 🔴 Unacceptable | Over 5,000ms | Significant delay, action required |

---

## Requirements

- Python 3.10 or later — [python.org/downloads](https://python.org/downloads)
- The `requests` library — install once with:
  ```
  pip install requests
  ```
  *(On Mac, use `pip3 install requests`)*

---

## Setup

### 1. Edit config.json

Open `config.json` and fill in your Cognigy details:

```json
{
  "projects": [
    {
      "name": "My Project",
      "api_key": "YOUR_API_KEY",
      "project_id": "YOUR_PROJECT_ID",
      "base_url": "https://api-trial-us.cognigy.ai",
      "notes": ""
    }
  ],
  "defaults": {
    "limit": 2000,
    "channel": "voiceGateway2",
    "reports_dir": "reports"
  }
}
```

**Where to find your values:**
- **api_key** — Cognigy UI → top-right menu → My Profile → API Keys
- **project_id** — visible in the URL when inside your project: `.../project/YOUR_PROJECT_ID/...`
- **base_url** — the root URL of your Cognigy environment. You can paste it directly from your browser's address bar — the tool automatically strips `/openapi` from the end if present. Examples:
  - `https://api-trial-us.cognigy.ai`
  - `https://api-trial-us.cognigy.ai/openapi` ← also works

To add multiple projects, copy and paste the `{ }` block inside `"projects"` and fill in the new values.

---

## Running a report

### Step 1 — Fetch logs and save a CSV

```bash
# Single project
python vg2_latency_report.py --project "My Project" --csv

# All projects in config.json
python vg2_latency_report.py --all --csv
```

Results print to the terminal immediately. The `--csv` flag saves a timestamped file to the `reports/` folder.

**Optional flags:**
```bash
--limit 5000     # Fetch more log history (default: 2000, use 0 for no limit)
--input logs.json  # Use a saved JSON file instead of calling the API
```

### Step 2 — Generate the HTML dashboard

```bash
python generate_dashboard.py
```

This reads the most recent CSV in `reports/` and creates `dashboard.html` in the same folder.

To use a specific CSV:
```bash
python generate_dashboard.py --input reports/My_Project_20260314_182435.csv
```

### Step 3 — Open the dashboard

Double-click `dashboard.html` to open it in your browser. No internet connection required.

---

## Folder structure

```
vg2-latency/
├── vg2_latency_report.py   — fetches logs, prints report, saves CSV
├── generate_dashboard.py   — reads CSV, generates dashboard.html
├── config.json             — your API keys and project settings
├── .gitignore              — prevents config.json from being committed
├── README.md               — this file
├── reports/                — auto-created, stores timestamped CSVs
└── dashboard.html          — auto-created, open in browser
```

---

## Understanding the output

### Terminal report
Printed immediately after fetching. Shows each session grouped with all its turns, latency values, and ⚠ flags for slow turns.

### CSV report
Each row is one conversational turn. Key columns:

| Column | Description |
|---|---|
| `session_number` | Which call (1, 2, 3...) |
| `turn_number_in_session` | Which turn within the call |
| `first_token_latency_ms` | Primary latency metric |
| `full_response_latency_ms` | Time to complete bot response |
| `exceeds_threshold` | True if over 5,000ms |
| `user_text` | What the caller said |
| `first_bot_text` | First thing the bot said |
| `user_text_length` | Character count — longer utterances may increase latency |
| `bot_output_segments` | Number of output events — more segments = longer response |

### HTML dashboard
Visual turn-by-turn breakdown with color-coded latency bars. Sessions are expandable. No internet connection required to view.

---

## Tips for QA testing

- **Run calls first, then pull logs** — allow 1–2 minutes after a call ends for logs to appear in the API
- **Turn 1 of each session is typically slower** — this is normal due to flow loading on call start
- **Compare sessions of similar length** — a 2-turn call and a 10-turn call will naturally show different patterns
- **Watch for yellow turns with long user_text** — complex utterances can increase NLU processing time
- **If adding LLM or RAG to the flow** — expect first-token latency to increase; re-baseline your thresholds accordingly

---

## Troubleshooting

| Error | Fix |
|---|---|
| `command not found: python` | Use `python3` instead, or add alias per setup instructions |
| `401 Unauthorized` | API key is wrong or expired — regenerate in Cognigy |
| `404 Not Found` | Check project_id in config.json matches the URL in Cognigy |
| `0 entries retrieved` | No logs yet — wait a minute after calls and retry |
| `No complete turns found` | Logs exist but no matching voiceGateway2 turns — check channel name in config |
