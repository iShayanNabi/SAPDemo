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
        elif task == "supplier_risk":
            text = json.dumps(_supplier_risk(payload), ensure_ascii=False)
        elif task == "inventory_forecast":
            text = json.dumps(_inventory_forecast(payload), ensure_ascii=False)
        elif task == "contract_analysis":
            text = json.dumps(_contract_analysis(payload), ensure_ascii=False)
        elif task == "contract_answer":
            text = json.dumps(_contract_answer(payload), ensure_ascii=False)
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
    if "supplier risk" in lowered or "risk assessment" in lowered:
        return "supplier_risk"
    if "inventory forecast" in lowered or "demand forecast" in lowered:
        return "inventory_forecast"
    if "contract answer" in lowered or "contract question" in lowered:
        return "contract_answer"
    if "contract review" in lowered or "contract analysis" in lowered:
        return "contract_analysis"
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


def _supplier_risk(payload: dict[str, Any]) -> dict[str, Any]:
    """Build the mock supplier risk narrative from the deterministic scores.

    Every figure below is copied from the payload the scoring model produced.
    The mock never invents a score, a band or a supplier.
    """
    summary_data: dict[str, Any] = payload.get("assessment_summary", {}) or {}
    top_suppliers: list[dict[str, Any]] = payload.get("top_suppliers", []) or []
    category_averages: dict[str, Any] = payload.get("category_averages", {}) or {}

    supplier_count = summary_data.get("supplier_count", 0)
    scored_count = summary_data.get("scored_count", 0)
    band_counts = summary_data.get("band_counts", {}) or {}
    average_score = summary_data.get("average_overall_score")
    expiring = summary_data.get("contracts_expiring_count", 0)
    limited = summary_data.get("limited_data_count", 0)

    sentences = [
        f"The risk model scored {scored_count:,} of {supplier_count:,} loaded suppliers using "
        f"the configured category weights.",
    ]
    if average_score is not None:
        sentences.append(
            f"The average overall risk is {float(average_score):.1f} out of 100, with "
            f"{band_counts.get('critical', 0)} supplier(s) in the critical band and "
            f"{band_counts.get('high', 0)} in the high band."
        )
    if top_suppliers:
        leader = top_suppliers[0]
        leader_score = leader.get("overall_score")
        if leader_score is not None:
            sentences.append(
                f"The highest-risk supplier is {leader.get('supplier_name') or leader.get('supplier_id')} "
                f"({leader.get('supplier_id')}) at {float(leader_score):.1f} "
                f"('{leader.get('overall_band')}')."
            )
    if expiring:
        sentences.append(f"{expiring} supplier contract(s) fall inside the expiry warning window.")
    sentences.append(
        "All figures come from the uploaded internal records only; no live financial, credit, "
        "ESG or news service was contacted."
    )

    key_findings: list[str] = []
    for supplier in top_suppliers[:3]:
        score = supplier.get("overall_score")
        if score is None:
            continue
        drivers = supplier.get("top_drivers", []) or []
        driver_text = ", ".join(
            f"{item.get('label')} {item.get('score')}" for item in drivers[:2]
        )
        name = supplier.get("supplier_name") or supplier.get("supplier_id")
        finding = f"{name} ({supplier.get('supplier_id')}): overall risk {float(score):.1f} "
        finding += f"('{supplier.get('overall_band')}')"
        if driver_text:
            finding += f", driven by {driver_text}"
        key_findings.append(finding + ".")

    ranked_categories = [
        (name, value) for name, value in category_averages.items() if value is not None
    ]
    ranked_categories.sort(key=lambda item: -float(item[1]))
    if ranked_categories:
        worst_name, worst_value = ranked_categories[0]
        key_findings.append(
            f"Across the portfolio the highest average category risk is "
            f"{worst_name.replace('_', ' ')} at {float(worst_value):.1f}."
        )
    if limited:
        key_findings.append(
            f"{limited} supplier(s) were flagged as having limited data, so their scores rest "
            f"on a partial set of metrics."
        )

    recommended_actions: list[str] = []
    for supplier in top_suppliers[:3]:
        actions = supplier.get("actions", []) or []
        if actions:
            name = supplier.get("supplier_name") or supplier.get("supplier_id")
            recommended_actions.append(f"{name}: {actions[0]}")
    if expiring:
        recommended_actions.append(
            "Review the contracts inside the expiry window before they lapse."
        )
    if not recommended_actions:
        recommended_actions.append(
            "No escalation was triggered by the risk rules; continue routine monitoring."
        )

    return {
        "summary": " ".join(sentences),
        "key_findings": key_findings,
        "recommended_actions": recommended_actions,
    }


def _inventory_forecast(payload: dict[str, Any]) -> dict[str, Any]:
    """Build the mock inventory narrative from the statistical results.

    Every quantity, date and metric below is copied out of the payload the
    forecasting engine already produced. The mock never forecasts anything - it
    is a text template over numbers that were computed before it ran, which is
    the same rule the real providers are held to by the prompt.
    """
    summary_data: dict[str, Any] = payload.get("forecast_summary", {}) or {}
    shortages: list[dict[str, Any]] = payload.get("shortage_items", []) or []
    overstocks: list[dict[str, Any]] = payload.get("overstock_items", []) or []
    accuracy: dict[str, Any] = payload.get("accuracy_summary", {}) or {}

    series_count = summary_data.get("series_count", 0)
    forecast_count = summary_data.get("forecast_count", 0)
    horizon = summary_data.get("horizon_periods", 0)
    shortage_count = summary_data.get("shortage_count", 0)
    reorder_now = summary_data.get("reorder_now_count", 0)
    overstock_count = summary_data.get("overstock_count", 0)
    dead_stock = summary_data.get("dead_stock_count", 0)
    insufficient = summary_data.get("insufficient_data_count", 0)
    model_usage: dict[str, Any] = summary_data.get("model_usage", {}) or {}

    sentences = [
        f"The predictor forecast {forecast_count:,} of {series_count:,} material/plant "
        f"combinations {horizon} period(s) ahead."
    ]
    if model_usage:
        leader = max(model_usage, key=lambda key: model_usage[key])
        sentences.append(
            f"{model_usage[leader]} of them were best served by the "
            f"{leader.replace('_', ' ')} model, chosen by backtesting each method on periods it "
            "had not seen."
        )
    if shortage_count:
        sentences.append(
            f"{shortage_count} material(s) are projected to run out of stock inside the "
            f"horizon, and {reorder_now} need a replenishment order raised now."
        )
    else:
        sentences.append("No material is projected to run out of stock inside the horizon.")
    if overstock_count or dead_stock:
        sentences.append(
            f"{overstock_count} material(s) carry an overstock risk and {dead_stock} are "
            "classified as dead stock."
        )
    if insufficient:
        sentences.append(
            f"{insufficient} material(s) have too little history to forecast and were reported "
            "as such rather than estimated."
        )
    sentences.append(
        "Every figure is a statistical estimate from the uploaded history, not a commitment, "
        "and none of it has been validated in a live SAP environment."
    )

    key_findings: list[str] = []
    for item in shortages[:3]:
        material = item.get("material")
        plant = item.get("plant")
        shortage_date = item.get("predicted_shortage_date")
        quantity = item.get("recommended_reorder_quantity")
        finding = f"{material} at plant {plant} is projected to run out on {shortage_date}"
        if quantity is not None:
            finding += f"; the recommended replenishment quantity is {quantity:g}"
        if item.get("expedite_recommended"):
            finding += ", and an open purchase order is expected too late to prevent it"
        key_findings.append(finding + ".")
    for item in overstocks[:2]:
        cover = item.get("days_of_cover")
        cover_text = f"{cover:g} days of cover" if cover is not None else "no projected demand"
        key_findings.append(
            f"{item.get('material')} at plant {item.get('plant')} holds {cover_text} "
            f"({item.get('overstock_risk')} overstock risk)."
        )

    mean_smape = accuracy.get("mean_smape")
    mean_mase = accuracy.get("mean_mase")
    if mean_smape is not None:
        accuracy_note = f"Average sMAPE across the forecast materials is {float(mean_smape):.1f}%"
        if mean_mase is not None:
            accuracy_note += (
                f", and the mean MASE of {float(mean_mase):.2f} means the models "
                + ("beat" if float(mean_mase) < 1 else "did not beat")
                + " a naive same-as-last-period forecast"
            )
        key_findings.append(accuracy_note + ".")

    actions = []
    if reorder_now:
        actions.append(
            f"Raise replenishment orders for the {reorder_now} material(s) already at or below "
            "their reorder point."
        )
    if shortage_count:
        actions.append(
            "Review the projected shortage dates against open purchase orders and expedite the "
            "deliveries that are expected too late."
        )
    if overstock_count:
        actions.append(
            "Review the overstocked materials for excess quantity before the next buying cycle."
        )
    if dead_stock:
        actions.append(
            "Decide what to do with the dead-stock materials: no demand has been recorded "
            "against them for the whole dead-stock window."
        )
    if insufficient:
        actions.append(
            "Extend the history for the materials that have too few periods to forecast."
        )
    actions.append(
        "Check the recommended safety stock against the material master figure where the two "
        "disagree."
    )

    return {
        "summary": " ".join(sentences),
        "key_findings": key_findings,
        "recommended_actions": actions[:5],
    }


def _contract_analysis(payload: dict[str, Any]) -> dict[str, Any]:
    """Build the mock contract narrative from the deterministic extraction.

    Every clause name, page number, date and severity below is copied out of
    the payload the engine produced. The mock never decides that a clause
    exists, never invents a page and never softens a finding.
    """
    summary_data: dict[str, Any] = payload.get("contract_summary", {}) or {}
    key_dates: dict[str, Any] = payload.get("key_dates", {}) or {}
    clauses: list[dict[str, Any]] = payload.get("clauses", []) or []
    risks: list[dict[str, Any]] = payload.get("risks", []) or []
    missing: list[dict[str, Any]] = payload.get("missing_clauses", []) or []

    title = summary_data.get("contract_title") or "The uploaded document"
    found = summary_data.get("clauses_found", 0)
    expected = summary_data.get("clauses_expected", 0)
    pages = summary_data.get("page_count", 0)
    severity = summary_data.get("severity_counts", {}) or {}

    sentences = [
        f"{title} was read across {pages} page(s) and {found} of {expected} expected clause "
        f"types were located by pattern matching."
    ]

    effective = key_dates.get("effective_date")
    expiration = key_dates.get("expiration_date")
    if effective or expiration:
        sentences.append(
            f"The term runs from {effective or 'a start date that is not stated'} to "
            f"{expiration or 'an end date that is not stated'}."
        )
    if key_dates.get("auto_renewal"):
        deadline = key_dates.get("notice_deadline")
        sentences.append(
            "The agreement renews automatically"
            + (f", with notice required by {deadline}." if deadline else ".")
        )
    if risks:
        sentences.append(
            f"{len(risks)} risk finding(s) were raised, including "
            f"{severity.get('critical', 0)} critical and {severity.get('high', 0)} high."
        )
    else:
        sentences.append("No risk findings were raised by the contract rules.")
    sentences.append(
        "Every statement above comes from the deterministic extraction, which records a page "
        "reference and a confidence score for each clause. This is an assistive review, not "
        "legal advice."
    )

    key_findings: list[str] = []
    for risk in risks[:4]:
        page = risk.get("page_number")
        where = f" (page {page})" if page else ""
        key_findings.append(
            f"[{str(risk.get('severity', '')).upper()}] {risk.get('title')}{where}."
        )
    for item in missing[:3]:
        key_findings.append(
            f"Expected clause not found: {item.get('label')} ({item.get('importance')} "
            f"importance)."
        )
    weak = [item for item in clauses if item.get("needs_review")]
    if weak:
        key_findings.append(
            f"{len(weak)} clause(s) were extracted with low confidence and should be checked "
            f"against the cited pages: "
            + ", ".join(str(item.get("label")) for item in weak[:4])
            + "."
        )
    if summary_data.get("injection_detected"):
        key_findings.append(
            "The document contained text written as an instruction to an automated system. It "
            "was treated as data only and was not acted on."
        )

    recommended_actions = [risk["recommended_action"] for risk in risks[:4] if risk.get("recommended_action")]
    if not recommended_actions:
        recommended_actions.append(
            "No contract rule was triggered; file the extracted dates in the contract register."
        )

    return {
        "summary": " ".join(sentences),
        "key_findings": key_findings,
        "recommended_actions": list(dict.fromkeys(recommended_actions)),
    }


def _contract_answer(payload: dict[str, Any]) -> dict[str, Any]:
    """Rephrase one deterministic contract answer, preserving every citation."""
    question = payload.get("question", "")
    answer: dict[str, Any] = payload.get("deterministic_answer", {}) or {}
    citations: list[dict[str, Any]] = payload.get("citations", []) or []

    body = str(answer.get("answer", "")).strip()
    if answer.get("answered") is False:
        summary = (
            f"The contract does not answer '{question}' as extracted. "
            f"{body.splitlines()[0] if body else ''}".strip()
        )
    else:
        first_lines = " ".join(line.strip() for line in body.splitlines()[:3] if line.strip())
        summary = (
            f"In answer to '{question}': {first_lines} "
            f"This restates the deterministic extraction; it adds no new facts."
        ).strip()

    key_findings = []
    for citation in citations[:4]:
        page = citation.get("page_number")
        heading = citation.get("section_heading")
        where = ", ".join(
            part for part in ([f"page {page}"] if page else []) + ([heading] if heading else [])
        )
        key_findings.append(f"{where}: {str(citation.get('excerpt', ''))[:180]}".strip(": "))

    return {
        "summary": summary,
        "key_findings": key_findings,
        "recommended_actions": [
            "Open the cited page in the original document before relying on this answer."
        ],
    }
