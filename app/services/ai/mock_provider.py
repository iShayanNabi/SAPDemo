"""Deterministic mock AI provider.

This is the default provider and the reason the whole lab runs with no API
keys. It produces *plausibly shaped* output - valid JSON matching the same
schemas a real model must satisfy - by templating the facts that the
deterministic engine already computed.

It never invents numbers: everything in a mock narrative comes from the payload
the caller passed in. Output is labelled ``mock_ai`` everywhere it appears.
"""

from __future__ import annotations

import json
import time
from typing import Any

from app.core.logging import get_logger
from app.schemas.common import OutputOrigin
from app.services.ai.base import AIProvider, AIRequest, AIResponse, extract_json_object

logger = get_logger(__name__)

MOCK_MODEL = "mock-deterministic-v1"


class MockAIProvider(AIProvider):
    """Templated stand-in for a real model."""

    name = "mock"

    def complete(self, request: AIRequest) -> AIResponse:
        """Return a deterministic response derived from the prompt payload."""
        started = time.perf_counter()
        payload = extract_json_object(request.user_prompt) or {}
        task = str(payload.get("task", "")).strip() or _infer_task(request.user_prompt)

        if task == "executive_summary":
            text = json.dumps(_executive_summary(payload), ensure_ascii=False)
        elif task == "explain_finding":
            text = json.dumps(_explain_finding(payload), ensure_ascii=False)
        elif task == "spend_summary":
            text = json.dumps(_spend_summary(payload), ensure_ascii=False)
        elif task == "supplier_recommendation":
            text = json.dumps(_supplier_recommendation(payload), ensure_ascii=False)
        elif task == "invoice_validation":
            text = json.dumps(_invoice_validation(payload), ensure_ascii=False)
        else:
            text = json.dumps(
                {
                    "summary": (
                        "Mock AI mode is active. No language model was called; this text is "
                        "generated locally from the deterministic analysis results."
                    ),
                    "key_risks": [],
                    "recommended_actions": [],
                },
                ensure_ascii=False,
            )

        latency = int((time.perf_counter() - started) * 1000)
        input_tokens = _approx_tokens(request.system_prompt) + _approx_tokens(request.user_prompt)
        output_tokens = _approx_tokens(text)
        logger.debug("Mock AI produced %d characters for task '%s'", len(text), task)

        return AIResponse(
            text=text,
            provider=self.name,
            model=MOCK_MODEL,
            origin=OutputOrigin.MOCK_AI,
            prompt_version=request.prompt_version,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=0.0,
            latency_ms=latency,
            raw_metadata={"task": task, "note": "generated locally, no API call"},
        )


def _infer_task(prompt: str) -> str:
    """Guess the task when the prompt is not a JSON payload."""
    lowered = prompt.lower()
    if "executive summary" in lowered:
        return "executive_summary"
    if "spend review" in lowered or "spend summary" in lowered:
        return "spend_summary"
    if "supplier ranking" in lowered or "supplier recommendation" in lowered:
        return "supplier_recommendation"
    if "invoice validation" in lowered or "invoice exception" in lowered:
        return "invoice_validation"
    if "finding" in lowered:
        return "explain_finding"
    return "unknown"


def _approx_tokens(text: str) -> int:
    """Rough token estimate (~4 characters per token) for usage reporting."""
    return max(1, len(text or "") // 4)


def _executive_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """Build the mock executive summary from the deterministic KPIs."""
    summary_data: dict[str, Any] = payload.get("analysis_summary", {}) or {}
    top_rules: list[dict[str, Any]] = payload.get("top_rules", []) or []
    top_suppliers: list[dict[str, Any]] = payload.get("top_suppliers", []) or []

    severity = summary_data.get("severity_counts", {}) or {}
    currency = summary_data.get("base_currency", "EUR")
    findings_count = summary_data.get("findings_count", 0)
    record_count = summary_data.get("record_count", 0)
    exposure = summary_data.get("estimated_exposure_base", 0)
    flagged_share = summary_data.get("flagged_value_share_pct", 0)

    sentences = [
        f"The rule engine reviewed {record_count:,} purchase order line items and raised "
        f"{findings_count:,} findings.",
        f"{severity.get('critical', 0)} are critical and {severity.get('high', 0)} are high "
        f"severity; together the findings touch {flagged_share:.1f}% of the analysed order value.",
        f"The estimated gross exposure across all findings is {float(exposure):,.0f} {currency}, "
        "which is an upper bound because one line item can trigger several rules.",
    ]
    if top_rules:
        leader = top_rules[0]
        sentences.append(
            f"The most frequent issue is '{leader.get('rule_name', leader.get('rule_id'))}' with "
            f"{leader.get('count', 0)} findings."
        )
    if top_suppliers:
        supplier = top_suppliers[0]
        sentences.append(
            f"Supplier {supplier.get('supplier_id')} "
            f"({supplier.get('supplier_name') or 'name not supplied'}) carries the largest share "
            f"of the risk with {supplier.get('findings_count', 0)} findings."
        )

    key_risks = [
        f"{rule.get('rule_name', rule.get('rule_id'))}: {rule.get('count', 0)} finding(s), "
        f"approximately {float(rule.get('exposure', 0)):,.0f} {currency} exposure"
        for rule in top_rules[:5]
    ] or ["No rule produced a finding for this dataset."]

    actions = [
        "Review the critical and high severity findings before the next invoice run.",
        "Confirm the approval trail for every unreleased order above the release threshold.",
        "Consolidate repeated small orders on the same supplier into contract call-offs.",
        "Check the flagged price deviations against the current info records and agreements.",
    ]

    return {
        "summary": " ".join(sentences),
        "key_risks": key_risks,
        "recommended_actions": actions[: max(2, min(4, len(actions)))],
    }


def _explain_finding(payload: dict[str, Any]) -> dict[str, Any]:
    """Build a mock business-friendly rewrite of a single finding."""
    finding: dict[str, Any] = payload.get("finding", {}) or {}
    rule_name = finding.get("rule_name", "risk rule")
    po_number = finding.get("po_number") or "the affected document"
    severity = finding.get("severity", "medium")
    exposure = float(finding.get("estimated_financial_exposure", 0) or 0)
    currency = finding.get("exposure_currency", "EUR")

    return {
        "plain_language_explanation": (
            f"{rule_name} was triggered on {po_number}. In business terms: the check compares this "
            f"document against the agreed purchasing policy and found a deviation rated "
            f"{severity}. About {exposure:,.0f} {currency} of order value is affected, so it is "
            "worth a manual look before the invoice is paid."
        ),
        "business_action": (
            "Ask the responsible buyer to confirm the deviation was intentional and documented; "
            "if it was not, correct the document before goods receipt."
        ),
    }


def _spend_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """Build the mock spend narrative from the deterministic metrics.

    Every number below is copied from the metrics that were already computed.
    The mock provider never calculates anything - it only templates, which is
    exactly what a real model is asked to do here too.
    """
    metrics: dict[str, Any] = payload.get("metrics", {}) or {}
    suppliers: list[dict[str, Any]] = payload.get("top_suppliers", []) or []
    categories: list[dict[str, Any]] = payload.get("top_categories", []) or []
    opportunities: list[dict[str, Any]] = payload.get("savings_opportunities", []) or []

    currency = metrics.get("base_currency", "EUR")
    total = float(metrics.get("total_spend", 0) or 0)
    suppliers_count = int(metrics.get("supplier_count", 0) or 0)
    transactions = int(metrics.get("line_item_count", 0) or 0)
    managed_pct = float(metrics.get("spend_under_management_pct", 0) or 0)
    maverick = float(metrics.get("maverick_spend", 0) or 0)
    maverick_pct = float(metrics.get("maverick_spend_pct", 0) or 0)
    tail_pct = float(metrics.get("tail_spend_pct", 0) or 0)
    tail_suppliers = int(metrics.get("tail_supplier_count", 0) or 0)
    top_share = float(metrics.get("top_supplier_share_pct", 0) or 0)
    concentration = metrics.get("supplier_concentration_level", "unknown")
    savings = float(metrics.get("estimated_savings_opportunity", 0) or 0)

    summary = (
        f"The analysis covers {total:,.0f} {currency} of spend across {transactions:,} "
        f"transactions with {suppliers_count:,} suppliers. "
        f"{managed_pct:.1f}% of that spend is under management, while "
        f"{maverick:,.0f} {currency} ({maverick_pct:.1f}%) was placed outside both a contract "
        f"and the preferred supplier list. "
        f"Supplier concentration is {concentration}, with the largest supplier holding "
        f"{top_share:.1f}% of spend, and {tail_suppliers:,} tail suppliers account for "
        f"{tail_pct:.1f}% of the total. "
        f"The savings models identify {savings:,.0f} {currency} of estimated opportunity, "
        "which is an indicative figure for investigation rather than a committed saving."
    )

    key_findings: list[str] = []
    if maverick > 0:
        key_findings.append(
            f"Maverick spend of {maverick:,.0f} {currency} ({maverick_pct:.1f}% of total) "
            "sits outside contract and preferred supplier coverage."
        )
    if suppliers:
        leader = suppliers[0]
        key_findings.append(
            f"Supplier {leader.get('supplier_id')} is the largest at "
            f"{float(leader.get('spend_base', 0) or 0):,.0f} {currency} "
            f"({float(leader.get('spend_share_pct', 0) or 0):.1f}% of spend)."
        )
    if categories:
        top_category = categories[0]
        key_findings.append(
            f"The largest category is {top_category.get('value')} at "
            f"{float(top_category.get('spend_base', 0) or 0):,.0f} {currency}."
        )
    if tail_suppliers:
        key_findings.append(
            f"{tail_suppliers:,} tail suppliers carry {tail_pct:.1f}% of spend, a candidate "
            "for rationalisation."
        )

    actions: list[str] = []
    for opportunity in opportunities[:3]:
        actions.append(
            f"{opportunity.get('title')} - estimated "
            f"{float(opportunity.get('estimated_saving_base', 0) or 0):,.0f} {currency} "
            f"(modelled, not guaranteed)."
        )
    if not actions:
        actions.append(
            "No savings opportunity cleared the configured thresholds for this data slice."
        )

    return {
        "summary": summary,
        "key_findings": key_findings,
        "recommended_actions": actions,
    }


def _supplier_recommendation(payload: dict[str, Any]) -> dict[str, Any]:
    """Build the mock supplier-recommendation narrative from the deterministic ranking.

    Every number below is copied from the ranking the engine already produced.
    The mock provider never re-ranks or recomputes anything.
    """
    requirement: dict[str, Any] = payload.get("requirement", {}) or {}
    summary_data: dict[str, Any] = payload.get("ranking_summary", {}) or {}
    suppliers: list[dict[str, Any]] = payload.get("top_suppliers", []) or []

    currency = summary_data.get("base_currency", "EUR")
    total = int(summary_data.get("total_supplier_count", 0) or 0)
    eligible = int(summary_data.get("eligible_count", 0) or 0)
    ineligible = int(summary_data.get("ineligible_count", 0) or 0)
    material = requirement.get("material") or "the requirement"

    lead = suppliers[0] if suppliers else {}
    lead_id = lead.get("supplier_id")
    lead_name = lead.get("supplier_name") or "the top-ranked supplier"
    lead_score = float(lead.get("overall_score", 0) or 0)
    lead_cost = lead.get("estimated_total_cost_base")

    sentences = [
        f"Of {total} suppliers assessed for {material}, {eligible} passed the eligibility filters "
        f"and {ineligible} were excluded before ranking.",
    ]
    if lead_id:
        cost_text = (
            f" with an estimated total cost of {float(lead_cost):,.0f} {currency}"
            if lead_cost is not None
            else ""
        )
        sentences.append(
            f"{lead_name} ({lead_id}) ranks first with an overall score of {lead_score:g}/100"
            f"{cost_text}."
        )
    sentences.append(
        "The ranking is produced by a deterministic weighted-scoring model; the figures here are "
        "indicative planning estimates, not quotations or commitments."
    )

    key_findings: list[str] = []
    for supplier in suppliers[:3]:
        if supplier.get("rank") is None:
            continue
        key_findings.append(
            f"#{supplier.get('rank')} {supplier.get('supplier_name') or supplier.get('supplier_id')} "
            f"- overall {float(supplier.get('overall_score', 0) or 0):g}/100 "
            f"(cost {float(supplier.get('cost_score', 0) or 0):g}, "
            f"delivery {float(supplier.get('delivery_score', 0) or 0):g}, "
            f"risk {float(supplier.get('risk_score', 0) or 0):g})."
        )
    if not key_findings:
        key_findings.append("No supplier passed the eligibility filters for this requirement.")

    actions: list[str] = []
    if lead_id:
        actions.append(
            f"Request a firm quotation from {lead_name} ({lead_id}) and confirm capacity and lead time."
        )
    if len(suppliers) > 1:
        runner_up = suppliers[1]
        actions.append(
            f"Keep {runner_up.get('supplier_name') or runner_up.get('supplier_id')} as a backup "
            "and use it to benchmark the negotiation."
        )
    actions.append(
        "Review the advantages and risks listed for each supplier before committing."
    )

    return {
        "summary": " ".join(sentences),
        "key_findings": key_findings,
        "recommended_actions": actions,
    }


def _invoice_validation(payload: dict[str, Any]) -> dict[str, Any]:
    """Build the mock invoice-validation narrative from the deterministic KPIs.

    Every number below is copied from the summary the engine already computed;
    the mock provider never re-matches or recomputes anything.
    """
    summary_data: dict[str, Any] = payload.get("validation_summary", {}) or {}
    top_rules: list[dict[str, Any]] = payload.get("top_rules", []) or []
    top_suppliers: list[dict[str, Any]] = payload.get("top_suppliers", []) or []

    severity = summary_data.get("severity_counts", {}) or {}
    currency = summary_data.get("base_currency", "EUR")
    invoice_count = summary_data.get("invoice_count", 0)
    exceptions_count = summary_data.get("exceptions_count", 0)
    matched = summary_data.get("fully_three_way_matched", 0)
    exposure = summary_data.get("estimated_exposure_base", 0)
    flagged_share = summary_data.get("flagged_value_share_pct", 0)

    sentences = [
        f"The validator checked {invoice_count:,} invoice line(s) against the uploaded purchase "
        f"orders and goods receipts and raised {exceptions_count:,} exception(s).",
        f"{severity.get('critical', 0)} are critical and {severity.get('high', 0)} are high "
        f"severity; the flagged invoices represent {float(flagged_share):.1f}% of the invoiced "
        f"value, and {matched:,} line(s) matched cleanly on all three documents.",
        f"The estimated gross exposure across all exceptions is {float(exposure):,.0f} {currency}, "
        "an upper bound because one invoice can raise several exceptions.",
    ]
    if top_rules:
        leader = top_rules[0]
        sentences.append(
            f"The most frequent exception is '{leader.get('rule_name', leader.get('rule_id'))}' "
            f"with {leader.get('count', 0)} occurrence(s)."
        )

    key_findings = [
        f"{rule.get('rule_name', rule.get('rule_id'))}: {rule.get('count', 0)} exception(s), "
        f"approximately {float(rule.get('exposure', 0)):,.0f} {currency} exposure"
        for rule in top_rules[:5]
    ] or ["No rule produced an exception for these files."]

    if top_suppliers:
        leader = top_suppliers[0]
        key_findings.append(
            f"Supplier {leader.get('supplier_id')} carries the most exceptions "
            f"({leader.get('exceptions_count', 0)})."
        )

    actions = [
        "Block the critical and high severity exceptions before the next payment run.",
        "Reconcile price and quantity mismatches against the purchase order and goods receipt.",
        "Confirm any duplicate invoices are not paid twice.",
        "Obtain the missing purchase orders and goods receipts before releasing those invoices.",
    ]

    return {
        "summary": " ".join(sentences),
        "key_findings": key_findings,
        "recommended_actions": actions[: max(2, min(4, len(actions)))],
    }
