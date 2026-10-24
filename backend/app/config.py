import os
from pathlib import Path
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Google Maps Platform keys and URLs
    GOOGLE_MAPS_BROWSER_KEY: Optional[str] = Field(
        default=None,
        description="Public browser key restricted to Maps JavaScript API and HTTP referrers."
    )
    GOOGLE_MAPS_JS_API_URL: str = Field(
        default="https://maps.googleapis.com/maps/api/js",
        description="Google Maps JavaScript API script URL."
    )
    GOOGLE_ROUTES_API_KEY: Optional[str] = Field(
        default=None,
        description="Server-side key for Google Routes API v2."
    )
    GOOGLE_ROUTES_API_URL: str = Field(
        default="https://routes.googleapis.com/directions/v2:computeRoutes",
        description="Google Routes API computeRoutes endpoint URL."
    )
    GOOGLE_STREET_VIEW_API_KEY: Optional[str] = Field(
        default=None,
        description="Server-side key for Street View Static API."
    )
    GOOGLE_STREET_VIEW_METADATA_URL: str = Field(
        default="https://maps.googleapis.com/maps/api/streetview/metadata",
        description="Google Street View Metadata API URL."
    )
    GOOGLE_STREET_VIEW_IMAGE_URL: str = Field(
        default="https://maps.googleapis.com/maps/api/streetview",
        description="Google Street View Static Image API URL."
    )

    # Google Gemini AI settings
    GEMINI_API_KEY: Optional[str] = Field(
        default=None,
        description="Gemini API Key for multimodal road inspection."
    )
    GEMINI_MODEL: str = Field(
        default="gemini-3.8-flash",
        description="Vision-capable Gemini model name."
    )
    GEMINI_API_URL: Optional[str] = Field(
        default=None,
        description="Optional custom API URL / endpoint for Gemini API."
    )

    # Frontend and Backend Server Network Configuration
    API_BASE_URL: Optional[str] = Field(
        default=None,
        description="Optional API base URL for client HTTP requests."
    )
    HOST: str = Field(
        default="0.0.0.0",
        description="Backend server host interface."
    )
    PORT: int = Field(
        default=8000,
        description="Backend server port."
    )

    # Persistence: No SQLite for now. Optional PostgreSQL for production.
    DATABASE_URL: Optional[str] = Field(
        default=None,
        description="Database connection string (Optional PostgreSQL only; SQLite is disabled)."
    )
    REDIS_URL: Optional[str] = Field(
        default=None,
        description="Optional Redis URL for shared caching and distributed allocation."
    )

    # Routing & Vision Parameters
    SAMPLE_INTERVAL_METERS: float = Field(default=300.0, ge=25.0, le=1000.0)
    MAX_IMAGE_BUDGET_PER_ROUTE: int = Field(default=2, ge=1, le=30)
    REQUEST_TIMEOUT_SECONDS: float = Field(default=25.0, ge=3.0, le=60.0)
    MAX_RETRIES: int = Field(default=3, ge=1, le=5)

    # Operational Mode: Strictly Online Mode
    ONLINE_MODE_ONLY: bool = Field(default=True, description="Strict online execution only.")
    ENVIRONMENT: str = Field(default="development")

    model_config = SettingsConfigDict(
        env_file=[
            str(Path(__file__).resolve().parents[2] / ".env"),
            str(Path(__file__).resolve().parent.parent / ".env"),
            ".env",
        ],
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def has_routes_key(self) -> bool:
        return bool(self.GOOGLE_ROUTES_API_KEY)

    @property
    def has_street_view_key(self) -> bool:
        return bool(self.GOOGLE_STREET_VIEW_API_KEY)

    @property
    def has_gemini_key(self) -> bool:
        return bool(self.GEMINI_API_KEY)

    @property
    def is_online_ready(self) -> bool:
        """Checks if minimum online credentials (Google Routes and Gemini) are configured."""
        return bool(self.GOOGLE_ROUTES_API_KEY and self.GEMINI_API_KEY)


settings = Settings()
