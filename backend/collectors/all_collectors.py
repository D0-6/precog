import httpx
from datetime import datetime, timedelta, timezone
import logging
from config import GITHUB_TOKEN, GITHUB_ORG
from models.schemas import GitHubSignals, JiraSignals, SlackSignals
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

RISKY_PATHS = ["auth", "payment", "database", "config", "secret", "security", "token", "cred"]

class GitHubCollector:
    def __init__(self):
        self.headers = {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        }
        self.base = "https://api.github.com"

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def _fetch_data(self, service: str, since: str) -> list:
        async with httpx.AsyncClient(timeout=10, verify=False) as client:
            resp = await client.get(
                f"{self.base}/repos/{GITHUB_ORG}/{service}/commits",
                params={"since": since},
                headers=self.headers
            )
            resp.raise_for_status()
            return resp.json()

    async def collect_all(self, service: str) -> GitHubSignals:
        since = (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat()
        try:
            commits = await self._fetch_data(service, since)
        except Exception as e:
            logger.warning(f"[GitHubCollector] Failed to fetch data: {e}")
            commits = []

        risky_files = []
        deploy_commits = []
        total_lines = 0

        for commit in commits[:10]:  # Cap at 10 to avoid rate limits
            msg = commit.get("commit", {}).get("message", "").lower()
            if any(w in msg for w in ["deploy", "release", "prod", "v2", "v3", "upgrade"]):
                deploy_commits.append(commit["commit"]["message"][:100])

            files = commit.get("files", [])
            for f in files:
                fname = f.get("filename", "").lower()
                if any(r in fname for r in RISKY_PATHS):
                    risky_files.append(f["filename"])
                total_lines += f.get("additions", 0) + f.get("deletions", 0)

        authors = list(set(
            c.get("commit", {}).get("author", {}).get("name", "unknown")
            for c in commits
        ))

        return GitHubSignals(
            commit_count=len(commits),
            risky_files_touched=list(set(risky_files)),
            deploy_related_commits=deploy_commits,
            authors=authors,
            lines_changed=total_lines,
        )


# collectors/jira_collector.py
import httpx
import base64
from config import JIRA_URL, JIRA_EMAIL, JIRA_TOKEN
from models.schemas import JiraSignals
from datetime import datetime, timedelta

class JiraCollector:
    def __init__(self):
        creds = base64.b64encode(f"{JIRA_EMAIL}:{JIRA_TOKEN}".encode()).decode()
        self.headers = {
            "Authorization": f"Basic {creds}",
            "Content-Type": "application/json"
        }

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def _fetch_data(self, jql: str) -> list:
        if not JIRA_URL or not JIRA_TOKEN:
            return []
            
        async with httpx.AsyncClient(timeout=10, verify=False) as client:
            resp = await client.post(
                f"{JIRA_URL}/rest/api/3/search",
                params={"jql": jql, "maxResults": 50, "fields": "priority,summary"},
                headers=self.headers
            )
            resp.raise_for_status()
            return resp.json().get("issues", [])

    async def collect_all(self, service: str) -> JiraSignals:
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
        jql_total = f'project = "{service}" AND status != Done'
        jql_week = f'project = "{service}" AND created >= "{week_ago}"'

        try:
            total_issues = await self._fetch_data(jql_total)
            week_issues = await self._fetch_data(jql_week)
        except Exception as e:
            logger.warning(f"[JiraCollector] Failed to fetch data: {e}")
            total_issues = []
            week_issues = []

        severity_map = {"Highest": "CRITICAL", "High": "HIGH", "Medium": "MEDIUM", "Low": "LOW"}
        max_sev = "LOW"
        for issue in total_issues:
            sev = severity_map.get(
                issue.get("fields", {}).get("priority", {}).get("name", "Low"), "LOW"
            )
            if ["LOW","MEDIUM","HIGH","CRITICAL"].index(sev) > \
               ["LOW","MEDIUM","HIGH","CRITICAL"].index(max_sev):
                max_sev = sev

        return JiraSignals(
            open_bugs_total=len(total_issues),
            bugs_filed_this_week=len(week_issues),
            max_severity=max_sev,
            unresolved_incidents=len([i for i in total_issues if "incident" in
                i.get("fields", {}).get("summary", "").lower()])
        )


# collectors/slack_collector.py
import httpx
from config import SLACK_TOKEN, SLACK_CHANNEL_IDS
from models.schemas import SlackSignals

DEPLOY_KEYWORDS = ["deployed", "deployment", "release", "going out", "pushing to prod", "rollout"]
CONCERN_KEYWORDS = ["seeing issues", "anyone else", "is it just me", "slow", "down", "broken", "errors"]

class SlackCollector:
    def __init__(self):
        self.headers = {"Authorization": f"Bearer {SLACK_TOKEN}"}

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def _fetch_channel(self, channel_id: str, oldest: str) -> list:
        async with httpx.AsyncClient(timeout=10, verify=False) as client:
            resp = await client.get(
                "https://slack.com/api/conversations.history",
                params={"channel": channel_id, "oldest": oldest, "limit": 100},
                headers=self.headers
            )
            resp.raise_for_status()
            return resp.json().get("messages", [])

    async def collect_all(self, service: str) -> SlackSignals:
        deploy_msgs = []
        concern_msgs = []
        mention_count = 0

        oldest = str(__import__("time").time() - 7200)  # Last 2 hours

        for channel_id in SLACK_CHANNEL_IDS[:3]:  # Cap channels
            try:
                messages = await self._fetch_channel(channel_id, oldest)
            except Exception as e:
                logger.warning(f"[SlackCollector] Failed to fetch channel {channel_id}: {e}")
                messages = []

            # Process messages OUTSIDE the except block — runs on success AND on fallback
            for msg in messages:
                text = msg.get("text", "").lower()
                if service.lower() in text:
                    mention_count += 1
                    if any(k in text for k in DEPLOY_KEYWORDS):
                        deploy_msgs.append(msg["text"][:200])
                    if any(k in text for k in CONCERN_KEYWORDS):
                        concern_msgs.append(msg["text"][:200])

        return SlackSignals(
            deploy_messages=deploy_msgs[:5],
            concern_messages=concern_msgs[:5],
            mention_count=mention_count,
        )
