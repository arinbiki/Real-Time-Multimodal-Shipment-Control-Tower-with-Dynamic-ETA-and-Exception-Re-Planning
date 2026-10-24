"""
Database engine and schema matching Section 19 of plan.md.
Provides relational persistence and audit trail for shipments, events, exceptions, and recommendations.
"""
import sqlite3
import json
from datetime import datetime
from typing import List, Optional, Dict, Any
from core.config import DB_PATH
from core.models import (
    Shipment, ShipmentLeg, Order, OrderLine, CanonicalEvent,
    ETASnapshot, ExceptionCase, ImpactAssessment, RecoveryRecommendation,
    ApprovalRecord, ShipmentState, CustomerTier, TransportMode,
    ExceptionSeverity, ExceptionStatus, RecoveryOptionType, ApprovalStatus,
    CanonicalEventCategory, CanonicalEventType
)

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    conn = get_connection()
    with conn:
        # 1. Raw Payloads (Immutable audit ledger)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS raw_events (
            raw_id TEXT PRIMARY KEY,
            source_system TEXT NOT NULL,
            payload_hash TEXT NOT NULL,
            raw_payload TEXT NOT NULL,
            received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # 2. Shipments
        conn.execute("""
        CREATE TABLE IF NOT EXISTS shipments (
            shipment_id TEXT PRIMARY KEY,
            tms_reference TEXT UNIQUE NOT NULL,
            customer_id TEXT NOT NULL,
            customer_name TEXT NOT NULL,
            customer_tier TEXT NOT NULL,
            origin TEXT NOT NULL,
            destination TEXT NOT NULL,
            planned_pickup TIMESTAMP NOT NULL,
            planned_delivery TIMESTAMP NOT NULL,
            required_delivery TIMESTAMP NOT NULL,
            committed_delivery TIMESTAMP NOT NULL,
            current_status TEXT NOT NULL,
            current_location TEXT,
            current_eta TIMESTAMP NOT NULL,
            baseline_eta TIMESTAMP NOT NULL,
            confidence_score REAL DEFAULT 1.0,
            total_legs INTEGER DEFAULT 1,
            active_leg_sequence INTEGER DEFAULT 1,
            carrier_id TEXT,
            container_no TEXT,
            bol_no TEXT,
            po_numbers TEXT,
            last_event_timestamp TIMESTAMP
        );
        """)

        # 3. Multimodal Shipment Legs
        conn.execute("""
        CREATE TABLE IF NOT EXISTS shipment_legs (
            leg_id TEXT PRIMARY KEY,
            shipment_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            mode TEXT NOT NULL,
            origin_code TEXT NOT NULL,
            origin_name TEXT NOT NULL,
            destination_code TEXT NOT NULL,
            destination_name TEXT NOT NULL,
            carrier_code TEXT NOT NULL,
            status TEXT NOT NULL,
            planned_start TIMESTAMP NOT NULL,
            planned_end TIMESTAMP NOT NULL,
            actual_start TIMESTAMP,
            actual_end TIMESTAMP,
            estimated_end TIMESTAMP,
            distance_km REAL DEFAULT 0.0,
            current_progress_pct REAL DEFAULT 0.0,
            FOREIGN KEY (shipment_id) REFERENCES shipments(shipment_id) ON DELETE CASCADE
        );
        """)

        # 4. Orders and Line Items
        conn.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            order_id TEXT PRIMARY KEY,
            shipment_id TEXT NOT NULL,
            customer_id TEXT NOT NULL,
            customer_name TEXT NOT NULL,
            customer_tier TEXT NOT NULL,
            promised_date TIMESTAMP NOT NULL,
            required_date TIMESTAMP NOT NULL,
            total_revenue REAL NOT NULL,
            penalty_rate_per_day REAL DEFAULT 500.0,
            criticality TEXT DEFAULT 'MEDIUM',
            FOREIGN KEY (shipment_id) REFERENCES shipments(shipment_id) ON DELETE CASCADE
        );
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS order_lines (
            line_id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT NOT NULL,
            sku TEXT NOT NULL,
            description TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            unit_price REAL NOT NULL,
            FOREIGN KEY (order_id) REFERENCES orders(order_id) ON DELETE CASCADE
        );
        """)

        # 5. Canonical Events
        conn.execute("""
        CREATE TABLE IF NOT EXISTS canonical_events (
            event_id TEXT PRIMARY KEY,
            raw_event_id TEXT,
            internal_shipment_id TEXT,
            category TEXT NOT NULL,
            event_type TEXT NOT NULL,
            event_timestamp_utc TIMESTAMP NOT NULL,
            location_code TEXT,
            location_name TEXT,
            carrier_code TEXT,
            delay_reason TEXT,
            source_confidence REAL DEFAULT 1.0,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (internal_shipment_id) REFERENCES shipments(shipment_id)
        );
        """)

        # 6. ETA Snapshots
        conn.execute("""
        CREATE TABLE IF NOT EXISTS eta_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            shipment_id TEXT NOT NULL,
            calculated_at TIMESTAMP NOT NULL,
            current_eta_utc TIMESTAMP NOT NULL,
            baseline_eta_utc TIMESTAMP NOT NULL,
            delay_hours REAL NOT NULL,
            confidence_score REAL NOT NULL,
            explanation TEXT NOT NULL,
            triggered_by_event_id TEXT,
            FOREIGN KEY (shipment_id) REFERENCES shipments(shipment_id)
        );
        """)

        # 7. Exception Cases
        conn.execute("""
        CREATE TABLE IF NOT EXISTS exception_cases (
            case_id TEXT PRIMARY KEY,
            shipment_id TEXT NOT NULL,
            exception_category TEXT NOT NULL,
            rule_id TEXT NOT NULL,
            severity TEXT NOT NULL,
            status TEXT NOT NULL,
            detected_at TIMESTAMP NOT NULL,
            title TEXT NOT NULL,
            details TEXT NOT NULL,
            days_late REAL DEFAULT 0.0,
            impact_score REAL DEFAULT 0.0,
            resolved_at TIMESTAMP,
            closure_reason TEXT,
            FOREIGN KEY (shipment_id) REFERENCES shipments(shipment_id)
        );
        """)

        # 8. Impact Assessments
        conn.execute("""
        CREATE TABLE IF NOT EXISTS impact_assessments (
            impact_id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL,
            shipment_id TEXT NOT NULL,
            revenue_at_risk REAL NOT NULL,
            penalty_at_risk REAL NOT NULL,
            stockout_risk_prob REAL NOT NULL,
            affected_orders_count INTEGER NOT NULL,
            customer_criticality TEXT NOT NULL,
            urgency_level TEXT NOT NULL,
            total_financial_risk REAL NOT NULL,
            details TEXT,
            assessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (case_id) REFERENCES exception_cases(case_id),
            FOREIGN KEY (shipment_id) REFERENCES shipments(shipment_id)
        );
        """)

        # 9. Recovery Recommendations
        conn.execute("""
        CREATE TABLE IF NOT EXISTS recovery_recommendations (
            recommendation_id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL,
            shipment_id TEXT NOT NULL,
            option_type TEXT NOT NULL,
            title TEXT NOT NULL,
            cost_estimate REAL NOT NULL,
            hours_saved REAL NOT NULL,
            net_service_score REAL NOT NULL,
            feasibility_status TEXT NOT NULL,
            approval_tier TEXT NOT NULL,
            details TEXT,
            generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (case_id) REFERENCES exception_cases(case_id)
        );
        """)

        # 10. Approvals & Governance
        conn.execute("""
        CREATE TABLE IF NOT EXISTS approvals (
            approval_id TEXT PRIMARY KEY,
            recommendation_id TEXT NOT NULL,
            case_id TEXT NOT NULL,
            approval_tier TEXT NOT NULL,
            required_role TEXT NOT NULL,
            approved_by TEXT,
            status TEXT NOT NULL,
            decision_timestamp TIMESTAMP,
            comments TEXT,
            FOREIGN KEY (recommendation_id) REFERENCES recovery_recommendations(recommendation_id)
        );
        """)

        # 11. Audit Logs
        conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            action TEXT NOT NULL,
            performed_by TEXT NOT NULL,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # Create Indexes for high-speed lookups
        conn.execute("CREATE INDEX IF NOT EXISTS idx_shipments_tms ON shipments(tms_reference);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_shipments_container ON shipments(container_no);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_shipments_bol ON shipments(bol_no);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_legs_shipment ON shipment_legs(shipment_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_shipment ON canonical_events(internal_shipment_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_exceptions_shipment ON exception_cases(shipment_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_exceptions_status ON exception_cases(status);")

# Data Repository Helpers

def save_raw_event(raw_id: str, source: str, payload_hash: str, raw_payload: dict):
    conn = get_connection()
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO raw_events (raw_id, source_system, payload_hash, raw_payload) VALUES (?, ?, ?, ?)",
            (raw_id, source, payload_hash, json.dumps(raw_payload, default=str))
        )

def get_shipment(shipment_id: str) -> Optional[Shipment]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM shipments WHERE shipment_id = ?", (shipment_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["po_numbers"] = json.loads(d["po_numbers"]) if d["po_numbers"] else []
    d["planned_pickup"] = datetime.fromisoformat(d["planned_pickup"])
    d["planned_delivery"] = datetime.fromisoformat(d["planned_delivery"])
    d["required_delivery"] = datetime.fromisoformat(d["required_delivery"])
    d["committed_delivery"] = datetime.fromisoformat(d["committed_delivery"])
    d["current_eta"] = datetime.fromisoformat(d["current_eta"])
    d["baseline_eta"] = datetime.fromisoformat(d["baseline_eta"])
    if d.get("last_event_timestamp"):
        d["last_event_timestamp"] = datetime.fromisoformat(d["last_event_timestamp"])
    return Shipment(**d)

def save_shipment(s: Shipment):
    conn = get_connection()
    with conn:
        conn.execute("""
        INSERT OR REPLACE INTO shipments (
            shipment_id, tms_reference, customer_id, customer_name, customer_tier,
            origin, destination, planned_pickup, planned_delivery, required_delivery, committed_delivery,
            current_status, current_location, current_eta, baseline_eta, confidence_score,
            total_legs, active_leg_sequence, carrier_id, container_no, bol_no, po_numbers, last_event_timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            s.shipment_id, s.tms_reference, s.customer_id, s.customer_name, s.customer_tier.value,
            s.origin, s.destination, s.planned_pickup.isoformat(), s.planned_delivery.isoformat(),
            s.required_delivery.isoformat(), s.committed_delivery.isoformat(),
            s.current_status.value, s.current_location, s.current_eta.isoformat(),
            s.baseline_eta.isoformat(), s.confidence_score, s.total_legs, s.active_leg_sequence,
            s.carrier_id, s.container_no, s.bol_no, json.dumps(s.po_numbers),
            s.last_event_timestamp.isoformat() if s.last_event_timestamp else None
        ))

def get_shipment_legs(shipment_id: str) -> List[ShipmentLeg]:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM shipment_legs WHERE shipment_id = ? ORDER BY sequence ASC", (shipment_id,)).fetchall()
    legs = []
    for r in rows:
        d = dict(r)
        d["planned_start"] = datetime.fromisoformat(d["planned_start"])
        d["planned_end"] = datetime.fromisoformat(d["planned_end"])
        if d.get("actual_start"):
            d["actual_start"] = datetime.fromisoformat(d["actual_start"])
        if d.get("actual_end"):
            d["actual_end"] = datetime.fromisoformat(d["actual_end"])
        if d.get("estimated_end"):
            d["estimated_end"] = datetime.fromisoformat(d["estimated_end"])
        legs.append(ShipmentLeg(**d))
    return legs

def save_shipment_leg(leg: ShipmentLeg):
    conn = get_connection()
    with conn:
        conn.execute("""
        INSERT OR REPLACE INTO shipment_legs (
            leg_id, shipment_id, sequence, mode, origin_code, origin_name,
            destination_code, destination_name, carrier_code, status,
            planned_start, planned_end, actual_start, actual_end, estimated_end,
            distance_km, current_progress_pct
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            leg.leg_id, leg.shipment_id, leg.sequence, leg.mode.value,
            leg.origin_code, leg.origin_name, leg.destination_code, leg.destination_name,
            leg.carrier_code, leg.status, leg.planned_start.isoformat(), leg.planned_end.isoformat(),
            leg.actual_start.isoformat() if leg.actual_start else None,
            leg.actual_end.isoformat() if leg.actual_end else None,
            leg.estimated_end.isoformat() if leg.estimated_end else None,
            leg.distance_km, leg.current_progress_pct
        ))

def get_orders_for_shipment(shipment_id: str) -> List[Order]:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM orders WHERE shipment_id = ?", (shipment_id,)).fetchall()
    orders = []
    for r in rows:
        d = dict(r)
        d["promised_date"] = datetime.fromisoformat(d["promised_date"])
        d["required_date"] = datetime.fromisoformat(d["required_date"])
        line_rows = conn.execute("SELECT * FROM order_lines WHERE order_id = ?", (d["order_id"],)).fetchall()
        lines = [OrderLine(sku=lr["sku"], description=lr["description"], quantity=lr["quantity"], unit_price=lr["unit_price"]) for lr in line_rows]
        orders.append(Order(**d, lines=lines))
    return orders

def save_order(o: Order):
    conn = get_connection()
    with conn:
        conn.execute("""
        INSERT OR REPLACE INTO orders (
            order_id, shipment_id, customer_id, customer_name, customer_tier,
            promised_date, required_date, total_revenue, penalty_rate_per_day, criticality
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            o.order_id, o.shipment_id, o.customer_id, o.customer_name, o.customer_tier.value,
            o.promised_date.isoformat(), o.required_date.isoformat(), o.total_revenue,
            o.penalty_rate_per_day, o.criticality
        ))
        conn.execute("DELETE FROM order_lines WHERE order_id = ?", (o.order_id,))
        for line in o.lines:
            conn.execute("""
            INSERT INTO order_lines (order_id, sku, description, quantity, unit_price)
            VALUES (?, ?, ?, ?, ?)
            """, (o.order_id, line.sku, line.description, line.quantity, line.unit_price))

def save_canonical_event(e: CanonicalEvent):
    conn = get_connection()
    with conn:
        conn.execute("""
        INSERT OR REPLACE INTO canonical_events (
            event_id, raw_event_id, internal_shipment_id, category, event_type,
            event_timestamp_utc, location_code, location_name, carrier_code,
            delay_reason, source_confidence, details
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            e.event_id, e.raw_event_id, e.internal_shipment_id, e.category.value,
            e.event_type.value, e.event_timestamp_utc.isoformat(), e.location_code,
            e.location_name, e.carrier_code, e.delay_reason, e.source_confidence,
            json.dumps(e.details, default=str)
        ))

def get_canonical_events(shipment_id: str) -> List[CanonicalEvent]:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM canonical_events WHERE internal_shipment_id = ? ORDER BY event_timestamp_utc ASC", (shipment_id,)).fetchall()
    events = []
    for r in rows:
        d = dict(r)
        d["event_timestamp_utc"] = datetime.fromisoformat(d["event_timestamp_utc"])
        d["details"] = json.loads(d["details"]) if d["details"] else {}
        events.append(CanonicalEvent(**d))
    return events

def save_eta_snapshot(snap: ETASnapshot):
    conn = get_connection()
    with conn:
        conn.execute("""
        INSERT OR REPLACE INTO eta_snapshots (
            snapshot_id, shipment_id, calculated_at, current_eta_utc, baseline_eta_utc,
            delay_hours, confidence_score, explanation, triggered_by_event_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            snap.snapshot_id, snap.shipment_id, snap.calculated_at.isoformat(),
            snap.current_eta_utc.isoformat(), snap.baseline_eta_utc.isoformat(),
            snap.delay_hours, snap.confidence_score, snap.explanation, snap.triggered_by_event_id
        ))

def save_exception_case(c: ExceptionCase):
    conn = get_connection()
    with conn:
        conn.execute("""
        INSERT OR REPLACE INTO exception_cases (
            case_id, shipment_id, exception_category, rule_id, severity, status,
            detected_at, title, details, days_late, impact_score
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            c.case_id, c.shipment_id, c.exception_category, c.rule_id, c.severity.value,
            c.status.value, c.detected_at.isoformat(), c.title, c.details,
            c.days_late, c.impact_score
        ))

def get_open_exceptions(shipment_id: Optional[str] = None) -> List[ExceptionCase]:
    conn = get_connection()
    if shipment_id:
        rows = conn.execute("SELECT * FROM exception_cases WHERE shipment_id = ? AND status = 'OPEN' ORDER BY detected_at DESC", (shipment_id,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM exception_cases WHERE status = 'OPEN' ORDER BY detected_at DESC").fetchall()
    cases = []
    for r in rows:
        d = dict(r)
        d["detected_at"] = datetime.fromisoformat(d["detected_at"])
        cases.append(ExceptionCase(**d))
    return cases

def save_impact_assessment(imp: ImpactAssessment):
    conn = get_connection()
    with conn:
        conn.execute("""
        INSERT OR REPLACE INTO impact_assessments (
            impact_id, case_id, shipment_id, revenue_at_risk, penalty_at_risk,
            stockout_risk_prob, affected_orders_count, customer_criticality,
            urgency_level, total_financial_risk, details
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            imp.impact_id, imp.case_id, imp.shipment_id, imp.revenue_at_risk,
            imp.penalty_at_risk, imp.stockout_risk_prob, imp.affected_orders_count,
            imp.customer_criticality, imp.urgency_level, imp.total_financial_risk,
            json.dumps(imp.details, default=str)
        ))

def save_recovery_recommendation(rec: RecoveryRecommendation):
    conn = get_connection()
    with conn:
        conn.execute("""
        INSERT OR REPLACE INTO recovery_recommendations (
            recommendation_id, case_id, shipment_id, option_type, title,
            cost_estimate, hours_saved, net_service_score, feasibility_status,
            approval_tier, details
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            rec.recommendation_id, rec.case_id, rec.shipment_id, rec.option_type.value,
            rec.title, rec.cost_estimate, rec.hours_saved, rec.net_service_score,
            rec.feasibility_status, rec.approval_tier, json.dumps(rec.details, default=str)
        ))

def save_approval(app: ApprovalRecord):
    conn = get_connection()
    with conn:
        conn.execute("""
        INSERT OR REPLACE INTO approvals (
            approval_id, recommendation_id, case_id, approval_tier, required_role,
            approved_by, status, decision_timestamp, comments
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            app.approval_id, app.recommendation_id, app.case_id, app.approval_tier,
            app.required_role, app.approved_by, app.status.value,
            app.decision_timestamp.isoformat() if app.decision_timestamp else None,
            app.comments
        ))

def log_audit(entity_type: str, entity_id: str, action: str, performed_by: str, details: dict):
    conn = get_connection()
    with conn:
        conn.execute(
            "INSERT INTO audit_logs (entity_type, entity_id, action, performed_by, details) VALUES (?, ?, ?, ?, ?)",
            (entity_type, entity_id, action, performed_by, json.dumps(details, default=str))
        )
