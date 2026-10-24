"""
Business Impact Analysis Engine matching Section 14 of plan.md.
Calculates monetary and operational risk for an active exception:
- Revenue at Risk
- SLA Contract Penalties / Chargebacks
- Stockout Risk Probability
- Customer Criticality Weighting
"""
import uuid
from typing import Optional
from core.database import (
    get_shipment, get_orders_for_shipment, save_impact_assessment, log_audit
)
from core.models import ExceptionCase, ImpactAssessment

def assess_business_impact(exception_case: ExceptionCase) -> ImpactAssessment:
    """
    Computes quantified financial and operational impact for an exception case.
    """
    shipment_id = exception_case.shipment_id
    shipment = get_shipment(shipment_id)
    if not shipment:
        raise ValueError(f"Shipment {shipment_id} not found")

    orders = get_orders_for_shipment(shipment_id)
    
    total_revenue = sum(o.total_revenue for o in orders) if orders else 25000.0
    days_late = exception_case.days_late
    
    # Calculate contract penalty risk
    total_penalty = 0.0
    if days_late > 0:
        for o in orders:
            total_penalty += days_late * o.penalty_rate_per_day
    elif exception_case.exception_category == "DWELL_EXCEEDED":
        # Estimate demurrage charge ($350/day)
        total_penalty = 350.0 * 3.0  # 3 days estimated overage

    # Stockout probability curve based on days late and customer tier
    tier = shipment.customer_tier.value
    if tier == "TIER_1_STRATEGIC":
        # Fragile supply chain / JIT manufacturing
        stockout_prob = min(1.0, 0.40 + (days_late * 0.25)) if days_late > 0 else 0.20
        urgency = "IMMEDIATE_INTERVENTION" if days_late > 0.5 or exception_case.severity.value == "P1_CRITICAL" else "HIGH"
    elif tier == "TIER_2_ENTERPRISE":
        stockout_prob = min(0.85, 0.25 + (days_late * 0.15)) if days_late > 0 else 0.10
        urgency = "HIGH" if days_late > 1.0 else "MEDIUM"
    else:
        stockout_prob = min(0.60, 0.10 + (days_late * 0.10)) if days_late > 0 else 0.05
        urgency = "MEDIUM" if days_late > 2.0 else "LOW"

    # Total financial exposure = Contract Penalty + Revenue at Risk * stockout probability
    total_risk = total_penalty + (total_revenue * stockout_prob)

    assessment = ImpactAssessment(
        impact_id=f"IMP-{uuid.uuid4().hex[:8].upper()}",
        case_id=exception_case.case_id,
        shipment_id=shipment_id,
        revenue_at_risk=round(total_revenue, 2),
        penalty_at_risk=round(total_penalty, 2),
        stockout_risk_prob=round(stockout_prob, 2),
        affected_orders_count=len(orders) if orders else 1,
        customer_criticality=tier,
        urgency_level=urgency,
        total_financial_risk=round(total_risk, 2),
        details={
            "days_late": days_late,
            "orders": [o.order_id for o in orders],
            "severity": exception_case.severity.value
        }
    )

    save_impact_assessment(assessment)
    log_audit("IMPACT", assessment.impact_id, "IMPACT_EVALUATED", "SYSTEM", {
        "case_id": exception_case.case_id,
        "financial_risk": assessment.total_financial_risk,
        "urgency": urgency
    })

    return assessment
