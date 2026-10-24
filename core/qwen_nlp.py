"""
Qwen NLP Extraction and Drafting Service matching Section 18 of plan.md.
Provides resilient extraction of unstructured carrier emails, delay classification,
incident summarization, and customer notification drafting.
Supports local Ollama (qwen2.5:3b / qwen3:4b), Groq Cloud Qwen fallback, and regex heuristics.
"""
import json
import re
import requests
from typing import Dict, Any, Optional
from core.config import (
    OLLAMA_BASE_URL, OLLAMA_MODEL, GROQ_API_KEY, GROQ_MODEL
)
from core.database import log_audit

EXTRACTION_PROMPT_TEMPLATE = """You are an expert logistics data extraction assistant.
Extract structured shipment status fields from the following unstructured email or message text.
Output MUST be strictly valid JSON with no markdown formatting.

Text to extract:
\"\"\"{text}\"\"\"

Required JSON Schema:
{{
  "carrier": "Carrier name or SCAC (e.g. CMA CGM, Maersk, Swift)",
  "container_no": "Container number (e.g. MSCU1234567) or null",
  "bol_no": "BOL number or null",
  "shipment_id": "TMS or shipment reference if mentioned or null",
  "po_number": "PO or order number if mentioned or null",
  "event_type": "One of: ARRIVED_AT_PORT, DISCHARGED_FROM_VESSEL, CUSTOMS_HOLD, CUSTOMS_RELEASED, DELAYED, IN_TRANSIT, OUT_FOR_DELIVERY, DELIVERED",
  "location": "Port, terminal, city, or hub location",
  "new_eta": "Revised date/time ISO string if stated, or null",
  "delay_hours_estimate": 24,
  "delay_reason": "Clear explanation of the delay or hold reason",
  "urgency": "One of: CRITICAL, HIGH, MEDIUM, LOW",
  "confidence": 0.95
}}
"""

SUMMARIZATION_PROMPT_TEMPLATE = """You are a Supply Chain Control Tower Operations Specialist.
Summarize the following shipment exception case, financial impact, and recommended action into a concise 2-sentence briefing for executive review.
Output must be plain text.

Shipment: {shipment_id} (Customer: {customer_name}, Tier: {customer_tier})
Exception: {exception_title} ({severity})
Financial Risk: ${total_risk:,.2f} (Penalty: ${penalty:,.2f}, Revenue at risk: ${revenue:,.2f})
Top Recommended Action: {recommended_action}
"""

DRAFTING_PROMPT_TEMPLATE = """You are a customer service logistics specialist.
Draft a professional, empathetic email to {customer_name} regarding a shipment delay for PO #{po_number}.
Explain the situation transparently, state the revised ETA ({revised_eta}), and explain the mitigation action ({mitigation_action}) we are taking to minimize delay.
Keep it under 150 words.
"""

def _call_ollama(prompt: str, json_format: bool = True) -> Optional[str]:
    """Attempt call to local Ollama server."""
    try:
        url = f"{OLLAMA_BASE_URL}/api/chat"
        payload = {
            "model": OLLAMA_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False
        }
        if json_format:
            payload["format"] = "json"
        resp = requests.post(url, json=payload, timeout=5)
        if resp.status_code == 200:
            return resp.json().get("message", {}).get("content")
    except Exception as e:
        print(f"[Ollama Info] Local Ollama fallback triggered: {e}")
    return None


def _call_groq(prompt: str, json_format: bool = True) -> Optional[str]:
    """Fallback call to high-speed Groq Qwen model."""
    try:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        body: Dict[str, Any] = {
            "model": GROQ_MODEL,
            "messages": [
                {"role": "system", "content": "You are a specialized logistics NLP parser. Output strict JSON only."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1
        }
        if json_format:
            body["response_format"] = {"type": "json_object"}
            
        resp = requests.post(url, headers=headers, json=body, timeout=12)
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"[Groq Warning] Cloud fallback call failed: {e}")
    return None

def _heuristic_regex_extract(text: str) -> Dict[str, Any]:
    """Air-gapped regex heuristic fallback if both LLMs are unreachable."""
    container_match = re.search(r"\b([A-Z]{4}\d{7})\b", text)
    bol_match = re.search(r"(?:BOL|B/L)[:#\s]*([A-Z0-9]{8,15})", text, re.IGNORECASE)
    po_match = re.search(r"(?:PO|Order)[:#\s]*([A-Z0-9-]{4,15})", text, re.IGNORECASE)
    
    is_hold = bool(re.search(r"customs|examination|hold|inspection", text, re.IGNORECASE))
    is_delayed = bool(re.search(r"delay|congestion|late|postponed|rescheduled", text, re.IGNORECASE))
    
    event_type = "CUSTOMS_HOLD" if is_hold else ("DELAYED" if is_delayed else "IN_TRANSIT")
    
    return {
        "carrier": "Unknown Carrier",
        "container_no": container_match.group(1) if container_match else None,
        "bol_no": bol_match.group(1) if bol_match else None,
        "shipment_id": None,
        "po_number": po_match.group(1) if po_match else None,
        "event_type": event_type,
        "location": "Port of Los Angeles",
        "new_eta": None,
        "delay_hours_estimate": 48 if is_hold else (24 if is_delayed else 0),
        "delay_reason": "Extracted via regex fallback: " + text[:80],
        "urgency": "HIGH" if (is_hold or is_delayed) else "MEDIUM",
        "confidence": 0.70
    }

def extract_logistics_email(raw_text: str) -> Dict[str, Any]:
    """
    Extracts structured operational fields from free-text emails or carrier alerts.
    """
    prompt = EXTRACTION_PROMPT_TEMPLATE.format(text=raw_text)
    
    # 1. Try local Ollama
    raw_response = _call_ollama(prompt, json_format=True)
    source = "LOCAL_OLLAMA_QWEN"
    
    # 2. Try Groq Cloud Fallback
    if not raw_response:
        raw_response = _call_groq(prompt, json_format=True)
        source = "GROQ_CLOUD_QWEN"

    # 3. Parse JSON or trigger heuristic fallback
    if raw_response:
        try:
            # Clean markdown codeblocks if any
            clean_json = raw_response.strip()
            if clean_json.startswith("```"):
                clean_json = re.sub(r"^```(?:json)?\n?", "", clean_json)
                clean_json = re.sub(r"\n?```$", "", clean_json)
            extracted = json.loads(clean_json)
            extracted["extraction_source"] = source
            log_audit("NLP", "EXTRACTION", "EMAIL_EXTRACTED", source, extracted)
            return extracted
        except Exception as e:
            print(f"[NLP Parse Error] Failed to parse model output: {e}")

    # Fallback heuristic
    fallback = _heuristic_regex_extract(raw_text)
    fallback["extraction_source"] = "HEURISTIC_REGEX"
    log_audit("NLP", "EXTRACTION", "EMAIL_EXTRACTED_FALLBACK", "REGEX", fallback)
    return fallback

def summarize_incident(
    shipment_id: str,
    customer_name: str,
    customer_tier: str,
    exception_title: str,
    severity: str,
    total_risk: float,
    penalty: float,
    revenue: float,
    recommended_action: str
) -> str:
    """Summarizes incident for executive control tower desk."""
    prompt = SUMMARIZATION_PROMPT_TEMPLATE.format(
        shipment_id=shipment_id,
        customer_name=customer_name,
        customer_tier=customer_tier,
        exception_title=exception_title,
        severity=severity,
        total_risk=total_risk,
        penalty=penalty,
        revenue=revenue,
        recommended_action=recommended_action
    )
    res = _call_ollama(prompt, json_format=False) or _call_groq(prompt, json_format=False)
    if res:
        return res.strip()
    return f"CRITICAL: Shipment {shipment_id} ({customer_name}) affected by {exception_title} ({severity}). Total financial exposure is ${total_risk:,.2f}. Recommended: {recommended_action}."

def draft_customer_delay_notification(
    customer_name: str,
    po_number: str,
    revised_eta: str,
    mitigation_action: str
) -> str:
    """Drafts proactive customer delay notification."""
    prompt = DRAFTING_PROMPT_TEMPLATE.format(
        customer_name=customer_name,
        po_number=po_number,
        revised_eta=revised_eta,
        mitigation_action=mitigation_action
    )
    res = _call_ollama(prompt, json_format=False) or _call_groq(prompt, json_format=False)
    if res:
        return res.strip()
    return (
        f"Dear {customer_name},\n\nWe are actively monitoring your order PO #{po_number}. "
        f"Due to unforeseen port congestion, the revised delivery ETA is {revised_eta}. "
        f"To mitigate further impact, our control tower has initiated {mitigation_action}. "
        f"We will provide continuous tracking updates as your shipment progresses.\n\nSincerely,\nLogistics Operations Team"
    )
