"""Pydantic schemas for coordinates, road segments, candidate routes, and selection results."""

from typing import Any, Optional
from pydantic import BaseModel, Field
from backend.app.schemas.road import RoadSuitabilityResult, VisionRoadAnalysis, VehicleType


class Coordinate(BaseModel):
    lat: float = Field(ge=-90.0, le=90.0, description="Latitude")
    lng: float = Field(ge=-180.0, le=180.0, description="Longitude")


class RoadSegmentData(BaseModel):
    segment_id: str
    name: str
    start_coord: Coordinate
    end_coord: Coordinate
    length_meters: float = Field(gt=0.0)
    functional_class: str = Field(default="residential", description="e.g. arterial, collector, residential, alley")
    nominal_capacity_vph: float = Field(default=500.0, description="Vehicles per hour baseline capacity")
    current_volume_vph: float = Field(default=0.0, description="Observed or simulated traffic volume")
    free_flow_speed_kmh: float = Field(default=40.0)
    traffic_delay_seconds: float = Field(default=0.0)
    traffic_speed_class: str = Field(default="NORMAL", description="NORMAL, SLOW, or TRAFFIC_JAM")
    restrictions: list[str] = Field(default_factory=list)
    vision_analysis: Optional[VisionRoadAnalysis] = None
    suitability: Optional[RoadSuitabilityResult] = None
    has_imagery: bool = True
    street_view_heading: Optional[float] = None
    imagery_timestamp: Optional[str] = None


class CandidateRoute(BaseModel):
    id: str
    name: str
    summary: str
    distance_meters: float
    free_flow_duration_seconds: float
    traffic_duration_seconds: float
    encoded_polyline: str
    coordinates: list[Coordinate] = Field(default_factory=list)
    segments: list[RoadSegmentData] = Field(default_factory=list)
    is_simulated: bool = False
    suitability_score: float = Field(default=50.0, ge=0.0, le=100.0)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    route_color: Optional[str] = None
    traffic_jams: list[dict[str, Any]] = Field(default_factory=list)
    delay_seconds: float = Field(default=0.0)
    delay_ratio: float = Field(default=1.0)
    traffic_condition: str = Field(default="Normal")


class RouteCostBreakdown(BaseModel):
    route_id: str
    route_name: str
    travel_time_seconds: float
    travel_time_cost: float
    congestion_penalty: float
    unsuitable_road_penalty: float
    uncertainty_penalty: float
    total_cost: float
    overall_suitability_score: float
    mean_confidence: float
    bottleneck_segment_id: Optional[str] = None
    bottleneck_reason: Optional[str] = None
    volume_to_capacity_ratio_max: float = 0.0


class SelectedRouteDecision(BaseModel):
    selected_route_id: str
    selected_route: CandidateRoute
    candidate_breakdowns: list[RouteCostBreakdown]
    recommendation_rationale: str
    algorithm_mode: str = "flowsplit_capacity_aware"
    hysteresis_applied: bool = False
    previous_route_id: Optional[str] = None
    vehicle_type: VehicleType = VehicleType.PASSENGER_CAR
    data_limitations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
