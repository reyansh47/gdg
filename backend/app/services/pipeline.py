"""End-to-end routing pipeline orchestrator.

Integrates real-time Google Routes API generation, Street View imagery sampling,
Gemini multimodal road inspection, deterministic suitability scoring, and capacity-aware selection.
Operates strictly in live online mode.
"""

import logging
from typing import Optional
from backend.app.config import settings
from backend.app.schemas.api import CostWeightsConfig
from backend.app.schemas.road import VehicleType
from backend.app.schemas.route import (
    CandidateRoute,
    Coordinate,
    SelectedRouteDecision,
    RoadSegmentData,
)
from backend.app.services.google_routes import get_candidate_routes
from backend.app.services.street_view import fetch_street_view_image_bytes
from backend.app.services.gemini_vision import analyze_road_imagery_with_gemini
from backend.app.engine.scoring import calculate_road_suitability
from backend.app.engine.routing import select_best_route
from backend.app.engine.registry import RouteAllocationRegistry

logger = logging.getLogger(__name__)


import asyncio

async def _inspect_single_segment(
    seg: RoadSegmentData,
    vehicle_type: VehicleType,
    semaphore: asyncio.Semaphore,
    fetch_image: bool = True,
) -> tuple[float, bool]:
    async with semaphore:
        image_bytes = None
        if fetch_image and settings.GOOGLE_STREET_VIEW_API_KEY:
            try:
                image_bytes = await asyncio.wait_for(
                    fetch_street_view_image_bytes(
                        seg.start_coord,
                        heading=seg.street_view_heading,
                    ),
                    timeout=8.0,
                )
            except Exception as e:
                logger.debug("Street view fetch error for '%s': %s", seg.name, e)
                image_bytes = None

        has_image = bool(image_bytes)
        seg.has_imagery = has_image

        vision = None
        if image_bytes and settings.GEMINI_API_KEY:
            try:
                vision, _ = await asyncio.wait_for(
                    analyze_road_imagery_with_gemini(
                        image_bytes=image_bytes,
                        road_name=seg.name,
                        functional_class=seg.functional_class,
                    ),
                    timeout=18.0,
                )
            except Exception as e:
                logger.debug("Gemini vision analysis error for '%s': %s", seg.name, e)
                vision = None

        seg.vision_analysis = vision

        suitability = calculate_road_suitability(
            analysis=vision,
            functional_class=seg.functional_class,
            vehicle_type=vehicle_type,
            known_restrictions=seg.restrictions,
            traffic_speed_class=seg.traffic_speed_class,
            traffic_delay_seconds=seg.traffic_delay_seconds,
        )
        seg.suitability = suitability
        return suitability.suitability_score, has_image


async def analyze_candidate_routes_pipeline(
    candidates: list[CandidateRoute],
    vehicle_type: VehicleType = VehicleType.PASSENGER_CAR,
    sample_interval_meters: float = 100.0,
) -> tuple[list[CandidateRoute], int, float, str]:
    """Inspects segments across live candidate routes concurrently via Street View and Gemini Vision."""
    total_segments = 0
    imagery_successes = 0
    provenance = f"gemini_{settings.GEMINI_MODEL}"

    semaphore = asyncio.Semaphore(2)
    tasks = []
    route_segment_counts = []

    for route in candidates:
        route_tasks = []
        for s_i, seg in enumerate(route.segments):
            should_fetch = s_i < settings.MAX_IMAGE_BUDGET_PER_ROUTE
            route_tasks.append(_inspect_single_segment(seg, vehicle_type, semaphore, fetch_image=should_fetch))
        route_segment_counts.append(len(route_tasks))
        tasks.extend(route_tasks)

    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=True)
    else:
        results = []

    result_idx = 0
    for r_idx, route in enumerate(candidates):
        count = route_segment_counts[r_idx]

        for seg_i in range(count):
            res = results[result_idx]
            result_idx += 1
            total_segments += 1

            if isinstance(res, tuple):
                score, has_img = res
                if has_img:
                    imagery_successes += 1
            else:
                # In case of unhandled exception
                logger.warning("Segment analysis raised unhandled exception: %s", res)
                seg = route.segments[seg_i]
                suitability = calculate_road_suitability(
                    analysis=None,
                    functional_class=seg.functional_class,
                    vehicle_type=vehicle_type,
                    known_restrictions=seg.restrictions,
                    traffic_speed_class=seg.traffic_speed_class,
                    traffic_delay_seconds=seg.traffic_delay_seconds,
                )
                seg.suitability = suitability

        if route.segments:
            total_len = sum(s.length_meters for s in route.segments)
            weighted_score = sum(s.suitability.suitability_score * s.length_meters for s in route.segments if s.suitability)
            weighted_conf = sum(s.suitability.confidence * s.length_meters for s in route.segments if s.suitability)
            route.suitability_score = round(weighted_score / max(1.0, total_len), 1)
            route.confidence = round(weighted_conf / max(1.0, total_len), 2)

    coverage_ratio = imagery_successes / max(1, total_segments)
    return candidates, total_segments, round(coverage_ratio, 2), provenance



async def run_flowsplit_pipeline(
    origin: Coordinate,
    destination: Coordinate,
    vehicle_type: VehicleType = VehicleType.PASSENGER_CAR,
    current_route_id: Optional[str] = None,
    weights: Optional[CostWeightsConfig] = None,
    registry: Optional[RouteAllocationRegistry] = None,
) -> tuple[SelectedRouteDecision, list[CandidateRoute], list[str]]:
    """Runs full online pipeline: Google Routes API -> Street View -> Gemini Vision -> FlowSplit selection."""
    # 1. Fetch live candidate routes from Google Routes API
    candidates, provider, warnings = await get_candidate_routes(
        origin, destination, vehicle_type
    )

    # 2. Road visual inspection and suitability scoring
    analyzed_candidates, _, _, _ = await analyze_candidate_routes_pipeline(
        candidates,
        vehicle_type=vehicle_type,
        sample_interval_meters=settings.SAMPLE_INTERVAL_METERS,
    )

    # 3. Capacity-aware route selection
    decision = select_best_route(
        candidates=analyzed_candidates,
        current_route_id=current_route_id,
        weights=weights,
        registry=registry,
        vehicle_type=vehicle_type,
    )

    return decision, analyzed_candidates, warnings
