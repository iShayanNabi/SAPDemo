"""Optional AI narrative for a supplier recommendation.

The AI never ranks a supplier or produces a score. By the time this module runs,
the deterministic engine has already ranked every supplier; the model is asked
only to describe that ranking in business language.

If the provider is slow, unavailable or returns something that does not match
the expected schema, the recommendation still completes and the error is
reported alongside the deterministic result.
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
from app.services.ai.prompts import build_supplier_reco_summary_request

logger = get_logger(__name__)


class SupplierRecoSummaryPayload(BaseModel):
    """Structure the model must return. Validated before anything is stored."""

    summary: str = Field(min_length=1, max_length=4000)
    key_findings: list[str] = Field(default_factory=list, max_length=12)
    recommended_actions: list[str] = Field(default_factory=list, max_length=12)


@dataclass
class SupplierRecoNarrativeResult:
    """Outcome of the optional narrative step."""

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


class SupplierRecoNarrativeService:
    """Produces the optional narrative around a completed recommendation."""

    def __init__(self, provider: AIProvider | None = None) -> None:
        self.provider = provider or get_ai_provider()

    def generate(
        self,
        requirement: dict[str, Any],
        weights: dict[str, Any],
        ranking_summary: dict[str, Any],
        top_suppliers: list[dict[str, Any]],
    ) -> SupplierRecoNarrativeResult:
        """Generate the recommendation summary, degrading gracefully on failure."""
        request = build_supplier_reco_summary_request(
            _requirement_for_prompt(requirement),
            weights,
            ranking_summary,
            [_supplier_for_prompt(s) for s in top_suppliers[:5]],
        )
        try:
            payload, response = self.provider.complete_structured(
                request, SupplierRecoSummaryPayload
            )
        except AIProviderError as exc:
            logger.warning("Supplier recommendation narrative unavailable: %s", exc)
            return SupplierRecoNarrativeResult(error=str(exc), provider=self.provider.name)

        return SupplierRecoNarrativeResult(
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


def _requirement_for_prompt(requirement: dict[str, Any]) -> dict[str, Any]:
    """Send only the headline requirement fields."""
    keys = (
        "material", "material_description", "material_group", "quantity", "unit_of_measure",
        "plant", "required_delivery_date", "target_price", "currency", "preferred_region",
        "risk_tolerance", "sustainability_requirement", "contract_requirement",
        "minimum_quality_score", "minimum_available_capacity",
    )
    return {key: requirement.get(key) for key in keys if requirement.get(key) is not None}


def _supplier_for_prompt(supplier: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "rank", "supplier_id", "supplier_name", "overall_score", "cost_score", "delivery_score",
        "quality_score", "risk_score", "esg_score", "contract_score", "estimated_total_cost_base",
        "estimated_delivery_date", "advantages", "risks",
    )
    return {key: supplier.get(key) for key in keys if key in supplier}
