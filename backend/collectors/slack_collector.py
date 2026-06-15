import httpx, time
from config import SLACK_TOKEN, SLACK_CHANNEL_IDS
from models.schemas import SlackSignals

DEPLOY_KW = ["deployed", "deployment", "release", "going out", "pushing to prod", "rollout"]
CONCERN_KW = ["seeing issues", "anyone else", "is it just me", "slow", "down", "broken", "errors"]

class SlackCollector:
    def __init__(self):
        self.headers = {"Authorization": f"Bearer {SLACK_TOKEN}"}

    async def collect_all(self, service: str) -> SlackSignals:
        deploy_msgs, concern_msgs, mention_count = [], [], 0
        oldest = str(time.time() - 7200)
        async with httpx.AsyncClient(timeout=20) as client:
            for channel_id in SLACK_CHANNEL_IDS[:3]:
                resp = await client.get("https://slack.com/api/conversations.history",
                    params={"channel": channel_id, "oldest": oldest, "limit": 100},
                    headers=self.headers)
                for msg in (resp.json().get("messages", []) if resp.status_code == 200 else []):
                    text = msg.get("text", "").lower()
                    if service.lower() in text:
                        mention_count += 1
                        if any(k in text for k in DEPLOY_KW): deploy_msgs.append(msg["text"][:200])
                        if any(k in text for k in CONCERN_KW): concern_msgs.append(msg["text"][:200])
        return SlackSignals(deploy_messages=deploy_msgs[:5], concern_messages=concern_msgs[:5], mention_count=mention_count)
