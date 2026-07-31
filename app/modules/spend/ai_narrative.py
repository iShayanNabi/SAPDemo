"""Optional AI narrative for a spend analysis.

The AI never produces a number. By the time this module runs, every metric,
breakdown and savings estimate already exists; the model is asked only to
describe them in business language.

If the provider is slow, unavailable or returns something that does not match
the expected schema, the analysis still completes and the error is reported.
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
from app.services.ai.prompts import build_spend_summary_request

logger = get_logger(__name__)


class SpendSummaryPayload(BaseModel):
    """Structure the model must return. Validated before anything is stored."""

    summary: str = Field(min_length=1, max_length=4000)
    key_findings: list[str] = Field(default_factory=list, max_length=12)
    recommended_actions: list[str] = Field(default_factory=list, max_length=12)


@dataclass
class SpendNarrativeResult:
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


class SpendNarrativeService:
    """Produces the optional narrative around a completed spend analysis."""

    def __init__(self, provider: AIProvider | None = None) -> None:
        self.provider = provider or get_ai_provider()

    def generate(
        self,
        metrics: dict[str, Any],
        top_suppliers: list[dict[str, Any]],
        top_categories: list[dict[str, Any]],
        opportunities: list[dict[str, Any]],
    ) -> SpendNarrativeResult:
        """Generate the spend summary, degrading gracefully on any failure."""
        request = build_spend_summary_request(
            _metrics_for_prompt(metrics),
            [_supplier_for_prompt(s) for s in top_suppliers[:5]],
            [_category_for_prompt(c) for c in top_categories[:8]],
            [_opportunity_for_prompt(o) for o in opportunities[:10]],
        )
        try:
            payload, response = self.provider.complete_structured(request, SpendSummaryPayload)
        except AIProviderError as exc:
            logger.warning("Spend narrative unavailable: %s", exc)
            return SpendNarrativeResult(error=str(exc), provider=self.provider.name)

        return SpendNarrativeResult(
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


def _metrics_for_prompt(metrics: dict[str, Any]) -> dict[str, Any]:
    """Send only the headline figures, not the whole metrics object."""
    keys = (
        "total_spend", "purchase_order_count", "line_item_count", "supplier_count",
        "average_po_value", "median_po_value", "contracted_spend_pct", "maverick_spend",
        "maverick_spend_pct", "spend_under_management_pct", "supplier_concentration_level",
        "supplier_concentration_hhi", "top_supplier_share_pct", "top_five_supplier_share_pct",
        "tail_spend_pct", "tail_supplier_count", "price_variance_base",
        "estimated_savings_opportunity", "base_currency",
    )
    return {key: metrics.get(key) for key in keys if key in metrics}


def _supplier_for_prompt(supplier: dict[str, Any]) -> dict[str, Any]:
    keys = ("supplier_id", "supplier_name", "spend_base", "spend_share_pct", "is_tail",
            "maverick_spend_base")
    return {key: supplier.get(key) for key in keys if key in supplier}


def _category_for_prompt(category: dict[str, Any]) -> dict[str, Any]:
    keys = ("value", "spend_base", "share_pct", "supplier_count")
    return {key: category.get(key) for key in keys if key in category}


def _opportunity_for_prompt(opportunity: dict[str, Any]) -> dict[str, Any]:
    keys = ("rule_id", "rule_name", "title", "estimated_saving_base", "confidence",
            "realization_factor", "is_estimate")
    return {key: opportunity.get(key) for key in keys if key in opportunity}
