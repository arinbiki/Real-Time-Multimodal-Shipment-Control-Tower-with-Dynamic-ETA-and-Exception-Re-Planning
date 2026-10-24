"""
Shipment Timeline and State Machine Engine matching Section 10 and Section 11 of plan.md.
Maintains canonical milestone event log, performs deduplication fingerprinting,
and manages multimodal leg state transitions.
"""
import hashlib
from datetime import datetime, timezone
from typing import Tuple, Optional
from core.database import (
    get_shipment, save_shipment, get_shipment_legs, save_shipment_leg,
    save_canonical_event, get_canonical_events, log_audit
)
from core.models import (
    CanonicalEvent, Shipment, ShipmentLeg, ShipmentState,
    CanonicalEventType, CanonicalEventCategory
)

# State transition matrix
EVENT_TO_STATE = {
    CanonicalEventType.SHIPMENT_PLANNED: ShipmentState.PLANNED,
    CanonicalEventType.SHIPMENT_BOOKED: ShipmentState.BOOKED,
    CanonicalEventType.TENDERED: ShipmentState.TENDERED,
    CanonicalEventType.PICKED_UP: ShipmentState.PICKED_UP,
    CanonicalEventType.DEPARTED_ORIGIN: ShipmentState.IN_TRANSIT,
    CanonicalEventType.LOADED_ON_VESSEL: ShipmentState.IN_TRANSIT,
    CanonicalEventType.VESSEL_DEPARTED: ShipmentState.IN_TRANSIT,
    CanonicalEventType.ARRIVED_AT_PORT: ShipmentState.AT_HUB,
    CanonicalEventType.DISCHARGED_FROM_VESSEL: ShipmentState.AT_HUB,
    CanonicalEventType.CUSTOMS_HOLD: ShipmentState.CUSTOMS_HOLD,
    CanonicalEventType.CUSTOMS_RELEASED: ShipmentState.CUSTOMS_RELEASED,
    CanonicalEventType.ARRIVED_AT_HUB: ShipmentState.AT_HUB,
    CanonicalEventType.IN_TRANSIT: ShipmentState.IN_TRANSIT,
    CanonicalEventType.OUT_FOR_DELIVERY: ShipmentState.OUT_FOR_DELIVERY,
    CanonicalEventType.DELIVERED: ShipmentState.DELIVERED,
    CanonicalEventType.POD_RECEIVED: ShipmentState.DELIVERED,
    CanonicalEventType.EXCEPTION_REPORTED: ShipmentState.EXCEPTION,
}

def generate_dedup_fingerprint(event: CanonicalEvent) -> str:
    """
    Creates a unique fingerprint for deduplication.
    Bucket timestamp to 1-hour window to catch duplicate EDI transmissions.
    """
    hour_bucket = event.event_timestamp_utc.strftime("%Y-%m-%d-%H")
    raw_str = f"{event.internal_shipment_id}|{event.event_type.value}|{event.location_code or ''}|{hour_bucket}"
    return hashlib.sha256(raw_str.encode("utf-8")).hexdigest()

def process_timeline_event(event: CanonicalEvent) -> Tuple[bool, str, Optional[Shipment]]:
    """
    Processes a canonical event against the shipment timeline.
    Returns: (is_new_event, explanation, updated_shipment)
    """
    shipment_id = event.internal_shipment_id
    if not shipment_id:
        return False, "Event is missing internal_shipment_id", None

    shipment = get_shipment(shipment_id)
    if not shipment:
        return False, f"Shipment {shipment_id} not found in database", None

    # 1. Deduplication check against past events
    existing_events = get_canonical_events(shipment_id)
    new_fingerprint = generate_dedup_fingerprint(event)
    
    for prev in existing_events:
        if generate_dedup_fingerprint(prev) == new_fingerprint:
            log_audit("EVENT", event.event_id, "DUPLICATE_SUPPRESSED", "SYSTEM", {
                "shipment_id": shipment_id,
                "fingerprint": new_fingerprint,
                "original_event_id": prev.event_id
            })
            return False, f"Exact duplicate event suppressed (Matched {prev.event_id})", shipment

    # 2. Persist Canonical Event to Timeline
    save_canonical_event(event)

    # 3. State Machine Transition
    new_state = EVENT_TO_STATE.get(event.event_type)
    if new_state and new_state != shipment.current_status:
        old_state = shipment.current_status
        shipment.current_status = new_state
        log_audit("SHIPMENT", shipment_id, "STATE_TRANSITION", "SYSTEM", {
            "from_state": old_state.value,
            "to_state": new_state.value,
            "event_type": event.event_type.value
        })

    # Update current location & timestamp
    if event.location_name:
        shipment.current_location = event.location_name
    shipment.last_event_timestamp = event.event_timestamp_utc

    # 4. Multimodal Leg Progression
    legs = get_shipment_legs(shipment_id)
    if legs:
        active_leg = None
        for leg in legs:
            if leg.sequence == shipment.active_leg_sequence:
                active_leg = leg
                break
        
        if active_leg:
            # Advance progress on events
            if event.event_type in (CanonicalEventType.DEPARTED_ORIGIN, CanonicalEventType.VESSEL_DEPARTED):
                active_leg.status = "IN_TRANSIT"
                active_leg.actual_start = event.event_timestamp_utc
                active_leg.current_progress_pct = 15.0
            elif event.event_type == CanonicalEventType.IN_TRANSIT:
                active_leg.status = "IN_TRANSIT"
                active_leg.current_progress_pct = min(active_leg.current_progress_pct + 25.0, 85.0)
            elif event.event_type in (CanonicalEventType.ARRIVED_AT_PORT, CanonicalEventType.ARRIVED_AT_HUB, CanonicalEventType.DISCHARGED_FROM_VESSEL):
                active_leg.status = "COMPLETED"
                active_leg.actual_end = event.event_timestamp_utc
                active_leg.current_progress_pct = 100.0
                save_shipment_leg(active_leg)
                
                # Advance to next leg if available
                if shipment.active_leg_sequence < shipment.total_legs:
                    shipment.active_leg_sequence += 1
                    next_leg = next((l for l in legs if l.sequence == shipment.active_leg_sequence), None)
                    if next_leg:
                        next_leg.status = "IN_PROGRESS"
                        next_leg.actual_start = event.event_timestamp_utc
                        save_shipment_leg(next_leg)
            elif event.event_type in (CanonicalEventType.DELIVERED, CanonicalEventType.POD_RECEIVED):
                active_leg.status = "COMPLETED"
                active_leg.actual_end = event.event_timestamp_utc
                active_leg.current_progress_pct = 100.0
                save_shipment_leg(active_leg)

            save_shipment_leg(active_leg)

    save_shipment(shipment)
    return True, f"Event successfully added to timeline. State: {shipment.current_status.value}", shipment
