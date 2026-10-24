"""
FastAPI Decision Engine REST Server for n8n Orchestration Layer.
Exposes endpoints matching Section 16 & 17 of plan.md:
- /api/v1/events/ingest: Complete pipeline (Raw -> Normalize -> Resolve -> Timeline -> ETA -> Exceptions -> Impact -> Recommendations)
- /api/v1/nlp/extract-email: Qwen 3B unstructured carrier email extraction
- /api/v1/nlp/draft-notification: Proactive customer notification drafting
- /api/v1/shipments/{id}: Detailed Control Tower shipment status & timeline
- /api/v1/exceptions: Active Control Tower exception desk
- /api/v1/approvals/{id}/action: Human-in-the-loop operational approval execution
"""
import uuid
import hashlib
import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core.database import (
    init_db, save_raw_event, get_shipment, get_shipment_legs,
    get_canonical_events, get_open_exceptions, get_connection, log_audit
)
from core.normalization import normalize_event
from core.entity_resolution import resolve_shipment_identity
from core.timeline import process_timeline_event
from core.eta_engine import recalculate_dynamic_eta
from core.exception_engine import evaluate_exceptions_for_shipment
from core.impact_engine import assess_business_impact
from core.recommendation_engine import generate_recovery_recommendations
from core.qwen_nlp import extract_logistics_email, draft_customer_delay_notification, summarize_incident

# Initialize app and database
init_db()
app = FastAPI(
    title="Multimodal Shipment Control Tower Decision Engine",
    description="Python Decision & Analytics Backbone for n8n Orchestration Layer",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class IngestEventRequest(BaseModel):
    source_system: str = "CARRIER_WEBHOOK"
    raw_payload: Dict[str, Any]

class EmailExtractionRequest(BaseModel):
    email_text: str
    source_sender: Optional[str] = "carrier-dispatch@logistics.com"

class ApprovalActionRequest(BaseModel):
    action: str  # "APPROVE" or "REJECT"
    approved_by: str
    comments: Optional[str] = None

@app.get("/")
def health_check():
    return {
        "status": "HEALTHY",
        "service": "Multimodal Shipment Control Tower Decision Engine",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@app.post("/api/v1/events/ingest")
def ingest_and_process_event(req: IngestEventRequest):
    """
    Primary n8n integration endpoint:
    Ingests raw signals, normalizes, resolves identity, updates timeline,
    evaluates dynamic ETA, evaluates exceptions, computes impact, and creates recommendations.
    """
    raw_id = f"RAW-{uuid.uuid4().hex[:10].upper()}"
    raw_json_str = json.dumps(req.raw_payload, sort_keys=True, default=str)
    payload_hash = hashlib.sha256(raw_json_str.encode("utf-8")).hexdigest()

    # 1. Immutable Raw Ingestion Ledger
    save_raw_event(raw_id, req.source_system, payload_hash, req.raw_payload)

    # 2. Event Normalization
    canonical_event, warnings = normalize_event(req.raw_payload, raw_event_id=raw_id)

    # 3. Entity Resolution (3-Tier Match)
    resolved_id, match_score, match_explanation, review_required = resolve_shipment_identity(req.raw_payload)
    
    if not resolved_id:
        return {
            "status": "QUARANTINED_UNRESOLVED",
            "raw_id": raw_id,
            "match_score": match_score,
            "explanation": match_explanation,
            "review_required": True,
            "canonical_event": canonical_event.dict()
        }

    canonical_event.internal_shipment_id = resolved_id

    # 4. Timeline Update & Deduplication
    is_new, timeline_msg, shipment = process_timeline_event(canonical_event)
    if not is_new:
        return {
            "status": "DUPLICATE_SUPPRESSED",
            "raw_id": raw_id,
            "shipment_id": resolved_id,
            "message": timeline_msg
        }

    # 5. Dynamic ETA Recalculation
    disruption_buffer = float(req.raw_payload.get("delay_hours_estimate") or 0.0)
    disruption_reason = req.raw_payload.get("delay_reason")
    updated_shipment, eta_snapshot = recalculate_dynamic_eta(
        shipment_id=resolved_id,
        triggered_by_event_id=canonical_event.event_id,
        disruption_buffer_hours=disruption_buffer,
        disruption_reason=disruption_reason
    )

    # 6. Exception Detection (Rules 1-5)
    new_exceptions = evaluate_exceptions_for_shipment(resolved_id)
    
    # 7. Impact Analysis & Recovery Recommendations
    exception_details = []
    for exc in new_exceptions:
        impact = assess_business_impact(exc)
        recommendations = generate_recovery_recommendations(exc, impact)
        exception_details.append({
            "exception": exc.dict(),
            "impact": impact.dict(),
            "recommendations": [r.dict() for r in recommendations]
        })

    return {
        "status": "PROCESSED_SUCCESSFULLY",
        "raw_id": raw_id,
        "event_id": canonical_event.event_id,
        "shipment_id": resolved_id,
        "match_explanation": match_explanation,
        "review_required": review_required,
        "timeline_status": shipment.current_status.value,
        "current_location": shipment.current_location,
        "dynamic_eta": updated_shipment.current_eta.isoformat(),
        "delay_hours_vs_baseline": eta_snapshot.delay_hours,
        "eta_confidence": eta_snapshot.confidence_score,
        "eta_explanation": eta_snapshot.explanation,
        "new_exceptions_detected": len(new_exceptions),
        "exception_details": exception_details,
        "warnings": warnings
    }

@app.post("/api/v1/nlp/extract-email")
def extract_email_endpoint(req: EmailExtractionRequest):
    """
    Extracts structured fields from carrier delay/status email via Qwen 3B.
    """
    extracted_fields = extract_logistics_email(req.email_text)
    return {
        "status": "EXTRACTED",
        "data": extracted_fields
    }

@app.post("/api/v1/nlp/draft-notification")
def draft_notification_endpoint(payload: Dict[str, Any]):
    """
    Drafts customer notification email.
    """
    draft = draft_customer_delay_notification(
        customer_name=payload.get("customer_name", "Valued Customer"),
        po_number=payload.get("po_number", "PO-1001"),
        revised_eta=payload.get("revised_eta", "TBD"),
        mitigation_action=payload.get("mitigation_action", "Expedited final mile team truck")
    )
    return {"status": "DRAFTED", "draft_text": draft}

@app.get("/api/v1/shipments/{shipment_id}")
def get_shipment_details(shipment_id: str):
    """
    Returns full control tower 360-degree view of a shipment.
    """
    shipment = get_shipment(shipment_id)
    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")

    legs = get_shipment_legs(shipment_id)
    events = get_canonical_events(shipment_id)
    open_exceptions = get_open_exceptions(shipment_id)

    return {
        "shipment": shipment.dict(),
        "legs": [l.dict() for l in legs],
        "timeline_events": [e.dict() for e in events],
        "open_exceptions": [exc.dict() for exc in open_exceptions]
    }

@app.get("/api/v1/exceptions")
def list_active_exceptions():
    """
    Returns active Control Tower exception desk cases.
    """
    cases = get_open_exceptions()
    conn = get_connection()
    enriched = []
    for c in cases:
        impact_row = conn.execute("SELECT * FROM impact_assessments WHERE case_id = ?", (c.case_id,)).fetchone()
        recs = conn.execute("SELECT * FROM recovery_recommendations WHERE case_id = ? ORDER BY net_service_score DESC", (c.case_id,)).fetchall()
        enriched.append({
            "case": c.dict(),
            "impact": dict(impact_row) if impact_row else None,
            "recommendations": [dict(r) for r in recs]
        })
    return {"active_exceptions_count": len(enriched), "cases": enriched}

@app.post("/api/v1/approvals/{approval_id}/action")
def execute_approval(approval_id: str, req: ApprovalActionRequest):
    """
    Approves or rejects a recovery recommendation.
    """
    conn = get_connection()
    row = conn.execute("SELECT * FROM approvals WHERE approval_id = ?", (approval_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Approval record not found")

    new_status = "APPROVED" if req.action.upper() == "APPROVE" else "REJECTED"
    now_utc = datetime.now(timezone.utc).isoformat()
    
    with conn:
        conn.execute("""
        UPDATE approvals
        SET status = ?, approved_by = ?, decision_timestamp = ?, comments = ?
        WHERE approval_id = ?
        """, (new_status, req.approved_by, now_utc, req.comments, approval_id))

        if new_status == "APPROVED":
            # Update exception case to MITIGATING
            conn.execute("""
            UPDATE exception_cases
            SET status = 'MITIGATING'
            WHERE case_id = ?
            """, (row["case_id"],))

    log_audit("APPROVAL", approval_id, f"ACTION_{new_status}", req.approved_by, {"comments": req.comments})

    return {
        "status": "DECISION_RECORDED",
        "approval_id": approval_id,
        "decision": new_status,
        "approved_by": req.approved_by,
        "case_state": "MITIGATING" if new_status == "APPROVED" else "REJECTED"
    }

if __name__ == "__main__":
    import uvicorn
    from core.config import DECISION_ENGINE_HOST, DECISION_ENGINE_PORT
    uvicorn.run("api.server:app", host=DECISION_ENGINE_HOST, port=DECISION_ENGINE_PORT, reload=False)
