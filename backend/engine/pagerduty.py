# engine/pagerduty.py
# Real PagerDuty API integration for Human Fatigue Score.
# Falls back to mock data gracefully if no PD token configured.

import httpx
from datetime import datetime, timedelta
from config import PAGERDUTY_TOKEN
from models.schemas import FatigueScore

PD_BASE = "https://api.pagerduty.com"

class PagerDutyCollector:
    def __init__(self):
        self.headers = {
            "Authorization": f"Token token={PAGERDUTY_TOKEN}",
            "Accept": "application/vnd.pagerduty+json;version=2",
            "Content-Type": "application/json"
        }
        self.available = bool(PAGERDUTY_TOKEN)

    async def get_oncall_engineer(self, service_name: str) -> dict | None:
        """Get who is currently on-call for this service."""
        if not self.available:
            return None
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{PD_BASE}/oncalls",
                headers=self.headers,
                params={"include[]": "users", "limit": 25}
            )
            if resp.status_code != 200:
                return None
            oncalls = resp.json().get("oncalls", [])
            # Find oncall matching service name
            for oc in oncalls:
                policy = oc.get("escalation_policy", {}).get("summary", "").lower()
                if service_name.lower().replace("-", "") in policy.replace("-", ""):
                    return {
                        "name": oc.get("user", {}).get("summary", "On-Call Engineer"),
                        "id": oc.get("user", {}).get("id")
                    }
        return None

    async def get_recent_alerts(self, user_id: str, hours: int = 6) -> list:
        """Get alerts this engineer responded to in last N hours."""
        if not self.available or not user_id:
            return []
        since = (datetime.utcnow() - timedelta(hours=hours)).isoformat() + "Z"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{PD_BASE}/incidents",
                headers=self.headers,
                params={
                    "user_ids[]": user_id,
                    "since": since,
                    "statuses[]": ["resolved", "acknowledged"],
                    "limit": 25
                }
            )
            if resp.status_code != 200:
                return []
            return resp.json().get("incidents", [])

    async def get_oncall_streak(self, user_id: str) -> int:
        """How many consecutive days has this engineer been on-call?"""
        if not self.available or not user_id:
            return 1
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{PD_BASE}/oncalls",
                headers=self.headers,
                params={"user_ids[]": user_id, "limit": 50}
            )
            if resp.status_code != 200:
                return 1
            # Count unique days in oncall schedule
            oncalls = resp.json().get("oncalls", [])
            days = set()
            for oc in oncalls:
                start = oc.get("start")
                if start:
                    days.add(start[:10])
            return min(len(days), 14)  # Cap at 14 days

    async def compute_fatigue(self, service: str) -> FatigueScore:
        """
        Real PagerDuty-powered fatigue score.
        Falls back to mock if PD not configured.
        """
        if not self.available:
            return _mock_fatigue(service)

        engineer = await self.get_oncall_engineer(service)
        if not engineer:
            return _mock_fatigue(service)

        user_id = engineer.get("id")
        alerts, streak = await asyncio.gather(
            self.get_recent_alerts(user_id, hours=6),
            self.get_oncall_streak(user_id)
        )

        alerts_last_6h = len(alerts)
        consecutive_days = streak

        # Estimate hours awake from first alert tonight
        hours_awake = 8.0  # default
        if alerts:
            first_alert = min(
                datetime.fromisoformat(a["created_at"].replace("Z", "+00:00"))
                for a in alerts
            )
            hours_awake = (datetime.utcnow().replace(tzinfo=first_alert.tzinfo) - first_alert).seconds / 3600
            hours_awake = max(hours_awake, 8.0)

        # Fatigue formula
        score = 0
        score += min(40, alerts_last_6h * 10)
        score += min(30, int(hours_awake * 1.5))
        score += min(20, consecutive_days * 3)
        score += 5  # baseline complexity
        score = min(100, score)

        level = (
            "CRITICAL" if score >= 75 else
            "HIGH"     if score >= 55 else
            "ELEVATED" if score >= 30 else "OK"
        )
        delivery = (
            "page_backup" if score >= 75 else
            "phone"       if score >= 55 else "slack"
        )
        rec = {
            "CRITICAL": f"CRITICAL fatigue. Auto-page backup engineer. Do NOT rely on {engineer['name']} alone.",
            "HIGH":     f"High fatigue detected. Page with full context. Consider co-responder.",
            "ELEVATED": f"Slightly elevated fatigue. Add context to alert.",
            "OK":       f"Engineer is well-rested. Standard notification."
        }[level]

        return FatigueScore(
            engineer_name=engineer["name"],
            fatigue_score=score,
            fatigue_level=level,
            alerts_last_6h=alerts_last_6h,
            hours_since_last_sleep_window=round(hours_awake, 1),
            consecutive_oncall_days=consecutive_days,
            recommendation=rec,
            alert_delivery_method=delivery
        )


# ── Mock fallback (same as before, used when PD not configured) ─────────────

import asyncio

def _mock_fatigue(service: str) -> FatigueScore:
    return FatigueScore(
        engineer_name="On-Call Engineer",
        fatigue_score=42,
        fatigue_level="ELEVATED",
        alerts_last_6h=2,
        hours_since_last_sleep_window=10.0,
        consecutive_oncall_days=2,
        recommendation=f"Use standard escalation for {service}; PagerDuty is not configured.",
        alert_delivery_method="slack"
    )

pagerduty = PagerDutyCollector()
