"""Real AI providers: Anthropic and OpenAI.

Both talk to their HTTP APIs through ``httpx`` so the project needs no vendor
SDKs. They share the same retry/timeout behaviour:

* the request times out after ``settings.ai_timeout_seconds``;
* transient failures (timeout, 429, 5xx) are retried up to
  ``settings.ai_max_retries`` times with exponential backoff;
* permanent failures (401, 400) fail immediately - retrying a bad key is waste.

API keys are read from settings, sent only in the request header, and never
logged or returned to the client.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.core.config import settings
from app.core.exceptions import AIProviderError
from app.core.logging import get_logger
from app.schemas.common import OutputOrigin
from app.services.ai.base import AIProvider, AIRequest, AIResponse, estimate_cost_usd

logger = get_logger(__name__)

_RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


class _HttpProviderMixin:
    """Shared retry loop for HTTP based providers."""

    name = "http"

    def _post_with_retries(
        self, url: str, headers: dict[str, str], payload: dict[str, Any]
    ) -> tuple[dict[str, Any], int, int]:
        """POST with retries. Returns (json_body, latency_ms, attempts)."""
        attempts = 0
        last_error: Exception | None = None
        started = time.perf_counter()

        for attempt in range(settings.ai_max_retries + 1):
            attempts = attempt + 1
            try:
                with httpx.Client(timeout=settings.ai_timeout_seconds) as client:
                    response = client.post(url, headers=headers, json=payload)

                if response.status_code in _RETRYABLE_STATUS:
                    last_error = AIProviderError(
                        f"The AI provider returned a temporary error (HTTP {response.status_code})."
                    )
                    logger.warning(
                        "%s call failed with HTTP %s (attempt %d/%d)",
                        self.name, response.status_code, attempts, settings.ai_max_retries + 1,
                    )
                elif response.status_code >= 400:
                    # Permanent - do not retry.
                    raise AIProviderError(
                        f"The AI provider rejected the request (HTTP {response.status_code}).",
                        details={"provider": self.name, "status_code": response.status_code},
                    )
                else:
                    latency = int((time.perf_counter() - started) * 1000)
                    return response.json(), latency, attempts

            except httpx.TimeoutException as exc:
                last_error = exc
                logger.warning(
                    "%s call timed out after %.1fs (attempt %d)",
                    self.name, settings.ai_timeout_seconds, attempts,
                )
            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning("%s transport error on attempt %d: %s", self.name, attempts, exc)

            if attempt < settings.ai_max_retries:
                time.sleep(min(2**attempt * 0.5, 4.0))

        raise AIProviderError(
            "The AI provider is unavailable. The deterministic analysis results are unaffected.",
            details={"provider": self.name, "attempts": attempts,
                     "last_error": type(last_error).__name__ if last_error else "unknown"},
        )


class AnthropicProvider(_HttpProviderMixin, AIProvider):
    """Claude via the Anthropic Messages API."""

    name = "anthropic"
    API_URL = "https://api.anthropic.com/v1/messages"
    API_VERSION = "2023-06-01"

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key or settings.anthropic_api_key
        self.model = model or settings.anthropic_model
        if not self.api_key:
            raise AIProviderError("No Anthropic API key is configured.")

    def complete(self, request: AIRequest) -> AIResponse:
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": self.API_VERSION,
            "content-type": "application/json",
        }
        payload = {
            "model": self.model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "system": request.system_prompt,
            "messages": [{"role": "user", "content": request.user_prompt}],
        }
        body, latency, attempts = self._post_with_retries(self.API_URL, headers, payload)

        text = "".join(
            block.get("text", "")
            for block in body.get("content", [])
            if block.get("type") == "text"
        )
        usage = body.get("usage", {}) or {}
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")

        return AIResponse(
            text=text,
            provider=self.name,
            model=body.get("model", self.model),
            origin=OutputOrigin.AI_GENERATED,
            prompt_version=request.prompt_version,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=estimate_cost_usd(self.model, input_tokens, output_tokens),
            latency_ms=latency,
            attempts=attempts,
            raw_metadata={"stop_reason": body.get("stop_reason")},
        )


class OpenAIProvider(_HttpProviderMixin, AIProvider):
    """OpenAI via the Chat Completions API."""

    name = "openai"
    API_URL = "https://api.openai.com/v1/chat/completions"

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key or settings.openai_api_key
        self.model = model or settings.openai_model
        if not self.api_key:
            raise AIProviderError("No OpenAI API key is configured.")

    def complete(self, request: AIRequest) -> AIResponse:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
        }
        if request.expects_json:
            payload["response_format"] = {"type": "json_object"}

        body, latency, attempts = self._post_with_retries(self.API_URL, headers, payload)

        choices = body.get("choices", [])
        text = choices[0].get("message", {}).get("content", "") if choices else ""
        usage = body.get("usage", {}) or {}
        input_tokens = usage.get("prompt_tokens")
        output_tokens = usage.get("completion_tokens")

        return AIResponse(
            text=text,
            provider=self.name,
            model=body.get("model", self.model),
            origin=OutputOrigin.AI_GENERATED,
            prompt_version=request.prompt_version,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=estimate_cost_usd(self.model, input_tokens, output_tokens),
            latency_ms=latency,
            attempts=attempts,
            raw_metadata={"finish_reason": choices[0].get("finish_reason") if choices else None},
        )
