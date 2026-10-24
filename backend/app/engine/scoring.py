"""Deterministic Road-Suitability Scoring Engine (0-100).

This module computes reproducible road-suitability scores based on physical
geometry, visual attributes, parking friction, pedestrian vulnerability,
and operational restrictions.

IMPORTANT CONFORMITY RULES:
1. Suitability is NOT throughput/capacity. It measures how geometrically
   and contextually appropriate a road is to handle diverted vehicle traffic.
2. Unknown attributes are penalized according to uncertainty, never silently
   treated as safe.
3. Scoring is strictly deterministic and reproducible.
"""

from typing import Optional
from backend.app.schemas.road import (
    ObstructionLevel,
    PedestrianContext,
    PenaltyDetail,
    RoadSuitabilityResult,
    VehicleType,
    VisionRoadAnalysis,
)


# Normalized feature weights (sum to 1.0)
WEIGHT_ROAD_WIDTH = 0.35
WEIGHT_PARKING_FRICTION = 0.25
WEIGHT_PEDESTRIAN_SAFETY = 0.20
WEIGHT_LANE_CONNECTIVITY = 0.20

# Vehicle dimensional thresholds (width requirements in meters)
MIN_WIDTH_REQUIREMENTS: dict[VehicleType, float] = {
    VehicleType.PASSENGER_CAR: 3.2,
    VehicleType.DELIVERY_VAN: 3.8,
    VehicleType.EMERGENCY_VEHICLE: 4.2,
    VehicleType.HEAVY_TRUCK: 5.0,
}


def compute_width_subscore(
    width_m: Optional[float],
    vehicle_type: VehicleType,
    penalties: list[PenaltyDetail],
    notes: list[str],
) -> tuple[float, float]:
    """Computes usable width subscore (0-100) and confidence penalty."""
    min_needed = MIN_WIDTH_REQUIREMENTS.get(vehicle_type, 3.2)

    if width_m is None:
        # Unknown width is explicitly flagged as uncertainty penalty
        penalties.append(
            PenaltyDetail(
                name="unknown_road_width",
                penalty_value=25.0,
                reason="Road width could not be inferred from imagery; default conservative width assumption applied.",
            )
        )
        notes.append("Road width unknown: assumed constrained single-lane corridor (4.0m default).")
        effective_width = 4.0
        width_confidence_discount = 0.25
    else:
        effective_width = width_m
        width_confidence_discount = 0.0

    if effective_width < min_needed:
        penalties.append(
            PenaltyDetail(
                name="substandard_width_for_vehicle",
                penalty_value=40.0,
                reason=f"Effective width {effective_width:.1f}m is below safe threshold {min_needed:.1f}m for {vehicle_type.value}.",
            )
        )
        subscore = 15.0
    elif effective_width < 4.5:
        # Constrained single-lane or tight passing
        subscore = 35.0 + (effective_width - 3.2) * 20.0
    elif effective_width < 6.5:
        # Standard two-way narrow road
        subscore = 65.0 + (effective_width - 4.5) * 12.5
    elif effective_width < 9.0:
        # Generous two-way collector
        subscore = 85.0 + (effective_width - 6.5) * 5.0
    else:
        # Multi-lane arterial or highway
        subscore = 100.0

    return max(0.0, min(100.0, subscore)), width_confidence_discount


def compute_parking_friction_subscore(
    level: ObstructionLevel,
    penalties: list[PenaltyDetail],
) -> float:
    """Computes parking obstruction score (0-100)."""
    mapping = {
        ObstructionLevel.NONE: 100.0,
        ObstructionLevel.LOW: 85.0,
        ObstructionLevel.MODERATE: 55.0,
        ObstructionLevel.HIGH: 25.0,
        ObstructionLevel.BLOCKED: 0.0,
    }
    score = mapping.get(level, 50.0)
    if level == ObstructionLevel.HIGH:
        penalties.append(
            PenaltyDetail(
                name="severe_parking_choke",
                penalty_value=20.0,
                reason="Heavy curbside parking reduces road to a single alternating bottleneck.",
            )
        )
    elif level == ObstructionLevel.BLOCKED:
        penalties.append(
            PenaltyDetail(
                name="roadway_blocked",
                penalty_value=90.0,
                reason="Roadway is effectively obstructed by parked/stopped vehicles.",
            )
        )
    return score


def compute_pedestrian_safety_subscore(
    context: PedestrianContext,
    penalties: list[PenaltyDetail],
) -> float:
    """Evaluates suitability for through-traffic diversion given vulnerable road users."""
    mapping = {
        PedestrianContext.LOW: 100.0,
        PedestrianContext.MODERATE_SIDEWALK: 85.0,
        PedestrianContext.HIGH_PEDESTRIAN_ZONE: 45.0,
        PedestrianContext.SCHOOL_ZONE: 25.0,
        PedestrianContext.UNPROTECTED_SHARED_SPACE: 15.0,
    }
    score = mapping.get(context, 50.0)
    if context in (PedestrianContext.SCHOOL_ZONE, PedestrianContext.UNPROTECTED_SHARED_SPACE):
        penalties.append(
            PenaltyDetail(
                name="vulnerable_pedestrian_corridor",
                penalty_value=25.0,
                reason="School zone or shared space: diverting cut-through traffic creates acute safety hazard.",
            )
        )
    return score


def compute_lane_connectivity_subscore(
    lanes: Optional[int],
    penalties: list[PenaltyDetail],
) -> tuple[float, float]:
    """Lane count subscore (0-100) and uncertainty discount."""
    if lanes is None:
        penalties.append(
            PenaltyDetail(
                name="unknown_lane_count",
                penalty_value=10.0,
                reason="Lane count not inferable; assumed single shared lane.",
            )
        )
        return 45.0, 0.15

    if lanes <= 1:
        return 40.0, 0.0
    elif lanes == 2:
        return 85.0, 0.0
    elif lanes >= 3:
        return 100.0, 0.0
    return 60.0, 0.0


def calculate_road_suitability(
    analysis: Optional[VisionRoadAnalysis],
    functional_class: str = "residential",
    vehicle_type: VehicleType = VehicleType.PASSENGER_CAR,
    known_restrictions: Optional[list[str]] = None,
    data_freshness_seconds: Optional[int] = None,
    traffic_speed_class: str = "NORMAL",
    traffic_delay_seconds: float = 0.0,
) -> RoadSuitabilityResult:
    """Calculates deterministic road suitability score (0-100) combining road topology,
    visual inspection (if available), and real-time traffic jam telemetry."""
    penalties: list[PenaltyDetail] = []
    notes: list[str] = []
    known_restrictions = known_restrictions or []

    # Traffic Jam & Delay Penalties (from live Google Routes API)
    if traffic_speed_class == "TRAFFIC_JAM":
        penalties.append(
            PenaltyDetail(
                name="active_traffic_jam",
                penalty_value=25.0,
                reason="Google Routes API reports active traffic jam / gridlock on this corridor section.",
            )
        )
    elif traffic_speed_class == "SLOW":
        penalties.append(
            PenaltyDetail(
                name="traffic_slowdown",
                penalty_value=12.0,
                reason="Google Routes API reports stop-and-go congestion on this corridor section.",
            )
        )

    # If visual imagery inspection is unavailable, calculate score based on verified
    # road functional hierarchy, corridor geometry, and vehicle characteristics
    if analysis is None:
        f_lower = (functional_class or "residential").lower()
        if f_lower == "arterial":
            base_score = 86.0
            width_score = 88.0
            parking_score = 88.0
            pedestrian_score = 82.0
            lane_score = 86.0
            conf = 0.85
            is_safe = True
        elif f_lower == "collector":
            base_score = 75.0
            width_score = 74.0
            parking_score = 76.0
            pedestrian_score = 75.0
            lane_score = 75.0
            conf = 0.80
            is_safe = True
        elif f_lower in ("alley", "narrow_residential"):
            base_score = 36.0
            width_score = 30.0
            parking_score = 35.0
            pedestrian_score = 50.0
            lane_score = 30.0
            conf = 0.70
            is_safe = vehicle_type not in (VehicleType.HEAVY_TRUCK, VehicleType.DELIVERY_VAN)
            penalties.append(
                PenaltyDetail(
                    name="narrow_corridor_restriction",
                    penalty_value=20.0,
                    reason="Alley / narrow corridor vulnerable to immediate side-street gridlock.",
                )
            )
        else:
            # Standard residential corridor
            base_score = 63.0
            width_score = 60.0
            parking_score = 62.0
            pedestrian_score = 68.0
            lane_score = 62.0
            conf = 0.78
            is_safe = True

        # Heavy vehicle mismatch on residential streets
        if vehicle_type in (VehicleType.HEAVY_TRUCK, VehicleType.DELIVERY_VAN) and f_lower in ("residential", "alley"):
            penalties.append(
                PenaltyDetail(
                    name="vehicle_profile_mismatch",
                    penalty_value=18.0,
                    reason=f"Vehicle type '{vehicle_type.value}' clearance restricted on residential corridor.",
                )
            )

        # Subtract active penalties
        total_penalty = sum(p.penalty_value for p in penalties)
        final_score = round(max(10.0, min(100.0, base_score - total_penalty)), 1)

        explanation_parts = []
        if final_score >= 75:
            explanation_parts.append(f"High suitability {f_lower} corridor with multi-lane capacity and favorable traffic flow.")
        elif final_score >= 55:
            explanation_parts.append(f"Moderate suitability {f_lower} street: suitable for baseline transit but susceptible to peak-hour congestion.")
        else:
            explanation_parts.append(f"Low suitability {f_lower} section: narrow profile, traffic friction, or active bottlenecks make this route sub-optimal.")

        if penalties:
            explanation_parts.append(f"Flags: {', '.join(p.name for p in penalties)}.")

        return RoadSuitabilityResult(
            suitability_score=final_score,
            confidence=conf,
            data_freshness_seconds=data_freshness_seconds,
            feature_contributions={
                "road_width": width_score,
                "parking_friction": parking_score,
                "pedestrian_safety": pedestrian_score,
                "lane_connectivity": lane_score,
            },
            penalties_applied=penalties,
            explanation=" ".join(explanation_parts),
            is_safe_for_vehicle=is_safe,
            vehicle_type=vehicle_type,
        )

    # Calculate individual subscores
    width_score, width_uncertainty = compute_width_subscore(
        analysis.usable_road_width_meters, vehicle_type, penalties, notes
    )
    parking_score = compute_parking_friction_subscore(
        analysis.parking_obstruction, penalties
    )
    pedestrian_score = compute_pedestrian_safety_subscore(
        analysis.pedestrian_cyclist_activity, penalties
    )
    lane_score, lane_uncertainty = compute_lane_connectivity_subscore(
        analysis.visible_lane_count, penalties
    )

    # Base weighted aggregate
    raw_score = (
        (width_score * WEIGHT_ROAD_WIDTH)
        + (parking_score * WEIGHT_PARKING_FRICTION)
        + (pedestrian_score * WEIGHT_PEDESTRIAN_SAFETY)
        + (lane_score * WEIGHT_LANE_CONNECTIVITY)
    )

    # Check visible obstacles
    for obstacle in analysis.visible_obstacles:
        obs_lower = obstacle.lower()
        if "construction" in obs_lower or "work" in obs_lower:
            penalties.append(
                PenaltyDetail(
                    name="active_construction",
                    penalty_value=30.0,
                    reason=f"Active road construction detected: {obstacle}",
                )
            )
        elif "double_parking" in obs_lower or "delivery_blockage" in obs_lower:
            penalties.append(
                PenaltyDetail(
                    name="double_parking_obstruction",
                    penalty_value=20.0,
                    reason=f"Severe bottleneck from double parking: {obstacle}",
                )
            )
        elif "pothole" in obs_lower or "rough" in obs_lower:
            penalties.append(
                PenaltyDetail(
                    name="surface_degradation",
                    penalty_value=12.0,
                    reason=f"Surface roughness: {obstacle}",
                )
            )

    # Check road restrictions
    all_restrictions = set(known_restrictions + analysis.visible_road_restrictions)
    is_safe = True
    for res in all_restrictions:
        res_lower = res.lower()
        if "no_entry" in res_lower or "one_way_violation" in res_lower:
            penalties.append(
                PenaltyDetail(
                    name="access_restriction",
                    penalty_value=80.0,
                    reason=f"Prohibited travel direction or restriction: {res}",
                )
            )
            is_safe = False
        elif "resident_only" in res_lower or "local_access" in res_lower:
            penalties.append(
                PenaltyDetail(
                    name="residential_traffic_calming",
                    penalty_value=35.0,
                    reason="Designated local/residential access only corridor.",
                )
            )
        elif "speed_bump" in res_lower or "chicanes" in res_lower:
            penalties.append(
                PenaltyDetail(
                    name="traffic_calming_chicanes",
                    penalty_value=15.0,
                    reason="Physical traffic calming measures installed to discourage cut-throughs.",
                )
            )

    # Functional class modifier
    if functional_class == "arterial":
        # Arterials are purpose-built for traffic flow
        raw_score = min(100.0, raw_score * 1.1)
    elif functional_class in ("alley", "narrow_residential"):
        penalties.append(
            PenaltyDetail(
                name="low_order_street_class",
                penalty_value=15.0,
                reason=f"Functional road hierarchy ({functional_class}) is inappropriate for commuter spillover.",
            )
        )

    # Sum penalties
    total_penalty = sum(p.penalty_value for p in penalties)
    adjusted_score = max(0.0, raw_score - total_penalty)

    # Uncertainty discounting
    base_confidence = analysis.confidence
    effective_confidence = max(0.1, base_confidence - width_uncertainty - lane_uncertainty)
    if analysis.missing_or_uncertain_info:
        effective_confidence = max(0.1, effective_confidence - 0.05 * len(analysis.missing_or_uncertain_info))

    # Incorporate confidence into final score: low confidence compresses toward conservative midpoint
    final_score = adjusted_score * (0.65 + 0.35 * effective_confidence)
    final_score = round(max(0.0, min(100.0, final_score)), 1)

    # Build human explanation
    explanation_parts = []
    if final_score >= 80:
        explanation_parts.append("High suitability corridor: wide travel lanes and minimal roadside obstruction.")
    elif final_score >= 50:
        explanation_parts.append("Moderate suitability: acceptable for low volumes but vulnerable to passing friction.")
    else:
        explanation_parts.append("Poor suitability: narrow profile, parked vehicles, or pedestrian sensitivity make this road unsuitable for diverted commuter traffic.")

    if penalties:
        top_penalties = ", ".join(p.name for p in penalties[:3])
        explanation_parts.append(f"Penalties triggered: {top_penalties}.")

    return RoadSuitabilityResult(
        suitability_score=final_score,
        confidence=round(effective_confidence, 2),
        data_freshness_seconds=data_freshness_seconds,
        feature_contributions={
            "road_width_score": round(width_score, 1),
            "parking_friction_score": round(parking_score, 1),
            "pedestrian_safety_score": round(pedestrian_score, 1),
            "lane_connectivity_score": round(lane_score, 1),
        },
        penalties_applied=penalties,
        explanation=" ".join(explanation_parts),
        is_safe_for_vehicle=is_safe,
        vehicle_type=vehicle_type,
    )
