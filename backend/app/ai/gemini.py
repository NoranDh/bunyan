"""Gemini access for language tasks only.

Modes (GEMINI_MODE):
- mock   : returns fixtures supplied by each feature. No network. Used by tests and offline demos.
- apikey : google-genai with GEMINI_API_KEY (Google AI Studio). For development before GCP.
- vertex : google-genai on Vertex AI (GCP_PROJECT, GCP_REGION). For production.

Every response is validated with Pydantic. An invalid response is retried once,
then the caller gets None and falls back to a non-AI path.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from functools import lru_cache
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.config import settings

log = logging.getLogger("bunyan.ai")

T = TypeVar("T", bound=BaseModel)
TEMPERATURE = 0.1  # CLAUDE.md: temperature ≤ 0.2
MAX_ATTEMPTS = 2  # one try and one retry


class GeminiUnavailable(RuntimeError):
    """Raised when the configuration cannot reach a model (for example, no key set)."""


class GeminiClient:
    def __init__(
        self,
        mode: str,
        model: str,
        api_key: str | None = None,
        project: str | None = None,
        region: str = "me-central2",
    ) -> None:
        if mode not in {"mock", "apikey", "vertex"}:
            raise ValueError(f"GEMINI_MODE must be mock, apikey or vertex, not {mode!r}")
        self.mode = mode
        self.model = model
        self.api_key = api_key
        self.project = project
        self.region = region
        self._client: Any = None  # injected in tests, created lazily otherwise

    def _get_client(self) -> Any:
        if self._client is None:
            from google import genai  # imported lazily: mock mode needs no SDK calls

            if self.mode == "apikey":
                if not self.api_key:
                    raise GeminiUnavailable("GEMINI_API_KEY is not set")
                self._client = genai.Client(api_key=self.api_key)
            else:
                if not self.project:
                    raise GeminiUnavailable("GCP_PROJECT is not set")
                self._client = genai.Client(vertexai=True, project=self.project, location=self.region)
        return self._client

    def structured(
        self,
        *,
        prompt: str,
        schema: type[T],
        mock: Callable[[], T],
        pdf: bytes | None = None,
    ) -> T | None:
        """Return a validated `schema` instance, or None if the model is unavailable or invalid."""
        if self.mode == "mock":
            return mock()
        if not self.model:
            log.warning("GEMINI_MODEL is not set; AI features are unavailable")
            return None

        from google.genai import types

        contents: list[Any] = [prompt]
        if pdf is not None:
            contents.append(types.Part.from_bytes(data=pdf, mime_type="application/pdf"))
        config = types.GenerateContentConfig(
            temperature=TEMPERATURE,
            response_mime_type="application/json",
            response_schema=schema,
        )

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = self._get_client().models.generate_content(
                    model=self.model, contents=contents, config=config
                )
                return schema.model_validate_json(response.text or "")
            except ValidationError as exc:
                log.warning("Gemini output failed validation (attempt %d): %s", attempt, exc.errors()[:2])
            except GeminiUnavailable as exc:
                log.warning("Gemini unavailable: %s", exc)
                return None
            except Exception as exc:  # network or quota errors: retry once, then give up
                log.warning("Gemini call failed (attempt %d): %s", attempt, exc)
        return None


@lru_cache(maxsize=1)
def get_llm() -> GeminiClient:
    return GeminiClient(
        mode=settings.gemini_mode,
        model=settings.gemini_model,
        api_key=settings.gemini_api_key,
        project=settings.gcp_project,
        region=settings.gcp_region,
    )
