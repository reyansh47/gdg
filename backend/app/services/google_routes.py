"""Google Routes API v2 client for real-time traffic-aware routing.

Operates strictly in online mode using Google Routes API v2.
All endpoints and API keys are dynamically loaded from environment configuration (.env).
Offline demo fallback and predefined data have been completely removed.
"""

import logging
from typing import Optional
import httpx
from backend.app.config import settings
from backend.app.schemas.route import (
    CandidateRoute,
    Coordinate,
    RoadSegmentData,
)
from backend.app.schemas.road import VehicleType
from backend.app.services.polyline_utils import (
    decode_encoded_polyline,
    haversine_distance_meters,
    sample_coordinates_at_interval,
)

logger = logging.getLogger(__name__)


def parse_duration_string(duration_str: Optional[str]) -> float:
    """Parses Google duration string like '345s' to float seconds."""
    if not duration_str:
        return 0.0
    val = duration_str.rstrip("s")
    try:
        return float(val)
    except ValueError:
        return 0.0


import re

def infer_road_properties(street_name: str) -> tuple[str, float, float]:
    """Infers (functional_class, nominal_capacity_vph, free_flow_speed_kmh) from road name."""
    name_lower = street_name.lower()
    if any(kw in name_lower for kw in ["expy", "expressway", "freeway", "highway", "hwy", "flyway", "blvd", "boulevard", "parkway", "pkwy", "bypass"]):
        return "arterial", 1800.0, 55.0
    elif any(kw in name_lower for kw in ["ave", "avenue"]):
        return "arterial", 1400.0, 45.0
    elif any(kw in name_lower for kw in ["road", "rd", "way", "drive", "dr", "route"]):
        return "collector", 900.0, 40.0
    elif any(kw in name_lower for kw in ["alley", "mews", "walk", "passage"]):
        return "alley", 250.0, 20.0
    elif any(kw in name_lower for kw in ["lane", "ln", "court", "ct", "place", "pl", "terrace", "ter"]):
        return "residential", 400.0, 30.0
    else:
        # Default street
        return "residential", 550.0, 35.0


def extract_street_name_from_instruction(instruction: str, default_name: str) -> str:
    """Extracts street name from Google navigation instruction text."""
    if not instruction:
        return default_name
    # Match patterns like "Turn right onto Geary Blvd" or "Continue onto Bush St" or "Head north on Clayton St"
    m = re.search(r'(?:onto|on|toward)\s+([A-Z0-9][A-Za-z0-9\s\.\-\'\&]+?)(?:\n|Pass by|\(|$)', instruction)
    if m:
        clean = m.group(1).strip()
        if len(clean) > 2 and not clean.lower().startswith("the "):
            return clean
    return default_name


async def fetch_candidate_routes_from_google(
    origin: Coordinate,
    destination: Coordinate,
    vehicle_type: VehicleType = VehicleType.PASSENGER_CAR,
) -> list[CandidateRoute]:
    """Calls Google Routes API v2 with alternative routes, traffic awareness, and speed intervals."""
    api_key = settings.GOOGLE_ROUTES_API_KEY
    if not api_key:
        raise ValueError(
            "GOOGLE_ROUTES_API_KEY is not configured in .env. "
            "FlowSplit runs strictly in online mode and requires a valid Google Routes API key."
        )

    api_url = settings.GOOGLE_ROUTES_API_URL or "https://routes.googleapis.com/directions/v2:computeRoutes"

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": (
            "routes.duration,routes.staticDuration,routes.distanceMeters,routes.polyline.encodedPolyline,"
            "routes.description,routes.warnings,routes.legs.steps,routes.travelAdvisory.speedReadingIntervals"
        ),
    }

    payload = {
        "origin": {
            "location": {
                "latLng": {"latitude": origin.lat, "longitude": origin.lng}
            }
        },
        "destination": {
            "location": {
                "latLng": {"latitude": destination.lat, "longitude": destination.lng}
            }
        },
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_AWARE",
        "computeAlternativeRoutes": True,
        "extraComputations": ["TRAFFIC_ON_POLYLINE"],
        "languageCode": "en-US",
        "units": "METRIC",
    }

    async with httpx.AsyncClient(timeout=settings.REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.post(api_url, json=payload, headers=headers)
        if response.status_code != 200:
            logger.error("Google Routes API error (%d): %s", response.status_code, response.text)
            raise RuntimeError(
                f"Google Routes API request failed with status {response.status_code}: {response.text[:250]}"
            )

        data = response.json()
        raw_routes = data.get("routes", [])
        if not raw_routes:
            logger.warning("Google Routes API returned 0 routes for coordinates.")
            return []

        results: list[CandidateRoute] = []
        colors = ["#2563eb", "#dc2626", "#10b981", "#d97706", "#8b5cf6"]

        for idx, r in enumerate(raw_routes):
            encoded = r.get("polyline", {}).get("encodedPolyline", "")
            coords = decode_encoded_polyline(encoded)
            dist_meters = float(r.get("distanceMeters", 0.0))
            duration_sec = parse_duration_string(r.get("duration", "0s"))
            static_sec = parse_duration_string(r.get("staticDuration", "0s")) or duration_sec
            summary = r.get("description", f"Route Alternative {idx + 1}")

            delay_sec = max(0.0, duration_sec - static_sec)
            delay_ratio = round(duration_sec / max(1.0, static_sec), 2)

            # Parse navigation steps and street names
            steps = r.get("legs", [{}])[0].get("steps", [])
            step_streets = []
            for s in steps:
                instr = s.get("navigationInstruction", {}).get("instructions", "")
                st_name = extract_street_name_from_instruction(instr, summary)
                step_streets.append(st_name)

            # Parse speed reading intervals (traffic jams and slowdowns)
            intervals = r.get("travelAdvisory", {}).get("speedReadingIntervals", [])
            traffic_jams = []
            has_gridlock = False
            has_slowdown = False

            for interval in intervals:
                speed = interval.get("speed", "NORMAL")
                start_p = interval.get("startPolylinePointIndex", 0)
                end_p = interval.get("endPolylinePointIndex", len(coords) - 1)
                
                if speed in ("TRAFFIC_JAM", "SLOW") and coords:
                    mid_idx = min(len(coords) - 1, max(0, (start_p + end_p) // 2))
                    jam_coord = coords[mid_idx]
                    is_heavy = speed == "TRAFFIC_JAM"
                    if is_heavy:
                        has_gridlock = True
                    else:
                        has_slowdown = True
                    
                    # Associate with closest step street
                    street_name = step_streets[min(len(step_streets) - 1, idx)] if step_streets else summary
                    traffic_jams.append({
                        "lat": jam_coord.lat,
                        "lng": jam_coord.lng,
                        "severity": "heavy" if is_heavy else "moderate",
                        "speed": speed,
                        "label": "Traffic Jam" if is_heavy else "Traffic Slowdown",
                        "street_name": street_name,
                        "delay_seconds": round(delay_sec),
                        "start_point_index": start_p,
                        "end_point_index": end_p,
                    })

            # Determine traffic condition
            if has_gridlock:
                condition = "Heavy Traffic Jam"
            elif has_slowdown or delay_ratio > 1.25:
                condition = "Congested Delays"
            elif delay_ratio > 1.08:
                condition = "Moderate Traffic"
            else:
                condition = "Smooth Flow"

            # Extract road segments across the full journey
            sampled = sample_coordinates_at_interval(
                coords,
                interval_meters=max(400.0, dist_meters / 8.0),
                max_samples=10,
            )

            segments: list[RoadSegmentData] = []
            for s_idx in range(len(sampled) - 1):
                start_c, bearing, p_idx = sampled[s_idx]
                end_c, _, _ = sampled[s_idx + 1]
                seg_len = haversine_distance_meters(start_c, end_c)

                # Match to appropriate street name along route
                seg_street = summary
                if step_streets:
                    st_i = min(len(step_streets) - 1, int((s_idx / max(1, len(sampled) - 1)) * len(step_streets)))
                    seg_street = step_streets[st_i]

                f_class, nom_cap, ff_speed = infer_road_properties(seg_street)

                # Check if this segment overlaps with any traffic jam interval
                seg_speed = "NORMAL"
                seg_delay = 0.0
                for tj in traffic_jams:
                    if tj.get("start_point_index", 0) <= p_idx <= tj.get("end_point_index", len(coords)):
                        seg_speed = tj["speed"]
                        seg_delay = delay_sec
                        break

                seg = RoadSegmentData(
                    segment_id=f"rt-{idx}-seg-{s_idx}",
                    name=f"{seg_street} (Sec {s_idx + 1})",
                    start_coord=start_c,
                    end_coord=end_c,
                    length_meters=max(20.0, round(seg_len, 1)),
                    functional_class=f_class,
                    nominal_capacity_vph=nom_cap,
                    current_volume_vph=0.0,
                    free_flow_speed_kmh=ff_speed,
                    traffic_delay_seconds=seg_delay,
                    traffic_speed_class=seg_speed,
                    street_view_heading=bearing,
                )
                segments.append(seg)

            # Compute initial baseline suitability score from road classes, traffic delays, and jams
            base_scores = []
            for s in segments:
                f_class = s.functional_class
                if f_class == "arterial":
                    s_score = 86.0
                elif f_class == "collector":
                    s_score = 75.0
                elif f_class in ("alley", "narrow_residential"):
                    s_score = 36.0
                else:
                    s_score = 63.0

                if s.traffic_speed_class == "TRAFFIC_JAM":
                    s_score -= 25.0
                elif s.traffic_speed_class == "SLOW":
                    s_score -= 12.0
                elif delay_ratio > 1.2:
                    s_score -= min(20.0, (delay_ratio - 1.0) * 35.0)

                base_scores.append(max(15.0, min(100.0, s_score)))

            computed_score = round(sum(base_scores) / max(1, len(base_scores)), 1) if base_scores else 70.0

            candidate = CandidateRoute(
                id=f"google-route-{idx}",
                name=summary,
                summary=f"{dist_meters / 1000.0:.1f} km, ~{duration_sec / 60.0:.1f} mins ({condition})",
                distance_meters=dist_meters,
                free_flow_duration_seconds=static_sec,
                traffic_duration_seconds=duration_sec,
                encoded_polyline=encoded,
                coordinates=coords,
                segments=segments,
                is_simulated=False,
                suitability_score=computed_score,
                confidence=0.82 if traffic_jams else 0.86,
                route_color=colors[idx % len(colors)],
                traffic_jams=traffic_jams,
                delay_seconds=delay_sec,
                delay_ratio=delay_ratio,
                traffic_condition=condition,
            )
            results.append(candidate)

        return results


async def get_candidate_routes(
    origin: Coordinate,
    destination: Coordinate,
    vehicle_type: VehicleType = VehicleType.PASSENGER_CAR,
) -> tuple[list[CandidateRoute], str, list[str]]:
    """Retrieves live candidate routes from Google Routes API.
    
    Offline fallback and predefined data are completely disabled.
    """
    warnings: list[str] = []

    if not settings.GOOGLE_ROUTES_API_KEY:
        raise ValueError(
            "GOOGLE_ROUTES_API_KEY is not configured in .env. "
            "Offline demo mode and predefined data are disabled. Live online mode requires an active key."
        )

    routes = await fetch_candidate_routes_from_google(origin, destination, vehicle_type)
    if not routes:
        raise ValueError(
            "Google Routes API returned zero paths between the specified origin and destination."
        )

    return routes, "google_routes_api", warnings
