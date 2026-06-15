# engine/correlator.py
import json
import re
import asyncio
import logging
from openai import AsyncOpenAI
from config import NVIDIA_API_KEY, NVIDIA_BASE_URL, MODEL_CHAIN
from collectors.splunk_collector import get_runtime_config
from models.schemas import (
    AllSignals, Prediction, DynamicWidget, BlastRadius, BlastRadiusNode,
    FatigueScore, RegretScore, TribalKnowledge, TribalKnowledgeItem,
    SilentIncident
)

logger = logging.getLogger(__name__)

client = AsyncOpenAI(
    base_url=NVIDIA_BASE_URL,
    api_key=NVIDIA_API_KEY
)

# Limit concurrent AI calls to prevent 429 rate limiting (4 = good balance for NIM free tier)
_ai_semaphore = asyncio.Semaphore(4)

# Models that support chain-of-thought (thinking) mode
THINKING_MODELS = {
    "deepseek-ai/deepseek-v4-flash",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
    "google/gemma-4-31b-it",
}

SYSTEM_PROMPT = """You are PreCog, the world's most advanced pre-incident 
intelligence system. You analyze weak signals across multiple systems and 
predict incidents BEFORE they happen.

CRITICAL RULES:
1. You MUST respond in valid JSON only. No markdown. No explanation outside JSON.
2. Think about signals TOGETHER, not individually. One weak signal = noise. 
   Five weak signals converging = disaster incoming.
3. Be specific. Vague predictions are useless.
4. If traditional monitoring would catch this, say so honestly.
5. Your recommended_action must be ONE specific thing someone can do RIGHT NOW."""

def build_prompt(signals: AllSignals) -> str:
    return f"""
Analyze these weak signals for service: {signals.service_name}
Collected at: {signals.collected_at}

=== SPLUNK SIGNALS (Raw Datasets & Extracted Fields) ===
Fields discovered dynamically: {', '.join(signals.splunk.discovered_fields)}
Textual anomaly summary: {signals.splunk.anomaly_summary}
Sample logs:
{json.dumps(signals.splunk.sample_logs[:10], indent=2)}

=== GITHUB SIGNALS (last 4 hours) ===
Commits pushed: {signals.github.commit_count}
Risky files touched: {', '.join(signals.github.risky_files_touched) or 'none'}
Deploy-related commits: {', '.join(signals.github.deploy_related_commits) or 'none'}
Authors: {', '.join(signals.github.authors) or 'none'}
Lines changed: {signals.github.lines_changed}

=== JIRA SIGNALS (last 7 days) ===
Open bugs against this service: {signals.jira.open_bugs_total}
Bugs filed this week: {signals.jira.bugs_filed_this_week}
Maximum severity open bug: {signals.jira.max_severity}
Unresolved incidents: {signals.jira.unresolved_incidents}

=== SLACK SIGNALS (last 2 hours) ===
Deployment announcements: {signals.slack.deploy_messages or ['none']}
Team concern messages: {signals.slack.concern_messages or ['none']}
Times service was mentioned: {signals.slack.mention_count}

=== HISTORICAL CONTEXT ===
Last incident: {signals.history.last_incident_days_ago} days ago
Same time last week status: {signals.history.same_time_last_week_status}
Incident frequency this month: {signals.history.incident_frequency_30d}
Average resolution time: {signals.history.avg_resolution_minutes} minutes

=== YOUR TASK ===
Correlate ALL signals together. Your job is to act as the AI backend for a pre-incident intelligence dashboard.
You must infer the risk, the blast radius, engineering fatigue, deployment regret, and invent dynamic UI widgets based purely on the data you see above. 
If the Splunk logs show HDFS blocks failing, invent an HDFS widget. If they show API errors, invent an API widget.

Respond ONLY in this exact JSON format. DO NOT USE MARKDOWN.
{{
    "risk_score": <integer 0-100>,
    "confidence": <integer 0-100>,
    "risk_level": "<LOW|MEDIUM|HIGH|CRITICAL>",
    "explanation": "<3 sentences max, plain English any engineer understands>",
    "key_signals": ["<signal 1>", "<signal 2>", "<signal 3>"],
    "recommended_action": "<one specific action RIGHT NOW>",
    
    "dynamic_widgets": [
        {{
            "title": "<title of widget you invented based on Splunk data>",
            "type": "<list|metric|chart>",
            "data": <any JSON structure appropriate for the widget>
        }}
    ],
    
    "blast_radius": {{
        "origin_service": "{signals.service_name}",
        "affected_services": [
            {{ "service": "<downstream service>", "failure_probability": 0.85, "historical_correlation": 0.9, "impact_type": "cascading" }}
        ],
        "customer_facing_features_at_risk": ["feature1"],
        "data_integrity_risks": ["risk1"],
        "total_blast_score": <integer>
    }},
    
    "fatigue": {{
        "engineer_name": "Eng-Lead",
        "fatigue_score": <integer 0-100 based on github/jira/slack signals>,
        "fatigue_level": "<OK|ELEVATED|HIGH|CRITICAL>",
        "alerts_last_6h": 5,
        "hours_since_last_sleep_window": 14,
        "consecutive_oncall_days": 3,
        "recommendation": "<e.g. Bring in backup on-call>",
        "alert_delivery_method": "<slack|phone|page_backup>"
    }},
    
    "regret": {{
        "deployment_id": "deploy-latest",
        "deployment_time": "recent",
        "minutes_since_deploy": 25,
        "regret_score": <integer 0-100>,
        "regret_trajectory": [
            {{"time": "10m ago", "score": 20}},
            {{"time": "Now", "score": 60}}
        ],
        "recommendation": "<rollback|monitor|proceed>",
        "cost_of_rollback_minutes": 5,
        "cost_of_waiting_minutes": 120
    }},
    
    "tribal_knowledge": {{
        "pattern_matched": "Historical anomaly match",
        "items": [
            {{"source": "postmortem", "date": "2026-05-12", "author": "Eng-Lead", "content": "<invented insight>", "relevance_score": 0.95, "author_still_at_company": true}}
        ],
        "key_insight": "<summary of tribal knowledge>"
    }},
    
    "silent_incidents": [
        {{
            "service": "{signals.service_name}",
            "duration_days": 19,
            "incident_type": "Silent Degradation",
            "evidence": ["<evidence 1>"],
            "estimated_revenue_impact_usd": 1500000,
            "triggered_any_alert": false,
            "root_cause_hypothesis": "<hypothesis>"
        }}
    ]
}}
"""

async def _call_thinking_model(model: str, messages: list) -> str:
    """
    Call a thinking/reasoning model (like Nemotron Ultra) using streaming.
    Collects reasoning_content (chain-of-thought) separately from the final answer.
    Returns only the final content (the JSON answer).
    """
    reasoning_chunks = []
    content_chunks = []

    extra_body = {}
    if model == "deepseek-ai/deepseek-v4-flash":
        extra_body = {"chat_template_kwargs": {"thinking": True, "reasoning_effort": "high"}}
    elif model == "google/gemma-4-31b-it":
        extra_body = {"chat_template_kwargs": {"enable_thinking": True}}
    else:
        extra_body = {
            "chat_template_kwargs": {"enable_thinking": True},
            "reasoning_budget": 16384,
        }

    stream = await client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=1,          # Required for thinking models
        top_p=0.95,
        max_tokens=16384,
        extra_body=extra_body,
        stream=True,
        timeout=120,            # Thinking models need more time
    )

    async for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        reasoning = getattr(delta, "reasoning_content", None)
        if reasoning:
            reasoning_chunks.append(reasoning)
        if delta.content:
            content_chunks.append(delta.content)

    reasoning_text = "".join(reasoning_chunks)
    content_text = "".join(content_chunks)

    if reasoning_text:
        logger.info(f"[PreCog] 🧠 Nemotron thought for {len(reasoning_text)} chars before answering")

    return content_text.strip()


async def _call_standard_model(model: str, messages: list, max_t: int = 1024) -> str:
    """
    Call a standard (non-thinking) model synchronously.
    Returns the response content string.
    """
    response = await client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=max_t,
        temperature=0.0,
        timeout=120,
    )
    return response.choices[0].message.content.strip()


def _extract_json(raw: str) -> dict:
    """
    Extract a JSON object from the model response.
    Handles markdown fences, raw JSON, and trailing text.
    """
    # Try markdown fences first
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if match:
        return json.loads(match.group(1))
    # Try raw JSON object
    match = re.search(r"(\{.*\})", raw, re.DOTALL)
    if match:
        return json.loads(match.group(1))
    return json.loads(raw)


async def correlate(signals: AllSignals) -> Prediction:
    """
    Main correlation function.
    Tries each model in fallback chain.
    Thinking models (Nemotron Ultra) get streaming + CoT.
    Never crashes — returns safe default if all models fail.
    """
    last_error = "No models tried"
    prompt = build_prompt(signals)

    cfg = get_runtime_config()
    cfg_model = cfg.get("ai_model", "")
    primary_model = cfg_model or MODEL_CHAIN[0]
    runtime_chain = [primary_model] + [m for m in MODEL_CHAIN if m != primary_model]
    logger.info(f"[PreCog] Model selected: {primary_model} (from {'Settings UI' if cfg_model else 'default chain'}) for {signals.service_name}")

    speed = cfg.get("ai_response_speed", "balanced")
    if speed == "fast":
        max_t = 500
    elif speed == "comprehensive":
        max_t = 2000
    else:
        max_t = 1024

    async with _ai_semaphore:  # Max 2 concurrent NVIDIA API calls
        for model in runtime_chain:
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ]

            for attempt in range(2):
                raw_response = ""
                try:
                    is_thinking = model in THINKING_MODELS
                    logger.info(f"[PreCog] Calling {'🧠 thinking' if is_thinking else 'standard'} model: {model}")

                    if is_thinking:
                        raw_response = await _call_thinking_model(model, messages)
                    else:
                        raw_response = await _call_standard_model(model, messages, max_t)

                    data = _extract_json(raw_response)

                    # Normalize schema keys
                    data["would_traditional_alert_catch"] = data.get(
                        "would_traditional_alert_catch_this",
                        data.get("would_traditional_alert_catch", False)
                    )
                    data["model_used"] = model

                    result = Prediction.model_validate(data)
                    logger.info(f"[PreCog] ✅ Prediction: {result.risk_level} ({result.risk_score}/100) via {model}")
                    return result

                except Exception as e:
                    err_str = str(e)
                    last_error = f"Attempt {attempt + 1} on {model}: {err_str}"
                    logger.warning(f"[PreCog] {last_error}")

                    # Rate limit → back off and try next model
                    if "429" in err_str:
                        await asyncio.sleep(3)
                        break

                    # JSON parse failure → ask model to self-correct (non-thinking only)
                    if model not in THINKING_MODELS:
                        messages.append({"role": "assistant", "content": raw_response})
                        messages.append({
                            "role": "user",
                            "content": (
                                f"Your output was invalid JSON or missing fields. "
                                f"Error: {err_str}\n"
                                f"Please fix it and output STRICTLY the requested JSON format without markdown."
                            )
                        })
                        continue

                    break  # thinking models: don't retry with conversation history

    # All models failed — safe default so demo never crashes
    logger.error(f"[PreCog] All models failed. Last error: {last_error}")
    return Prediction(
        risk_score=35,
        confidence=35,
        risk_level="MEDIUM",
        explanation="AI correlation is temporarily unavailable, so PreCog is showing a conservative signal-only assessment.",
        key_signals=[
            f"{len(signals.splunk.sample_logs)} Splunk events available for review",
            signals.splunk.anomaly_summary or "No anomaly summary available",
            "NVIDIA model call failed or returned invalid JSON"
        ],
        recommended_action="Check Splunk telemetry manually and verify NVIDIA NIM connectivity before relying on AI scoring.",
        estimated_time_to_incident="N/A",
        would_traditional_alert_catch=False,
        dynamic_widgets=[
            DynamicWidget(
                title="Raw Signal Fallback",
                type="list",
                data={
                    "fields": signals.splunk.discovered_fields[:20],
                    "last_error": last_error
                }
            )
        ],
        blast_radius=BlastRadius(
            origin_service=signals.service_name,
            affected_services=[
                BlastRadiusNode(
                    service="unknown-downstream",
                    failure_probability=0.25,
                    historical_correlation=0.0,
                    impact_type="unverified"
                )
            ],
            customer_facing_features_at_risk=[],
            data_integrity_risks=[],
            total_blast_score=25
        ),
        fatigue=FatigueScore(
            engineer_name="On-Call Engineer",
            fatigue_score=30,
            fatigue_level="ELEVATED",
            alerts_last_6h=0,
            hours_since_last_sleep_window=8.0,
            consecutive_oncall_days=1,
            recommendation="Use standard escalation until PagerDuty/on-call context is connected.",
            alert_delivery_method="slack"
        ),
        regret=RegretScore(
            deployment_id="unknown",
            deployment_time="unknown",
            minutes_since_deploy=0,
            regret_score=20,
            regret_trajectory=[{"time": "Now", "score": 20}],
            recommendation="Monitor while validating AI and Splunk connectivity.",
            cost_of_rollback_minutes=0,
            cost_of_waiting_minutes=0
        ),
        tribal_knowledge=TribalKnowledge(
            pattern_matched="No verified historical pattern",
            items=[
                TribalKnowledgeItem(
                    source="system",
                    date="current",
                    author="PreCog",
                    content="No tribal knowledge was generated because AI correlation failed.",
                    relevance_score=0.0,
                    author_still_at_company=True
                )
            ],
            key_insight="Restore AI connectivity to unlock historical pattern matching."
        ),
        silent_incidents=[
            SilentIncident(
                service=signals.service_name,
                duration_days=0,
                incident_type="Unknown",
                evidence=["Silent incident analysis unavailable in AI fallback mode."],
                estimated_revenue_impact_usd=0,
                triggered_any_alert=False,
                root_cause_hypothesis="Insufficient correlated evidence."
            )
        ],
        model_used="none"
    )
