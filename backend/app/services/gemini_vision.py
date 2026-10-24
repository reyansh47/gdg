"""Gemini Vision Analysis Service using official Google Gen AI SDK.

Inspects street imagery to produce structured physical road characteristics:
usable width, lanes, parking friction, obstacles, pedestrian context, and restrictions.

Operates strictly in online mode using Gemini API keys and models from .env.
Predefined mock data and offline fallback modes have been removed.
"""

import logging
from typing import Optional
from backend.app.config import settings
from backend.app.schemas.road import VisionRoadAnalysis

logger = logging.getLogger(__name__)

GEMINI_ANALYSIS_PROMPT = """You are a senior traffic engineer and geometric road safety inspector.
Analyze this street-level photograph of a road segment.
Inspect directly visible physical conditions:
1. Usable road width: estimate the clear carriageway width in meters between curb/parked cars. If obscured, mark as null.
2. Lane count: count marked or functional travel lanes. If ambiguous, mark as null.
3. Parking obstruction: evaluate curb parking density (none, low, moderate, high, blocked).
4. Visible obstacles: identify hazards such as construction, double parking, road surface defects, or delivery vehicles.
5. Pedestrian context: observe sidewalk adequacy, crosswalks, school zones, or shared street spaces.
6. Visible restrictions: notice signs like one-way, no entry, speed humps, or weight limits.
7. Confidence: rate your assessment confidence from 0.0 to 1.0.
8. Missing or uncertain information: list anything you cannot reliably ascertain from this perspective.
9. Evidence notes: provide brief factual observations supporting your findings.

Do NOT invent vehicle throughput numbers or guess exact traffic volumes. Distinguish clearly visible facts from inferences."""


async def analyze_road_imagery_with_gemini(
    image_bytes: Optional[bytes],
    road_name: Optional[str] = None,
    functional_class: str = "residential",
) -> tuple[Optional[VisionRoadAnalysis], str]:
    """Inspects road image using official Google Gen AI SDK in live online mode."""
    if not settings.GEMINI_API_KEY:
        raise ValueError(
            "GEMINI_API_KEY is not configured in .env. "
            "Offline fallback and mock data are disabled. Live online mode requires a valid Gemini API key."
        )

    if not image_bytes:
        # Factual indicator that Street View imagery was not available for this geographic coordinate
        logger.debug("No image bytes supplied for road segment '%s'", road_name)
        return None, "no_imagery_available"

    import asyncio

    try:
        from google import genai
        from google.genai import types

        client_kwargs = {"api_key": settings.GEMINI_API_KEY}
        if settings.GEMINI_API_URL and settings.GEMINI_API_URL != "https://generativelanguage.googleapis.com":
            client_kwargs["http_options"] = types.HttpOptions(base_url=settings.GEMINI_API_URL)

        client = genai.Client(**client_kwargs)
        image_part = types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")

        max_attempts = 2
        delay = 2.0
        for attempt in range(max_attempts):
            try:
                response = await client.aio.models.generate_content(
                    model=settings.GEMINI_MODEL,
                    contents=[image_part, GEMINI_ANALYSIS_PROMPT],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=VisionRoadAnalysis,
                        temperature=0.2,
                    ),
                )

                if response.text:
                    analysis = VisionRoadAnalysis.model_validate_json(response.text)
                    return analysis, f"gemini_{settings.GEMINI_MODEL}"
                else:
                    logger.warning("Gemini API returned an empty response body for road '%s'.", road_name)
                    return None, "empty_gemini_response"

            except Exception as exc:
                err_str = str(exc)
                if "RESOURCE_EXHAUSTED" in err_str or "quota" in err_str.lower():
                    logger.info("Gemini API daily quota limit reached; falling back instantly to road intelligence model.")
                    return None, "gemini_quota_exceeded"
                if "429" in err_str and attempt < max_attempts - 1:
                    logger.info("Gemini 429 rate limit reached, retrying in %.1fs...", delay)
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
                logger.warning("Gemini Vision API invocation failed for road '%s': %s", road_name, exc)
                return None, f"gemini_error: {err_str[:100]}"

    except Exception as outer_exc:
        logger.warning("Gemini client initialization error: %s", outer_exc)
        return None, f"gemini_init_error: {str(outer_exc)[:100]}"

