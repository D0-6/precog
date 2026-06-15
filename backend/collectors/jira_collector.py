import httpx, base64
from config import JIRA_URL, JIRA_EMAIL, JIRA_TOKEN
from models.schemas import JiraSignals
from datetime import datetime, timedelta

class JiraCollector:
    def __init__(self):
        creds = base64.b64encode(f"{JIRA_EMAIL}:{JIRA_TOKEN}".encode()).decode()
        self.headers = {"Authorization": f"Basic {creds}", "Content-Type": "application/json"}

    async def collect_all(self, service: str) -> JiraSignals:
        week_ago = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
        async with httpx.AsyncClient(timeout=20) as client:
            r1 = await client.get(f"{JIRA_URL}/rest/api/3/search",
                params={"jql": f'project="{service}" AND status!=Done', "maxResults": 50, "fields": "priority,summary"},
                headers=self.headers)
            r2 = await client.get(f"{JIRA_URL}/rest/api/3/search",
                params={"jql": f'project="{service}" AND created>="{week_ago}"', "maxResults": 50, "fields": "priority"},
                headers=self.headers)

        total = r1.json().get("issues", []) if r1.status_code == 200 else []
        week = r2.json().get("issues", []) if r2.status_code == 200 else []
        smap = {"Highest": "CRITICAL", "High": "HIGH", "Medium": "MEDIUM", "Low": "LOW"}
        max_sev = "LOW"
        for i in total:
            sev = smap.get(i.get("fields", {}).get("priority", {}).get("name", "Low"), "LOW")
            if ["LOW","MEDIUM","HIGH","CRITICAL"].index(sev) > ["LOW","MEDIUM","HIGH","CRITICAL"].index(max_sev):
                max_sev = sev

        return JiraSignals(open_bugs_total=len(total), bugs_filed_this_week=len(week),
            max_severity=max_sev,
            unresolved_incidents=len([i for i in total if "incident" in i.get("fields",{}).get("summary","").lower()]))
