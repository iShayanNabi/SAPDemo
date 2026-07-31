"""Optional AI narrative layer for the Purchase Order Risk Checker.

What this layer does **not** do: decide risk. Severity, exposure, evidence and
the finding itself all come from the deterministic engine. The AI is only asked
to restate those facts in business language and to draft an executive summary.

Every result is validated with Pydantic before it is stored, and is labelled
``ai_generated`` or ``mock_ai`` so a reader always knows what they are looking
at. If the provider fails, the analysis continues without narratives.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.core.exceptions import AIProviderError
from app.core.logging import get_logger
from app.schemas.common import OutputOrigin
from app.services.ai.base import AIProvider
from app.services.ai.factory import get_ai_provider
from app.services.ai.prompts import (
    PROMPT_VERSION,
    build_executive_summary_request,
    build_finding_explanation_request,
)

logger = get_logger(__name__)

MAX_FINDINGS_TO_REWRITE = 10


class ExecutiveSummaryPayload(BaseModel):
    """Schema an executive summary response must satisfy."""

    summary: str = Field(min_length=20, max_length=4000)
    key_risks: list[str] = Field(default_factory=list, max_length=12)
    recommended_actions: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("key_risks", "recommended_actions", mode="before")
    @classmethod
    def _coerce_list(cls, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        return value


class FindingExplanationPayload(BaseModel):
    """Schema a per-finding rewrite must satisfy."""

    plain_language_explanation: str = Field(min_length=10, max_length=2000)
    business_action: str = Field(default="", max_length=1000)


@dataclass
class NarrativeResult:
    """Outcome of the optional AI enrichment step."""

    provider: str
    origin: OutputOrigin | None
    prompt_version: str
    summary: str | None = None
    key_risks: list[str] = field(default_factory=list)
    recommended_actions: list[str] = field(default_factory=list)
    finding_explanations: dict[str, dict[str, str]] = field(default_factory=dict)
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost_usd: float | None = None
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.summary is not None and self.error is None


class NarrativeService:
    """Generates the optional AI narratives for an analysis."""

    def __init__(self, provider: AIProvider | None = None) -> None:
        self.provider = provider or get_ai_provider()

    def generate(
        self,
        summary: dict[str, Any],
        supplier_risk: list[dict[str, Any]],
        findings: list[dict[str, Any]],
        *,
        rewrite_findings: bool = True,
    ) -> NarrativeResult:
        """Produce the executive summary and (optionally) per-finding rewrites."""
        result = NarrativeResult(
            provider=self.provider.name,
            origin=None,
            prompt_version=PROMPT_VERSION,
        )

        request = build_executive_summary_request(
            analysis_summary=_summary_for_prompt(summary),
            top_rules=summary.get("rule_counts", [])[:8],
            top_suppliers=supplier_risk[:5],
            sample_findings=[_finding_for_prompt(f) for f in findings[:15]],
        )

        try:
            payload, response = self.provider.complete_structured(request, ExecutiveSummaryPayload)
        except AIProviderError as exc:
            logger.warning("Executive summary unavailable: %s", exc.message)
            result.error = exc.message
            return result

        result.summary = payload.summary
        result.key_risks = payload.key_risks
        result.recommended_actions = payload.recommended_actions
        result.origin = response.origin
        result.input_tokens = response.input_tokens
        result.output_tokens = response.output_tokens
        result.estimated_cost_usd = response.estimated_cost_usd

        if rewrite_findings:
            self._rewrite_top_findings(findings, result)
        return result

    def _rewrite_top_findings(
        self, findings: list[dict[str, Any]], result: NarrativeResult
    ) -> None:
        """Rewrite the most severe findings, accumulating token usage."""
        for finding in findings[:MAX_FINDINGS_TO_REWRITE]:
            finding_id = finding.get("id") or finding.get("finding_id")
            if not finding_id:
                continue
            request = build_finding_explanation_request(_finding_for_prompt(finding))
            try:
                payload, response = self.provider.complete_structured(
                    request, FindingExplanationPayload
                )
            except AIProviderError as exc:
                logger.info("Skipping AI rewrite for finding %s: %s", finding_id, exc.message)
                continue

            result.finding_explanations[str(finding_id)] = {
                "explanation": payload.plain_language_explanation,
                "action": payload.business_action,
                "origin": response.origin.value,
            }
            result.input_tokens = _add(result.input_tokens, response.input_tokens)
            result.output_tokens = _add(result.output_tokens, response.output_tokens)
            if response.estimated_cost_usd is not None:
                result.estimated_cost_usd = round(
                    (result.estimated_cost_usd or 0.0) + response.estimated_cost_usd, 6
                )


def _add(current: int | None, addition: int | None) -> int | None:
    """Add two optional token counters."""
    if current is None and addition is None:
        return None
    return (current or 0) + (addition or 0)


def _summary_for_prompt(summary: dict[str, Any]) -> dict[str, Any]:
    """Trim the KPI block to the fields the narrative needs."""
    keys = (
        "record_count", "purchase_order_count", "supplier_count", "total_value_base",
        "base_currency", "findings_count", "severity_counts", "category_counts",
        "flagged_value_base", "flagged_value_share_pct", "estimated_exposure_base", "risk_score",
    )
    return {key: summary.get(key) for key in keys if key in summary}


def _finding_for_prompt(finding: dict[str, Any]) -> dict[str, Any]:
    """Trim one finding to the fields the narrative needs."""
    keys = (
        "rule_id", "rule_name", "risk_category", "severity", "po_number", "po_item",
        "supplier_id", "supplier_name", "explanation", "recommended_action",
        "estimated_financial_exposure", "exposure_currency",
    )
    return {key: finding.get(key) for key in keys if key in finding}
