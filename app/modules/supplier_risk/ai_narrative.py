"""Optional AI narrative for a supplier risk assessment.

The AI layer is strictly additive. Every risk score, band, trend and
recommended action has already been decided by the deterministic model before
this module is called; the narrative only rephrases those results for a reader.

If the provider fails, times out or returns something that does not validate,
the failure is captured and reported - the assessment itself is never lost.
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
from app.services.ai.prompts import build_supplier_risk_summary_request

logger = get_logger(__name__)

__all__ = [
    "SupplierRiskNarrativeResult",
    "SupplierRiskNarrativeService",
    "SupplierRiskSummaryPayload",
]


class SupplierRiskSummaryPayload(BaseModel):
    """The JSON shape the model must return, validated before use."""

    summary: str
    key_findings: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)


@dataclass
class SupplierRiskNarrativeResult:
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


class SupplierRiskNarrativeService:
    """Turn a computed assessment into an optional, clearly-labelled narrative."""

    def __init__(self, provider: AIProvider | None = None) -> None:
        self.provider = provider or get_ai_provider()

    def generate(
        self,
        assessment_summary: dict[str, Any],
        top_suppliers: list[dict[str, Any]],
        category_averages: dict[str, Any],
    ) -> SupplierRiskNarrativeResult:
        """Ask the active provider to summarise an already-computed assessment."""
        request = build_supplier_risk_summary_request(
            assessment_summary=assessment_summary,
            top_suppliers=top_suppliers,
            category_averages=category_averages,
        )
        try:
            payload, response = self.provider.complete_structured(
                request, SupplierRiskSummaryPayload
            )
        except AIProviderError as exc:
            logger.warning("Supplier risk narrative unavailable: %s", exc)
            return SupplierRiskNarrativeResult(error=str(exc), provider=self.provider.name)
        except Exception as exc:  # noqa: BLE001 - an AI failure never fails an assessment
            logger.warning(
                "Supplier risk narrative failed unexpectedly: %s", type(exc).__name__
            )
            return SupplierRiskNarrativeResult(
                error=f"The AI provider failed: {type(exc).__name__}.",
                provider=self.provider.name,
            )

        return SupplierRiskNarrativeResult(
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
