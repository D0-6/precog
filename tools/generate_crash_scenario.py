"""
PreCog Demo: Realistic Crash Scenario Log Generator
====================================================
Generates log files that simulate a REAL service failure on March 15, 2025.

CRASH EVENT: payments-api goes down at 02:47:00 AM
CASCADE:      auth-service and user-service follow at 02:51:00 AM

TIMELINE:
  01:17 AM  [T-90min]  All INFO logs. No errors. Subtle signals begin.
                        → response_time slowly creeping up
                        → memory slowly climbing
                        → connection pool filling
                        ← PreCog FIRES HERE (before any human sees anything)

  02:02 AM  [T-45min]  First WARN logs appear.
                        ← Traditional monitoring still SILENT

  02:32 AM  [T-15min]  ERROR logs start flooding.
                        ← Traditional alert FIRES HERE (too late)

  02:47 AM  [T=0]      payments-api CRASHES.
  02:51 AM  [T+4min]   auth-service and user-service cascade.

HOW TO USE:
  1. Run this script: python generate_crash_scenario.py
  2. It creates logs/ folder with .log files
  3. Open Splunk → Add Data → Upload → select all .log files
  4. Set sourcetype = _json
  5. Open PreCog → watch it predict the crash from the early signals

"""

import json
import random
import math
from datetime import datetime, timedelta
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────────────────────
CRASH_TIME = datetime(2025, 3, 15, 2, 47, 0)   # payments-api crash
CASCADE_TIME = CRASH_TIME + timedelta(minutes=4) # auth + user cascade
START_TIME = CRASH_TIME - timedelta(minutes=90)  # start generating from T-90

OUTPUT_DIR = Path("logs")
OUTPUT_DIR.mkdir(exist_ok=True)

random.seed(42)  # reproducible

# ── Services ───────────────────────────────────────────────────────────────────
SERVICES = {
    "payments-api": {
        "port": 8080,
        "normal_response_ms": 45,
        "normal_memory_mb": 512,
        "normal_cpu_pct": 22,
        "normal_rps": 340,
        "db": "payments-db",
        "upstream": ["auth-service"],
        "is_victim": True,       # this service crashes
        "crash_at_minutes": 90,  # minutes from START_TIME
    },
    "auth-service": {
        "port": 8081,
        "normal_response_ms": 28,
        "normal_memory_mb": 256,
        "normal_cpu_pct": 15,
        "normal_rps": 890,
        "db": "auth-db",
        "upstream": [],
        "is_victim": False,
        "is_cascade": True,      # cascades when payments-api falls
        "cascade_at_minutes": 94,
    },
    "user-service": {
        "port": 8082,
        "normal_response_ms": 35,
        "normal_memory_mb": 384,
        "normal_cpu_pct": 18,
        "normal_rps": 520,
        "db": "user-db",
        "upstream": ["auth-service", "payments-api"],
        "is_victim": False,
        "is_cascade": True,
        "cascade_at_minutes": 95,
    },
    "data-pipeline": {
        "port": 8083,
        "normal_response_ms": 120,
        "normal_memory_mb": 768,
        "normal_cpu_pct": 35,
        "normal_rps": 90,
        "db": "analytics-db",
        "upstream": [],
        "is_victim": False,
        "is_cascade": False,
    },
    "recommendations-engine": {
        "port": 8084,
        "normal_response_ms": 180,
        "normal_memory_mb": 1024,
        "normal_cpu_pct": 45,
        "normal_rps": 210,
        "db": "recommendations-db",
        "upstream": ["user-service"],
        "is_victim": False,
        "is_cascade": False,
    },
}

# ── Realistic log message templates ────────────────────────────────────────────

# Phase 1 (T-90 to T-45): ALL INFO — subtle anomalies only visible in metrics
PHASE1_MESSAGES = {
    "payments-api": [
        "Payment authorization completed successfully",
        "Transaction processed: txn_id={txn}",
        "Database connection pool: {pool_used}/{pool_max} connections active",
        "Stripe webhook received and queued",
        "Cache hit ratio: {cache_hit}%",
        "Heartbeat OK — uptime {uptime}s",
        "Request processed in {rt}ms",
        "Scheduled job: fraud_score_update completed",
        "Memory usage: {mem}MB / 512MB",
        "GC minor collection: {gc}ms pause",
    ],
    "auth-service": [
        "JWT token issued for user_id={uid}",
        "Session validated successfully",
        "OAuth2 flow completed",
        "Token refresh successful",
        "Rate limit check passed",
        "Request processed in {rt}ms",
        "Active sessions: {sessions}",
    ],
    "user-service": [
        "User profile fetched: user_id={uid}",
        "Preferences updated successfully",
        "Request processed in {rt}ms",
        "Cache miss — fetching from DB",
        "Batch job: user_sync completed in {rt}ms",
    ],
    "data-pipeline": [
        "Batch processing: {batch} records completed",
        "ETL job: analytics_rollup finished",
        "Kafka consumer lag: {lag} messages",
        "Data validation passed",
    ],
    "recommendations-engine": [
        "Model inference completed in {rt}ms",
        "Recommendation set generated: {n} items",
        "Cache warmed for user_id={uid}",
        "Model version: v2.4.1 active",
    ],
}

# Phase 2 (T-45 to T-15): First WARNings appear
PHASE2_WARN_MESSAGES = {
    "payments-api": [
        "WARN: Database query exceeded threshold — {rt}ms (threshold: 200ms)",
        "WARN: Connection pool utilization high — {pool_used}/{pool_max} ({pct}%)",
        "WARN: Response time degraded for /v1/charge — avg {rt}ms",
        "WARN: Stripe API retry attempt {attempt}/3 — upstream latency",
        "WARN: Memory pressure detected — {mem}MB ({pct}% of limit)",
        "WARN: GC pause spike — {gc}ms (normal: <15ms)",
        "WARN: Thread pool queue depth elevated — {depth} pending",
    ],
    "auth-service": [
        "WARN: Upstream payments-api response slow — {rt}ms",
        "WARN: Token validation taking longer than expected",
        "WARN: Connection refused retried successfully on attempt {attempt}",
    ],
    "user-service": [
        "WARN: payments-api dependency slow — {rt}ms timeout approaching",
        "WARN: Increased retry rate on external calls",
    ],
}

# Phase 3 (T-15 to T-0): ERROR flood
PHASE3_ERROR_MESSAGES = {
    "payments-api": [
        "ERROR: Database connection timeout after {timeout}ms — retrying",
        "ERROR: OOM killer invoked — heap dump written to /tmp/heap_{ts}.hprof",
        "ERROR: Circuit breaker OPEN for payments-db",
        "ERROR: Transaction rollback — connection pool exhausted",
        "ERROR: Failed to acquire DB connection after {attempts} retries",
        "CRITICAL: Stripe webhook processing failed — queue backup: {queue} events",
        "ERROR: /v1/charge returning 503 — downstream unavailable",
        "ERROR: Memory limit exceeded — {mem}MB > 512MB limit",
        "CRITICAL: Health check FAILED — liveness probe timeout",
    ],
    "auth-service": [
        "ERROR: payments-api unreachable — ConnectionRefused",
        "WARN: Degraded mode active — payments validation bypassed",
    ],
    "user-service": [
        "ERROR: payments-api timeout on /v1/status — {timeout}ms",
        "ERROR: Dependency check failed for payments-api",
    ],
}

# Crash and cascade messages
CRASH_MESSAGES = {
    "payments-api": [
        "CRITICAL: Process killed by OOM — heap size {mem}MB exceeded container limit",
        "CRITICAL: Unhandled exception: java.lang.OutOfMemoryError: Java heap space",
        "CRITICAL: Service DOWN — health check failing for 3 consecutive intervals",
        "CRITICAL: Pod payments-api-7d9f4b-xkz2p terminated with exit code 137",
    ],
    "auth-service": [
        "CRITICAL: payments-api dependency UNAVAILABLE — failing fast",
        "ERROR: 100% of upstream requests to payments-api failing",
        "CRITICAL: Service entering degraded state — payments validation disabled",
    ],
    "user-service": [
        "CRITICAL: Multiple upstream dependencies DOWN (payments-api, auth-service)",
        "CRITICAL: Unable to process requests — dependency failures",
        "ERROR: Falling back to stale cache — data may be up to {stale}min old",
    ],
}


# ── Metric simulation ──────────────────────────────────────────────────────────

def get_metrics_for_service(service_name: str, svc: dict, minutes_from_start: float) -> dict:
    """
    Returns realistic metrics for a service at a given time offset.
    
    The key insight: metrics degrade GRADUALLY and SUBTLY in Phase 1.
    No errors. Just slow drift. Traditional monitoring misses this.
    PreCog detects it.
    """
    phase1_end = 45    # T-45min from start = when warnings begin
    phase2_end = 75    # T-15min from start = when errors begin
    crash_min  = 90    # T=0 from start = crash
    
    is_victim = svc.get("is_victim", False)
    is_cascade = svc.get("is_cascade", False)
    cascade_at = svc.get("cascade_at_minutes", 999)

    t = minutes_from_start

    # Base metrics
    base_rt   = svc["normal_response_ms"]
    base_mem  = svc["normal_memory_mb"]
    base_cpu  = svc["normal_cpu_pct"]
    base_rps  = svc["normal_rps"]
    pool_max  = 20   # defined here so all branches can reference it
    
    if is_victim:
        if t < phase1_end:
            # Phase 1: Subtle drift. All INFO. Traditional monitoring blind.
            # Memory leak: +1.2MB per minute (tiny but consistent)
            mem_leak = t * 1.2
            # Response time: slow creep, +0.8ms per minute
            rt_creep = t * 0.8
            # CPU: gradual climb due to GC pressure
            cpu_creep = t * 0.15
            # Connection pool fills as queries slow
            pool_used = int(8 + (t / phase1_end) * 7)  # 8 → 15 of 20
            pool_max  = 20
            
            jitter = random.uniform(0.9, 1.1)
            return {
                "response_ms":  round((base_rt + rt_creep) * jitter, 1),
                "memory_mb":    round(base_mem + mem_leak, 1),
                "cpu_pct":      round(min(95, base_cpu + cpu_creep) * jitter, 1),
                "rps":          round(base_rps * random.uniform(0.95, 1.05)),
                "pool_used":    pool_used,
                "pool_max":     pool_max,
                "error_rate":   0.0,       # NO ERRORS in phase 1
                "gc_ms":        round(8 + t * 0.1, 1),
                "cache_hit":    round(94 - t * 0.15, 1),
                "queue_depth":  int(t * 0.8),
                "phase":        1,
            }
            
        elif t < phase2_end:
            # Phase 2: Warnings start. Metrics visibly bad.
            progress = (t - phase1_end) / (phase2_end - phase1_end)
            mem_leak = phase1_end * 1.2 + (t - phase1_end) * 4  # accelerating
            rt_spike = base_rt + phase1_end * 0.8 + (t - phase1_end) * 8
            pool_used = int(15 + progress * 4)
            
            return {
                "response_ms":  round(rt_spike * random.uniform(0.85, 1.25), 1),
                "memory_mb":    round(base_mem + mem_leak, 1),
                "cpu_pct":      round(min(95, base_cpu + 30 + progress * 20) * random.uniform(0.9, 1.1), 1),
                "rps":          round(base_rps * (1 - progress * 0.3) * random.uniform(0.8, 1.0)),
                "pool_used":    pool_used,
                "pool_max":     pool_max,
                "error_rate":   round(progress * 0.08, 4),
                "gc_ms":        round(15 + progress * 80, 1),
                "cache_hit":    round(94 - phase1_end * 0.15 - progress * 20, 1),
                "queue_depth":  int(phase1_end * 0.8 + (t - phase1_end) * 3),
                "phase":        2,
            }
            
        elif t < crash_min:
            # Phase 3: Error storm. Service dying.
            progress = (t - phase2_end) / (crash_min - phase2_end)
            mem = base_mem + phase1_end * 1.2 + 30 * 4 + (t - phase2_end) * 15  # OOM approaching
            
            return {
                "response_ms":  round((base_rt + 500 + progress * 2000) * random.uniform(0.5, 2.0), 1),
                "memory_mb":    round(min(mem, 510), 1),  # approaching 512MB limit
                "cpu_pct":      round(min(99, 75 + progress * 24) * random.uniform(0.95, 1.0), 1),
                "rps":          round(base_rps * (1 - progress * 0.8) * random.uniform(0.5, 1.0)),
                "pool_used":    min(20, int(19 + progress)),
                "pool_max":     pool_max,
                "error_rate":   round(0.08 + progress * 0.7, 4),
                "gc_ms":        round(80 + progress * 400, 1),
                "cache_hit":    round(max(5, 60 - progress * 55), 1),
                "queue_depth":  int(50 + progress * 200),
                "phase":        3,
            }
        else:
            # CRASHED
            return {
                "response_ms":  0,
                "memory_mb":    0,
                "cpu_pct":      0,
                "rps":          0,
                "pool_used":    0,
                "pool_max":     pool_max,
                "error_rate":   1.0,
                "gc_ms":        0,
                "cache_hit":    0,
                "queue_depth":  0,
                "phase":        4,
            }
    
    elif is_cascade:
        # Cascade services: mostly normal until their cascade time
        if t < cascade_at:
            # Slight degradation as upstream slows
            upstream_stress = max(0, (t - 60) / 30) if t > 60 else 0
            return {
                "response_ms":  round(base_rt * (1 + upstream_stress * 0.5) * random.uniform(0.9, 1.1), 1),
                "memory_mb":    round(base_mem * random.uniform(0.95, 1.05), 1),
                "cpu_pct":      round(base_cpu * (1 + upstream_stress * 0.3) * random.uniform(0.9, 1.1), 1),
                "rps":          round(base_rps * random.uniform(0.95, 1.05)),
                "error_rate":   round(upstream_stress * 0.05, 4),
                "phase":        1 if t < phase1_end else (2 if t < phase2_end else 3),
            }
        else:
            # Cascaded — service is degraded/down
            return {
                "response_ms":  0,
                "memory_mb":    0,
                "cpu_pct":      0,
                "rps":          0,
                "error_rate":   1.0,
                "phase":        4,
            }
    else:
        # Healthy services — normal operation throughout
        return {
            "response_ms":  round(base_rt * random.uniform(0.9, 1.1), 1),
            "memory_mb":    round(base_mem * random.uniform(0.97, 1.03), 1),
            "cpu_pct":      round(base_cpu * random.uniform(0.9, 1.1), 1),
            "rps":          round(base_rps * random.uniform(0.95, 1.05)),
            "error_rate":   round(random.uniform(0, 0.002), 4),
            "phase":        0,
        }


def make_log_entry(timestamp: datetime, service: str, level: str, message: str,
                   metrics: dict, host_id: str) -> dict:
    """Create a JSON log entry in Splunk-friendly format."""
    txn = f"txn_{random.randint(100000, 999999)}"
    uid = f"user_{random.randint(10000, 99999)}"
    
    # Fill in template variables
    msg = message.format(
        txn=txn,
        uid=uid,
        rt=metrics.get("response_ms", 0),
        mem=metrics.get("memory_mb", 0),
        cpu=metrics.get("cpu_pct", 0),
        pool_used=metrics.get("pool_used", 0),
        pool_max=metrics.get("pool_max", 20),
        pct=round(metrics.get("pool_used", 0) / metrics.get("pool_max", 20) * 100) if metrics.get("pool_max") else 0,
        gc=metrics.get("gc_ms", 0),
        cache_hit=metrics.get("cache_hit", 95),
        uptime=random.randint(80000, 90000),
        sessions=random.randint(1200, 1800),
        batch=random.randint(5000, 15000),
        lag=random.randint(0, 50),
        n=random.randint(5, 20),
        attempt=random.randint(1, 3),
        depth=metrics.get("queue_depth", 0),
        timeout=random.randint(5000, 30000),
        attempts=random.randint(3, 5),
        queue=random.randint(100, 500),
        ts=timestamp.strftime("%Y%m%d_%H%M%S"),
        stale=random.randint(3, 15),
    )
    
    return {
        "timestamp":      timestamp.strftime("%Y-%m-%dT%H:%M:%S.") + f"{random.randint(0,999):03d}Z",
        "level":          level,
        "service":        service,
        "host":           host_id,
        "message":        msg,
        "response_ms":    metrics.get("response_ms", 0),
        "memory_mb":      metrics.get("memory_mb", 0),
        "cpu_pct":        metrics.get("cpu_pct", 0),
        "rps":            metrics.get("rps", 0),
        "error_rate":     metrics.get("error_rate", 0),
        "gc_pause_ms":    metrics.get("gc_ms", 0),
        "pool_used":      metrics.get("pool_used", 0),
        "pool_max":       metrics.get("pool_max", 20),
        "queue_depth":    metrics.get("queue_depth", 0),
        "cache_hit_pct":  metrics.get("cache_hit", 95),
        "phase":          metrics.get("phase", 0),
        "scenario":       "payments_crash_march_2025",
    }


def choose_message(service: str, metrics: dict) -> tuple[str, str]:
    """Choose appropriate log level and message based on current phase."""
    phase = metrics.get("phase", 0)
    
    if phase == 4:
        # Crashed / cascaded
        msgs = CRASH_MESSAGES.get(service, ["CRITICAL: Service unavailable"])
        return "CRITICAL", random.choice(msgs)
    
    elif phase == 3:
        # Error storm
        if service in PHASE3_ERROR_MESSAGES and random.random() < 0.7:
            msgs = PHASE3_ERROR_MESSAGES[service]
            return "ERROR", random.choice(msgs)
        elif service in PHASE1_MESSAGES:
            return "INFO", random.choice(PHASE1_MESSAGES[service])
        else:
            return "ERROR", "Service error — see metrics"
    
    elif phase == 2:
        # Warning phase
        if service in PHASE2_WARN_MESSAGES and random.random() < 0.5:
            msgs = PHASE2_WARN_MESSAGES[service]
            return "WARN", random.choice(msgs)
        elif service in PHASE1_MESSAGES:
            return "INFO", random.choice(PHASE1_MESSAGES[service])
        else:
            return "INFO", "Processing request"
    
    else:
        # Phase 0 or 1 — ALL INFO. Subtle metrics only.
        if service in PHASE1_MESSAGES:
            return "INFO", random.choice(PHASE1_MESSAGES[service])
        else:
            return "INFO", "Processing request"


# ── Main generator ─────────────────────────────────────────────────────────────

def generate_logs():
    print("=" * 60)
    print("PreCog Demo: Crash Scenario Log Generator")
    print("=" * 60)
    print(f"Crash time:    {CRASH_TIME}")
    print(f"Cascade time:  {CASCADE_TIME}")
    print(f"Start time:    {START_TIME}")
    print(f"Output folder: {OUTPUT_DIR.absolute()}")
    print()
    
    total_entries = 0
    
    for service_name, svc in SERVICES.items():
        host_id = f"{service_name}-pod-{random.randint(1, 3)}"
        entries = []
        
        # Generate one log entry every ~8-15 seconds over 100 minutes
        current_time = START_TIME
        end_time = CRASH_TIME + timedelta(minutes=15)
        
        while current_time < end_time:
            minutes_from_start = (current_time - START_TIME).total_seconds() / 60
            
            # Get metrics for this moment
            metrics = get_metrics_for_service(service_name, svc, minutes_from_start)
            
            # Determine how many log entries per interval (errors = more logs)
            phase = metrics.get("phase", 0)
            entries_this_tick = 1
            if phase == 2:
                entries_this_tick = random.randint(1, 3)
            elif phase == 3:
                entries_this_tick = random.randint(3, 8)
            elif phase == 4:
                entries_this_tick = random.randint(1, 4)
            
            for _ in range(entries_this_tick):
                tick_offset = timedelta(seconds=random.uniform(0, 12))
                ts = current_time + tick_offset
                
                level, message = choose_message(service_name, metrics)
                entry = make_log_entry(ts, service_name, level, message, metrics, host_id)
                entries.append(entry)
            
            # Advance time (faster logging = shorter intervals in error phases)
            if phase >= 3:
                interval = random.uniform(3, 8)
            elif phase == 2:
                interval = random.uniform(8, 15)
            else:
                interval = random.uniform(10, 20)
            
            current_time += timedelta(seconds=interval)
        
        # Write to file
        output_file = OUTPUT_DIR / f"{service_name}.log"
        with open(output_file, "w", encoding="utf-8") as f:
            for entry in sorted(entries, key=lambda x: x["timestamp"]):
                f.write(json.dumps(entry) + "\n")
        
        phase_counts = {}
        for e in entries:
            p = e.get("phase", 0)
            phase_counts[p] = phase_counts.get(p, 0) + 1
        
        print(f"  [OK] {service_name:<28} {len(entries):>5} log entries  ->  {output_file.name}")
        print(f"       Phase breakdown: {phase_counts}")
        total_entries += len(entries)
    
    print()
    print(f"Total log entries generated: {total_entries:,}")
    print()
    print("=" * 60)
    print("NEXT STEPS - How to load into Splunk:")
    print("=" * 60)
    print()
    print("1. Open Splunk Web -> Settings -> Add Data -> Upload")
    print()
    print("2. Upload all files from the logs/ folder:")
    for svc in SERVICES.keys():
        print(f"     logs/{svc}.log")
    print()
    print("3. On 'Set Source Type' screen:")
    print("     Source type = _json")
    print("     (Splunk will auto-parse JSON fields)")
    print()
    print("4. On 'Input Settings' screen:")
    print("     Index = main  (or create a new 'precog_demo' index)")
    print("     Host = leave as-is")
    print()
    print("5. Click 'Review' -> 'Submit'")
    print()
    print("6. Open PreCog dashboard — the services will appear")
    print("   and PreCog will show HIGH risk for payments-api")
    print("   BEFORE any WARN or ERROR logs appeared!")
    print()
    print("=" * 60)
    print("KEY DEMO TALKING POINT:")
    print("  PreCog detects the failure at T-90 minutes")
    print("  First WARNING log appears at T-45 minutes")
    print("  Traditional alert fires at T-15 minutes")
    print("  Crash happens at T=0")
    print()
    print("  PreCog gives you a 75-minute head start.")
    print("=" * 60)


if __name__ == "__main__":
    generate_logs()
