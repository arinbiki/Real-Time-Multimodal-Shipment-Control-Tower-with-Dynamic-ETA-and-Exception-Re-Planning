"""
Dynamic ETA Engine matching Section 12 of plan.md.
Calculates multimodal leg-by-leg dynamic ETAs, dwell time adjustments,
confidence scoring, and persists auditable ETA snapshots.
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Tuple, Dict, Any
from core.database import (
    get_shipment, save_shipment, get_shipment_legs, save_shipment_leg,
    save_eta_snapshot, get_canonical_events, log_audit
)
from core.models import Shipment, ETASnapshot, CanonicalEventType, ShipmentState

# Mode average transit speeds (km/h) and typical dwell buffers (hours)
MODE_METRICS = {
    "ROAD_FTL": {"avg_speed_kmh": 65.0, "dwell_buffer_hrs": 3.0},
    "ROAD_LTL": {"avg_speed_kmh": 50.0, "dwell_buffer_hrs": 6.0},
    "OCEAN": {"avg_speed_kmh": 32.0, "dwell_buffer_hrs": 36.0},     # 36 hrs port dwell
    "AIR": {"avg_speed_kmh": 650.0, "dwell_buffer_hrs": 8.0},
    "RAIL": {"avg_speed_kmh": 40.0, "dwell_buffer_hrs": 18.0},
    "PARCEL": {"avg_speed_kmh": 55.0, "dwell_buffer_hrs": 4.0}
}

def recalculate_dynamic_eta(
    shipment_id: str,
    triggered_by_event_id: str = None,
    disruption_buffer_hours: float = 0.0,
    disruption_reason: str = None
) -> Tuple[Shipment, ETASnapshot]:
    """
    Computes updated dynamic ETA for a multimodal shipment.
    Iterates through all legs (completed, active, upcoming),
    applies progress modeling and dwell buffers, and updates the shipment record.
    """
    shipment = get_shipment(shipment_id)
    if not shipment:
        raise ValueError(f"Shipment {shipment_id} not found")

    legs = get_shipment_legs(shipment_id)
    events = get_canonical_events(shipment_id)
    
    now_utc = datetime.now(timezone.utc)
    running_eta = None
    accumulated_delay_hours = disruption_buffer_hours
    confidence = 1.0

    # Check for active customs holds or port congestion in recent events
    active_hold = False
    for ev in events[-3:]:
        if ev.event_type == CanonicalEventType.CUSTOMS_HOLD:
            active_hold = True
            accumulated_delay_hours += 48.0  # 48 hr hold estimate
            disruption_reason = disruption_reason or "Active Customs Hold"
        elif ev.event_type == CanonicalEventType.DELAYED:
            accumulated_delay_hours += 24.0  # Port / carrier congestion delay
            disruption_reason = disruption_reason or (ev.delay_reason or "Carrier Delay Reported")

    # Evaluate legs sequentially
    current_time_cursor = shipment.planned_pickup
    
    for leg in legs:
        mode_cfg = MODE_METRICS.get(leg.mode.value, {"avg_speed_kmh": 50.0, "dwell_buffer_hrs": 4.0})
        
        if leg.status == "COMPLETED" and leg.actual_end:
            current_time_cursor = leg.actual_end
        elif leg.sequence == shipment.active_leg_sequence:
            # Active Leg: Compute remaining time
            remaining_pct = max(0.0, 1.0 - (leg.current_progress_pct / 100.0))
            nominal_duration_hrs = (leg.distance_km / mode_cfg["avg_speed_kmh"]) + mode_cfg["dwell_buffer_hrs"]
            remaining_leg_hrs = nominal_duration_hrs * remaining_pct
            
            # Leg estimated end
            leg_start = leg.actual_start or leg.planned_start
            current_time_cursor = max(now_utc, leg_start) + timedelta(hours=remaining_leg_hrs)
            leg.estimated_end = current_time_cursor
            save_shipment_leg(leg)
        else:
            # Future leg: add nominal planned duration + dwell buffer
            nominal_duration_hrs = (leg.distance_km / mode_cfg["avg_speed_kmh"]) + mode_cfg["dwell_buffer_hrs"]
            current_time_cursor = current_time_cursor + timedelta(hours=nominal_duration_hrs)
            leg.estimated_end = current_time_cursor
            save_shipment_leg(leg)

    # Final calculated ETA is the final leg's estimated end + cumulative disruption buffers
    dynamic_eta = current_time_cursor + timedelta(hours=accumulated_delay_hours)
    
    # Calculate delay variance against baseline ETA and required delivery date
    delay_vs_baseline_hrs = (dynamic_eta - shipment.baseline_eta).total_seconds() / 3600.0
    delay_vs_required_hrs = (dynamic_eta - shipment.required_delivery).total_seconds() / 3600.0

    # Confidence calculation: decays if no events received recently
    if shipment.last_event_timestamp:
        hours_since_last_event = (now_utc - shipment.last_event_timestamp).total_seconds() / 3600.0
        if hours_since_last_event > 24:
            confidence = max(0.5, 1.0 - (hours_since_last_event - 24) * 0.02)
    else:
        confidence = 0.85

    # Explainability text
    explanation_parts = [
        f"Dynamic ETA updated to {dynamic_eta.strftime('%Y-%m-%d %H:%M UTC')}."
    ]
    if accumulated_delay_hours > 0:
        explanation_parts.append(f"Includes +{accumulated_delay_hours:.1f}h buffer due to: {disruption_reason or 'disruption'}.")
    if delay_vs_required_hrs > 0:
        explanation_parts.append(f"WARNING: Slipping required customer date by {delay_vs_required_hrs:.1f} hours.")
    else:
        explanation_parts.append(f"On schedule (margin: {abs(delay_vs_required_hrs):.1f} hours buffer).")
    
    explanation = " ".join(explanation_parts)

    # Update shipment
    shipment.current_eta = dynamic_eta
    shipment.confidence_score = round(confidence, 2)
    save_shipment(shipment)

    # Create ETA snapshot
    snapshot = ETASnapshot(
        snapshot_id=f"SNAP-{uuid.uuid4().hex[:10].upper()}",
        shipment_id=shipment_id,
        calculated_at=now_utc,
        current_eta_utc=dynamic_eta,
        baseline_eta_utc=shipment.baseline_eta,
        delay_hours=round(delay_vs_baseline_hrs, 1),
        confidence_score=round(confidence, 2),
        explanation=explanation,
        triggered_by_event_id=triggered_by_event_id
    )
    save_eta_snapshot(snapshot)

    log_audit("ETA", shipment_id, "ETA_RECALCULATED", "SYSTEM", {
        "new_eta": dynamic_eta.isoformat(),
        "delay_vs_baseline_hrs": delay_vs_baseline_hrs,
        "delay_vs_required_hrs": delay_vs_required_hrs,
        "confidence": confidence
    })

    return shipment, snapshot
