"""
Configuration settings for Real-Time Multimodal Shipment Control Tower.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env file
load_dotenv(dotenv_path=BASE_DIR / ".env")

# Database configuration (SQLite for self-contained execution, fully relational schema)
DB_PATH = os.environ.get("CONTROL_TOWER_DB", str(BASE_DIR / "control_tower.db"))


# Ollama NLP Service configuration
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://158.69.215.232:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")  # Fallback: qwen3:4b, qwen2.5-coder:3b

# Groq Cloud API configuration (optional high-speed fallback)
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "qwen/qwen3.6-27b")

# n8n Service configuration
N8N_BASE_URL = os.environ.get("N8N_BASE_URL", "https://ubuntu.arindam818.cloud")
N8N_PUBLIC_API_KEY = os.environ.get("N8N_PUBLIC_API_KEY", "")
N8N_MCP_TOKEN = os.environ.get("N8N_MCP_TOKEN", "")
N8N_MCP_URL = f"{N8N_BASE_URL}/mcp-server/http"

# Decision Engine Service Port
DECISION_ENGINE_PORT = int(os.environ.get("DECISION_ENGINE_PORT", 8088))
DECISION_ENGINE_HOST = os.environ.get("DECISION_ENGINE_HOST", "0.0.0.0")

# SLA and Visibility Gap Thresholds (in hours)
VISIBILITY_GAP_THRESHOLDS = {
    "ROAD_FTL": 4,
    "ROAD_LTL": 8,
    "OCEAN": 24,
    "AIR": 4,
    "RAIL": 12,
    "PARCEL": 12
}

# Dwell thresholds (in hours) before triggering exception
DWELL_THRESHOLDS = {
    "PORT_ORIGIN": 48,
    "PORT_DISCHARGE": 72,
    "RAIL_RAMP": 24,
    "CROSS_DOCK": 12,
    "CUSTOMS_HOLD": 4
}

# Customer Priority Buffer tolerances (hours beyond promised date before escalating)
CUSTOMER_TIER_BUFFERS = {
    "TIER_1_STRATEGIC": 2,     # Zero-tolerance, alert if > 2 hrs late
    "TIER_2_ENTERPRISE": 6,
    "TIER_3_STANDARD": 12,
    "TIER_4_LOW_PRIORITY": 24
}

# Approval Tiers based on recovery cost
APPROVAL_TIERS = {
    "TIER_1_AUTO": {"max_cost": 250, "approver": "SYSTEM_AUTOMATIC"},
    "TIER_2_SUPERVISOR": {"max_cost": 1500, "approver": "LOGISTICS_SUPERVISOR"},
    "TIER_3_MANAGER": {"max_cost": 5000, "approver": "OPERATIONS_MANAGER"},
    "TIER_4_EXECUTIVE": {"max_cost": float("inf"), "approver": "VP_SUPPLY_CHAIN_OR_FINANCE"}
}
