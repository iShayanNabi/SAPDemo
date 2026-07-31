"""Shared contract for every AI provider.

The rest of the codebase only knows :class:`AIProvider`. Swapping Anthropic for
OpenAI, or falling back to the deterministic mock, therefore never changes a
line of business logic.

Two guarantees hold for every provider:

* an AI failure is **never** fatal - the caller receives an
  :class:`AIProviderError` and keeps its rule-based results;
* every response is labelled with its origin (``ai_generated`` or ``mock_ai``)
  so the UI can show the user where the text came from.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError as PydanticValidationError

from app.core.exceptions import AIProviderError
from app.core.logging import get_logger
from app.schemas.common import OutputOrigin

logger = get_logger(__name__)

SchemaT = TypeVar("SchemaT", bound=BaseModel)

#: Indicative prices per 1M tokens, used only for local cost visibility.
#: They are estimates for reporting, not billing figures.
MODEL_PRICING_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-5": (3.00, 15.00),
    "claude-opus-4-1": (15.00, 75.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
}


@dataclass
class AIRequest:
    """A single completion request."""

    system_prompt: str
    user_prompt: str
    prompt_version: str
    max_tokens: int = 1200
    temperature: float = 0.2
    expects_json: bool = True


@dataclass
class AIResponse:
    """A completion result plus its provenance and usage metrics."""

    text: str
    provider: str
    model: str
    origin: OutputOrigin
    prompt_version: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost_usd: float | None = None
    latency_ms: int = 0
    attempts: int = 1
    raw_metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_mock(self) -> bool:
        return self.origin is OutputOrigin.MOCK_AI


def estimate_cost_usd(model: str, input_tokens: int | None, output_tokens: int | None) -> float | None:
    """Estimate the USD cost of a call from the token counts."""
    pricing = MODEL_PRICING_USD_PER_MTOK.get(model)
    if pricing is None or input_tokens is None or output_tokens is None:
        return None
    input_price, output_price = pricing
    cost = (input_tokens / 1_000_000) * input_price + (output_tokens / 1_000_000) * output_price
    return round(cost, 6)


class AIProvider(ABC):
    """Interface implemented by the mock, Anthropic and OpenAI providers."""

    name: str = "base"

    @abstractmethod
    def complete(self, request: AIRequest) -> AIResponse:
        """Run a completion and return the response."""

    @property
    def is_mock(self) -> bool:
        return self.name == "mock"

    def complete_structured(
        self, request: AIRequest, schema: type[SchemaT]
    ) -> tuple[SchemaT, AIResponse]:
        """Run a completion and validate the JSON payload against ``schema``.

        Raises:
            AIProviderError: when the model does not return JSON that matches
                the schema. Callers treat this as "no AI enrichment available"
                and continue with the deterministic output.
        """
        response = self.complete(request)
        payload = extract_json_object(response.text)
        if payload is None:
            raise AIProviderError(
                "The AI response did not contain a JSON object.",
                details={"provider": self.name, "prompt_version": request.prompt_version},
            )
        try:
            model = schema.model_validate(payload)
        except PydanticValidationError as exc:
            logger.warning("AI response failed schema validation: %s", exc.error_count())
            raise AIProviderError(
                "The AI response did not match the expected structure.",
                details={
                    "provider": self.name,
                    "schema": schema.__name__,
                    "errors": exc.errors(include_url=False)[:5],
                },
            ) from exc
        return model, response


def extract_json_object(text: str) -> dict[str, Any] | None:
    """Pull the first JSON object out of a model response.

    Handles bare JSON, ```json fenced blocks and a little surrounding prose.
    """
    if not text:
        return None
    candidate = text.strip()

    fenced = re.search(r"```(?:json)?\s*(.+?)```", candidate, re.DOTALL)
    if fenced:
        candidate = fenced.group(1).strip()

    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    start = candidate.find("{")
    end = candidate.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        parsed = json.loads(candidate[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None
