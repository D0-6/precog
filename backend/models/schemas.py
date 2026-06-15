# models/schemas.py
from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime

class SplunkSignals(BaseModel):
    discovered_fields: list[str]
    sample_logs: list[dict]
    anomaly_summary: Optional[str] = None

class GitHubSignals(BaseModel):
    commit_count: int
    risky_files_touched: list[str]
    deploy_related_commits: list[str]
    authors: list[str]
    lines_changed: int

class JiraSignals(BaseModel):
    open_bugs_total: int
    bugs_filed_this_week: int
    max_severity: str         # "LOW", "MEDIUM", "HIGH", "CRITICAL"
    unresolved_incidents: int

class SlackSignals(BaseModel):
    deploy_messages: list[str]
    concern_messages: list[str]
    mention_count: int

class HistoricalContext(BaseModel):
    last_incident_days_ago: int
    same_time_last_week_status: str   # "NORMAL", "INCIDENT", "DEGRADED"
    incident_frequency_30d: int
    avg_resolution_minutes: int

class AllSignals(BaseModel):
    service_name: str
    collected_at: datetime
    splunk: SplunkSignals
    github: GitHubSignals
    jira: JiraSignals
    slack: SlackSignals
    history: HistoricalContext

from typing import Any

class DynamicWidget(BaseModel):
    title: str
    type: str # "metric", "list", "table", "markdown", "chart"
    data: Any

class BlastRadiusNode(BaseModel):
    service: str
    failure_probability: float
    historical_correlation: float
    impact_type: str

class BlastRadius(BaseModel):
    origin_service: str
    affected_services: list[BlastRadiusNode]
    customer_facing_features_at_risk: list[str]
    data_integrity_risks: list[str]
    total_blast_score: int

class FatigueScore(BaseModel):
    engineer_name: str
    fatigue_score: int                 # 0-100
    fatigue_level: str                 # OK, ELEVATED, HIGH, CRITICAL
    alerts_last_6h: int
    hours_since_last_sleep_window: float
    consecutive_oncall_days: int
    recommendation: str
    alert_delivery_method: str         # "slack", "phone", "page_backup"

class RegretScore(BaseModel):
    deployment_id: str
    deployment_time: str
    minutes_since_deploy: int
    regret_score: int                  # 0-100, rising over time
    regret_trajectory: list[dict]      # [{time, score}]
    recommendation: str
    cost_of_rollback_minutes: int
    cost_of_waiting_minutes: int

class TribalKnowledgeItem(BaseModel):
    source: str                        # "slack", "confluence", "postmortem"
    date: str
    author: str
    content: str
    relevance_score: float
    author_still_at_company: bool

class TribalKnowledge(BaseModel):
    pattern_matched: str
    items: list[TribalKnowledgeItem]
    key_insight: str

class SilentIncident(BaseModel):
    service: str
    duration_days: int
    incident_type: str
    evidence: list[str]
    estimated_revenue_impact_usd: int
    triggered_any_alert: bool
    root_cause_hypothesis: str

class Prediction(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    risk_score: int                    # 0-100
    confidence: int                    # 0-100
    risk_level: str                    # LOW, MEDIUM, HIGH, CRITICAL
    explanation: str
    key_signals: list[str]
    recommended_action: str
    estimated_time_to_incident: Optional[str] = None
    would_traditional_alert_catch: bool = False
    dynamic_widgets: list[DynamicWidget]
    
    # Generated dynamically by the LLM now!
    blast_radius: BlastRadius
    fatigue: FatigueScore
    regret: RegretScore
    tribal_knowledge: TribalKnowledge
    silent_incidents: list[SilentIncident]
    
    model_used: str
    trace_queries: Optional[list[str]] = None

class FullPrediction(BaseModel):
    service: str
    timestamp: datetime
    signals: AllSignals
    prediction: Prediction
    why_now: list[dict] = []
    blast_radius: BlastRadius
    fatigue: FatigueScore
    regret: Optional[RegretScore]
    tribal_knowledge: Optional[TribalKnowledge]
    silent_incidents: list[SilentIncident]
