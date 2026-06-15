"""
PreCog Live Demo Streamer
=========================
Streams realistic logs LIVE to Splunk via HTTP Event Collector (HEC).
Compresses the 90-minute crash scenario into 3 minutes of real time.

HOW IT WORKS:
  Every 3 real seconds = 3 scenario minutes of logs sent to Splunk.
  PreCog polls Splunk every 30s and updates the dashboard live.
  You watch payments-api go LOW -> MEDIUM -> HIGH -> CRITICAL on screen.

SETUP (one time):
  1. Enable HEC in Splunk:
       Splunk Web -> Settings -> Data Inputs -> HTTP Event Collector
       Click "Global Settings" -> Enable SSL (or disable) -> Save
       Click "New Token" -> Name: precog_demo -> Next -> Next -> Submit
       Copy the TOKEN shown

  2. Edit the CONFIG section below with your Splunk host + HEC token

  3. Run:  python live_demo_streamer.py

TIMELINE (compressed to 3 real minutes):
  Real 0:00  -> Scenario T-90min  -> payments-api: ALL INFO, subtle signals
  Real 0:45  -> Scenario T-45min  -> WARN logs start appearing
  Real 1:30  -> Scenario T-15min  -> ERROR flood begins
  Real 2:00  -> Scenario T=0      -> payments-api CRASH
  Real 2:15  -> Cascade           -> auth-service + user-service fall
  Real 3:00  -> END

Watch PreCog dashboard: risk score climbs in real time!
"""

from pickle import FALSE
import json
import time
import random
import httpx
import sys
from datetime import datetime

# ══════════════════════════════════════════════════════════════════════
# CONFIG — edit these before running
# ══════════════════════════════════════════════════════════════════════
SPLUNK_HOST  = "host"                      # Splunk host
HEC_PORT     = 8088                        # HEC port
HEC_TOKEN    = "addf9d7d-501d-4534-aaf2-8b56ff1eaae0"
HEC_INDEX    = "history"                   # Index to stream into
VERIFY_SSL   = False                       # SSL verify

# Demo timing — total crash scenario compressed into DEMO_DURATION_SECONDS
DEMO_DURATION_SECONDS = 180   # 3 minutes total (adjust for your video length)
BATCH_INTERVAL = 3            # Send a new batch every N real seconds
# ══════════════════════════════════════════════════════════════════════

# Splunk HEC URL
HEC_URL = f"https://{SPLUNK_HOST}:{HEC_PORT}/services/collector/event"

# Scenario phases (as fraction of total demo duration)
PHASE_BOUNDARIES = {
    "normal":  (0.00, 0.50),   # 0-50% = T-90 to T-45min: ALL INFO, subtle drift
    "warning": (0.50, 0.75),   # 50-75% = T-45 to T-15min: WARN logs appear
    "error":   (0.75, 0.90),   # 75-90% = T-15 to T-0: ERROR flood
    "crash":   (0.90, 1.00),   # 90-100% = T=0: CRASH + cascade
}

random.seed(int(time.time()))

# ── Service definitions ────────────────────────────────────────────────────────
SERVICES = {
    "payments-api": {
        "is_victim":   True,
        "base_rt":     45,
        "base_mem":    512,
        "base_cpu":    22,
        "base_rps":    340,
        "cascade_at":  0.92,   # fraction when cascade hits this service
    },
    "auth-service": {
        "is_victim":   False,
        "is_cascade":  True,
        "base_rt":     28,
        "base_mem":    256,
        "base_cpu":    15,
        "base_rps":    890,
        "cascade_at":  0.94,
    },
    "user-service": {
        "is_victim":   False,
        "is_cascade":  True,
        "base_rt":     35,
        "base_mem":    384,
        "base_cpu":    18,
        "base_rps":    520,
        "cascade_at":  0.96,
    },
    "data-pipeline": {
        "is_victim":   False,
        "is_cascade":  False,
        "base_rt":     120,
        "base_mem":    768,
        "base_cpu":    35,
        "base_rps":    90,
    },
    "recommendations-engine": {
        "is_victim":   False,
        "is_cascade":  False,
        "base_rt":     180,
        "base_mem":    1024,
        "base_cpu":    45,
        "base_rps":    210,
    },
}

# ── Message templates ──────────────────────────────────────────────────────────
INFO_MSGS = {
    "payments-api": [
        "Payment authorization completed successfully | txn_id=TXN{n}",
        "Transaction processed OK | amount=${amt}.00 | txn_id=TXN{n}",
        "DB connection pool: {pool}/20 active | response_ms={rt}",
        "Heartbeat OK | uptime={up}s | memory={mem}MB",
        "Cache hit | ratio={cache}% | response_ms={rt}",
        "GC minor collection completed | pause_ms={gc} | heap={mem}MB",
        "Stripe webhook queued | event=charge.succeeded",
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
        "Model inference OK | items={n} | response_ms={rt}",
        "Cache warmed | user_id=USR{uid}",
        "Recommendation set generated | response_ms={rt}",
    ],
}

WARN_MSGS = {
    "payments-api": [
        "WARN DB query slow | elapsed_ms={rt} | threshold=200ms",
        "WARN Connection pool pressure | active={pool}/20 | utilization={pct}%",
        "WARN Response time degraded | endpoint=/v1/charge | avg_ms={rt}",
        "WARN GC pause elevated | pause_ms={gc} | normal=<15ms",
        "WARN Memory pressure | heap={mem}MB | limit=512MB",
        "WARN Thread pool queue backing up | depth={depth} pending",
        "WARN Stripe upstream slow | retry_attempt={attempt}/3",
    ],
    "auth-service": [
        "WARN Upstream payments-api slow | response_ms={rt}",
        "WARN Elevated retry rate on dependency calls",
    ],
    "user-service": [
        "WARN payments-api dependency degraded | response_ms={rt}",
        "WARN Increased circuit breaker half-open calls",
    ],
}

ERROR_MSGS = {
    "payments-api": [
        "ERROR DB connection timeout | elapsed_ms={rt} | retrying",
        "ERROR Circuit breaker OPEN | target=payments-db | failures=5",
        "ERROR OOM pressure | heap={mem}MB / 512MB | GC overhead limit",
        "ERROR Connection pool exhausted | active=20/20 | request queued",
        "ERROR /v1/charge returning 503 | downstream unavailable",
        "CRITICAL Stripe webhook backlog | queued={depth} events unprocessed",
        "ERROR Transaction rollback | reason=connection_pool_exhausted",
        "CRITICAL Health check FAILING | liveness probe timeout | attempt={attempt}/3",
    ],
    "auth-service": [
        "ERROR payments-api unreachable | ConnectionRefused after {attempt} retries",
        "WARN Degraded mode ACTIVE | payments validation bypassed",
    ],
    "user-service": [
        "ERROR payments-api timeout | elapsed_ms={rt} | circuit_open=true",
        "ERROR Dependency check failed | service=payments-api",
    ],
}

CRASH_MSGS = {
    "payments-api": [
        "CRITICAL Process killed by OOM | heap={mem}MB exceeded 512MB container limit",
        "CRITICAL java.lang.OutOfMemoryError: Java heap space | thread=payment-worker-7",
        "CRITICAL Service DOWN | health check failed 3 consecutive times | pod=payments-api-7d9f4b",
        "CRITICAL Pod terminated | exit_code=137 | reason=OOMKilled",
    ],
    "auth-service": [
        "CRITICAL payments-api UNAVAILABLE | 100% upstream requests failing",
        "CRITICAL Entering emergency degraded mode | payments validation disabled",
        "ERROR Fallback exhausted | circuit_breaker=OPEN | upstream=payments-api",
    ],
    "user-service": [
        "CRITICAL Multiple upstream services DOWN | affected=payments-api,auth-service",
        "CRITICAL Unable to serve requests | dependency_failures=2",
        "ERROR Serving stale cache data | age=8min | reason=upstream_unavailable",
    ],
}


# ── Metric generation ──────────────────────────────────────────────────────────
def get_metrics(service: str, svc: dict, progress: float) -> dict:
    """
    progress = 0.0 (start of demo) to 1.0 (end of demo)
    Returns current metrics for the service at this point in time.
    """
    base_rt  = svc["base_rt"]
    base_mem = svc["base_mem"]
    base_cpu = svc["base_cpu"]

    if svc.get("is_victim"):
        if progress < 0.50:   # Phase 1: subtle drift only
            p = progress / 0.50
            return {
                "rt":    round(base_rt  + p * base_rt  * 0.9  * random.uniform(0.9, 1.1), 1),
                "mem":   round(base_mem + p * base_mem * 0.12 * random.uniform(0.98, 1.02), 1),
                "cpu":   round(base_cpu + p * base_cpu * 0.30 * random.uniform(0.9, 1.1), 1),
                "pool":  int(8 + p * 7),
                "gc":    round(8  + p * 8, 1),
                "cache": round(94 - p * 10, 1),
                "depth": int(p * 30),
                "error_rate": 0.0,
                "phase": "INFO",
            }
        elif progress < 0.75: # Phase 2: warnings
            p = (progress - 0.50) / 0.25
            return {
                "rt":    round((base_rt + base_rt * 0.9 + p * base_rt * 4)  * random.uniform(0.85, 1.2), 1),
                "mem":   round(base_mem + base_mem * 0.12 + p * base_mem * 0.20, 1),
                "cpu":   round(min(95, base_cpu + base_cpu * 0.30 + p * 30) * random.uniform(0.9, 1.1), 1),
                "pool":  min(20, int(15 + p * 4)),
                "gc":    round(16 + p * 70, 1),
                "cache": round(84 - p * 25, 1),
                "depth": int(30 + p * 60),
                "error_rate": round(p * 0.08, 4),
                "phase": "WARN",
            }
        elif progress < 0.90: # Phase 3: error storm
            p = (progress - 0.75) / 0.15
            return {
                "rt":    round((base_rt + 500 + p * 2000) * random.uniform(0.5, 2.0), 1),
                "mem":   round(min(510, base_mem + base_mem * 0.32 + p * 80), 1),
                "cpu":   round(min(99, 80 + p * 19) * random.uniform(0.95, 1.0), 1),
                "pool":  20,
                "gc":    round(90 + p * 350, 1),
                "cache": round(max(5, 59 - p * 54), 1),
                "depth": int(90 + p * 300),
                "error_rate": round(0.08 + p * 0.70, 4),
                "phase": "ERROR",
            }
        else:                  # Crashed
            return {"rt": 0, "mem": 0, "cpu": 0, "pool": 0, "gc": 0,
                    "cache": 0, "depth": 0, "error_rate": 1.0, "phase": "CRASH"}

    elif svc.get("is_cascade"):
        cascade_at = svc.get("cascade_at", 0.95)
        if progress >= cascade_at:
            return {"rt": 0, "mem": 0, "cpu": 0, "pool": 0, "gc": 0,
                    "cache": 0, "depth": 0, "error_rate": 1.0, "phase": "CRASH"}
        # slight upstream stress as payments-api degrades after 60%
        upstream_stress = max(0, (progress - 0.60) / 0.30) if progress > 0.60 else 0
        return {
            "rt":    round(svc["base_rt"]  * (1 + upstream_stress * 0.5) * random.uniform(0.9, 1.1), 1),
            "mem":   round(svc["base_mem"] * random.uniform(0.97, 1.03), 1),
            "cpu":   round(svc["base_cpu"] * (1 + upstream_stress * 0.3) * random.uniform(0.9, 1.1), 1),
            "pool":  0,
            "gc":    0,
            "cache": 0,
            "depth": 0,
            "error_rate": round(upstream_stress * 0.05, 4),
            "phase": "WARN" if upstream_stress > 0.3 else "INFO",
        }
    else:
        return {
            "rt":    round(svc["base_rt"]  * random.uniform(0.9, 1.1), 1),
            "mem":   round(svc["base_mem"] * random.uniform(0.97, 1.03), 1),
            "cpu":   round(svc["base_cpu"] * random.uniform(0.9, 1.1), 1),
            "pool":  0, "gc": 0, "cache": 95, "depth": 0, "error_rate": 0.0,
            "phase": "INFO",
        }


def pick_message(service: str, metrics: dict) -> tuple:
    phase = metrics["phase"]
    n   = random.randint(10000, 99999)
    uid = random.randint(10000, 99999)
    fmt = dict(
        n=n, uid=uid, amt=random.randint(10, 9999),
        rt=metrics["rt"], mem=metrics["mem"], cpu=metrics["cpu"],
        pool=metrics["pool"], pct=int(metrics["pool"]/20*100) if metrics["pool"] else 0,
        gc=metrics["gc"], cache=metrics["cache"], depth=metrics["depth"],
        up=random.randint(80000, 90000), sess=random.randint(1200, 1800),
        batch=random.randint(5000, 20000), lag=random.randint(0, 50),
        attempt=random.randint(1, 3),
    )

    if phase == "CRASH":
        msgs = CRASH_MSGS.get(service, ["CRITICAL: Service unavailable"])
        return "CRITICAL", random.choice(msgs).format(**fmt)
    elif phase == "ERROR":
        pool = ERROR_MSGS.get(service)
        if pool and random.random() < 0.7:
            return "ERROR", random.choice(pool).format(**fmt)
        pool2 = INFO_MSGS.get(service, ["Request processed"])
        return "INFO", random.choice(pool2).format(**fmt)
    elif phase == "WARN":
        pool = WARN_MSGS.get(service)
        if pool and random.random() < 0.5:
            return "WARN", random.choice(pool).format(**fmt)
        pool2 = INFO_MSGS.get(service, ["Request processed"])
        return "INFO", random.choice(pool2).format(**fmt)
    else:
        pool = INFO_MSGS.get(service, ["Request processed | response_ms={rt}"])
        return "INFO", random.choice(pool).format(**fmt)


# ── HEC sender ─────────────────────────────────────────────────────────────────
def send_batch(events: list) -> bool:
    """Send a batch of events to Splunk HEC."""
    if not events:
        return True

    headers = {
        "Authorization": f"Splunk {HEC_TOKEN}",
        "Content-Type":  "application/json",
    }

    # HEC batch format: newline-delimited JSON objects
    body = "\n".join(json.dumps(e) for e in events)

    try:
        resp = httpx.post(HEC_URL, headers=headers, content=body,
                          verify=VERIFY_SSL, timeout=10)
        if resp.status_code == 200:
            return True
        else:
            print(f"  [HEC ERROR] {resp.status_code}: {resp.text[:200]}")
            return False
    except Exception as ex:
        print(f"  [NETWORK ERROR] {ex}")
        return False


def build_hec_event(service: str, level: str, message: str,
                    metrics: dict, ts: float) -> dict:
    """Build a Splunk HEC event payload."""
    return {
        "time":       ts,
        "sourcetype": "_json",
        "source":     f"{service}-live",
        "host":       f"{service}-pod-1",
        "event": {
            "timestamp":    datetime.fromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "level":        level,
            "service":      service,
            "Component":    service,            # PreCog uses Component field
            "message":      message,
            "response_ms":  metrics["rt"],
            "memory_mb":    metrics["mem"],
            "cpu_pct":      metrics["cpu"],
            "error_rate":   metrics["error_rate"],
            "gc_pause_ms":  metrics["gc"],
            "pool_used":    metrics["pool"],
            "queue_depth":  metrics["depth"],
            "cache_hit_pct": metrics["cache"],
            "demo":         "live_crash_scenario",
        }
    }


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("PreCog LIVE Demo Streamer")
    print("=" * 60)
    print(f"Splunk HEC : {HEC_URL}")
    print(f"Index      : {HEC_INDEX}")
    print(f"Duration   : {DEMO_DURATION_SECONDS}s ({DEMO_DURATION_SECONDS//60}m {DEMO_DURATION_SECONDS%60}s)")
    print(f"Batch      : every {BATCH_INTERVAL}s")
    print()

    if HEC_TOKEN == "YOUR-HEC-TOKEN-HERE":
        print("[ERROR] Please edit HEC_TOKEN in this script before running!")
        print("  Splunk Web -> Settings -> Data Inputs -> HTTP Event Collector")
        sys.exit(1)

    print("Starting stream in 3 seconds... open PreCog dashboard now!")
    print()
    time.sleep(3)

    start_real = time.time()
    total_sent = 0
    batch_num  = 0

    print(f"{'Time':>6}  {'Progress':>8}  {'Phase':<12}  {'Events':>6}  {'Status'}")
    print("-" * 60)

    while True:
        now_real = time.time()
        elapsed  = now_real - start_real
        progress = min(1.0, elapsed / DEMO_DURATION_SECONDS)

        # Determine current scenario phase for display
        if progress < 0.50:
            phase_label = "INFO only"
        elif progress < 0.75:
            phase_label = "WARN start"
        elif progress < 0.90:
            phase_label = "ERROR flood"
        else:
            phase_label = "CRASHED"

        # Build a batch of events for this tick
        events = []
        now_ts  = time.time()

        for service, svc in SERVICES.items():
            metrics = get_metrics(service, svc, progress)

            # Number of log lines per service per tick
            if metrics["phase"] == "ERROR":
                n_logs = random.randint(4, 8)
            elif metrics["phase"] == "WARN":
                n_logs = random.randint(2, 4)
            elif metrics["phase"] == "CRASH":
                n_logs = random.randint(1, 3)
            else:
                n_logs = random.randint(1, 2)

            for i in range(n_logs):
                level, message = pick_message(service, metrics)
                ts = now_ts + i * 0.1  # slight offset per log line
                ev = build_hec_event(service, level, message, metrics, ts)
                events.append(ev)

        ok = send_batch(events)
        total_sent += len(events)
        batch_num  += 1

        mins  = int(elapsed) // 60
        secs  = int(elapsed) %  60
        status = "OK" if ok else "FAIL"
        print(f"  {mins:02d}:{secs:02d}  {progress*100:>7.1f}%  {phase_label:<12}  {len(events):>6}  {status}  (total={total_sent})")

        if progress >= 1.0:
            break

        time.sleep(BATCH_INTERVAL)

    print()
    print("=" * 60)
    print(f"Stream complete! {total_sent} events sent to Splunk.")
    print()
    print("PreCog should now show payments-api as CRITICAL.")
    print("auth-service and user-service as HIGH/CRITICAL.")
    print("data-pipeline and recommendations-engine as LOW.")
    print("=" * 60)


if __name__ == "__main__":
    main()
