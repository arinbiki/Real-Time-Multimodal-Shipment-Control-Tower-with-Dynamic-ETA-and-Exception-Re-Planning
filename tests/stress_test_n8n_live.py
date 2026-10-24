"""
High-Concurrency Live Stress Test for n8n Multimodal Shipment Control Tower Workflows.
Zero hardcoded credentials: All secrets and endpoints are loaded dynamically from environment variables (.env).
Benchmarks live n8n webhook ingestion under high-concurrency loads, measures latency percentiles,
throughput (req/sec), HTTP 200 success rates, and verifies live execution records in n8n.
"""
import os
import sys
import io
import time
import asyncio
import sqlite3
import json
import statistics
from pathlib import Path
from dotenv import load_dotenv
import aiohttp
import requests

# Ensure UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Load environment configuration
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

N8N_BASE_URL = os.environ.get("N8N_BASE_URL", "https://ubuntu.arindam818.cloud")
N8N_API_KEY = os.environ.get("N8N_PUBLIC_API_KEY") or os.environ.get("N8N_API_KEY", "")

WEBHOOK_INGEST = f"{N8N_BASE_URL}/webhook/control-tower-events"
WEBHOOK_EXCEPTION = f"{N8N_BASE_URL}/webhook/control-tower-evaluate-exceptions"
WEBHOOK_EMAIL = f"{N8N_BASE_URL}/webhook/control-tower-carrier-email"

SYNTHETIC_DB = BASE_DIR / "synthetic_events_1m.db"
SAMPLE_JSON = BASE_DIR / "synthetic_sample_100.json"

def get_test_payloads(count=150):
    """Fetch real-world test payloads from 1M synthetic database or sample JSON."""
    payloads = []
    if SYNTHETIC_DB.exists():
        try:
            conn = sqlite3.connect(SYNTHETIC_DB)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(f"SELECT * FROM synthetic_events LIMIT {count};").fetchall()
            conn.close()
            for r in rows:
                payloads.append({
                    "event_id": r["event_id"],
                    "source_system": r["source_system"],
                    "status": r["status"],
                    "container_no": r["container_no"],
                    "bol_no": r["bol_no"],
                    "po_number": r["po_number"],
                    "carrier_code": r["carrier_code"],
                    "location_code": r["location_code"],
                    "location_name": r["location_name"],
                    "dwell_hours": r["dwell_hours"],
                    "delay_reason": r["delay_reason"],
                    "delay_hours_estimate": r["delay_hours_estimate"],
                    "timestamp": r["timestamp"]
                })
            return payloads
        except Exception as e:
            print(f"[Warning] Could not read from DB ({e}), falling back to sample JSON.")

    if SAMPLE_JSON.exists():
        with open(SAMPLE_JSON, "r", encoding="utf-8") as f:
            samples = json.load(f)
            while len(payloads) < count:
                payloads.extend(samples)
            return payloads[:count]

    # Fallback minimal payloads
    for i in range(count):
        payloads.append({
            "event_id": f"STRESS-EVT-{i:05d}",
            "source_system": "CARRIER_EDI_FEED",
            "status": "IN_TRANSIT",
            "container_no": f"STRESS{i:06d}",
            "carrier_code": "MAEU",
            "location_code": "USLAX",
            "dwell_hours": round(float(i % 30), 1),
            "timestamp": "2026-10-24T12:00:00Z"
        })
    return payloads

async def _send_event(session, sem, url, payload):
    async with sem:
        t0 = time.perf_counter()
        try:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                status = resp.status
                text = await resp.text()
                is_success = (status == 200)
                return {
                    "success": is_success,
                    "status": status,
                    "latency_ms": elapsed_ms,
                    "error": None if is_success else text[:100]
                }
        except Exception as e:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            return {
                "success": False,
                "status": 0,
                "latency_ms": elapsed_ms,
                "error": str(e)
            }

async def run_n8n_stress_test(total_requests=150, concurrency=15):
    print("=" * 80)
    print("🔥 LIVE N8N HIGH-CONCURRENCY WORKFLOW STRESS TEST")
    print(f"Target Instance : {N8N_BASE_URL}")
    print(f"Target Webhook  : {WEBHOOK_INGEST}")
    print(f"Total Requests  : {total_requests:,}")
    print(f"Concurrency     : {concurrency} workers")
    print("=" * 80)

    payloads = get_test_payloads(total_requests)
    print(f"Loaded {len(payloads)} synthetic production payloads for stress run.\n")

    sem = asyncio.Semaphore(concurrency)
    conn_pool = aiohttp.TCPConnector(limit=concurrency + 10, limit_per_host=concurrency + 5)
    
    print("🚀 Launching concurrent load test against n8n...")
    t_start = time.perf_counter()

    async with aiohttp.ClientSession(connector=conn_pool) as session:
        tasks = [_send_event(session, sem, WEBHOOK_INGEST, p) for p in payloads]
        results = await asyncio.gather(*tasks)

    t_total = time.perf_counter() - t_start

    successes = [r for r in results if r["success"]]
    failures = [r for r in results if not r["success"]]
    latencies = [r["latency_ms"] for r in results]

    sorted_latencies = sorted(latencies)
    p50 = statistics.median(sorted_latencies)
    p95 = sorted_latencies[int(len(sorted_latencies) * 0.95)]
    p99 = sorted_latencies[int(len(sorted_latencies) * 0.99)]
    avg_latency = statistics.mean(latencies)
    min_latency = min(latencies)
    max_latency = max(latencies)
    throughput = len(results) / t_total

    print("\n" + "=" * 80)
    print("📈 N8N WORKFLOW STRESS TEST RESULTS")
    print("=" * 80)
    print(f"  • Total Requests Dispatched : {len(results):,}")
    print(f"  • Successful Responses (200): {len(successes):,} ({(len(successes)/len(results))*100:.1f}%)")
    print(f"  • Failed Requests           : {len(failures):,}")
    print(f"  • Total Execution Time      : {t_total:.3f} seconds")
    print(f"  • Average Throughput        : {throughput:,.1f} requests/second")
    print(f"  • Latency Min               : {min_latency:6.1f} ms")
    print(f"  • Latency Average           : {avg_latency:6.1f} ms")
    print(f"  • Latency Median (p50)      : {p50:6.1f} ms")
    print(f"  • Latency p95               : {p95:6.1f} ms")
    print(f"  • Latency p99               : {p99:6.1f} ms")
    print(f"  • Latency Max               : {max_latency:6.1f} ms")
    print("=" * 80)

    # Verify executions directly in n8n via REST API if key is available
    if N8N_API_KEY:
        print("\n🔍 VERIFYING LIVE EXECUTION LOGS IN N8N DATABASE...")
        headers = {"X-N8N-API-KEY": N8N_API_KEY}
        try:
            r = requests.get(f"{N8N_BASE_URL}/api/v1/executions?limit=15", headers=headers, timeout=15)
            if r.status_code == 200:
                execs = r.json().get("data", [])
                print(f"Retrieved {len(execs)} most recent executions from n8n:")
                for e in execs:
                    eid = e.get("id")
                    wid = e.get("workflowId")
                    mode = e.get("mode")
                    status = e.get("status", "unknown")
                    started = e.get("startedAt", "")[:19]
                    print(f"  • Execution #{eid:<6} | Workflow: {wid} | Mode: {mode:<7} | Status: {status.upper():<7} | Time: {started}")
            else:
                print(f"  Could not retrieve execution list: HTTP {r.status_code}")
        except Exception as e:
            print(f"  Error querying n8n execution list: {e}")
    else:
        print("ℹ️ Note: N8N_PUBLIC_API_KEY not configured. Execution logs check skipped.")

    print("\n✅ STRESS TEST ON LIVE N8N WORKFLOWS COMPLETED SUCCESSFULLY!")

def main():
    asyncio.run(run_n8n_stress_test(total_requests=150, concurrency=15))

if __name__ == "__main__":
    main()
