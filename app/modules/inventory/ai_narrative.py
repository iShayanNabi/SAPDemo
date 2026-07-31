"""Optional AI narrative for an inventory forecast run.

The AI layer is strictly additive, and in this module that rule carries more
weight than anywhere else in the lab: a language model is perfectly willing to
produce something that looks like a demand forecast, and it would be wrong. Every
quantity, date, interval and accuracy figure has already been calculated by the
statistical engine before this module is called. The narrative only rephrases
them, in separate fields, and it is labelled with its origin wherever it appears.

If the provider fails, times out or returns something that does not validate, the
failure is captured and reported - the forecast itself is never lost.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from app.core.exceptions import AIProviderError
from app.core.logging import get_logger
from app.schemas.common import OutputOrigin
from app.services.ai.base import AIProvider
from app.services.ai.factory import get_ai_provider
from app.services.ai.prompts import build_inventory_summary_request

logger = get_logger(__name__)

__all__ = [
    "InventoryNarrativeResult",
    "InventoryNarrativeService",
    "InventorySummaryPayload",
]


class InventorySummaryPayload(BaseModel):
    """The JSON shape the model must return, validated before use."""

    summary: str
    key_findings: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)


@dataclass
class InventoryNarrativeResult:
    """The outcome of asking a provider for a narrative."""

    summary: str | None = None
    key_findings: list[str] = field(default_factory=list)
    recommended_actions: list[str] = field(default_factory=list)
    provider: str | None = None
    origin: OutputOrigin | None = None
    prompt_version: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost_usd: float | None = None
    error: str | None = None

    @property
    def available(self) -> bool:
        return self.summary is not None


class InventoryNarrativeService:
    """Turn a computed forecast run into an optional, clearly-labelled narrative."""

    def __init__(self, provider: AIProvider | None = None) -> None:
        self.provider = provider or get_ai_provider()

    def generate(
        self,
        forecast_summary: dict[str, Any],
        shortage_items: list[dict[str, Any]],
        overstock_items: list[dict[str, Any]],
        accuracy_summary: dict[str, Any],
    ) -> InventoryNarrativeResult:
        """Ask the active provider to summarise an already-computed forecast run."""
        request = build_inventory_summary_request(
            forecast_summary=forecast_summary,
            shortage_items=shortage_items,
            overstock_items=overstock_items,
            accuracy_summary=accuracy_summary,
        )
        try:
            payload, response = self.provider.complete_structured(
                request, InventorySummaryPayload
            )
        except AIProviderError as exc:
            logger.warning("Inventory narrative unavailable: %s", exc)
            return InventoryNarrativeResult(error=str(exc), provider=self.provider.name)
        except Exception as exc:  # noqa: BLE001 - an AI failure never fails a forecast
            logger.warning("Inventory narrative failed unexpectedly: %s", type(exc).__name__)
            return InventoryNarrativeResult(
                error=f"The AI provider failed: {type(exc).__name__}.",
                provider=self.provider.name,
            )

        return InventoryNarrativeResult(
            summary=payload.summary,
            key_findings=list(payload.key_findings),
            recommended_actions=list(payload.recommended_actions),
            provider=response.provider,
            origin=response.origin,
            prompt_version=response.prompt_version,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            estimated_cost_usd=response.estimated_cost_usd,
        )
