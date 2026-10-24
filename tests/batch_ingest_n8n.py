import requests
import json
import io
import sys

# Ensure UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

N8N_BASE_URL = os.environ.get("N8N_BASE_URL", "https://ubuntu.arindam818.cloud")
url = f"{N8N_BASE_URL}/webhook/control-tower-events"
with open('synthetic_sample_100.json', 'r', encoding='utf-8') as f:
    samples = json.load(f)[:20]

print(f"Sending 20 live synthetic events to n8n webhook: {url}...")
success = 0
for idx, s in enumerate(samples, 1):
    try:
        r = requests.post(url, json=s, timeout=10)
        if r.status_code == 200:
            success += 1
            print(f"[{idx:02d}/20] Event {s['event_id']} -> 200 OK (Status: {s['status']}, Container: {s['container_no']})")
        else:
            print(f"[{idx:02d}/20] Status {r.status_code}")
    except Exception as e:
        print(f"[{idx:02d}/20] Error: {e}")

print(f"\nAll {success}/20 events processed live into n8n executions!")
