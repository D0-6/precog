# config.py
import os
from dotenv import load_dotenv

load_dotenv()

# NVIDIA NIM
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY")          # nvapi-xxxx
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"

# Model Fallback chain for LLM calls (NVIDIA NIM endpoints)
MODEL_CHAIN = [
    "meta/llama-3.3-70b-instruct",
    "deepseek-ai/deepseek-v4-flash",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
    "google/gemma-4-31b-it",
    "stepfun-ai/step-3.7-flash"
]

# Splunk MCP
SPLUNK_MCP_URL = "https://localhost:8089" # Used as fallback if MCP fails
SPLUNK_TOKEN = os.getenv("SPLUNK_TOKEN") # Overridable at runtime
# Splunk AI Toolkit — connection name configured in AITK Connections tab
# This unlocks the | ai SPL command which runs Splunk Hosted Models inside Splunk
SPLUNK_AI_CONNECTION = os.getenv("SPLUNK_AI_CONNECTION", "splunk_hosted_llm")

# GitHub
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")              # ghp_xxxx
GITHUB_ORG = os.getenv("GITHUB_ORG", "your-org")

# Jira
JIRA_URL = os.getenv("JIRA_URL")                      # https://your-org.atlassian.net
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_TOKEN = os.getenv("JIRA_TOKEN")

# Slack
SLACK_TOKEN = os.getenv("SLACK_TOKEN")                # xoxb-xxxx
SLACK_CHANNEL_IDS = os.getenv("SLACK_CHANNEL_IDS", "").split(",")

# Services to monitor
# NOTE: Only "recommendations-engine" exists in the Splunk index (metrics.csv, app_logs.csv, db_logs.csv).
# All other service names are phantom — they return empty Splunk results.
MONITORED_SERVICES = [
    "recommendations-engine",
]

# How often to run predictions (minutes)
PREDICTION_INTERVAL_MINUTES = 15

# Demo mode — uses synthetic data and skips AI completely (instant, safe fallback)
_env_demo = os.getenv("DEMO_MODE", "").lower()
if _env_demo == "false":
    DEMO_MODE = False
elif _env_demo == "true":
    DEMO_MODE = True
else:
    # Auto-detect: if we have an AI key, we turn off full Demo Mode so the AI runs live
    DEMO_MODE = not bool(NVIDIA_API_KEY)

# PagerDuty (optional — falls back to mock if not set)
PAGERDUTY_TOKEN = os.getenv("PAGERDUTY_TOKEN", "")  # Get free at pagerduty.com
