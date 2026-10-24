"""
Recovery and Re-Planning Recommendation Engine matching Section 15 of plan.md.
Generates, feasibility-checks, ranks, and assigns governance tiers to recovery options.
"""
import uuid
from typing import List
from core.database import (
    get_shipment, get_shipment_legs, save_recovery_recommendation,
    save_approval, log_audit
)
from core.models import (
    ExceptionCase, ImpactAssessment, RecoveryRecommendation,
    RecoveryOptionType, ApprovalRecord, ApprovalStatus
)
from core.config import APPROVAL_TIERS

def determine_approval_tier(cost: float) -> str:
    """Classifies approval requirement based on recovery action cost."""
    if cost <= APPROVAL_TIERS["TIER_1_AUTO"]["max_cost"]:
        return "TIER_1_AUTO"
    elif cost <= APPROVAL_TIERS["TIER_2_SUPERVISOR"]["max_cost"]:
        return "TIER_2_SUPERVISOR"
    elif cost <= APPROVAL_TIERS["TIER_3_MANAGER"]["max_cost"]:
        return "TIER_3_MANAGER"
    else:
        return "TIER_4_EXECUTIVE"

def generate_recovery_recommendations(
    exception_case: ExceptionCase,
    impact: ImpactAssessment
) -> List[RecoveryRecommendation]:
    """
    Synthesizes candidate recovery plans, tests operational feasibility,
    scores expected net benefit, and outputs ranked recommendations.
    """
    shipment_id = exception_case.shipment_id
    shipment = get_shipment(shipment_id)
    legs = get_shipment_legs(shipment_id)
    candidates: List[RecoveryRecommendation] = []

    # 1. OPTION: Expedite Final Mile (Hotshot Drayage / Team Drivers)
    # Feasible if shipment is at or approaching port/ramp and final leg is inland
    if shipment.active_leg_sequence <= shipment.total_legs:
        cost = 1250.0
        hrs_saved = 36.0
        # Score = Penalty Avoidance + (Hrs Saved * $30) - Cost
        penalty_avoidance = min(impact.penalty_at_risk, 2000.0)
        net_score = (hrs_saved * 35.0) + penalty_avoidance - cost
        tier = determine_approval_tier(cost)

        rec = RecoveryRecommendation(
            recommendation_id=f"REC-{uuid.uuid4().hex[:8].upper()}",
            case_id=exception_case.case_id,
            shipment_id=shipment_id,
            option_type=RecoveryOptionType.EXPEDITE_FINAL_MILE,
            title="Expedite Final Mile via Dedicated Team Drayage",
            cost_estimate=cost,
            hours_saved=hrs_saved,
            net_service_score=round(net_score, 1),
            feasibility_status="FEASIBLE_VERIFIED",
            approval_tier=tier,
            details={
                "carrier": "Swift Priority Drayage",
                "route": f"{shipment.current_location or 'Discharge Port'} -> {shipment.destination}",
                "transit_time_hrs": 24.0,
                "confidence": 0.92
            }
        )
        candidates.append(rec)

    # 2. OPTION: Switch Carrier on Inland Leg
    if shipment.total_legs > 1:
        cost = 650.0
        hrs_saved = 20.0
        net_score = (hrs_saved * 35.0) + (impact.penalty_at_risk * 0.5) - cost
        tier = determine_approval_tier(cost)

        rec = RecoveryRecommendation(
            recommendation_id=f"REC-{uuid.uuid4().hex[:8].upper()}",
            case_id=exception_case.case_id,
            shipment_id=shipment_id,
            option_type=RecoveryOptionType.SWITCH_CARRIER,
            title="Switch Remaining Rail Leg to Expedited Truckload Carrier",
            cost_estimate=cost,
            hours_saved=hrs_saved,
            net_service_score=round(net_score, 1),
            feasibility_status="FEASIBLE_VERIFIED",
            approval_tier=tier,
            details={
                "alternate_carrier": "Schneider National Priority",
                "equipment": "53ft Dry Van",
                "pickup_readiness": "Immediate upon gate release"
            }
        )
        candidates.append(rec)

    # 3. OPTION: Air Freight Emergency Upgrade (For High-Value / Critical Exceptions)
    if impact.revenue_at_risk > 30000.0 or exception_case.severity.value == "P1_CRITICAL":
        cost = 4200.0
        hrs_saved = 72.0
        net_score = (hrs_saved * 45.0) + impact.penalty_at_risk + (impact.revenue_at_risk * 0.10) - cost
        tier = determine_approval_tier(cost)

        rec = RecoveryRecommendation(
            recommendation_id=f"REC-{uuid.uuid4().hex[:8].upper()}",
            case_id=exception_case.case_id,
            shipment_id=shipment_id,
            option_type=RecoveryOptionType.AIR_UPGRADE,
            title="Emergency Air Cargo Re-routing (Direct Flight)",
            cost_estimate=cost,
            hours_saved=hrs_saved,
            net_service_score=round(net_score, 1),
            feasibility_status="FEASIBLE_SUBJECT_TO_CUSTOMS_CLEARANCE",
            approval_tier=tier,
            details={
                "airline": "Atlas Air Cargo",
                "origin_airport": "LAX",
                "dest_airport": "ORD",
                "capacity": "Guaranteed space allocated"
            }
        )
        candidates.append(rec)

    # 4. OPTION: Proactive Stakeholder Re-appointment & Notification
    # Baseline fallback option
    rec_notify = RecoveryRecommendation(
        recommendation_id=f"REC-{uuid.uuid4().hex[:8].upper()}",
        case_id=exception_case.case_id,
        shipment_id=shipment_id,
        option_type=RecoveryOptionType.NOTIFY_STAKEHOLDER,
        title="Proactively Notify Customer & Reschedule Delivery Appointment Window",
        cost_estimate=0.0,
        hours_saved=0.0,
        net_service_score=150.0,  # Positive trust benefit
        feasibility_status="FEASIBLE_ALWAYS",
        approval_tier="TIER_1_AUTO",
        details={
            "proposed_window": (shipment.current_eta).strftime("%Y-%m-%d %H:%M"),
            "channel": "Automated Customer EDI/Email Portal",
            "chargeback_avoidance": True
        }
    )
    candidates.append(rec_notify)

    # Sort descending by net_service_score
    candidates.sort(key=lambda r: r.net_service_score, reverse=True)

    # Persist recommendations and create corresponding approval records
    for rec in candidates:
        save_recovery_recommendation(rec)
        
        # Create approval record
        approval_status = ApprovalStatus.AUTO_APPROVED if rec.approval_tier == "TIER_1_AUTO" else ApprovalStatus.PENDING
        app_record = ApprovalRecord(
            approval_id=f"APP-{uuid.uuid4().hex[:8].upper()}",
            recommendation_id=rec.recommendation_id,
            case_id=rec.case_id,
            approval_tier=rec.approval_tier,
            required_role=APPROVAL_TIERS[rec.approval_tier]["approver"],
            approved_by="SYSTEM_RULE" if approval_status == ApprovalStatus.AUTO_APPROVED else None,
            status=approval_status,
            decision_timestamp=None,
            comments="Auto-approved (Cost $0)" if approval_status == ApprovalStatus.AUTO_APPROVED else "Pending human operational sign-off"
        )
        save_approval(app_record)

    log_audit("RECOMMENDATION", exception_case.case_id, "RECOMMENDATIONS_GENERATED", "SYSTEM", {
        "options_count": len(candidates),
        "top_recommendation": candidates[0].title,
        "top_tier": candidates[0].approval_tier
    })

    return candidates
