# main.py — PreCog Backend
# Architecture: Data-driven. Services are auto-discovered from Splunk.
# No service names are hardcoded. Whatever is in Splunk IS the monitored service set.

import asyncio
import time
import random
import logging
from datetime import datetime
from typing import List, Dict, Optional, Union

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address)

from config import DEMO_MODE
from collectors.splunk_collector import SplunkCollector, get_runtime_config, update_runtime_config
from collectors.all_collectors import GitHubCollector, JiraCollector, SlackCollector
from engine.correlator import correlate, client as openai_client, MODEL_CHAIN
from engine.features import (
    get_fatigue_score, get_regret_score,
    start_simulation, reset_simulation, get_simulation_risk_boost,
    estimate_incident_cost
)
from engine.extras import init_db, log_prediction, get_accuracy_stats, get_sparkline_data, format_slack_brief
from demo.synthetic_data import get_demo_scenario, get_all_services_demo
from models.schemas import (
    AllSignals, HistoricalContext, FullPrediction,
    BlastRadius, BlastRadiusNode, FatigueScore,
    RegretScore, TribalKnowledge, TribalKnowledgeItem, SilentIncident,
    Prediction as PredModel
)

app = FastAPI(
    title="PreCog — Pre-Incident Intelligence",
    description="Detect incidents before they happen.",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── Collectors ─────────────────────────────────────────────────────────────────
splunk = SplunkCollector()
github = GitHubCollector()
jira   = JiraCollector()
slack  = SlackCollector()

# ── In-memory caches ──────────────────────────────────────────────────────────
_llm_cache: Dict[str, dict] = {}           # LLM predictions (20s TTL per service)
_services_cache: Dict = {"services": [], "ts": 0.0}  # Auto-discovered services (60s TTL)

LLM_CACHE_TTL       = 20.0    # seconds — LLM result cache before re-calling AI
SVC_CACHE_TTL       = 60.0    # seconds — re-scan Splunk for new services every minute
PREDICTION_CACHE_TTL = 300.0  # seconds — full prediction cached for 5 minutes (separate from WS poll rate)


# ─────────────────────────────────────────────────────────────────────────────
# SERVICE AUTO-DISCOVERY
# Splunk is the single source of truth for what services exist.
# We run `| stats count by service` to find all unique service names.
# ─────────────────────────────────────────────────────────────────────────────

async def discover_services() -> List[str]:
    """
    Delegates to the adaptive SplunkCollector which uses the runtime-configured
    index and service_field — works with any judge's Splunk data automatically.
    """
    now = time.time()
    if _services_cache["services"] and (now - _services_cache["ts"]) < SVC_CACHE_TTL:
        return _services_cache["services"]

    try:
        services = await splunk.discover_services()
        if services:
            logger.info(f"[PreCog] Discovered {len(services)} services: {services}")
            _services_cache["services"] = services
            _services_cache["ts"] = now
            return services
    except Exception as e:
        logger.warning(f"[PreCog] Service discovery failed: {e}")

    return _services_cache.get("services", [])


# ─────────────────────────────────────────────────────────────────────────────
# CORE PREDICTION ENGINE
# ─────────────────────────────────────────────────────────────────────────────

_full_prediction_cache = {}

async def _calculate_prediction(service: str) -> FullPrediction:
    """
    Core prediction logic — collects all signals, runs AI correlation.
    Signal priority: 1) Splunk live  2) Uploaded file  3) Other collectors
    """
    if DEMO_MODE:
        full_pred = get_demo_scenario(service)
        _full_prediction_cache[service] = {"ts": time.time(), "pred": full_pred}
        log_prediction(service, full_pred.prediction.risk_score, full_pred.prediction.risk_level)
        return full_pred

    # 1. Collect real signals from all sources in parallel
    splunk_signals, github_signals, jira_signals, slack_signals = await asyncio.gather(
        splunk.collect_all(service),
        github.collect_all(service),
        jira.collect_all(service),
        slack.collect_all(service),
    )

    # 2. No fallback needed: Splunk is the single source of truth for metrics.

    # Historical context — derived from runtime config or Splunk data when available.
    # These are reasonable defaults; a future phase can query Splunk for real history.
    cfg_inner = get_runtime_config()
    history = HistoricalContext(
        last_incident_days_ago=cfg_inner.get("last_incident_days_ago", 19),
        same_time_last_week_status=cfg_inner.get("same_time_last_week_status", "NORMAL"),
        incident_frequency_30d=cfg_inner.get("incident_frequency_30d", 1),
        avg_resolution_minutes=cfg_inner.get("avg_resolution_minutes", 94)
    )

    signals = AllSignals(
        service_name=service,
        collected_at=datetime.now(),
        splunk=splunk_signals,
        github=github_signals,
        jira=jira_signals,
        slack=slack_signals,
        history=history
    )

    # 2. AI correlation — cached per service to avoid NVIDIA rate limits
    now = time.time()
    if service in _llm_cache and (now - _llm_cache[service]["ts"]) < LLM_CACHE_TTL:
        prediction = _llm_cache[service]["pred"]
    else:
        prediction = await correlate(signals)
        log_prediction(service, prediction.risk_score, prediction.risk_level)
        _llm_cache[service] = {"ts": now, "pred": prediction}

    # Simulation boost is now applied on-the-fly in predict_service, not cached here!

    # 4. Extract dynamic data from LLM prediction and signals
    # No more hardcoded mock data generation! The LLM returns it all inside `prediction`.
    blast = prediction.blast_radius
    fatigue = prediction.fatigue
    regret = prediction.regret
    tribal = prediction.tribal_knowledge
    silent = prediction.silent_incidents

    full_pred = FullPrediction(
        service=service,
        timestamp=datetime.now(),
        signals=signals,
        prediction=prediction,
        why_now=[
            {
                "time": "Now",
                "risk": prediction.risk_score,
                "trigger": "AI correlation",
                "detail": prediction.explanation[:180]
            }
        ],
        blast_radius=blast,
        fatigue=fatigue,
        regret=regret,
        tribal_knowledge=tribal,
        silent_incidents=silent
    )
    _full_prediction_cache[service] = {"ts": time.time(), "pred": full_pred}
    return full_pred

def apply_boost_to_prediction(fp: FullPrediction) -> FullPrediction:
    boost = get_simulation_risk_boost()
    if boost == 0:
        return fp
    
    new_fp = fp.model_copy(deep=True)
    boosted_score = min(100, new_fp.prediction.risk_score + boost)
    new_fp.prediction.risk_score = boosted_score
    new_fp.prediction.risk_level = "CRITICAL" if boosted_score >= 85 else "HIGH" if boosted_score >= 70 else "MEDIUM" if boosted_score >= 40 else "LOW"
    return new_fp

async def predict_service(service: str) -> FullPrediction:
    now = time.time()
    if service in _full_prediction_cache:
        age = now - _full_prediction_cache[service]["ts"]
        if age < PREDICTION_CACHE_TTL:   # Use dedicated 5-min TTL, not polling interval
            fp = _full_prediction_cache[service]["pred"]
            return apply_boost_to_prediction(fp)
    fp = await _calculate_prediction(service)
    return apply_boost_to_prediction(fp)


# ─────────────────────────────────────────────────────────────────────────────
# API ROUTES
# ─────────────────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup_event():
    init_db()
    asyncio.create_task(background_prediction_worker())

async def background_prediction_worker():
    logger.info("Starting background AI prediction worker...")
    while True:
        try:
            services = await discover_services()
            now = time.time()
            if services:
                # Only recompute services whose 5-min prediction cache has expired
                stale = [
                    svc for svc in services
                    if svc not in _full_prediction_cache
                    or (now - _full_prediction_cache[svc]["ts"]) >= PREDICTION_CACHE_TTL
                ]
                if stale:
                    logger.info(f"[PreCog] Refreshing {len(stale)} stale predictions in background...")
                    results = await asyncio.gather(
                        *[_calculate_prediction(svc) for svc in stale],
                        return_exceptions=True
                    )
                    for res in results:
                        if isinstance(res, Exception):
                            logger.error(f"Error predicting for service: {res}")
        except Exception as e:
            logger.error(f"Background worker loop error: {e}", exc_info=True)
        # Poll Splunk for new services every 30s; AI re-runs only when cache expires
        await asyncio.sleep(30)

@app.get("/")
async def root():
    services = await discover_services()
    return {
        "name": "PreCog",
        "tagline": "Detect incidents before they happen.",
        "status": "running",
        "demo_mode": DEMO_MODE,
        "monitored_services": services
    }


@app.get("/api/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


@app.get("/api/services")
async def get_services():
    """Returns the live list of services discovered from Splunk."""
    services = await discover_services()
    return {"services": services}


@app.get("/api/dashboard")
async def dashboard():
    """
    Main dashboard — all services auto-discovered from Splunk.
    Returns immediately so the frontend loads instantly. 
    Heavy AI correlation happens when a card is clicked.
    """
    services = await discover_services()
    if DEMO_MODE and not services:
        return {"services": get_all_services_demo(), "last_updated": datetime.now().isoformat()}
    if not services:
        return {"services": [], "last_updated": datetime.now().isoformat(),
                "message": f"No services found in Splunk. Feed data to see results."}

    out = []
    for service in services:
        if service in _full_prediction_cache:
            fp = apply_boost_to_prediction(_full_prediction_cache[service]["pred"])
            out.append({
                "service": service,
                "risk_level": fp.prediction.risk_level,
                "risk_score": fp.prediction.risk_score,
                "traditional_alert_fired": False,
                "summary": fp.prediction.explanation[:150]
            })
        else:
            out.append({
                "service": service,
                "risk_level": "UNKNOWN",
                "risk_score": 0,
                "traditional_alert_fired": False,
                "summary": "Analyzing in background..."
            })

    return {"services": out, "last_updated": datetime.now().isoformat()}


@app.get("/api/predict/{service}", response_model=FullPrediction)
@limiter.limit("15/minute")
async def predict_service_endpoint(request: Request, service: str):
    return await predict_service(service)


@app.get("/api/instant/{service}")
async def instant_summary(service: str):
    """
    INSTANT endpoint — returns cached result or a fast rule-based assessment.
    NEVER blocks on an LLM call. Response time: <200ms.
    Frontend calls this first for immediate display, then fetches /api/predict in background.
    """
    # Serve from cache if warm (most common case after startup)
    if service in _full_prediction_cache:
        fp = apply_boost_to_prediction(_full_prediction_cache[service]["pred"])
        p = fp.prediction
        return {
            "service": service,
            "from_cache": True,
            "risk_score": p.risk_score,
            "risk_level": p.risk_level,
            "confidence": p.confidence,
            "explanation": p.explanation,
            "key_signals": p.key_signals,
            "recommended_action": p.recommended_action,
            "would_traditional_alert_catch": p.would_traditional_alert_catch,
            "model_used": p.model_used,
            "blast_radius": fp.blast_radius,
            "fatigue": fp.fatigue,
            "regret": fp.regret,
            "tribal_knowledge": fp.tribal_knowledge,
            "silent_incidents": fp.silent_incidents,
            "why_now": fp.why_now,
            "dynamic_widgets": p.dynamic_widgets,
            "timestamp": fp.timestamp.isoformat(),
        }

    # Not cached — return fast rule-based assessment without any LLM call
    # Kick off full AI prediction in background so it's ready soon
    asyncio.create_task(_calculate_prediction(service))

    # Fast Splunk signal fetch (usually <2s)
    try:
        splunk_signals = await asyncio.wait_for(splunk.collect_all(service), timeout=3.0)
        n_logs = len(splunk_signals.sample_logs)
        fields = splunk_signals.discovered_fields
        anomaly = splunk_signals.anomaly_summary or ""
        has_errors = "ERROR" in anomaly.upper() or "error" in anomaly.lower()
        error_count = anomaly.lower().count("error") + anomaly.lower().count("exception")

        if has_errors and error_count >= 3:
            risk_score, risk_level = 72, "HIGH"
            explanation = f"Multiple error patterns detected in Splunk logs for {service}. {anomaly[:200]}"
            action = "Investigate the top error messages in Splunk and check recent deployments."
        elif has_errors:
            risk_score, risk_level = 48, "MEDIUM"
            explanation = f"Some error signals detected for {service}. {anomaly[:200]}"
            action = "Monitor closely and review error trends."
        elif n_logs > 0:
            risk_score, risk_level = 18, "LOW"
            explanation = f"{service} is generating telemetry ({n_logs} events sampled). No critical error patterns detected. Full AI analysis is computing in background."
            action = "Continue monitoring. AI correlation will complete shortly."
        else:
            risk_score, risk_level = 10, "LOW"
            explanation = f"No recent telemetry found for {service} in Splunk. Service may be idle or data may not be flowing."
            action = "Verify Splunk data pipeline for this service."

        key_signals = [s for s in [
            f"{n_logs} log events sampled" if n_logs else None,
            f"{len(fields)} fields discovered" if fields else None,
            anomaly[:100] if anomaly and anomaly != "No textual anomalies calculated." else None,
        ] if s]

        return {
            "service": service,
            "from_cache": False,
            "computing": True,   # tells frontend: full AI prediction is computing
            "risk_score": risk_score,
            "risk_level": risk_level,
            "confidence": 40,    # lower confidence for rule-based
            "explanation": explanation,
            "key_signals": key_signals or ["Telemetry analysis in progress"],
            "recommended_action": action,
            "would_traditional_alert_catch": False,
            "model_used": "rule-based-instant",
            "blast_radius": None,
            "fatigue": None,
            "regret": None,
            "tribal_knowledge": None,
            "silent_incidents": [],
            "why_now": [{"time": "Now", "risk": risk_score, "trigger": "Signal scan", "detail": explanation[:180]}],
            "dynamic_widgets": [],
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.warning(f"[Instant] Fast assessment failed for {service}: {e}")
        return {
            "service": service,
            "from_cache": False,
            "computing": True,
            "risk_score": 0,
            "risk_level": "UNKNOWN",
            "confidence": 0,
            "explanation": f"AI prediction is computing for {service}. Please wait a moment...",
            "key_signals": ["Full AI analysis is running in background"],
            "recommended_action": "Refresh in 30 seconds for full AI-powered analysis.",
            "would_traditional_alert_catch": False,
            "model_used": "pending",
            "blast_radius": None, "fatigue": None, "regret": None,
            "tribal_knowledge": None, "silent_incidents": [],
            "why_now": [], "dynamic_widgets": [],
            "timestamp": datetime.now().isoformat(),
        }


@app.post("/api/predict-background/{service}")
async def trigger_background_prediction(service: str):
    """Fire-and-forget: start AI prediction for a service without waiting."""
    if service not in _full_prediction_cache:
        asyncio.create_task(_calculate_prediction(service))
        return {"status": "computing", "service": service}
    return {"status": "cached", "service": service}



# ─────────────────────────────────────────────────────────────────────────────
# CHATBOT
# Context-aware — injects real Splunk prediction context into every message
# ─────────────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    service: str
    history: List[Dict] = []
    prediction_context: Optional[Union[Dict, List[Dict]]] = None  # Frontend passes current prediction


@app.post("/api/chat")
async def chat_bot(req: ChatRequest):
    """AI SRE chatbot — answers questions about whatever service is being monitored."""
    try:
        # Build rich context from the latest prediction for this service
        ctx = ""
        if req.prediction_context:
            contexts = req.prediction_context if isinstance(req.prediction_context, list) else [req.prediction_context]
            for p in contexts:
                svc_name = p.get('service', req.service).upper()
                ctx += f"""
CURRENT LIVE STATE FOR {svc_name}:
- Risk Score: {p.get('risk_score', 'N/A')}/100 ({p.get('risk_level', 'N/A')})
- AI Assessment: {p.get('explanation', 'N/A')}
- Key Signals: {', '.join(p.get('key_signals', []))}
- Recommended Action: {p.get('recommended_action', 'N/A')}
- Would traditional Splunk alert catch this? {p.get('would_traditional_alert_catch', 'Unknown')}
"""
        else:
            # Fall back to a fresh prediction
            try:
                pred = await predict_service(req.service)
                p = pred.prediction
                ctx = f"""
CURRENT LIVE STATE FOR {req.service.upper()}:
- Risk Score: {p.risk_score}/100 ({p.risk_level})
- AI Assessment: {p.explanation}
- Key Signals: {', '.join(p.key_signals)}
- Recommended Action: {p.recommended_action}
"""
            except Exception:
                ctx = f"Monitoring {req.service}. Live Splunk data is being ingested."

        system_msg = {
            "role": "system",
            "content": (
                f"You are PreCog, an expert AI SRE assistant. "
                f"You are analyzing the '{req.service}' service in real time using Splunk data.\n"
                f"{ctx}\n"
                f"Answer the engineer's question in under 4 sentences. "
                f"Be direct, technical, and actionable. Use Markdown formatting. "
                f"If risk is HIGH or CRITICAL, always recommend rolling back or escalating immediately."
            )
        }

        msgs = [system_msg]
        for m in req.history[-6:]:
            role = "assistant" if m.get("role") == "ai" else "user"
            msgs.append({"role": role, "content": m.get("text", "")})
        msgs.append({"role": "user", "content": req.message})

        # Chat uses smart local inference from live prediction data
        # This preserves NVIDIA API quota entirely for the prediction engine (the core AI feature)
        p = (req.prediction_context if isinstance(req.prediction_context, dict)
             else (req.prediction_context[0] if isinstance(req.prediction_context, list) and req.prediction_context else {}))

        # If no context passed, try to get from cache
        if not p and req.service in _full_prediction_cache:
            fp = _full_prediction_cache[req.service]["pred"]
            pred = fp.prediction
            p = {
                "risk_score": pred.risk_score,
                "risk_level": pred.risk_level,
                "explanation": pred.explanation,
                "key_signals": pred.key_signals,
                "recommended_action": pred.recommended_action,
                "confidence": pred.confidence,
            }

        risk = p.get("risk_score", 0)
        level = p.get("risk_level", "UNKNOWN")
        explanation = p.get("explanation", "")
        action = p.get("recommended_action", "Monitor closely and check Splunk for anomalies.")
        signals = p.get("key_signals", [])
        confidence = p.get("confidence", 0)
        svc = req.service
        q = req.message.lower()

        if any(w in q for w in ["what", "happening", "wrong", "status", "explain", "tell"]):
            reply = (f"**{svc}** is at **{risk}/100 risk** ({level}, {confidence}% confidence).\n\n"
                     f"{explanation[:250] if explanation else 'PreCog has detected weak signal convergence.'}\n\n"
                     f"**Key signals:** {', '.join(signals[:4]) if signals else 'Elevated error rate and latency spikes.'}")
        elif any(w in q for w in ["action", "do", "fix", "recommend", "should", "next", "how"]):
            reply = (f"**Recommended action:** {action}\n\n"
                     f"{'🔴 Act immediately — cascade failure imminent.' if risk > 70 else '🟠 Prepare rollback and alert on-call team.' if risk > 40 else '🟢 No immediate action needed — continue monitoring.'}")
        elif any(w in q for w in ["risk", "score", "danger", "critical", "high", "level"]):
            emoji = "🔴" if risk > 70 else "🟠" if risk > 40 else "🟡" if risk > 20 else "🟢"
            reply = (f"{emoji} **{svc}** risk: **{risk}/100** ({level})\n\n"
                     f"Confidence: {confidence}%. "
                     f"{'Immediate action required.' if risk > 70 else 'Monitor and prepare response plan.' if risk > 40 else 'System is stable.'}")
        elif any(w in q for w in ["signal", "log", "splunk", "data", "evidence"]):
            sig_list = "\n".join([f"- {s}" for s in signals[:5]]) if signals else "- No critical signals yet"
            reply = f"**Live signals from Splunk for {svc}:**\n{sig_list}\n\nRisk: **{risk}/100** ({level})"
        else:
            reply = (f"**{svc}** — Risk: **{risk}/100** ({level})\n\n"
                     f"{explanation[:200] if explanation else 'PreCog is analyzing live Splunk telemetry in real time.'}\n\n"
                     f"**Action:** {action}")

        return {"reply": reply}
    except Exception as e:
        logger.error(f"Chat error: {e}")
        return {"reply": f"⚠️ Error analyzing {req.service}. Check Splunk directly."}


# ─────────────────────────────────────────────────────────────────────────────
# DEMO / SIMULATION ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/demo/trigger_incident")
async def trigger_incident():
    """
    Starts the simulation — risk score rises gradually over 120s.
    This lets you demo PreCog catching a rising incident in real time.
    """
    start_simulation()
    return {"status": "simulation_started", "message": "Risk score will rise over the next 2 minutes. Watch the dashboard."}


@app.post("/api/demo/reset")
async def reset_demo():
    """Resets simulation and clears all caches."""
    reset_simulation()
    _services_cache["services"] = []
    _services_cache["ts"] = 0.0
    return {"status": "reset", "message": "Simulation cleared. Splunk data will be re-fetched."}


@app.get("/api/demo/dashboard")
async def demo_dashboard():
    return {"services": get_all_services_demo(), "last_updated": datetime.now().isoformat()}


# ─────────────────────────────────────────────────────────────────────────────
# JUDGE / CUSTOM SPLUNK CONFIGURATION
# Judges enter their own Splunk URL + token + field mappings via Settings UI.
# PreCog adapts every query automatically — zero code changes needed.
# ─────────────────────────────────────────────────────────────────────────────



class SplunkConfigRequest(BaseModel):
    url:               Optional[str] = None
    token:             Optional[str] = None
    index:             Optional[str] = None
    ai_response_speed: Optional[str] = None
    ai_model:          Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# EXTRAS (Stats, Sparklines, Slack)
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/stats/accuracy")
async def get_accuracy():
    return get_accuracy_stats()

@app.get("/api/stats/sparkline/{service}")
async def get_sparkline(service: str):
    return {"sparkline": get_sparkline_data(service)}

@app.get("/api/slack/brief/{service}")
async def get_slack_brief(service: str):
    if service in _full_prediction_cache:
        fp = _full_prediction_cache[service]["pred"]
        return {"markdown": format_slack_brief(fp)}
    return {"markdown": "Service prediction not found yet. Try again in a few seconds."}




# ── Industry benchmark endpoints ────────────────────────────────────────────

@app.get("/api/benchmarks/{service}")
async def service_benchmarks(service: str, mttr: int = 94):
    return get_service_benchmark(service, your_mttr=mttr)

@app.get("/api/benchmarks")
async def all_benchmarks():
    return get_all_benchmarks()

@app.get("/api/config")
async def get_config():
    """Returns the current Splunk connection configuration (token masked)."""
    cfg = get_runtime_config()
    if cfg.get("token"):
        t = cfg["token"]
        cfg["token_masked"] = t[:8] + "..." + t[-4:] if len(t) > 12 else "****"
        del cfg["token"]
    return cfg


@app.post("/api/configure")
async def configure_splunk(req: SplunkConfigRequest):
    """
    Update Splunk connection at runtime — judges paste their own URL + token.
    All caches clear so next poll uses the new config immediately.
    """
    updates = {k: v for k, v in req.dict().items() if v is not None and v != ""}
    update_runtime_config(updates)
    _llm_cache.clear()
    _full_prediction_cache.clear()
    _services_cache["services"] = []
    _services_cache["ts"] = 0.0
    logger.info(f"[Configure] Updated: {list(updates.keys())}")
    return {
        "status": "updated",
        "message": "Configuration saved. Dashboard will reload with your data.",
        "updated_fields": list(updates.keys())
    }


@app.post("/api/connect-test")
async def test_connection():
    """Test the current Splunk connection. Returns health + event count."""
    return await splunk.test_connection()


@app.get("/api/introspect")
async def introspect_splunk(index: Optional[str] = None):
    """
    Auto-discovers structure of the Splunk data:
    all field names, service identifiers, metric fields, and unique services.
    Judges use this to understand their data without writing SPL.
    """
    cfg = get_runtime_config()
    target_index = index or cfg.get("index", "main")

    fields_data, services, indexes = await asyncio.gather(
        splunk.discover_fields(target_index),
        splunk.discover_services(),
        splunk.discover_indexes(),
        return_exceptions=True
    )

    return {
        "index": target_index,
        "available_indexes": indexes if not isinstance(indexes, Exception) else [],
        "discovered_services": services if not isinstance(services, Exception) else [],
        "fields": fields_data if not isinstance(fields_data, Exception) else {},
        "current_config": {
            k: cfg.get(k) for k in
            ["service_field","cpu_field","mem_field","error_rate_field","level_field","message_field"]
        },
        "hint": "Use POST /api/configure to apply suggested field mappings."
    }





@app.get("/api/demo/scenario/{service}")
async def demo_scenario(service: str):
    return await predict_service(service)



@app.get("/api/demo/logs")
async def demo_logs():
    """Stream real Splunk log entries using adaptive field config."""
    try:
        cfg = get_runtime_config()
        idx = cfg.get("index", "main")
        svc_f = cfg.get("service_field", "service")
        lvl_f = cfg.get("level_field", "level")
        msg_f = cfg.get("message_field", "message")
        fields = " ".join(filter(None, ["_time", svc_f, lvl_f, msg_f]))
        spl = f"index={idx} | sort -_time | head 8 | table {fields}"
        data = await splunk.run_query(spl)
        results = data.get("results", [])

        logs = []
        for row in results:
            ts = row.get("_time", "")
            if "T" in ts:
                ts = ts.split("T")[1][:8]
            logs.append({
                "id": random.randint(1000, 9999),
                "timestamp": ts or datetime.now().strftime("%H:%M:%S"),
                "source": row.get("service", "splunk"),
                "level": row.get("level", "INFO"),
                "message": row.get("message", "Telemetry received")
            })

        if not logs:
            logs = [{
                "id": 0,
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "source": "system",
                "level": "INFO",
                "message": "Waiting for Splunk data..."
            }]
        return {"logs": logs}

    except Exception as e:
        return {"logs": [{
            "id": 0,
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "source": "system",
            "level": "ERROR",
            "message": f"Log fetch error: {e}"
        }]}


# ─────────────────────────────────────────────────────────────────────────────
# SUPPORTING ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

from engine.extras import (
    get_accuracy_stats, get_sparkline_data,
    format_slack_brief, log_prediction, init_db
)
from engine.benchmarks import get_all_benchmarks, get_service_benchmark



@app.get("/api/accuracy")
async def accuracy():
    return get_accuracy_stats()


@app.get("/api/sparkline/{service}")
async def sparkline(service: str):
    return {"service": service, "history": get_sparkline_data(service)}


@app.get("/api/sparklines")
async def all_sparklines():
    services = await discover_services()
    if DEMO_MODE and not services:
        services = [svc["service"] for svc in get_all_services_demo()]
    return {svc: get_sparkline_data(svc) for svc in services}


@app.get("/api/brief/{service}")
async def incident_brief(service: str):
    prediction = await predict_service(service)
    return {"brief": format_slack_brief(prediction), "service": service}


@app.get("/api/cost/{service}")
async def cost_estimate(service: str, risk_score: int = 50):
    total = estimate_incident_cost(risk_score)
    revenue = int(total * 0.78)
    engineering = max(0, total - revenue)
    return {
        "service": service,
        "risk_score": risk_score,
        "total_cost_usd": total,
        "revenue_at_risk_usd": revenue,
        "engineering_cost_usd": engineering,
        "customers_affected": 0 if total == 0 else max(120, risk_score * 37),
        "downtime_minutes_estimate": 0 if total == 0 else max(8, int(risk_score * 1.2)),
        "precog_estimated_saving_usd": int(total * 0.82)
    }




# ─────────────────────────────────────────────────────────────────────────────
# WEBSOCKET — Live Dashboard
# ─────────────────────────────────────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self.active: list = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, data: dict):
        dead = []
        for ws in self.active:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

manager = ConnectionManager()


@app.websocket("/ws/dashboard")
async def websocket_dashboard(websocket: WebSocket):
    """
    Real-time WebSocket feed — auto-discovers services from Splunk.
    Broadcasts lightweight status updates without triggering massive AI correlation.
    """
    await manager.connect(websocket)
    try:
        while True:
            services = await discover_services()
            if not services:
                await websocket.send_json({
                    "services": [],
                    "timestamp": datetime.now().isoformat(),
                    "type": "dashboard_update",
                    "message": "Waiting for data in Splunk"
                })
            else:
                out = []
                for svc in services:
                    if svc in _full_prediction_cache:
                        fp = apply_boost_to_prediction(_full_prediction_cache[svc]["pred"])
                        out.append({
                            "service": svc,
                            "risk_level": fp.prediction.risk_level,
                            "risk_score": fp.prediction.risk_score,
                            "traditional_alert_fired": False,
                            "summary": fp.prediction.explanation[:150]
                        })
                    else:
                        out.append({
                            "service": svc,
                            "risk_level": "UNKNOWN",
                            "risk_score": 0,
                            "traditional_alert_fired": False,
                            "summary": "Analyzing in background..."
                        })
                await websocket.send_json({
                    "services": out,
                    "timestamp": datetime.now().isoformat(),
                    "type": "dashboard_update"
                })
            await asyncio.sleep(get_runtime_config().get('mcp_polling_interval', 2))
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
        manager.disconnect(websocket)
