"""
Exception Detection Engine matching Section 13 of plan.md.
Evaluates Rules 1 through 5:
- Rule 1: ETA vs Required Delivery Date & Customer Priority Buffer
- Rule 2: Missed Milestone
- Rule 3: Visibility Gap
- Rule 4: Excessive Dwell Time
- Rule 5: Customs Hold
"""
import uuid
from datetime import datetime, timezone
from typing import List, Optional
from core.database import (
    get_shipment, get_shipment_legs, get_canonical_events,
    get_open_exceptions, save_exception_case, log_audit
)
from core.models import (
    Shipment, ExceptionCase, ExceptionSeverity, ExceptionStatus,
    CanonicalEventType, ShipmentState
)
from core.config import (
    CUSTOMER_TIER_BUFFERS, VISIBILITY_GAP_THRESHOLDS, DWELL_THRESHOLDS
)

def evaluate_exceptions_for_shipment(shipment_id: str) -> List[ExceptionCase]:
    """
    Evaluates all exception rules against a shipment and returns any newly created or active cases.
    """
    shipment = get_shipment(shipment_id)
    if not shipment:
        return []

    legs = get_shipment_legs(shipment_id)
    events = get_canonical_events(shipment_id)
    open_cases = get_open_exceptions(shipment_id)
    open_rule_ids = {c.rule_id for c in open_cases}
    
    new_exceptions: List[ExceptionCase] = []
    now_utc = datetime.now(timezone.utc)

    # -----------------------------------------------------------------
    # RULE 1: ETA vs Required Customer Date
    # -----------------------------------------------------------------
    tier_buffer_hrs = CUSTOMER_TIER_BUFFERS.get(shipment.customer_tier.value, 12)
    delay_hours = (shipment.current_eta - shipment.required_delivery).total_seconds() / 3600.0
    days_late = max(0.0, delay_hours / 24.0)

    if delay_hours > tier_buffer_hrs:
        rule_id = "RULE_01_SLA_BREACH"
        if rule_id not in open_rule_ids:
            # Determine severity based on customer tier & delay
            if shipment.customer_tier.value == "TIER_1_STRATEGIC" or delay_hours > 48:
                severity = ExceptionSeverity.P1_CRITICAL
            elif delay_hours > 24:
                severity = ExceptionSeverity.P2_HIGH
            else:
                severity = ExceptionSeverity.P3_MEDIUM

            case = ExceptionCase(
                case_id=f"EXC-{uuid.uuid4().hex[:8].upper()}",
                shipment_id=shipment_id,
                exception_category="DELAY_RISK",
                rule_id=rule_id,
                severity=severity,
                status=ExceptionStatus.OPEN,
                detected_at=now_utc,
                title=f"Delivery SLA Breach Risk ({shipment.customer_tier.value})",
                details=(
                    f"Current ETA ({shipment.current_eta.strftime('%Y-%m-%d %H:%M')}) exceeds "
                    f"required date ({shipment.required_delivery.strftime('%Y-%m-%d %H:%M')}) by {delay_hours:.1f} hours. "
                    f"Exceeds customer tier buffer of {tier_buffer_hrs}h."
                ),
                days_late=round(days_late, 2),
                impact_score=round(min(100.0, delay_hours * 2.5), 1)
            )
            save_exception_case(case)
            new_exceptions.append(case)
            log_audit("EXCEPTION", case.case_id, "EXCEPTION_RAISED", "RULE_ENGINE", {"rule": rule_id, "delay_hours": delay_hours})

    # -----------------------------------------------------------------
    # RULE 2: Customs Hold
    # -----------------------------------------------------------------
    has_active_customs_hold = any(
        ev.event_type == CanonicalEventType.CUSTOMS_HOLD for ev in events[-3:]
    )
    if has_active_customs_hold:
        rule_id = "RULE_02_CUSTOMS_HOLD"
        if rule_id not in open_rule_ids:
            case = ExceptionCase(
                case_id=f"EXC-{uuid.uuid4().hex[:8].upper()}",
                shipment_id=shipment_id,
                exception_category="CUSTOMS_HOLD",
                rule_id=rule_id,
                severity=ExceptionSeverity.P1_CRITICAL,
                status=ExceptionStatus.OPEN,
                detected_at=now_utc,
                title="Critical Customs Examination Hold",
                details=f"Customs authority placed hold at {shipment.current_location or 'Port of Discharge'}. Release documentation required.",
                days_late=round(days_late, 2),
                impact_score=85.0
            )
            save_exception_case(case)
            new_exceptions.append(case)
            log_audit("EXCEPTION", case.case_id, "EXCEPTION_RAISED", "RULE_ENGINE", {"rule": rule_id})

    # -----------------------------------------------------------------
    # RULE 3: Visibility Gap (Stale Tracking)
    # -----------------------------------------------------------------
    if shipment.current_status not in (ShipmentState.DELIVERED, ShipmentState.CANCELLED):
        last_event_time = shipment.last_event_timestamp or shipment.planned_pickup
        hours_since_last_event = (now_utc - last_event_time).total_seconds() / 3600.0
        
        # Get active leg mode
        active_leg = next((l for l in legs if l.sequence == shipment.active_leg_sequence), None)
        mode_val = active_leg.mode.value if active_leg else "ROAD_FTL"
        gap_threshold = VISIBILITY_GAP_THRESHOLDS.get(mode_val, 12)

        if hours_since_last_event > gap_threshold:
            rule_id = "RULE_03_VISIBILITY_GAP"
            if rule_id not in open_rule_ids:
                case = ExceptionCase(
                    case_id=f"EXC-{uuid.uuid4().hex[:8].upper()}",
                    shipment_id=shipment_id,
                    exception_category="VISIBILITY_GAP",
                    rule_id=rule_id,
                    severity=ExceptionSeverity.P3_MEDIUM,
                    status=ExceptionStatus.OPEN,
                    detected_at=now_utc,
                    title=f"Tracking Visibility Gap ({mode_val})",
                    details=f"No tracking event received for {hours_since_last_event:.1f} hours (Mode SLA: {gap_threshold}h). Carrier poll required.",
                    days_late=0.0,
                    impact_score=40.0
                )
                save_exception_case(case)
                new_exceptions.append(case)
                log_audit("EXCEPTION", case.case_id, "EXCEPTION_RAISED", "RULE_ENGINE", {"rule": rule_id, "hours_stale": hours_since_last_event})

    # -----------------------------------------------------------------
    # RULE 4: Excessive Dwell Time at Port / Hub
    # -----------------------------------------------------------------
    if shipment.current_status == ShipmentState.AT_HUB and events:
        last_arrival_event = next(
            (ev for ev in reversed(events) if ev.event_type in (CanonicalEventType.ARRIVED_AT_PORT, CanonicalEventType.ARRIVED_AT_HUB, CanonicalEventType.DISCHARGED_FROM_VESSEL)),
            None
        )
        if last_arrival_event:
            dwell_hours = (now_utc - last_arrival_event.event_timestamp_utc).total_seconds() / 3600.0
            dwell_limit = DWELL_THRESHOLDS.get("PORT_DISCHARGE", 72)
            
            if dwell_hours > dwell_limit:
                rule_id = "RULE_04_DWELL_EXCEEDED"
                if rule_id not in open_rule_ids:
                    case = ExceptionCase(
                        case_id=f"EXC-{uuid.uuid4().hex[:8].upper()}",
                        shipment_id=shipment_id,
                        exception_category="DWELL_EXCEEDED",
                        rule_id=rule_id,
                        severity=ExceptionSeverity.P2_HIGH,
                        status=ExceptionStatus.OPEN,
                        detected_at=now_utc,
                        title="Demurrage Threat: Terminal Dwell Exceeded",
                        details=f"Container has dwelled at {shipment.current_location} for {dwell_hours:.1f} hours (Free-time threshold: {dwell_limit}h). Demurrage charges imminent.",
                        days_late=round(days_late, 2),
                        impact_score=75.0
                    )
                    save_exception_case(case)
                    new_exceptions.append(case)
                    log_audit("EXCEPTION", case.case_id, "EXCEPTION_RAISED", "RULE_ENGINE", {"rule": rule_id, "dwell_hours": dwell_hours})

    return new_exceptions
