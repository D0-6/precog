import httpx
from datetime import datetime, timedelta
from config import GITHUB_TOKEN, GITHUB_ORG
from models.schemas import GitHubSignals

RISKY_PATHS = ["auth", "payment", "database", "config", "secret", "security", "token", "cred"]

class GitHubCollector:
    def __init__(self):
        self.headers = {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        }
        self.base = "https://api.github.com"

    async def collect_all(self, service: str) -> GitHubSignals:
        since = (datetime.utcnow() - timedelta(hours=4)).isoformat() + "Z"
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                f"{self.base}/repos/{GITHUB_ORG}/{service}/commits",
                params={"since": since},
                headers=self.headers
            )
            commits = resp.json() if resp.status_code == 200 else []

        risky_files, deploy_commits, total_lines = [], [], 0
        for commit in commits[:10]:
            msg = commit.get("commit", {}).get("message", "").lower()
            if any(w in msg for w in ["deploy", "release", "prod", "v2", "v3", "upgrade"]):
                deploy_commits.append(commit["commit"]["message"][:100])
            for f in commit.get("files", []):
                fname = f.get("filename", "").lower()
                if any(r in fname for r in RISKY_PATHS):
                    risky_files.append(f["filename"])
                total_lines += f.get("additions", 0) + f.get("deletions", 0)

        return GitHubSignals(
            commit_count=len(commits),
            risky_files_touched=list(set(risky_files)),
            deploy_related_commits=deploy_commits,
            authors=list(set(c.get("commit", {}).get("author", {}).get("name", "unknown") for c in commits)),
            lines_changed=total_lines,
        )
