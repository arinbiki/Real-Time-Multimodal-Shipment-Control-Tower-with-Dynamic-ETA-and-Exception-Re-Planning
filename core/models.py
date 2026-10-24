"""
Domain models for the Real-Time Multimodal Shipment Control Tower.
"""
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class TransportMode(str, Enum):
    ROAD_FTL = "ROAD_FTL"
    ROAD_LTL = "ROAD_LTL"
    OCEAN = "OCEAN"
    AIR = "AIR"
    RAIL = "RAIL"
    PARCEL = "PARCEL"

class ShipmentState(str, Enum):
    PLANNED = "PLANNED"
    BOOKED = "BOOKED"
    TENDERED = "TENDERED"
    PICKED_UP = "PICKED_UP"
    IN_TRANSIT = "IN_TRANSIT"
    AT_HUB = "AT_HUB"
    CUSTOMS_HOLD = "CUSTOMS_HOLD"
    CUSTOMS_RELEASED = "CUSTOMS_RELEASED"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    EXCEPTION = "EXCEPTION"
    CANCELLED = "CANCELLED"

class CanonicalEventCategory(str, Enum):
    PLAN = "PLAN"
    BOOKING = "BOOKING"
    PICKUP = "PICKUP"
    DEPARTURE = "DEPARTURE"
    ARRIVAL = "ARRIVAL"
    HANDLING = "HANDLING"
    CUSTOMS = "CUSTOMS"
    DELAY = "DELAY"
    EXCEPTION = "EXCEPTION"
    DELIVERY = "DELIVERY"
    PROOF_OF_DELIVERY = "PROOF_OF_DELIVERY"
    CANCELLATION = "CANCELLATION"
    DATA_QUALITY = "DATA_QUALITY"

class CanonicalEventType(str, Enum):
    SHIPMENT_PLANNED = "SHIPMENT_PLANNED"
    SHIPMENT_BOOKED = "SHIPMENT_BOOKED"
    TENDERED = "TENDERED"
    PICKED_UP = "PICKED_UP"
    DEPARTED_ORIGIN = "DEPARTED_ORIGIN"
    ARRIVED_AT_HUB = "ARRIVED_AT_HUB"
    LOADED_ON_VESSEL = "LOADED_ON_VESSEL"
    VESSEL_DEPARTED = "VESSEL_DEPARTED"
    ARRIVED_AT_PORT = "ARRIVED_AT_PORT"
    DISCHARGED_FROM_VESSEL = "DISCHARGED_FROM_VESSEL"
    CUSTOMS_HOLD = "CUSTOMS_HOLD"
    CUSTOMS_RELEASED = "CUSTOMS_RELEASED"
    IN_TRANSIT = "IN_TRANSIT"
    DELAYED = "DELAYED"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    POD_RECEIVED = "POD_RECEIVED"
    EXCEPTION_REPORTED = "EXCEPTION_REPORTED"
    VISIBILITY_GAP_DETECTED = "VISIBILITY_GAP_DETECTED"

class CustomerTier(str, Enum):
    TIER_1_STRATEGIC = "TIER_1_STRATEGIC"
    TIER_2_ENTERPRISE = "TIER_2_ENTERPRISE"
    TIER_3_STANDARD = "TIER_3_STANDARD"
    TIER_4_LOW_PRIORITY = "TIER_4_LOW_PRIORITY"

class ExceptionSeverity(str, Enum):
    P1_CRITICAL = "P1_CRITICAL"
    P2_HIGH = "P2_HIGH"
    P3_MEDIUM = "P3_MEDIUM"
    P4_LOW = "P4_LOW"

class ExceptionStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    MITIGATING = "MITIGATING"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"

class RecoveryOptionType(str, Enum):
    EXPEDITE_FINAL_MILE = "EXPEDITE_FINAL_MILE"
    SWITCH_CARRIER = "SWITCH_CARRIER"
    AIR_UPGRADE = "AIR_UPGRADE"
    ALLOCATE_ALTERNATE_INVENTORY = "ALLOCATE_ALTERNATE_INVENTORY"
    SPLIT_SHIPMENT = "SPLIT_SHIPMENT"
    RE_ROUTE = "RE_ROUTE"
    NOTIFY_STAKEHOLDER = "NOTIFY_STAKEHOLDER"

class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    AUTO_APPROVED = "AUTO_APPROVED"

# Data Models
class RawEventPayload(BaseModel):
    source_system: str
    raw_payload: Dict[str, Any]
    received_at: Optional[datetime] = None

class CanonicalEvent(BaseModel):
    event_id: str
    raw_event_id: Optional[str] = None
    internal_shipment_id: Optional[str] = None
    category: CanonicalEventCategory
    event_type: CanonicalEventType
    event_timestamp_utc: datetime
    location_code: Optional[str] = None
    location_name: Optional[str] = None
    carrier_code: Optional[str] = None
    delay_reason: Optional[str] = None
    source_confidence: float = 1.0
    details: Dict[str, Any] = Field(default_factory=dict)

class ShipmentLeg(BaseModel):
    leg_id: str
    shipment_id: str
    sequence: int
    mode: TransportMode
    origin_code: str
    origin_name: str
    destination_code: str
    destination_name: str
    carrier_code: str
    status: str = "PLANNED"  # PLANNED, IN_PROGRESS, COMPLETED, DELAYED
    planned_start: datetime
    planned_end: datetime
    actual_start: Optional[datetime] = None
    actual_end: Optional[datetime] = None
    estimated_end: Optional[datetime] = None
    distance_km: float = 0.0
    current_progress_pct: float = 0.0

class OrderLine(BaseModel):
    sku: str
    description: str
    quantity: int
    unit_price: float

class Order(BaseModel):
    order_id: str
    shipment_id: str
    customer_id: str
    customer_name: str
    customer_tier: CustomerTier
    promised_date: datetime
    required_date: datetime
    total_revenue: float
    penalty_rate_per_day: float = 500.0  # Daily contract penalty for SLA breach
    lines: List[OrderLine] = Field(default_factory=list)
    criticality: str = "MEDIUM"

class Shipment(BaseModel):
    shipment_id: str
    tms_reference: str
    customer_id: str
    customer_name: str
    customer_tier: CustomerTier
    origin: str
    destination: str
    planned_pickup: datetime
    planned_delivery: datetime
    required_delivery: datetime
    committed_delivery: datetime
    current_status: ShipmentState = ShipmentState.PLANNED
    current_location: Optional[str] = None
    current_eta: datetime
    baseline_eta: datetime
    confidence_score: float = 1.0
    total_legs: int = 1
    active_leg_sequence: int = 1
    carrier_id: Optional[str] = None
    container_no: Optional[str] = None
    bol_no: Optional[str] = None
    po_numbers: List[str] = Field(default_factory=list)
    last_event_timestamp: Optional[datetime] = None

class ETASnapshot(BaseModel):
    snapshot_id: str
    shipment_id: str
    calculated_at: datetime
    current_eta_utc: datetime
    baseline_eta_utc: datetime
    delay_hours: float
    confidence_score: float
    explanation: str
    triggered_by_event_id: Optional[str] = None

class ExceptionCase(BaseModel):
    case_id: str
    shipment_id: str
    exception_category: str
    rule_id: str
    severity: ExceptionSeverity
    status: ExceptionStatus = ExceptionStatus.OPEN
    detected_at: datetime
    title: str
    details: str
    days_late: float = 0.0
    impact_score: float = 0.0

class ImpactAssessment(BaseModel):
    impact_id: str
    case_id: str
    shipment_id: str
    revenue_at_risk: float
    penalty_at_risk: float
    stockout_risk_prob: float
    affected_orders_count: int
    customer_criticality: str
    urgency_level: str
    total_financial_risk: float
    details: Dict[str, Any] = Field(default_factory=dict)

class RecoveryRecommendation(BaseModel):
    recommendation_id: str
    case_id: str
    shipment_id: str
    option_type: RecoveryOptionType
    title: str
    cost_estimate: float
    hours_saved: float
    net_service_score: float
    feasibility_status: str
    approval_tier: str
    details: Dict[str, Any] = Field(default_factory=dict)

class ApprovalRecord(BaseModel):
    approval_id: str
    recommendation_id: str
    case_id: str
    approval_tier: str
    required_role: str
    approved_by: Optional[str] = None
    status: ApprovalStatus = ApprovalStatus.PENDING
    decision_timestamp: Optional[datetime] = None
    comments: Optional[str] = None
