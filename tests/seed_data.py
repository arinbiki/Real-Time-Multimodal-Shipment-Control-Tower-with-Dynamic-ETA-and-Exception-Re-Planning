"""
Seed Data generator for Control Tower testing matching Section 25 MVP Scope.
Creates realistic Multimodal Shipments (Ocean + Rail + Truck) and Orders.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import datetime, timedelta, timezone
from core.database import (
    init_db, save_shipment, save_shipment_leg, save_order
)

from core.models import (
    Shipment, ShipmentLeg, Order, OrderLine, ShipmentState,
    CustomerTier, TransportMode
)

def populate_seed_data():
    init_db()
    now = datetime.now(timezone.utc)

    # =================================================================
    # SHIPMENT 1: High-Value Transpacific Multimodal Container
    # Shanghai -> Port of LA (Ocean) -> Chicago Ramp (Rail) -> Chicago DC (Truck)
    # =================================================================
    s1_pickup = now - timedelta(days=12)
    s1_planned_del = now + timedelta(days=4)
    s1_required_del = now + timedelta(days=5)  # Customer required date

    s1 = Shipment(
        shipment_id="SHP-OCEAN-1001",
        tms_reference="TMS-882910",
        customer_id="CUST-APEX",
        customer_name="Apex Global Retail Corp",
        customer_tier=CustomerTier.TIER_1_STRATEGIC,
        origin="Port of Shanghai, China",
        destination="Chicago Distribution Center, IL",
        planned_pickup=s1_pickup,
        planned_delivery=s1_planned_del,
        required_delivery=s1_required_del,
        committed_delivery=s1_planned_del,
        current_status=ShipmentState.IN_TRANSIT,
        current_location="Port of Los Angeles / Long Beach, CA",
        current_eta=s1_planned_del,
        baseline_eta=s1_planned_del,
        confidence_score=0.98,
        total_legs=3,
        active_leg_sequence=1,
        carrier_id="CMA CGM",
        container_no="MSCU1234567",
        bol_no="BOL-CMA-9921",
        po_numbers=["PO-APEX-8801", "PO-APEX-8802"],
        last_event_timestamp=now - timedelta(hours=3)
    )
    save_shipment(s1)

    # Leg 1: Ocean (Shanghai -> LA)
    leg1 = ShipmentLeg(
        leg_id="LEG-1001-1",
        shipment_id="SHP-OCEAN-1001",
        sequence=1,
        mode=TransportMode.OCEAN,
        origin_code="CNSHA",
        origin_name="Port of Shanghai",
        destination_code="USLAX",
        destination_name="Port of Los Angeles",
        carrier_code="CMA CGM",
        status="IN_TRANSIT",
        planned_start=s1_pickup,
        planned_end=now + timedelta(days=1),
        actual_start=s1_pickup,
        actual_end=None,
        estimated_end=now + timedelta(days=1),
        distance_km=10450.0,
        current_progress_pct=85.0
    )
    save_shipment_leg(leg1)

    # Leg 2: Intermodal Rail (LA -> Chicago)
    leg2 = ShipmentLeg(
        leg_id="LEG-1001-2",
        shipment_id="SHP-OCEAN-1001",
        sequence=2,
        mode=TransportMode.RAIL,
        origin_code="USLAX",
        origin_name="Port of Los Angeles",
        destination_code="USCHI",
        destination_name="Chicago Intermodal Ramp",
        carrier_code="BNSF",
        status="PLANNED",
        planned_start=now + timedelta(days=1, hours=12),
        planned_end=now + timedelta(days=3, hours=12),
        distance_km=3500.0,
        current_progress_pct=0.0
    )
    save_shipment_leg(leg2)

    # Leg 3: Final Mile Drayage (Chicago Ramp -> DC)
    leg3 = ShipmentLeg(
        leg_id="LEG-1001-3",
        shipment_id="SHP-OCEAN-1001",
        sequence=3,
        mode=TransportMode.ROAD_FTL,
        origin_code="USCHI",
        origin_name="Chicago Intermodal Ramp",
        destination_code="USCHI-DC",
        destination_name="Chicago Distribution Center",
        carrier_code="Swift Priority",
        status="PLANNED",
        planned_start=now + timedelta(days=3, hours=16),
        planned_end=s1_planned_del,
        distance_km=65.0,
        current_progress_pct=0.0
    )
    save_shipment_leg(leg3)

    # Orders for Shipment 1
    o1 = Order(
        order_id="PO-APEX-8801",
        shipment_id="SHP-OCEAN-1001",
        customer_id="CUST-APEX",
        customer_name="Apex Global Retail Corp",
        customer_tier=CustomerTier.TIER_1_STRATEGIC,
        promised_date=s1_planned_del,
        required_date=s1_required_del,
        total_revenue=180000.0,
        penalty_rate_per_day=750.0,
        criticality="CRITICAL",
        lines=[
            OrderLine(sku="SKU-TV-75-OLED", description="75-inch 4K OLED Smart TV", quantity=400, unit_price=450.0)
        ]
    )
    save_order(o1)

    o2 = Order(
        order_id="PO-APEX-8802",
        shipment_id="SHP-OCEAN-1001",
        customer_id="CUST-APEX",
        customer_name="Apex Global Retail Corp",
        customer_tier=CustomerTier.TIER_1_STRATEGIC,
        promised_date=s1_planned_del,
        required_date=s1_required_del,
        total_revenue=75000.0,
        penalty_rate_per_day=250.0,
        criticality="HIGH",
        lines=[
            OrderLine(sku="SKU-AUDIO-BAR", description="Dolby Atmos Soundbar System", quantity=1000, unit_price=75.0)
        ]
    )
    save_order(o2)

    # =================================================================
    # SHIPMENT 2: JIT Automotive Truckload (Laredo to Detroit)
    # =================================================================
    s2_pickup = now - timedelta(hours=14)
    s2_planned_del = now + timedelta(hours=18)
    s2_required_del = now + timedelta(hours=20)

    s2 = Shipment(
        shipment_id="SHP-TRUCK-2002",
        tms_reference="TMS-991204",
        customer_id="CUST-TITAN",
        customer_name="Titan Automotive Assembly",
        customer_tier=CustomerTier.TIER_1_STRATEGIC,
        origin="Laredo Border Terminal, TX",
        destination="Detroit Assembly Plant #4, MI",
        planned_pickup=s2_pickup,
        planned_delivery=s2_planned_del,
        required_delivery=s2_required_del,
        committed_delivery=s2_planned_del,
        current_status=ShipmentState.IN_TRANSIT,
        current_location="Little Rock, AR",
        current_eta=s2_planned_del,
        baseline_eta=s2_planned_del,
        confidence_score=0.95,
        total_legs=1,
        active_leg_sequence=1,
        carrier_id="Knight-Swift",
        bol_no="BOL-SWIFT-7711",
        po_numbers=["PO-TITAN-4410"],
        last_event_timestamp=now - timedelta(hours=2)
    )
    save_shipment(s2)

    leg2_1 = ShipmentLeg(
        leg_id="LEG-2002-1",
        shipment_id="SHP-TRUCK-2002",
        sequence=1,
        mode=TransportMode.ROAD_FTL,
        origin_code="USLRD",
        origin_name="Laredo Border Terminal",
        destination_code="USDTW",
        destination_name="Detroit Assembly Plant",
        carrier_code="Knight-Swift",
        status="IN_TRANSIT",
        planned_start=s2_pickup,
        planned_end=s2_planned_del,
        actual_start=s2_pickup,
        distance_km=2150.0,
        current_progress_pct=45.0
    )
    save_shipment_leg(leg2_1)

    o3 = Order(
        order_id="PO-TITAN-4410",
        shipment_id="SHP-TRUCK-2002",
        customer_id="CUST-TITAN",
        customer_name="Titan Automotive Assembly",
        customer_tier=CustomerTier.TIER_1_STRATEGIC,
        promised_date=s2_planned_del,
        required_date=s2_required_del,
        total_revenue=120000.0,
        penalty_rate_per_day=1500.0,
        criticality="CRITICAL",
        lines=[
            OrderLine(sku="SKU-AUTO-ECU-90", description="Engine Control Module Units", quantity=600, unit_price=200.0)
        ]
    )
    save_order(o3)

    print("Seed data successfully populated:")
    print("1. SHP-OCEAN-1001 (Multimodal Ocean/Rail/Truck: CNSHA -> USLAX -> USCHI)")
    print("2. SHP-TRUCK-2002 (Cross-border FTL: USLRD -> USDTW)")

if __name__ == "__main__":
    populate_seed_data()
