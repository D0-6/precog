#!/usr/bin/env python
"""
precog_script_input.py — PreCog Demo Data Generator (Splunk Scripted Input)

HOW TO INSTALL IN SPLUNK:
  Settings → Data Inputs → Scripts → New Local Script
  Command : $SPLUNK_HOME/bin/python $SPLUNK_HOME/etc/apps/<your-app>/bin/precog_script_input.py
  Interval : 60  (run every 60 seconds)
  Source type: _json
  Index: history  (or whatever index your PreCog backend queries)

  Then copy THIS FILE to:
    Windows: C:\Program Files\Splunk\etc\apps\<your-app>\bin\precog_script_input.py
    Linux:   /opt/splunk/etc/apps/<your-app>/bin/precog_script_input.py

HOW IT WORKS:
  Splunk runs this script every <interval> seconds.
  Whatever this script prints to stdout → Splunk ingests as events.
  No HEC token, no network calls, no SSL errors.
"""

import json
import random
import time
import sys
import os
from datetime import datetime, timezone

# ── SERVICES ──────────────────────────────────────────────────────────────────
SERVICES = {
    "payments-api":         {"base_rt": 45,  "base_mem": 512, "base_cpu": 12},
    "auth-service":         {"base_rt": 18,  "base_mem": 256, "base_cpu": 8},
    "user-service":         {"base_rt": 22,  "base_mem": 384, "base_cpu": 10},
    "data-pipeline":        {"base_rt": 180, "base_mem": 768, "base_cpu": 35},
    "recommendations-engine":{"base_rt": 95, "base_mem": 1024,"base_cpu": 45},
}

# ── MESSAGE TEMPLATES ─────────────────────────────────────────────────────────
INFO_MSGS = {
    "payments-api": [
        "Payment authorization completed successfully | txn_id=TXN{n}",
        "Transaction processed OK | amount=${amt}.00 | txn_id=TXN{n}",
        "DB connection pool: {pool}/20 active | response_ms={rt}",
        "Heartbeat OK | uptime={up}s | memory={mem}MB",
        "Cache hit | ratio={cache}% | response_ms={rt}",
    ],
    "auth-service": [
        "JWT issued | user_id=USR{n} | response_ms={rt}",
        "Session validated | active_sessions={sess}",
        "OAuth2 flow complete | response_ms={rt}",
        "Token refresh OK | response_ms={rt}",
    ],
    "user-service": [
        "Profile fetched | user_id=USR{n} | response_ms={rt}",
        "Preferences updated | response_ms={rt}",
        "Batch sync completed | records={batch} | response_ms={rt}",
    ],
    "data-pipeline": [
        "ETL batch complete | records={batch} | elapsed_ms={rt}",
        "Kafka consumer lag: {lag} messages",
        "Analytics rollup finished | response_ms={rt}",
    ],
    "recommendations-engine": [
        "Model inference OK | user_id=USR{n} | response_ms={rt}",
        "Feature vector computed | response_ms={rt}",
        "Recommendation batch served | count={batch} | response_ms={rt}",
    ],
}

WARN_MSGS = {
    "payments-api":         ["High DB pool usage: {pool}/20 connections", "Payment latency spike: {rt}ms > threshold"],
    "auth-service":         ["Token cache miss rate elevated: {cache}%", "Session store latency: {rt}ms"],
    "user-service":         ["Slow profile fetch: {rt}ms | user_id=USR{n}", "DB replica lag detected: {lag}ms"],
    "data-pipeline":        ["Kafka consumer lag rising: {lag} messages", "ETL job delayed: {rt}ms"],
    "recommendations-engine":["Model latency high: {rt}ms", "Feature cache miss: {cache}%"],
}

ERROR_MSGS = {
    "payments-api":         ["Payment gateway timeout: {rt}ms | txn_id=TXN{n}", "DB connection refused | pool exhausted"],
    "auth-service":         ["JWT validation failed | user_id=USR{n}", "Auth service unresponsive: {rt}ms"],
    "user-service":         ["Profile service ERROR: connection pool exhausted", "DB write failed: timeout after {rt}ms"],
    "data-pipeline":        ["Pipeline FAILURE: upstream timeout | {rt}ms", "Kafka partition unavailable"],
    "recommendations-engine":["Model inference FAILED: OOM | memory={mem}MB", "Feature store connection lost"],
}

CRASH_MSGS = {
    "payments-api":         ["CRITICAL: payments-api is DOWN | all connections refused", "FATAL: DB connection pool exhausted | txn_id=TXN{n} FAILED"],
    "auth-service":         ["CRITICAL: auth-service unavailable | all requests failing", "FATAL: session store unreachable"],
    "user-service":         ["CRITICAL: user-service crashed | OOM killer invoked", "FATAL: profile DB unreachable"],
    "data-pipeline":        ["CRITICAL: pipeline halted | data loss possible", "FATAL: Kafka cluster unreachable"],
    "recommendations-engine":["CRITICAL: recommendation engine DOWN | model OOM", "FATAL: feature store connection pool exhausted"],
}


def get_phase_from_state_file():
    """
    Read a phase state file if it exists — lets you control the demo phase
    by writing a file: echo crash > C:\\Temp\\precog_phase.txt
    Phases: normal, warn, error, crash
    """
    phase_file = os.path.join(os.environ.get("TEMP", "/tmp"), "precog_phase.txt")
    try:
        if os.path.exists(phase_file):
            phase = open(phase_file).read().strip().lower()
            if phase in ("normal", "warn", "error", "crash"):
                return phase
    except Exception:
        pass
    return "normal"  # default: healthy services


def make_event(service, phase):
    svc = SERVICES[service]
    rng = random.Random()

    # Metrics vary by phase
    if phase == "normal":
        rt      = rng.randint(svc["base_rt"] - 10, svc["base_rt"] + 20)
        mem     = rng.randint(svc["base_mem"] - 50, svc["base_mem"] + 80)
        cpu     = rng.randint(svc["base_cpu"] - 3, svc["base_cpu"] + 5)
        err_rate= round(rng.uniform(0.0, 0.3), 2)
        pool    = rng.randint(3, 8)
        cache   = rng.randint(88, 98)
        level   = "INFO"
        pool_msgs = INFO_MSGS.get(service, ["OK | response_ms={rt}"])
        msg_template = rng.choice(pool_msgs)
    elif phase == "warn":
        rt      = rng.randint(svc["base_rt"] * 2, svc["base_rt"] * 4)
        mem     = rng.randint(svc["base_mem"] + 100, svc["base_mem"] + 300)
        cpu     = rng.randint(svc["base_cpu"] * 2, svc["base_cpu"] * 3)
        err_rate= round(rng.uniform(2.0, 8.0), 2)
        pool    = rng.randint(14, 18)
        cache   = rng.randint(60, 80)
        level   = "WARN" if rng.random() < 0.6 else "INFO"
        pool_msgs = WARN_MSGS.get(service, INFO_MSGS.get(service, ["WARN | response_ms={rt}"]))
        msg_template = rng.choice(pool_msgs)
    elif phase == "error":
        rt      = rng.randint(svc["base_rt"] * 5, svc["base_rt"] * 10)
        mem     = rng.randint(svc["base_mem"] + 400, svc["base_mem"] + 700)
        cpu     = min(98, rng.randint(svc["base_cpu"] * 4, svc["base_cpu"] * 6))
        err_rate= round(rng.uniform(15.0, 40.0), 2)
        pool    = rng.randint(18, 20)
        cache   = rng.randint(20, 50)
        level   = "ERROR" if rng.random() < 0.7 else "WARN"
        pool_msgs = ERROR_MSGS.get(service, WARN_MSGS.get(service, ["ERROR | response_ms={rt}"]))
        msg_template = rng.choice(pool_msgs)
    else:  # crash
        rt      = rng.randint(30000, 60000)
        mem     = svc["base_mem"] * 3
        cpu     = rng.randint(95, 100)
        err_rate= round(rng.uniform(80.0, 100.0), 2)
        pool    = 20
        cache   = 0
        level   = "CRITICAL"
        pool_msgs = CRASH_MSGS.get(service, ["CRITICAL: Service DOWN"])
        msg_template = rng.choice(pool_msgs)

    fmt = dict(
        n=rng.randint(100000, 999999), amt=rng.randint(10, 9999),
        rt=rt, mem=mem, cpu=cpu, pool=pool, cache=cache,
        up=rng.randint(80000, 90000), sess=rng.randint(1200, 1800),
        batch=rng.randint(5000, 20000), lag=rng.randint(0, 500),
    )
    message = msg_template.format(**fmt)

    now = datetime.now(timezone.utc)
    return {
        "timestamp":    now.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "level":        level,
        "service":      service,
        "Component":    service,
        "message":      message,
        "response_ms":  rt,
        "memory_mb":    mem,
        "cpu_pct":      cpu,
        "error_rate":   err_rate,
        "pool_used":    pool,
        "cache_hit_pct":cache,
        "demo":         "precog_scripted_input",
        "phase":        phase,
    }


def main():
    phase = get_phase_from_state_file()

    events_per_service = 3 if phase == "normal" else (5 if phase == "warn" else 8)

    for service in SERVICES:
        for _ in range(events_per_service):
            event = make_event(service, phase)
            # Print JSON — Splunk ingests each line as one event
            print(json.dumps(event))
            sys.stdout.flush()


if __name__ == "__main__":
    main()
