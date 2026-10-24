"""
Live Execution Trigger for all 4 Control Tower Workflows on https://ubuntu.arindam818.cloud.
Fires authentic production payloads against n8n webhooks,
verifies that every execution succeeds (HTTP 200), and fetches the execution logs from n8n.
"""
import os
import sys
import io
import time
import requests
import json
from pathlib import Path
from dotenv import load_dotenv

# Ensure UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

N8N_BASE_URL = os.environ.get("N8N_BASE_URL", "https://ubuntu.arindam818.cloud")
N8N_API_KEY = os.environ.get("N8N_PUBLIC_API_KEY") or os.environ.get("N8N_API_KEY", "")

def trigger_all_live_workflows():
    print("=" * 80)
    print("⚡ TRIGGERING LIVE N8N EXECUTIONS ACROSS ALL CONTROL TOWER WORKFLOWS")
    print(f"Target: {N8N_BASE_URL}")
    print("=" * 80)

    # -----------------------------------------------------------------
    # 1. TRIGGER WORKFLOW 1: Normal In-flight Milestone
    # -----------------------------------------------------------------
    print("\n[1/5] Firing Workflow 1 (Normal Transit Webhook)...")
    url_wf1 = f"{N8N_BASE_URL}/webhook/control-tower-events"
    payload_normal = {
        "source_system": "OCEAN_AIS_FEED",
        "status": "ARRIVED_PORT",
        "container_no": "MSCU1234567",
        "carrier_code": "CMA CGM",
        "location_code": "USLAX",
        "dwell_hours": 12.0,
        "timestamp": "2026-10-24T06:00:00Z"
    }
    r1 = requests.post(url_wf1, json=payload_normal, timeout=15)
    print(f"  HTTP Response: {r1.status_code}")
    if r1.status_code == 200:
        print(f"  Result: {json.dumps(r1.json(), indent=2)[:250]}...")
    else:
        print(f"  Error: {r1.text}")

    # -----------------------------------------------------------------
    # 2. TRIGGER WORKFLOW 1: Critical Customs Hold Exception
    # -----------------------------------------------------------------
    print("\n[2/5] Firing Workflow 1 (Critical Disruption & SLA Breach)...")
    payload_disruption = {
        "source_system": "CUSTOMS_ACE_PORTAL",
        "status": "CUSTOMS_HOLD",
        "container_no": "MSCU1234567",
        "carrier_code": "CMA CGM",
        "location_code": "USLAX",
        "delay_reason": "Mandatory CBP intensive x-ray examination hold",
        "delay_hours_estimate": 48.0,
        "dwell_hours": 52.0,
        "timestamp": "2026-10-24T06:15:00Z"
    }
    r2 = requests.post(url_wf1, json=payload_disruption, timeout=15)
    print(f"  HTTP Response: {r2.status_code}")
    if r2.status_code == 200:
        print(f"  Result: {json.dumps(r2.json(), indent=2)[:300]}...")
    else:
        print(f"  Error: {r2.text}")

    # -----------------------------------------------------------------
    # 3. TRIGGER WORKFLOW 2: Carrier Delay Email NLP Extraction
    # -----------------------------------------------------------------
    print("\n[3/5] Firing Workflow 2 (Qwen Email NLP Processor)...")
    url_wf2 = f"{N8N_BASE_URL}/webhook/control-tower-carrier-email"
    payload_email = {
        "email_text": "URGENT DISPATCH NOTICE: Container MSCU1234567 under BOL CMA9921 for PO APEX-8801 has been placed on customs hold at Port of Los Angeles Pier 400. Vessel discharge delayed by 48 hours. Please reschedule drayage appointment."
    }
    r3 = requests.post(url_wf2, json=payload_email, timeout=15)
    print(f"  HTTP Response: {r3.status_code}")
    if r3.status_code == 200:
        print(f"  Result: {json.dumps(r3.json(), indent=2)[:280]}...")
    else:
        print(f"  Error: {r3.text}")

    # -----------------------------------------------------------------
    # 4. TRIGGER WORKFLOW 3: Dynamic ETA & Exception Desk Aggregator
    # -----------------------------------------------------------------
    print("\n[4/5] Firing Workflow 3 (Dynamic ETA & Exception Desk)...")
    url_wf3 = f"{N8N_BASE_URL}/webhook/control-tower-evaluate-exceptions"
    r4 = requests.post(url_wf3, json={"trigger": "SCHEDULED_POLL"}, timeout=15)
    print(f"  HTTP Response: {r4.status_code}")
    if r4.status_code == 200:
        print(f"  Result: {json.dumps(r4.json(), indent=2)[:280]}...")
    else:
        print(f"  Error: {r4.text}")

    # -----------------------------------------------------------------
    # 5. TRIGGER WORKFLOW 4: Re-Planning & Human Approval Gate
    # -----------------------------------------------------------------
    print("\n[5/5] Firing Workflow 4 (Re-Planning & Human Approval Gate)...")
    url_wf4 = f"{N8N_BASE_URL}/webhook/control-tower-approval"
    payload_approval = {
        "approval_id": "APP-301B1888",
        "action": "APPROVE",
        "approved_by": "operations_supervisor_john",
        "comments": "Authorized dedicated team drayage to recover 36h and safeguard $255k stockout."
    }
    r5 = requests.post(url_wf4, json=payload_approval, timeout=15)
    print(f"  HTTP Response: {r5.status_code}")
    if r5.status_code == 200:
        print(f"  Result: {json.dumps(r5.json(), indent=2)[:280]}...")
    else:
        print(f"  Error: {r5.text}")

    # -----------------------------------------------------------------
    # FETCH RECENT EXECUTIONS FROM N8N REST API
    # -----------------------------------------------------------------
    time.sleep(1)
    print("\n" + "=" * 80)
    print("📋 LIVE N8N EXECUTION LOGS IN YOUR INSTANCE")
    print("=" * 80)
    headers = {"X-N8N-API-KEY": N8N_API_KEY}
    exec_resp = requests.get(f"{N8N_BASE_URL}/api/v1/executions?limit=10", headers=headers, timeout=15)
    if exec_resp.status_code == 200:
        execs = exec_resp.json().get("data", [])
        print(f"Total Recent Executions Retrieved: {len(execs)}")
        for e in execs:
            eid = e["id"]
            wid = e["workflowId"]
            status = e.get("status")
            started = e.get("startedAt", "")[:19]
            print(f"  • Execution #{eid:<6} | Workflow: {wid} | Status: {status.upper():<7} | Started: {started} | URL: {N8N_BASE_URL}/execution/{eid}")
    else:
        print(f"Could not fetch execution list: {exec_resp.status_code}")

    print("=" * 80)

if __name__ == "__main__":
    trigger_all_live_workflows()
