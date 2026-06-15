# demo/synthetic_data.py
# This file is your safety net.
# ALWAYS use this for your demo video recording.
# Real APIs can be slow/down. This never fails.

from datetime import datetime
from models.schemas import (
    AllSignals, SplunkSignals, GitHubSignals, JiraSignals,
    SlackSignals, HistoricalContext, Prediction,
    BlastRadius, BlastRadiusNode, FatigueScore,
    RegretScore, TribalKnowledge, TribalKnowledgeItem,
    SilentIncident, FullPrediction
)

def get_demo_scenario(service: str = "payments-api") -> FullPrediction:
    """
    Returns a perfectly crafted demo scenario.
    Shows 5 individually innocent signals combining into HIGH RISK.
    This is the money shot of your demo.
    """
    
    signals = AllSignals(
        service_name=service,
        collected_at=datetime.now(),
        splunk=SplunkSignals(
            discovered_fields=["service", "cpu_pct", "mem_pct", "error_rate", "level", "message"],
            sample_logs=[
                {"service": service, "mem_pct": 68.1, "error_rate": 2.7, "level": "WARN", "message": "checkout latency rising"},
                {"service": service, "mem_pct": 69.4, "error_rate": 3.1, "level": "ERROR", "message": "payment tokenization timeout after 847ms"},
                {"service": service, "mem_pct": 71.2, "error_rate": 3.4, "level": "WARN", "message": "connection pool saturation increasing"}
            ],
            anomaly_summary="Memory drift +8.1%, error rate rising, and slow payment tokenization queries clustered after deploy."
        ),
        github=GitHubSignals(
            commit_count=4,
            risky_files_touched=["auth/payment_processor.py", "config/db.yml"],
            deploy_related_commits=["feat: update payment tokenization v2 (#2847)"],
            authors=["alex.chen", "priya.sharma"],
            lines_changed=847
        ),
        jira=JiraSignals(
            open_bugs_total=5,
            bugs_filed_this_week=3,   # Spike. Alone = maybe.
            max_severity="HIGH",
            unresolved_incidents=1
        ),
        slack=SlackSignals(
            deploy_messages=["payments-api v2.4.1 deployed to prod ~47min ago ✅"],
            concern_messages=["anyone else seeing slightly slow checkouts? might be nothing"],
            mention_count=7
        ),
        history=HistoricalContext(
            last_incident_days_ago=7,         # SAME DAY LAST WEEK
            same_time_last_week_status="INCIDENT",  # The smoking gun
            incident_frequency_30d=2,
            avg_resolution_minutes=94
        )
    )

    prediction = Prediction(
        risk_score=81,
        confidence=78,
        risk_level="HIGH",
        explanation=(
            "A deployment 47 minutes ago touched payment authentication — "
            "the same component that caused last week's incident. "
            "Memory has been creeping up 8% above baseline since the deploy, "
            "3 high-severity bugs were filed this week, and a team member "
            "just asked if checkouts feel slow. No individual signal is alarming. "
            "Together, they match the exact pattern from 7 days ago — "
            "which became a 94-minute incident."
        ),
        key_signals=[
            "Deploy 47min ago touched auth/payment_processor.py",
            "Memory +8.1% drift since deploy (rising, not plateauing)",
            "Same time last week: INCIDENT status",
            "3 HIGH-severity bugs filed this week (spike)",
            "Team member reporting slow checkouts in Slack"
        ],
        recommended_action=(
            "Roll back commit a3f9b2 (payments-api v2.4.1) immediately. "
            "Rollback cost: ~8 minutes. "
            "Cost of waiting: ~94 minutes (historical average for this pattern)."
        ),
        estimated_time_to_incident="35-60 minutes if no action taken",
        would_traditional_alert_catch=False,
        dynamic_widgets=[
            {
                "title": "Payment Timeout Cluster",
                "type": "list",
                "data": [
                    "Payment processing timeout after 847ms",
                    "Connection pool saturation increasing",
                    "Checkout latency mentioned in Slack"
                ]
            }
        ],
        blast_radius=BlastRadius(
            origin_service="payments-api",
            affected_services=[
                BlastRadiusNode(
                    service="checkout-service",
                    failure_probability=0.70,
                    historical_correlation=0.87,
                    impact_type="direct_dependency"
                ),
                BlastRadiusNode(
                    service="order-confirmation",
                    failure_probability=0.81,
                    historical_correlation=1.0,
                    impact_type="full_dependency"
                ),
                BlastRadiusNode(
                    service="inventory-service",
                    failure_probability=0.54,
                    historical_correlation=0.67,
                    impact_type="orphaned_writes"
                ),
            ],
            customer_facing_features_at_risk=[
                "Checkout flow",
                "Subscription renewals",
                "Refund processing"
            ],
            data_integrity_risks=[
                "Inventory count corruption",
                "Duplicate charge risk"
            ],
            total_blast_score=89
        ),
        fatigue=FatigueScore(
            engineer_name="Alex Chen",
            fatigue_score=87,
            fatigue_level="CRITICAL",
            alerts_last_6h=4,
            hours_since_last_sleep_window=19.2,
            consecutive_oncall_days=6,
            recommendation=(
                "CRITICAL fatigue level. Alex has been awake 19+ hours and responded to "
                "4 alerts tonight. Auto-page backup engineer Priya Sharma."
            ),
            alert_delivery_method="page_backup"
        ),
        regret=RegretScore(
            deployment_id="payments-api-v2.4.1",
            deployment_time=datetime.now().strftime("%H:%M"),
            minutes_since_deploy=47,
            regret_score=73,
            regret_trajectory=[
                {"time": "0m", "score": 12},
                {"time": "15m", "score": 24},
                {"time": "30m", "score": 41},
                {"time": "Now", "score": 73},
            ],
            recommendation="ROLL BACK commit a3f9b2 NOW.",
            cost_of_rollback_minutes=8,
            cost_of_waiting_minutes=94
        ),
        tribal_knowledge=TribalKnowledge(
            pattern_matched="memory_drift",
            items=[
                TribalKnowledgeItem(
                    source="slack",
                    date="Nov 14, 2024",
                    author="Sarah Chen",
                    content="This memory pattern on payments means the connection pool is leaking. Restart payments-worker-2 before the main service.",
                    relevance_score=0.95,
                    author_still_at_company=False
                )
            ],
            key_insight="Restart payments-worker-2 before the main service to avoid checkout cascade failures."
        ),
        silent_incidents=[
            SilentIncident(
                service="recommendations-engine",
                duration_days=19,
                incident_type="Gradual performance degradation",
                evidence=[
                    "P99 latency: +340ms over 19 days",
                    "Recommendation click-through rate: -12%",
                    "Model inference time: +18%"
                ],
                estimated_revenue_impact_usd=47000,
                triggered_any_alert=False,
                root_cause_hypothesis="numpy version change altered embedding precision enough to degrade recommendation quality."
            )
        ],
        model_used="moonshotai/kimi-k2-instruct"
    )

    blast_radius = BlastRadius(
        origin_service="payments-api",
        affected_services=[
            BlastRadiusNode(
                service="checkout-service",
                failure_probability=0.70,
                historical_correlation=0.87,
                impact_type="direct_dependency"
            ),
            BlastRadiusNode(
                service="order-confirmation",
                failure_probability=0.81,
                historical_correlation=1.0,
                impact_type="full_dependency"
            ),
            BlastRadiusNode(
                service="inventory-service",
                failure_probability=0.54,
                historical_correlation=0.67,
                impact_type="orphaned_writes"
            ),
        ],
        customer_facing_features_at_risk=[
            "Checkout flow",
            "Subscription renewals",
            "Refund processing"
        ],
        data_integrity_risks=[
            "Inventory count corruption",
            "Duplicate charge risk"
        ],
        total_blast_score=89
    )

    fatigue = FatigueScore(
        engineer_name="Alex Chen",
        fatigue_score=87,
        fatigue_level="CRITICAL",
        alerts_last_6h=4,
        hours_since_last_sleep_window=19.2,
        consecutive_oncall_days=6,
        recommendation=(
            "CRITICAL fatigue level. Alex has been awake 19+ hours and responded to "
            "4 alerts tonight. Auto-page backup engineer Priya Sharma. "
            "Do NOT send this as a Slack message — call directly."
        ),
        alert_delivery_method="page_backup"
    )

    regret = RegretScore(
        deployment_id="payments-api-v2.4.1",
        deployment_time=datetime.now().strftime("%H:%M"),
        minutes_since_deploy=47,
        regret_score=73,
        regret_trajectory=[
            {"minutes": 0, "score": 12},
            {"minutes": 15, "score": 24},
            {"minutes": 30, "score": 41},
            {"minutes": 47, "score": 73},
        ],
        recommendation=(
            "ROLL BACK commit a3f9b2 NOW. "
            "Rollback cost: 8 minutes downtime. "
            "Cost of waiting: ~94 minutes incident (historical average). "
            "Regret score is rising — this pattern preceded rollback in 3 of 4 similar deploys."
        ),
        cost_of_rollback_minutes=8,
        cost_of_waiting_minutes=94
    )

    tribal = TribalKnowledge(
        pattern_matched="memory_drift",
        items=[
            TribalKnowledgeItem(
                source="slack",
                date="Nov 14, 2024",
                author="Sarah Chen",
                content=(
                    "this memory pattern on payments always means the connection pool is leaking. "
                    "restart payments-worker-2 BEFORE restarting the main service "
                    "or you get cascading failures into checkout"
                ),
                relevance_score=0.95,
                author_still_at_company=False
            ),
            TribalKnowledgeItem(
                source="postmortem",
                date="Dec 2, 2024",
                author="Incident Review Team",
                content=(
                    "Root cause: connection pool leak triggered by payment processor changes. "
                    "Resolution: manual restart of payments-worker-2 first. "
                    "Sarah's note was correct. This should be in the runbook."
                ),
                relevance_score=0.92,
                author_still_at_company=True
            )
        ],
        key_insight=(
            "Sarah Chen no longer works here. "
            "This knowledge would have been permanently lost without PreCog. "
            "The fix is: restart payments-worker-2 BEFORE the main service."
        )
    )

    silent = SilentIncident(
        service="recommendations-engine",
        duration_days=19,
        incident_type="Gradual performance degradation",
        evidence=[
            "P99 latency: +340ms over 19 days (2.3ms/day — never crossed 500ms threshold)",
            "Recommendation click-through rate: -12% (business metrics Splunk index)",
            "Model inference time: +18% (below +25% alert threshold)",
            "Correlated: numpy library upgrade 19 days ago"
        ],
        estimated_revenue_impact_usd=47000,
        triggered_any_alert=False,
        root_cause_hypothesis=(
            "numpy version change altered float precision in embedding calculations. "
            "Subtle enough to pass unit tests. Impactful enough to degrade recommendation quality."
        )
    )

    return FullPrediction(
        service=service,
        timestamp=datetime.now(),
        signals=signals,
        prediction=prediction,
        why_now=[
            {"time": "47m ago", "risk": 24, "trigger": "Deploy", "detail": "Payment tokenization v2.4.1 shipped."},
            {"time": "31m ago", "risk": 41, "trigger": "Memory drift", "detail": "Heap slope rose 8.1% without threshold breach."},
            {"time": "12m ago", "risk": 67, "trigger": "Team signal", "detail": "Slack concern about slow checkouts."},
            {"time": "Now", "risk": 81, "trigger": "Pattern match", "detail": "Matches last week's incident window."}
        ],
        blast_radius=blast_radius,
        fatigue=fatigue,
        regret=regret,
        tribal_knowledge=tribal,
        silent_incidents=[silent]
    )


def get_all_services_demo() -> list[dict]:
    """Dashboard overview — 3 green, 1 yellow, 1 silent incident"""
    return [
        {
            "service": "payments-api",
            "risk_level": "HIGH",
            "risk_score": 81,
            "traditional_alert_fired": False,
            "summary": "Deploy 47min ago + memory drift + same pattern as last week's incident"
        },
        {
            "service": "auth-service",
            "risk_level": "LOW",
            "risk_score": 12,
            "traditional_alert_fired": False,
            "summary": "All signals nominal"
        },
        {
            "service": "data-pipeline",
            "risk_level": "MEDIUM",
            "risk_score": 38,
            "traditional_alert_fired": False,
            "summary": "Slight lag increase — monitoring"
        },
        {
            "service": "user-service",
            "risk_level": "LOW",
            "risk_score": 8,
            "traditional_alert_fired": False,
            "summary": "All signals nominal"
        },
        {
            "service": "recommendations-engine",
            "risk_level": "SILENT",     # Special category — the wow moment
            "risk_score": 0,
            "traditional_alert_fired": False,
            "summary": "19-day silent incident detected. $47K revenue impact. Zero alerts fired."
        },
    ]
