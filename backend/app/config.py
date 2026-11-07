"""Runtime configuration, read only from environment variables.

Local defaults need no GCP account: an in-memory store and mocked Gemini.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    firestore_disabled: bool
    gemini_mode: str  # mock | apikey | vertex
    gemini_model: str
    gemini_api_key: str | None
    gcp_project: str | None
    gcp_region: str
    upload_bucket: str | None
    cors_origins: tuple[str, ...]


def load_settings() -> Settings:
    origins = os.environ.get("CORS_ORIGINS", "http://localhost:5173")
    return Settings(
        firestore_disabled=_env_bool("FIRESTORE_DISABLED", True),
        gemini_mode=os.environ.get("GEMINI_MODE", "mock"),
        # Model ID is never hardcoded; confirm it in Vertex AI Model Garden.
        gemini_model=os.environ.get("GEMINI_MODEL", ""),
        gemini_api_key=os.environ.get("GEMINI_API_KEY"),
        gcp_project=os.environ.get("GCP_PROJECT"),
        gcp_region=os.environ.get("GCP_REGION", "me-central2"),
        upload_bucket=os.environ.get("UPLOAD_BUCKET"),
        cors_origins=tuple(o.strip() for o in origins.split(",") if o.strip()),
    )


settings = load_settings()
