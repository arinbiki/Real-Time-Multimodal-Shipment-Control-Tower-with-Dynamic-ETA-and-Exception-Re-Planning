"""
Event Normalization Service matching Section 9 of plan.md.
Transforms heterogeneous raw carrier/telematics/EDI events into canonical events.
"""
import uuid
import re
from datetime import datetime, timezone
from typing import Dict, Any, Tuple
from core.models import (
    CanonicalEvent, CanonicalEventCategory, CanonicalEventType
)

# Canonical mapping dictionaries
STATUS_MAP = {
    # Ocean status codes
    "DISCH": (CanonicalEventCategory.HANDLING, CanonicalEventType.DISCHARGED_FROM_VESSEL),
    "DEPARTED_PORT": (CanonicalEventCategory.DEPARTURE, CanonicalEventType.VESSEL_DEPARTED),
    "ARRIVED_PORT": (CanonicalEventCategory.ARRIVAL, CanonicalEventType.ARRIVED_AT_PORT),
    "LOADED": (CanonicalEventCategory.HANDLING, CanonicalEventType.LOADED_ON_VESSEL),
    "CUSTOMS_HOLD": (CanonicalEventCategory.CUSTOMS, CanonicalEventType.CUSTOMS_HOLD),
    "CUSTOMS_CLEARED": (CanonicalEventCategory.CUSTOMS, CanonicalEventType.CUSTOMS_RELEASED),
    "RELEASED": (CanonicalEventCategory.CUSTOMS, CanonicalEventType.CUSTOMS_RELEASED),
    
    # Road / Drayage / Rail status codes
    "X6": (CanonicalEventCategory.BOOKING, CanonicalEventType.SHIPMENT_BOOKED),
    "AF": (CanonicalEventCategory.DEPARTURE, CanonicalEventType.DEPARTED_ORIGIN),
    "P1": (CanonicalEventCategory.PICKUP, CanonicalEventType.PICKED_UP),
    "CP": (CanonicalEventCategory.HANDLING, CanonicalEventType.ARRIVED_AT_HUB),
    "I1": (CanonicalEventCategory.HANDLING, CanonicalEventType.IN_TRANSIT),
    "IN_TRANSIT": (CanonicalEventCategory.HANDLING, CanonicalEventType.IN_TRANSIT),
    "OUT_FOR_DELIVERY": (CanonicalEventCategory.DELIVERY, CanonicalEventType.OUT_FOR_DELIVERY),
    "OF": (CanonicalEventCategory.DELIVERY, CanonicalEventType.OUT_FOR_DELIVERY),
    "D1": (CanonicalEventCategory.DELIVERY, CanonicalEventType.DELIVERED),
    "DELIVERED": (CanonicalEventCategory.DELIVERY, CanonicalEventType.DELIVERED),
    "X1": (CanonicalEventCategory.PROOF_OF_DELIVERY, CanonicalEventType.POD_RECEIVED),
    "POD": (CanonicalEventCategory.PROOF_OF_DELIVERY, CanonicalEventType.POD_RECEIVED),
    
    # Delay and Disruption codes
    "DELAYED": (CanonicalEventCategory.DELAY, CanonicalEventType.DELAYED),
    "WEATHER_DELAY": (CanonicalEventCategory.DELAY, CanonicalEventType.DELAYED),
    "CONGESTION": (CanonicalEventCategory.DELAY, CanonicalEventType.DELAYED),
    "MECHANICAL_BREAKDOWN": (CanonicalEventCategory.EXCEPTION, CanonicalEventType.EXCEPTION_REPORTED),
    "EXCEPTION": (CanonicalEventCategory.EXCEPTION, CanonicalEventType.EXCEPTION_REPORTED),
}

# Standard Location Port / Ramp Codes
LOCATION_MAP = {
    "USLAX": "Port of Los Angeles / Long Beach, CA",
    "USCHI": "Chicago Intermodal Ramp, IL",
    "USNYC": "Port of New York / New Jersey",
    "USSEA": "Port of Seattle / Tacoma, WA",
    "USOAK": "Port of Oakland, CA",
    "CNSHA": "Port of Shanghai, China",
    "CNNBO": "Port of Ningbo, China",
    "KRPUS": "Port of Busan, South Korea",
    "JPTYO": "Port of Tokyo, Japan"
}

def parse_iso_or_flexible_datetime(dt_str: str) -> datetime:
    """Normalize any date/time string into a UTC datetime object."""
    if not dt_str:
        return datetime.now(timezone.utc)
    
    # Clean string
    dt_str = dt_str.strip()
    
    # Try standard ISO
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass
    
    # Common format fallbacks
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M",
        "%d-%m-%Y %H:%M:%S"
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(dt_str, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
            
    return datetime.now(timezone.utc)

def normalize_event(raw_payload: Dict[str, Any], raw_event_id: str = None) -> Tuple[CanonicalEvent, Dict[str, Any]]:
    """
    Normalizes incoming raw event dict into a CanonicalEvent.
    Returns (canonical_event, warnings_dict).
    """
    warnings = {}
    event_id = f"EVT-{uuid.uuid4().hex[:10].upper()}"
    
    # 1. Status classification
    raw_status = str(raw_payload.get("status") or raw_payload.get("event_type") or raw_payload.get("edi_code") or "").upper().strip()
    category, event_type = STATUS_MAP.get(raw_status, (CanonicalEventCategory.HANDLING, CanonicalEventType.IN_TRANSIT))
    
    if raw_status not in STATUS_MAP:
        warnings["unmapped_status"] = f"Status '{raw_status}' unmapped; defaulted to IN_TRANSIT"

    # 2. Timestamp normalization
    raw_time = raw_payload.get("timestamp") or raw_payload.get("event_time") or raw_payload.get("date")
    event_time_utc = parse_iso_or_flexible_datetime(raw_time)

    # 3. Location normalization
    loc_code = (raw_payload.get("location_code") or raw_payload.get("port") or raw_payload.get("terminal") or "").upper().strip()
    loc_name = LOCATION_MAP.get(loc_code, raw_payload.get("location_name") or loc_code or "In Transit Location")

    # 4. Carrier & Reference identification
    carrier_code = (raw_payload.get("carrier_code") or raw_payload.get("carrier") or raw_payload.get("scac") or "").upper().strip()
    delay_reason = raw_payload.get("reason") or raw_payload.get("delay_reason") or raw_payload.get("comment")

    # Source confidence
    confidence = float(raw_payload.get("confidence", 1.0))

    details = {
        "raw_status": raw_status,
        "vessel_name": raw_payload.get("vessel_name"),
        "voyage_number": raw_payload.get("voyage_number"),
        "coordinates": raw_payload.get("coordinates"),
        "dwell_hours": raw_payload.get("dwell_hours"),
        "estimated_impact": raw_payload.get("estimated_impact")
    }

    event = CanonicalEvent(
        event_id=event_id,
        raw_event_id=raw_event_id,
        internal_shipment_id=raw_payload.get("shipment_id"),  # May be None before entity resolution
        category=category,
        event_type=event_type,
        event_timestamp_utc=event_time_utc,
        location_code=loc_code,
        location_name=loc_name,
        carrier_code=carrier_code,
        delay_reason=delay_reason,
        source_confidence=confidence,
        details=details
    )

    return event, warnings
