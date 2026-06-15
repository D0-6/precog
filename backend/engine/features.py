# engine/features.py
import random
from typing import List, Dict

# ─── Simulation Globals ────────────────────────────────────────────────────────
_SIMULATION_ACTIVE = False
_SIMULATION_BOOST = 0

def start_simulation():
    global _SIMULATION_ACTIVE, _SIMULATION_BOOST
    _SIMULATION_ACTIVE = True
    _SIMULATION_BOOST = 60

def reset_simulation():
    global _SIMULATION_ACTIVE, _SIMULATION_BOOST
    _SIMULATION_ACTIVE = False
    _SIMULATION_BOOST = 0

def get_simulation_risk_boost() -> int:
    return _SIMULATION_BOOST


# ─── Incident Cost Estimation ──────────────────────────────────────────────────
def estimate_incident_cost(risk_score: int) -> int:
    """Mathematical cost estimation based purely on risk score."""
    if risk_score < 40:
        return 0
    elif risk_score < 70:
        return random.randint(15000, 50000)
    elif risk_score < 90:
        return random.randint(80000, 250000)
    else:
        return random.randint(500000, 2000000)


# ─── Fatigue Score ─────────────────────────────────────────────────────────────
class FatigueResult:
    def __init__(self, fatigue_score: int, alert_delivery_method: str, recommendation: str, alerts_last_6h: int = 0):
        self.fatigue_score = fatigue_score
        self.alert_delivery_method = alert_delivery_method
        self.recommendation = recommendation
        self.alerts_last_6h = alerts_last_6h

def get_fatigue_score(engineer: str, alerts: int, hours_awake: int, days: int) -> FatigueResult:
    score = (alerts * 10) + (hours_awake * 1.5) + (days * 3) + 5
    score = min(100, int(score))

    if score < 30:
        method = "slack"
        rec = f"{engineer} is well-rested. Notify via Slack."
    elif score < 55:
        method = "page_primary"
        rec = f"Keep an eye on {engineer} — elevated load."
    elif score < 75:
        method = "page_backup"
        rec = f"Page backup engineer instead of {engineer}."
    else:
        method = "page_backup"
        rec = f"CRITICAL: Do NOT rely on {engineer} alone. Page backup immediately."

    return FatigueResult(score, method, rec, alerts)


# ─── Regret Score ──────────────────────────────────────────────────────────────
class RegretResult:
    def __init__(self, regret_score: int, regret_trajectory: List[Dict], recommendation: str):
        self.regret_score = regret_score
        self.regret_trajectory = regret_trajectory
        self.recommendation = recommendation

def get_regret_score(minutes_since_deploy: int, signals_penalty: int) -> RegretResult:
    base = 10
    score = base + signals_penalty
    score = int(score * (1 + minutes_since_deploy / 240.0))
    score = min(100, score)

    trajectory = []
    for m in [0, 15, 30, 45, 60]:
        if m <= minutes_since_deploy:
            s = (base + signals_penalty) * (1 + m / 240.0)
            trajectory.append({"minutes": m, "score": min(100, int(s))})

    if score < 30:
        rec = "Continue monitoring"
    elif score < 50:
        rec = "Prepare rollback plan"
    elif score < 70:
        rec = "High regret — consider rollback"
    else:
        rec = "ROLL BACK NOW"

    return RegretResult(score, trajectory, rec)
