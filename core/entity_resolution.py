"""
Entity Resolution Engine matching Section 8 of plan.md.
Implements 3-tier identity resolution strategy:
Tier 1: Strong exact identifier match (Container, BOL, TMS Reference, Shipment ID)
Tier 2: Reference-based candidate search (PO number, Customer Ref)
Tier 3: Multi-attribute probabilistic matching (Carrier + Lane + Time Window + Customer)
"""
import json
from datetime import datetime
from typing import Optional, Dict, Any, Tuple
from core.database import get_connection, log_audit
from core.models import Shipment

CONFIDENCE_HIGH_THRESHOLD = 0.85
CONFIDENCE_MEDIUM_THRESHOLD = 0.50

def resolve_shipment_identity(raw_event: Dict[str, Any]) -> Tuple[Optional[str], float, str, bool]:
    """
    Attempts to match an incoming event payload to a known internal shipment.
    Returns:
      (shipment_id, confidence_score, resolution_tier_explanation, review_required)
    """
    conn = get_connection()
    
    # -------------------------------------------------------------
    # TIER 1: Exact Strong Identifier Match
    # -------------------------------------------------------------
    # 1. Direct Shipment ID
    direct_id = raw_event.get("shipment_id")
    if direct_id:
        row = conn.execute("SELECT shipment_id FROM shipments WHERE shipment_id = ?", (direct_id,)).fetchone()
        if row:
            log_audit("SHIPMENT", row["shipment_id"], "RESOLVED_TIER1", "SYSTEM", {"matched_key": "shipment_id", "value": direct_id})
            return row["shipment_id"], 1.0, "Tier 1: Exact Internal Shipment ID Match", False

    # 2. TMS Reference
    tms_ref = raw_event.get("tms_reference") or raw_event.get("tms_id")
    if tms_ref:
        row = conn.execute("SELECT shipment_id FROM shipments WHERE tms_reference = ?", (tms_ref,)).fetchone()
        if row:
            log_audit("SHIPMENT", row["shipment_id"], "RESOLVED_TIER1", "SYSTEM", {"matched_key": "tms_reference", "value": tms_ref})
            return row["shipment_id"], 1.0, "Tier 1: Exact TMS Reference Match", False

    # 3. Container Number (ISO 6346, e.g. MSCU1234567)
    container_no = raw_event.get("container_no") or raw_event.get("container")
    if container_no:
        clean_container = container_no.strip().upper().replace(" ", "")
        row = conn.execute("SELECT shipment_id FROM shipments WHERE UPPER(container_no) = ?", (clean_container,)).fetchone()
        if row:
            log_audit("SHIPMENT", row["shipment_id"], "RESOLVED_TIER1", "SYSTEM", {"matched_key": "container_no", "value": clean_container})
            return row["shipment_id"], 0.98, f"Tier 1: Exact Container Number Match ({clean_container})", False

    # 4. Bill of Lading (BOL)
    bol_no = raw_event.get("bol_no") or raw_event.get("bol") or raw_event.get("bill_of_lading")
    if bol_no:
        clean_bol = bol_no.strip().upper()
        row = conn.execute("SELECT shipment_id FROM shipments WHERE UPPER(bol_no) = ?", (clean_bol,)).fetchone()
        if row:
            log_audit("SHIPMENT", row["shipment_id"], "RESOLVED_TIER1", "SYSTEM", {"matched_key": "bol_no", "value": clean_bol})
            return row["shipment_id"], 0.95, f"Tier 1: Exact BOL Match ({clean_bol})", False

    # -------------------------------------------------------------
    # TIER 2: Reference-Based Candidate Search (PO, Order, Customer Ref)
    # -------------------------------------------------------------
    po_no = raw_event.get("po_number") or raw_event.get("po") or raw_event.get("order_id")
    if po_no:
        clean_po = str(po_no).strip().upper()
        # Check orders table
        order_row = conn.execute("SELECT shipment_id FROM orders WHERE UPPER(order_id) = ?", (clean_po,)).fetchone()
        if order_row:
            log_audit("SHIPMENT", order_row["shipment_id"], "RESOLVED_TIER2", "SYSTEM", {"matched_key": "order_id", "value": clean_po})
            return order_row["shipment_id"], 0.90, f"Tier 2: Linked Order/PO Match ({clean_po})", False
            
        # Check shipment po_numbers JSON array
        all_shipments = conn.execute("SELECT shipment_id, po_numbers FROM shipments WHERE po_numbers IS NOT NULL").fetchall()
        for s in all_shipments:
            try:
                pos = [str(p).upper() for p in json.loads(s["po_numbers"])]
                if clean_po in pos:
                    log_audit("SHIPMENT", s["shipment_id"], "RESOLVED_TIER2", "SYSTEM", {"matched_key": "po_numbers", "value": clean_po})
                    return s["shipment_id"], 0.88, f"Tier 2: Shipment PO Number Match ({clean_po})", False
            except Exception:
                continue

    # -------------------------------------------------------------
    # TIER 3: Probabilistic Candidate Scoring
    # -------------------------------------------------------------
    carrier = (raw_event.get("carrier_code") or raw_event.get("carrier") or "").upper().strip()
    origin = (raw_event.get("origin") or raw_event.get("location_code") or "").upper().strip()
    destination = (raw_event.get("destination") or "").upper().strip()
    customer_id = (raw_event.get("customer_id") or "").upper().strip()
    
    candidates = conn.execute("SELECT * FROM shipments WHERE current_status NOT IN ('DELIVERED', 'CANCELLED')").fetchall()
    best_candidate_id = None
    best_score = 0.0
    match_factors = []

    for cand in candidates:
        score = 0.0
        factors = []
        
        # 1. Carrier match (weight 0.30)
        if carrier and cand["carrier_id"] and carrier in cand["carrier_id"].upper():
            score += 0.30
            factors.append("carrier_match")
            
        # 2. Origin/Location match (weight 0.25)
        if origin and (origin in cand["origin"].upper() or origin in (cand["current_location"] or "").upper()):
            score += 0.25
            factors.append("origin_or_location_match")
            
        # 3. Destination match (weight 0.25)
        if destination and destination in cand["destination"].upper():
            score += 0.25
            factors.append("destination_match")
            
        # 4. Customer match (weight 0.20)
        if customer_id and customer_id == cand["customer_id"].upper():
            score += 0.20
            factors.append("customer_match")

        if score > best_score:
            best_score = score
            best_candidate_id = cand["shipment_id"]
            match_factors = factors

    # Band evaluation
    if best_score >= CONFIDENCE_HIGH_THRESHOLD:
        explanation = f"Tier 3 Probabilistic Match (Score: {best_score:.2f}, Factors: {', '.join(match_factors)})"
        log_audit("SHIPMENT", best_candidate_id, "RESOLVED_TIER3_HIGH", "SYSTEM", {"score": best_score, "factors": match_factors})
        return best_candidate_id, best_score, explanation, False

    elif best_score >= CONFIDENCE_MEDIUM_THRESHOLD:
        explanation = f"Tier 3 Probabilistic Match - Needs Human Review (Score: {best_score:.2f}, Factors: {', '.join(match_factors)})"
        log_audit("SHIPMENT", best_candidate_id, "RESOLVED_TIER3_MEDIUM_REVIEW", "SYSTEM", {"score": best_score, "factors": match_factors})
        return best_candidate_id, best_score, explanation, True  # Review required

    # Low confidence -> Quarantine / Manual Matching Queue
    log_audit("EVENT", "UNKNOWN", "UNRESOLVED_LOW_CONFIDENCE", "SYSTEM", {"best_score": best_score, "payload": raw_event})
    return None, best_score, "No candidate met minimum confidence threshold (< 0.50)", True
