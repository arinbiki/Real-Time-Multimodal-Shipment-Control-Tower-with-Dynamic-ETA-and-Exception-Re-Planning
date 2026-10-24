"""
Massive 1 Million Synthetic Logistics Events Generator.
Generates 1,000,000 production-grade real-time multimodal shipment events:
- ISO 6346 Container numbers, BOLs, PO numbers
- Real ocean, rail, and road carrier SCAC codes
- UN/LOCODE locations with GPS coordinates & reefer temperatures
- Multi-tier delay classifications (Customs hold, Terminal congestion, Rail dwell, Weather)
Persists into a high-performance indexed SQLite database (synthetic_events_1m.db)
and exports sample payloads for live n8n webhook stress testing.
"""
import sys
import io
import os
import time
import random
import sqlite3
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ensure UTF-8 output
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE_DIR = Path(__file__).resolve().parent.parent
SYNTHETIC_DB_PATH = BASE_DIR / "synthetic_events_1m.db"

CARRIERS = [
    ("MSCU", "Mediterranean Shipping Company", "OCEAN"),
    ("CMDU", "CMA CGM Group", "OCEAN"),
    ("MAEU", "Maersk Line", "OCEAN"),
    ("COSU", "COSCO Shipping Lines", "OCEAN"),
    ("ONEY", "Ocean Network Express", "OCEAN"),
    ("BNSF", "BNSF Railway Intermodal", "RAIL"),
    ("UNP", "Union Pacific Railroad", "RAIL"),
    ("KNIG", "Knight-Swift Transportation", "ROAD_FTL"),
    ("JBHT", "J.B. Hunt Intermodal", "ROAD_FTL"),
    ("ODFL", "Old Dominion Freight Line", "ROAD_LTL"),
    ("ATLA", "Atlas Air Cargo", "AIR"),
    ("FDX", "FedEx Freight Priority", "PARCEL")
]

LOCATIONS = [
    ("USLAX", "Port of Los Angeles, CA", 33.7432, -118.2673),
    ("USLGB", "Port of Long Beach, CA", 33.7542, -118.2165),
    ("USCHI", "Chicago BNSF Logistics Park, IL", 41.5303, -88.1158),
    ("USNYC", "Port of New York / New Jersey, NJ", 40.6698, -74.1357),
    ("USSEA", "Port of Seattle Terminal 18, WA", 47.5902, -122.3551),
    ("USLRD", "Laredo World Trade Bridge, TX", 27.5954, -99.5312),
    ("USDTW", "Detroit Intermodal Ramp, MI", 42.3314, -83.0458),
    ("CNSHA", "Port of Shanghai Yangshan, China", 30.6278, 122.0642),
    ("CNNBO", "Port of Ningbo-Zhoushan, China", 29.8683, 121.5440),
    ("KRPUS", "Port of Busan New Port, South Korea", 35.0761, 128.8286),
    ("NLRTM", "Port of Rotterdam Maasvlakte, Netherlands", 51.9567, 4.0289),
    ("DEHAM", "Port of Hamburg Container Terminal, Germany", 53.5323, 9.9472),
    ("SGSIN", "Port of Singapore Pasir Panjang, Singapore", 1.2842, 103.7852)
]

STATUS_TYPES = [
    ("ARRIVED_PORT", "ARRIVAL", 0.12),
    ("DISCH", "HANDLING", 0.15),
    ("LOADED", "HANDLING", 0.10),
    ("CUSTOMS_HOLD", "CUSTOMS", 0.05),
    ("CUSTOMS_CLEARED", "CUSTOMS", 0.08),
    ("AF", "DEPARTURE", 0.10),      # Departed origin / ramp
    ("I1", "IN_TRANSIT", 0.22),     # In-transit telematics ping
    ("CP", "HANDLING", 0.08),       # Completed transfer
    ("OUT_FOR_DELIVERY", "DELIVERY", 0.05),
    ("D1", "DELIVERY", 0.03),       # Delivered
    ("DELAYED", "DELAY", 0.02)
]

DELAY_REASONS = [
    "Severe terminal congestion & berth waiting queue",
    "Mandatory CBP intensive x-ray examination hold",
    "Chassis deficit at intermodal rail ramp",
    "Severe blizzard disrupting highway corridor",
    "High winds and tidal surge preventing pilot boarding",
    "Locomotive power outage and track maintenance",
    "Driver hours-of-service mandatory rest requirement",
    "Warehouse gate appointment rescheduling required"
]

CUSTOMERS = ["CUST-APEX", "CUST-TITAN", "CUST-WALM", "CUST-AMZN", "CUST-TARGET", "CUST-TESLA", "CUST-APPLE"]

def generate_container_no():
    prefix = random.choice(["MSCU", "CMAU", "MAEU", "COSU", "TCLU", "ONEU", "KKFU"])
    num = random.randint(1000000, 9999999)
    return f"{prefix}{num}"

def init_synthetic_db():
    if os.path.exists(SYNTHETIC_DB_PATH):
        os.remove(SYNTHETIC_DB_PATH)
        
    conn = sqlite3.connect(SYNTHETIC_DB_PATH)
    with conn:
        conn.execute("""
        CREATE TABLE synthetic_events (
            event_id TEXT PRIMARY KEY,
            timestamp TIMESTAMP NOT NULL,
            source_system TEXT NOT NULL,
            carrier_code TEXT NOT NULL,
            carrier_name TEXT NOT NULL,
            mode TEXT NOT NULL,
            status TEXT NOT NULL,
            category TEXT NOT NULL,
            container_no TEXT NOT NULL,
            bol_no TEXT NOT NULL,
            po_number TEXT NOT NULL,
            customer_id TEXT NOT NULL,
            location_code TEXT NOT NULL,
            location_name TEXT NOT NULL,
            latitude REAL,
            longitude REAL,
            temperature_c REAL,
            dwell_hours REAL,
            delay_reason TEXT,
            delay_hours_estimate REAL,
            urgency TEXT NOT NULL
        );
        """)
        # High performance indexes for stress tests
        conn.execute("CREATE INDEX idx_synth_status ON synthetic_events(status);")
        conn.execute("CREATE INDEX idx_synth_container ON synthetic_events(container_no);")
        conn.execute("CREATE INDEX idx_synth_timestamp ON synthetic_events(timestamp);")
        conn.execute("CREATE INDEX idx_synth_carrier ON synthetic_events(carrier_code);")
    conn.close()

def generate_1m_events(total_events=1_000_000, batch_size=50_000):
    print("=" * 80)
    print(f"🚀 GENERATING {total_events:,} MASSIVE REAL-TIME LOGISTICS DATASETS")
    print(f"Output Target: {SYNTHETIC_DB_PATH}")
    print(f"Batch Size: {batch_size:,} records per transaction")
    print("=" * 80)

    start_time = time.time()
    init_synthetic_db()

    conn = sqlite3.connect(SYNTHETIC_DB_PATH)
    # Performance pragmas for bulk ingestion
    conn.execute("PRAGMA synchronous = OFF;")
    conn.execute("PRAGMA journal_mode = MEMORY;")
    conn.execute("PRAGMA cache_size = 100000;")

    # Status distribution weights
    status_choices = [s[0] for s in STATUS_TYPES]
    status_weights = [s[2] for s in STATUS_TYPES]
    status_to_cat = {s[0]: s[1] for s in STATUS_TYPES}

    # Reference pools to simulate realistic multi-event lifecycle per container
    CONTAINER_POOL_SIZE = 100_000
    container_pool = [generate_container_no() for _ in range(CONTAINER_POOL_SIZE)]
    bol_pool = [f"BOL-2026-{random.randint(100000, 999999)}" for _ in range(CONTAINER_POOL_SIZE)]
    po_pool = [f"PO-{random.choice(CUSTOMERS)[5:]}-{random.randint(10000, 99999)}" for _ in range(CONTAINER_POOL_SIZE)]

    now = datetime.now(timezone.utc)
    inserted_count = 0

    insert_sql = """
    INSERT INTO synthetic_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    sample_for_export = []

    for batch_num in range(total_events // batch_size):
        batch_records = []
        for _ in range(batch_size):
            idx = random.randint(0, CONTAINER_POOL_SIZE - 1)
            carrier = random.choice(CARRIERS)
            loc = random.choice(LOCATIONS)
            status = random.choices(status_choices, weights=status_weights)[0]
            category = status_to_cat[status]
            
            # Timestamp uniformly spread over past 14 days up to now
            event_time = now - timedelta(seconds=random.randint(0, 14 * 86400))
            
            is_delayed = status in ("CUSTOMS_HOLD", "DELAYED") or random.random() < 0.05
            delay_reason = random.choice(DELAY_REASONS) if is_delayed else None
            delay_hrs = random.choice([12.0, 24.0, 36.0, 48.0, 72.0]) if is_delayed else 0.0
            dwell_hrs = random.uniform(2.0, 96.0) if status in ("ARRIVED_PORT", "DISCH", "CUSTOMS_HOLD") else random.uniform(0.5, 8.0)
            
            urgency = "CRITICAL" if (status == "CUSTOMS_HOLD" or delay_hrs >= 48) else (
                "HIGH" if delay_hrs > 0 else "LOW"
            )

            # Reefer temperature fluctuation (-22 to +6 C)
            temp_c = round(random.uniform(-22.0, 5.0), 1) if random.random() < 0.35 else None

            event_id = f"EVT-{batch_num:02d}-{len(batch_records):05d}-{random.randint(100, 999)}"

            row = (
                event_id,
                event_time.isoformat(),
                "CARRIER_EDI_214" if carrier[2] == "ROAD_FTL" else ("OCEAN_AIS_FEED" if carrier[2] == "OCEAN" else "RAIL_CLM_FEED"),
                carrier[0],
                carrier[1],
                carrier[2],
                status,
                category,
                container_pool[idx],
                bol_pool[idx],
                po_pool[idx],
                random.choice(CUSTOMERS),
                loc[0],
                loc[1],
                loc[2] + random.uniform(-0.02, 0.02),
                loc[3] + random.uniform(-0.02, 0.02),
                temp_c,
                round(dwell_hrs, 1),
                delay_reason,
                delay_hrs,
                urgency
            )
            batch_records.append(row)

            # Save 100 realistic samples for HTTP stress testing
            if len(sample_for_export) < 100:
                sample_for_export.append({
                    "event_id": row[0],
                    "timestamp": row[1],
                    "source_system": row[2],
                    "carrier_code": row[3],
                    "status": row[6],
                    "container_no": row[8],
                    "bol_no": row[9],
                    "po_number": row[10],
                    "customer_id": row[11],
                    "location_code": row[12],
                    "location_name": row[13],
                    "dwell_hours": row[17],
                    "delay_reason": row[18],
                    "delay_hours_estimate": row[19]
                })

        conn.executemany(insert_sql, batch_records)
        conn.commit()
        inserted_count += len(batch_records)

        elapsed = time.time() - start_time
        rate = inserted_count / elapsed if elapsed > 0 else 0
        print(f"  [Batch {batch_num + 1:02d}/{(total_events // batch_size):02d}] "
              f"Inserted {inserted_count:,} records ({rate:,.0f} records/sec)")

    conn.close()
    total_time = time.time() - start_time
    file_size_mb = os.path.getsize(SYNTHETIC_DB_PATH) / (1024 * 1024)

    # Export sample JSON for n8n stress tests
    sample_file = BASE_DIR / "synthetic_sample_100.json"
    with open(sample_file, "w", encoding="utf-8") as f:
        json.dump(sample_for_export, f, indent=2)

    print("\n" + "=" * 80)
    print(f"✅ SUCCESS: {total_events:,} SYNTHETIC RECORDS GENERATED")
    print(f"  Total Duration: {total_time:.2f} seconds")
    print(f"  Throughput    : {total_events / total_time:,.0f} rows/second")
    print(f"  Database File : {SYNTHETIC_DB_PATH} ({file_size_mb:.1f} MB)")
    print(f"  Sample JSON   : {sample_file} (100 production payloads)")
    print("=" * 80)

if __name__ == "__main__":
    generate_1m_events()
