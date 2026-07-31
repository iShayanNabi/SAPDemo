"""Optional AI narrative for a contract analysis.

The AI layer is strictly additive. Every clause, date, obligation, missing
clause and risk finding has already been decided by the deterministic engine
before this module is called; the narrative only rephrases those results for a
reader and lands in its own fields, labelled with its origin.

Two things make this the module's most safety-sensitive call, and both are
handled before the request leaves:

* the payload is a summary of *results*, not the document, so a whole contract
  never reaches the provider;
* every string in it is passed through the shared injection filter, and the
  prompt wraps it in an explicit untrusted-data block.

If the provider fails, times out or returns something that does not validate,
the failure is captured and reported - the analysis itself is never lost.
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
from app.services.ai.prompts import (
    build_contract_answer_request,
    build_contract_summary_request,
)

logger = get_logger(__name__)

__all__ = [
    "ContractNarrativeResult",
    "ContractNarrativeService",
    "ContractSummaryPayload",
]


class ContractSummaryPayload(BaseModel):
    """The JSON shape the model must return, validated before use."""

    summary: str
    key_findings: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)


@dataclass
class ContractNarrativeResult:
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


class ContractNarrativeService:
    """Turn a completed contract analysis into an optional, labelled narrative."""

    def __init__(self, provider: AIProvider | None = None) -> None:
        self.provider = provider or get_ai_provider()

    def summarise_analysis(
        self,
        contract_summary: dict[str, Any],
        key_dates: dict[str, Any],
        clauses: list[dict[str, Any]],
        risks: list[dict[str, Any]],
        missing_clauses: list[dict[str, Any]],
    ) -> ContractNarrativeResult:
        """Ask the active provider to explain an already-computed analysis."""
        request = build_contract_summary_request(
            contract_summary=contract_summary,
            key_dates=key_dates,
            clauses=clauses,
            risks=risks,
            missing_clauses=missing_clauses,
        )
        return self._run(request)

    def rephrase_answer(
        self,
        question: str,
        answer: dict[str, Any],
        citations: list[dict[str, Any]],
    ) -> ContractNarrativeResult:
        """Ask the active provider to rephrase one deterministic answer."""
        request = build_contract_answer_request(
            question=question, answer=answer, citations=citations
        )
        return self._run(request)

    def _run(self, request: Any) -> ContractNarrativeResult:
        """Run one request, converting every failure into a reported result."""
        try:
            payload, response = self.provider.complete_structured(
                request, ContractSummaryPayload
            )
        except AIProviderError as exc:
            logger.warning("Contract narrative unavailable: %s", exc)
            return ContractNarrativeResult(error=str(exc), provider=self.provider.name)
        except Exception as exc:  # noqa: BLE001 - an AI failure never fails an analysis
            logger.warning("Contract narrative failed unexpectedly: %s", type(exc).__name__)
            return ContractNarrativeResult(
                error=f"The AI provider failed: {type(exc).__name__}.",
                provider=self.provider.name,
            )

        return ContractNarrativeResult(
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
