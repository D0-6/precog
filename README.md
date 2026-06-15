# 🧠 PreCog — Pre-Incident Intelligence for Splunk

> *"Traditional monitoring tells you your house is on fire. PreCog smells the smoke 15 minutes before."*

**PreCog** is an AI-powered pre-incident intelligence dashboard that monitors live Splunk logs across microservices and **predicts system failures before they happen** — not after.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue)](https://python.org)
[![React 18](https://img.shields.io/badge/React-18-61DAFB)](https://react.dev)

---

## 🎥 Demo Video

> **[Watch 3-minute demo on YouTube](#)** ← *(replace with your link)*

---

## 🚀 What PreCog Does

| Traditional Monitoring | PreCog |
|---|---|
| Alerts **after** crash | **Predicts before crash** |
| Single data source | Cross-signal correlation (Splunk + GitHub + Jira + Slack) |
| "Something is wrong" | "payments-api fails in 8 min — here's why" |
| Static dashboard | Live risk scores rising in real time |

**Key Features:**
- 🔴 **Real-time risk scoring** — 0–100 per service, updated every 30s from live Splunk data
- 🧠 **AI correlation** — NVIDIA NIM LLM correlates weak signals across data sources
- 💥 **Blast radius** — which downstream services will cascade-fail
- 💰 **Cost of inaction** — live dollar estimate updated as risk rises
- 🤖 **AI Assistant** — context-aware chatbot answers questions about live signals
- 📡 **Splunk Scripted Input** — native Splunk ingestion, no HEC token needed

---

## 🏗️ Architecture

![Architecture Diagram](architecture_diagram.png)

### Data Flow
```
[Your Services / Logs]
        ↓
precog_script_input.py   ← runs inside Splunk every 60s (Scripted Input)
        ↓
Splunk Index (main)      ← stores all telemetry events
        ↓
PreCog Backend (FastAPI :8081)
  ├── SplunkCollector    → queries anomalies via Splunk REST API
  ├── GitHubCollector    → recent risky commits (optional)
  ├── JiraCollector      → open bugs & severity (optional)
  └── SlackCollector     → deployment messages (optional)
        ↓
NVIDIA NIM LLM (llama-3.3-70b-instruct)
  → Correlates all signals → outputs risk_score, blast_radius, recommended_action
        ↓
WebSocket → React Dashboard (:5173)
  → Live risk cards, sparklines, cost panel, AI chat
```

---

## ⚡ Quick Start

### Prerequisites
- Splunk Enterprise running locally (port 8089)
- Python 3.10+, Node.js 18+
- Free NVIDIA NIM API key from [build.nvidia.com](https://build.nvidia.com)

### Step 1 — Clone & Install
```bash
git clone https://github.com/YOUR_USERNAME/precog.git
cd precog

# Backend
cd backend
pip install -r ../requirements.txt
cp ../.env.example .env
# Edit .env with your NVIDIA_API_KEY and SPLUNK_TOKEN
```

### Step 2 — Get Splunk API Token
1. Open Splunk Web → **Settings → Tokens**
2. Click **New Token** → name it `precog`
3. Copy the token → paste into `backend/.env` as `SPLUNK_TOKEN`

### Step 3 — Deploy Splunk Scripted Input
This runs **inside Splunk every 60s**, sending live telemetry into your index — no HEC needed.

**Copy script to Splunk:**
```bash
# Windows
copy tools\precog_script_input.py "D:\Splunk\etc\apps\search\bin\"

# Linux/Mac
cp tools/precog_script_input.py $SPLUNK_HOME/etc/apps/search/bin/
```

**Create the Scripted Input in Splunk Web:**
1. Go to **Settings → Data Inputs → Scripts → New**
2. Set:
   ```
   Script:    python3 precog_script_input.py
   Interval:  60
   Sourcetype: _json
   Index:     main
   ```
3. Click **Save**

**Verify in Splunk Search:**
```
index=main sourcetype=_json | head 10
```
You should see events with `service`, `level`, `cpu_usage`, `memory_usage` fields.

### Step 4 — Start PreCog Backend
```bash
cd backend
python -m uvicorn main:app --host 127.0.0.1 --port 8081 --reload
```

### Step 5 — Start Frontend
```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173** — services from Splunk appear automatically.

#### Step 6 — Connect your own Splunk (runtime)
In the PreCog dashboard, click the **Settings** gear icon and enter:
- **Splunk URL**: `https://localhost:8089`
- **Index**: `main`
- **Token**: your Splunk API token

Click **Save & Reconnect** — dashboard reloads with your live data.

---

## 🎯 Running the Demo (Live Crash Scenario)

Once running, trigger a crash scenario to show PreCog predicting failure:

```bash
# Step 1 — Everything is healthy (normal traffic)
echo normal > C:\Temp\precog_phase.txt

# Step 2 — Introduce anomalies (watch risk scores climb to 40-60)
echo warn > C:\Temp\precog_phase.txt

# Step 3 — Critical signals (risk scores spike to 80-100)
echo crash > C:\Temp\precog_phase.txt

# Step 4 — Reset after demo
echo normal > C:\Temp\precog_phase.txt
```

> 💡 Each phase takes effect on the **next Splunk script run** (within 60s).  
> Watch the dashboard — risk scores rise **before** any actual crash occurs.

---

## 🔧 Configuration Reference

### `backend/.env` (required)
```env
# NVIDIA NIM — free at build.nvidia.com
NVIDIA_API_KEY=nvapi-xxxx

# Splunk connection
SPLUNK_MCP_URL=https://localhost:8089
SPLUNK_TOKEN=your-splunk-api-token

# Set true to run with synthetic demo data (no Splunk needed)
DEMO_MODE=true

# Optional integrations
GITHUB_TOKEN=ghp_xxxx
GITHUB_ORG=your-org
JIRA_URL=https://yourorg.atlassian.net
JIRA_EMAIL=you@email.com
JIRA_TOKEN=your-jira-token
SLACK_TOKEN=xoxb-xxxx
SLACK_CHANNEL_IDS=C01234567
```

---

## 📁 Project Structure

```
precog/
├── backend/
│   ├── main.py                    # FastAPI app — all API + WebSocket endpoints
│   ├── config.py                  # API keys, NVIDIA model chain
│   ├── collectors/
│   │   ├── splunk_collector.py    # Live Splunk REST API integration
│   │   ├── github_collector.py    # GitHub commit signals
│   │   ├── jira_collector.py      # Jira bug signals
│   │   └── slack_collector.py     # Slack deployment signals
│   ├── engine/
│   │   ├── correlator.py          # NVIDIA NIM AI signal correlation
│   │   ├── extras.py              # DB logging, sparklines
│   │   └── features.py            # Cost estimation, benchmarks
│   ├── models/
│   │   └── schemas.py             # Pydantic data models
│   └── demo/
│       └── synthetic_data.py      # Demo scenario data (DEMO_MODE=true)
├── frontend/
│   └── src/
│       └── App.jsx                # Full React dashboard
├── tools/
│   ├── precog_script_input.py     # ← Deploy this to Splunk bin/
│   └── generate_crash_scenario.py # Manual crash scenario generator
├── architecture_diagram.png
├── .env.example                   # Copy to backend/.env
├── requirements.txt
└── README.md
```

---

## 📦 Dependencies

Install with:
```bash
pip install -r requirements.txt
```

**Python:** `fastapi`, `uvicorn`, `openai`, `httpx`, `splunk-sdk`, `pydantic`, `python-dotenv`, `websockets`  
**Node:** `react`, `recharts`, `vite`, `@vitejs/plugin-react`  
**AI:** [NVIDIA NIM](https://build.nvidia.com) free API — `meta/llama-3.3-70b-instruct`  
**Data:** Splunk Enterprise (free trial at [splunk.com](https://splunk.com))

---

## 🤖 How AI Works in PreCog

1. **Every 30s** — SplunkCollector queries live logs for anomalies, error patterns, latency spikes
2. **AI Correlation** — `correlator.py` sends all signals to NVIDIA NIM with a structured prompt
3. **LLM Output** — JSON with `risk_score`, `risk_level`, `explanation`, `blast_radius`, `recommended_action`
4. **Fallback Chain** — if one model is busy, auto-retries with next model in chain
5. **WebSocket Push** — frontend receives live updates every 30s

---

## 📄 License

MIT — see [LICENSE](LICENSE)

---

*Built for the Splunk AI Hackathon 2025*
