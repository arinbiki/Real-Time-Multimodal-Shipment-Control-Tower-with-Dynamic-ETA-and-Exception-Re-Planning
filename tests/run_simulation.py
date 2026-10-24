"""
End-to-End Simulation Script matching Section 29 & Section 32 of plan.md.
Simulates:
1. Normal in-flight transit event.
2. Severe port congestion and customs hold disruption.
3. Dynamic ETA slippage calculation.
4. Multi-rule exception detection (P1 Critical SLA Breach).
5. Business impact assessment (Revenue at risk & penalty calculation).
6. Recovery option catalog generation and approval tier classification.
7. Unstructured carrier delay email parsing via Qwen NLP.
8. Operational approval execution.
"""
import sys
import io
# Ensure UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import datetime, timezone
from core.database import (
    get_shipment, get_open_exceptions, get_connection
)
from core.normalization import normalize_event
from core.entity_resolution import resolve_shipment_identity
from core.timeline import process_timeline_event
from core.eta_engine import recalculate_dynamic_eta
from core.exception_engine import evaluate_exceptions_for_shipment
from core.impact_engine import assess_business_impact
from core.recommendation_engine import generate_recovery_recommendations
from core.qwen_nlp import extract_logistics_email, draft_customer_delay_notification
from tests.seed_data import populate_seed_data

def run_control_tower_simulation():
    print("=" * 80)
    print(">>> REAL-TIME MULTIMODAL SHIPMENT CONTROL TOWER: END-TO-END SIMULATION <<<")
    print("=" * 80)


    # Reset seed data
    populate_seed_data()
    print("\n--- [STEP 1] Initial Shipment State (SHP-OCEAN-1001) ---")
    s = get_shipment("SHP-OCEAN-1001")
    print(f"Shipment ID       : {s.shipment_id} (TMS: {s.tms_reference})")
    print(f"Customer          : {s.customer_name} [{s.customer_tier.value}]")
    print(f"Current Status    : {s.current_status.value} at {s.current_location}")
    print(f"Baseline ETA      : {s.baseline_eta.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"Required Delivery : {s.required_delivery.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"Current ETA       : {s.current_eta.strftime('%Y-%m-%d %H:%M UTC')}")

    # =================================================================
    # SCENARIO 1: Vessel Arrival Event (Normal In-transit Progress)
    # =================================================================
    print("\n--- [STEP 2] Ingesting Vessel Arrival Event (Raw Webhook Signal) ---")
    arrival_event_raw = {
        "status": "ARRIVED_PORT",
        "container_no": "MSCU1234567",
        "carrier_code": "CMA CGM",
        "location_code": "USLAX",
        "location_name": "Port of Los Angeles / Long Beach, CA",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "vessel_name": "CMA CGM DAKAR"
    }

    # Normalize
    can_event, warnings = normalize_event(arrival_event_raw)
    print(f"Normalized Event  : {can_event.event_type.value} | Category: {can_event.category.value}")

    # Resolve Identity
    shipment_id, score, explanation, review_req = resolve_shipment_identity(arrival_event_raw)
    print(f"Entity Resolution : Matched Shipment '{shipment_id}' (Confidence: {score:.2f}) -> {explanation}")
    can_event.internal_shipment_id = shipment_id

    # Update Timeline
    is_new, msg, s_updated = process_timeline_event(can_event)
    print(f"Timeline Engine   : {msg}")

    # Recalculate ETA
    s_updated, eta_snap = recalculate_dynamic_eta(shipment_id, triggered_by_event_id=can_event.event_id)
    print(f"Dynamic ETA       : {s_updated.current_eta.strftime('%Y-%m-%d %H:%M UTC')} (Delay: {eta_snap.delay_hours:+.1f}h)")

    # =================================================================
    # SCENARIO 2: Catastrophic Port Strike & Customs Hold Disruption
    # =================================================================
    print("\n--- [STEP 3] DISRUPTION ALERT: Port Congestion & Customs Examination Hold ---")
    disruption_raw = {
        "status": "CUSTOMS_HOLD",
        "container_no": "MSCU1234567",
        "carrier_code": "CMA CGM",
        "location_code": "USLAX",
        "location_name": "Port of Los Angeles, Terminal Pier 400",
        "delay_reason": "Severe labor slowdown + Mandatory CBP intensive cargo x-ray exam",
        "delay_hours_estimate": 54.0,  # +54 hours catastrophic delay
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

    can_disruption, _ = normalize_event(disruption_raw)
    shipment_id, _, _, _ = resolve_shipment_identity(disruption_raw)
    can_disruption.internal_shipment_id = shipment_id
    process_timeline_event(can_disruption)

    # Dynamic ETA slippage calculation
    s_disrupted, eta_disrupted = recalculate_dynamic_eta(
        shipment_id=shipment_id,
        triggered_by_event_id=can_disruption.event_id,
        disruption_buffer_hours=54.0,
        disruption_reason="Severe port congestion + Customs examination hold"
    )
    print(f"🚨 SLIPPED ETA     : {s_disrupted.current_eta.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"🚨 SLIPPAGE vs PLAN: +{eta_disrupted.delay_hours:.1f} hours late!")
    print(f"🚨 EXPLANATION     : {eta_disrupted.explanation}")

    # =================================================================
    # SCENARIO 3: Exception Detection Engine
    # =================================================================
    print("\n--- [STEP 4] Exception Rule Engine Triggered ---")
    active_exceptions = evaluate_exceptions_for_shipment(shipment_id)
    print(f"Active Exceptions Detected: {len(active_exceptions)}")
    for exc in active_exceptions:
        print(f"  ⚡ [{exc.severity.value}] {exc.title}")
        print(f"     Details   : {exc.details}")
        print(f"     Days Late : {exc.days_late} days | Impact Score: {exc.impact_score}/100")

    # =================================================================
    # SCENARIO 4: Business Impact Analysis Engine
    # =================================================================
    primary_exception = active_exceptions[0]
    print(f"\n--- [STEP 5] Business Impact Analysis for {primary_exception.case_id} ---")
    impact = assess_business_impact(primary_exception)
    print(f"  💰 Revenue at Risk     : ${impact.revenue_at_risk:,.2f}")
    print(f"  💰 Contract SLA Penalty: ${impact.penalty_at_risk:,.2f}")
    print(f"  📈 Stockout Probability: {impact.stockout_risk_prob * 100:.1f}%")
    print(f"  🔥 Urgency Level       : {impact.urgency_level}")
    print(f"  🎯 TOTAL FINANCIAL RISK: ${impact.total_financial_risk:,.2f}")

    # =================================================================
    # SCENARIO 5: Autonomous Recovery Re-Planning Engine
    # =================================================================
    print(f"\n--- [STEP 6] Re-Planning Engine: Ranked Recovery Options Catalog ---")
    recommendations = generate_recovery_recommendations(primary_exception, impact)
    for i, r in enumerate(recommendations, 1):
        print(f"  {i}. [{r.approval_tier}] {r.title}")
        print(f"     Cost: ${r.cost_estimate:,.2f} | Time Recovered: {r.hours_saved:.0f} hrs | Net Score: +{r.net_service_score}")
        print(f"     Status: {r.feasibility_status}")

    top_rec = recommendations[0]
    print(f"\n🌟 TOP RECOMMENDATION: {top_rec.title}")
    print(f"   Approval Tier Required: {top_rec.approval_tier}")

    # =================================================================
    # SCENARIO 6: Qwen 3B Local NLP Assistant (Email Parsing)
    # =================================================================
    print("\n--- [STEP 7] Qwen 3B Local NLP Assistant: Carrier Email Ingestion ---")
    unstructured_carrier_email = """
    URGENT NOTICE FROM CMA CGM OPERATIONS:
    Due to terminal berth congestion at LA Pier 400, container MSCU1234567 on voyage 102
    under PO APEX-8801 has incurred an extended customs hold.
    Discharge delayed by approximately 48 hours. Please reschedule inland rail transfer.
    """
    print(f"Raw Carrier Email Ingested:\n{unstructured_carrier_email.strip()}\n")
    extracted_fields = extract_logistics_email(unstructured_carrier_email)
    print("Qwen 3B Extracted Fields (Structured JSON):")
    for k, v in extracted_fields.items():
        print(f"  - {k}: {v}")

    # Draft Stakeholder Communication
    print("\n--- [STEP 8] Drafting Proactive Stakeholder Notification ---")
    draft_email = draft_customer_delay_notification(
        customer_name=s.customer_name,
        po_number="PO-APEX-8801",
        revised_eta=s_disrupted.current_eta.strftime("%A, %B %d at %H:%M UTC"),
        mitigation_action=top_rec.title
    )
    print(f"Draft Email for Customer Success Team:\n{'-'*60}\n{draft_email}\n{'-'*60}")

    # =================================================================
    # SCENARIO 7: Human-in-the-Loop Operational Approval Execution
    # =================================================================
    print(f"\n--- [STEP 9] Human-in-the-Loop Operational Approval ---")
    conn = get_connection()
    approval_row = conn.execute(
        "SELECT * FROM approvals WHERE recommendation_id = ?",
        (top_rec.recommendation_id,)
    ).fetchone()

    if approval_row:
        app_id = approval_row["approval_id"]
        print(f"Approval Request ID : {app_id}")
        print(f"Required Role       : {approval_row['required_role']}")
        print(f"Current State       : {approval_row['status']}")

        # Simulate Supervisor Sign-off
        with conn:
            conn.execute("""
            UPDATE approvals
            SET status = 'APPROVED', approved_by = 'operations_supervisor_john',
                decision_timestamp = ?, comments = 'Approved dedicated team drayage to avoid $255k stockout.'
            WHERE approval_id = ?
            """, (datetime.now(timezone.utc).isoformat(), app_id))

            conn.execute("""
            UPDATE exception_cases
            SET status = 'MITIGATING'
            WHERE case_id = ?
            """, (primary_exception.case_id,))

        print("✅ Decision: APPROVED by 'operations_supervisor_john'")
        print("✅ Exception Case State updated to: 'MITIGATING'")
        print("✅ Dedicated Drayage Dispatch Order auto-routed to Carrier API.")

    print("\n" + "=" * 80)
    print("🎯 SIMULATION COMPLETE: All 6 Core Control Tower Questions Answered Autonomously!")
    print("=" * 80)

if __name__ == "__main__":
    run_control_tower_simulation()
