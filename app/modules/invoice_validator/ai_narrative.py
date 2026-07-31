"""Optional AI narrative for an invoice validation run.

The AI never decides whether an invoice is an exception. By the time this module
runs, the deterministic engine has already matched every invoice and raised the
exceptions; the model is asked only to describe them in business language.

If the provider is slow, unavailable or returns something that does not match the
expected schema, the validation still completes and the error is reported
alongside the deterministic result.
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
from app.services.ai.prompts import build_invoice_validation_summary_request

logger = get_logger(__name__)


class InvoiceValidationSummaryPayload(BaseModel):
    """Structure the model must return. Validated before anything is stored."""

    summary: str = Field(min_length=1, max_length=4000)
    key_findings: list[str] = Field(default_factory=list, max_length=12)
    recommended_actions: list[str] = Field(default_factory=list, max_length=12)


@dataclass
class InvoiceNarrativeResult:
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


class InvoiceNarrativeService:
    """Produces the optional narrative around a completed validation."""

    def __init__(self, provider: AIProvider | None = None) -> None:
        self.provider = provider or get_ai_provider()

    def generate(
        self,
        summary: dict[str, Any],
        supplier_summary: list[dict[str, Any]],
        exceptions: list[dict[str, Any]],
    ) -> InvoiceNarrativeResult:
        """Generate the validation summary, degrading gracefully on failure."""
        request = build_invoice_validation_summary_request(
            _summary_for_prompt(summary),
            summary.get("rule_counts", []),
            [_supplier_for_prompt(s) for s in supplier_summary[:5]],
            [_exception_for_prompt(e) for e in exceptions[:15]],
        )
        try:
            payload, response = self.provider.complete_structured(
                request, InvoiceValidationSummaryPayload
            )
        except AIProviderError as exc:
            logger.warning("Invoice validation narrative unavailable: %s", exc)
            return InvoiceNarrativeResult(error=str(exc), provider=self.provider.name)

        return InvoiceNarrativeResult(
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


def _summary_for_prompt(summary: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "invoice_count", "purchase_order_line_count", "goods_receipt_count", "supplier_count",
        "base_currency", "total_invoice_amount_base", "matched_to_po", "matched_to_goods_receipt",
        "fully_three_way_matched", "exceptions_count", "severity_counts", "category_counts",
        "flagged_invoice_count", "flagged_value_share_pct", "estimated_exposure_base",
        "exception_score",
    )
    return {key: summary.get(key) for key in keys if summary.get(key) is not None}


def _supplier_for_prompt(supplier: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "supplier_id", "supplier_name", "invoice_count", "exceptions_count",
        "estimated_exposure_base", "top_exception_type",
    )
    return {key: supplier.get(key) for key in keys if key in supplier}


def _exception_for_prompt(exception: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "rule_id", "rule_name", "exception_type", "severity", "invoice_number", "supplier_id",
        "po_number", "expected_value", "actual_value", "difference", "difference_amount", "currency",
    )
    return {key: exception.get(key) for key in keys if key in exception}
