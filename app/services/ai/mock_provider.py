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
        elif task == "test_case_generation":
            text = json.dumps(_test_case_generation(payload), ensure_ascii=False)
        elif task == "test_case_regeneration":
            text = json.dumps(
                _test_case_generation(payload, regenerated=True), ensure_ascii=False
            )
        elif task == "blueprint_generation":
            text = json.dumps(_blueprint_generation(payload), ensure_ascii=False)
        elif task == "blueprint_section":
            text = json.dumps(
                _blueprint_generation(payload, regenerated=True), ensure_ascii=False
            )
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
    if "redraft the single blueprint section" in lowered:
        return "blueprint_section"
    if "blueprint section" in lowered or "implementation blueprint" in lowered:
        return "blueprint_generation"
    if "redraft the single sap test case" in lowered:
        return "test_case_regeneration"
    if "test case" in lowered or "test_case" in lowered:
        return "test_case_generation"
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


# ---------------------------------------------------------------------------
# SAP Test Case Generator
# ---------------------------------------------------------------------------

#: Step outlines the mock provider writes from, one per test type.
#:
#: These are deliberately *not* the templates in the module configuration. The
#: template build is the deterministic fallback; this is what a drafted case
#: looks like. Keeping the two voices distinct is what lets a test - and a
#: reader - tell "the provider drafted this" from "the provider was unavailable
#: and the template filled in", which would otherwise be indistinguishable in
#: mock mode.
_MOCK_STEP_OUTLINES: dict[str, list[tuple[str, str]]] = {
    "sit": [
        ("Open the transaction used for {process} in {product} as {role}.",
         "The initial screen is displayed and ready for entry."),
        ("Create the document for {process} with the data listed under Test data.",
         "The entry is accepted with no error message."),
        ("Save the document and note the number the system returns.",
         "A document number is issued and the save is confirmed."),
        ("Follow the document flow through {module} and check each follow-on document.",
         "Every follow-on document exists with the status the design expects."),
        ("Compare the resulting values with the business rules recorded for {process}.",
         "The values agree with the business rules without manual correction."),
    ],
    "uat": [
        ("As {role}, start {process} the way it is started on a normal working day.",
         "The starting point is reachable without technical help."),
        ("Work through {process} using the business data listed under Test data.",
         "Each screen can be completed with the information a business user holds."),
        ("Check that the wording on screen matches how the business describes {process}.",
         "The labels and messages are recognisable to the business."),
        ("Produce the document or report the business expects at the end.",
         "The output contains the values the business needs and is readable."),
        ("Record whether the business accepts this step, and why.",
         "An acceptance decision with a reason is recorded against the case."),
    ],
    "negative": [
        ("Open the transaction used for {process} as {role}.",
         "The transaction is ready for entry."),
        ("Enter data that breaks exactly one rule: {focus}.",
         "The invalid value is accepted into the field so the check runs on save."),
        ("Try to save the document.",
         "The system refuses to save."),
        ("Note the message type, number and text the system issues.",
         "The message names the field at fault and says what is wrong."),
        ("Check that nothing was posted and no follow-on document exists.",
         "No document number was issued and {module} is unchanged."),
    ],
    "integration": [
        ("Check that the connection to {integration} is active and the monitor is clear.",
         "The connection test succeeds and no unrelated message is queued."),
        ("Run {process} in {product} so the interface to {integration} is triggered.",
         "The document is created and the interface call is raised."),
        ("Find the message in the interface monitor and record its id and status.",
         "Exactly one message exists for this run, with a successful status."),
        ("Compare the payload with the interface specification, field by field.",
         "Every mapped field carries the expected value, format and unit."),
        ("Confirm {integration} processed it and the status returned to {product}.",
         "The receiving system holds the record and the SAP document shows the status."),
    ],
    "regression": [
        ("Open the recorded baseline for {process} taken before the change.",
         "The baseline lists the document numbers, values and statuses to reproduce."),
        ("Confirm only the change under test is present in the client.",
         "The transport log shows the expected change and nothing else."),
        ("Run {process} again with the data that produced the baseline.",
         "The process completes as it did before the change."),
        ("Compare the result with the baseline, paying attention to {focus}.",
         "Every compared value matches, or the difference is explained by the change."),
        ("Look for new messages, warnings or dumps the baseline run did not produce.",
         "No new message, warning or dump appears."),
    ],
    "security": [
        ("Check the controls documented for {process} against what is active in the client.",
         "Every documented control is present and switched on."),
        ("As a permitted user, run {process} and note what {focus} exposes on screen.",
         "Only the data the security concept allows is visible."),
        ("Repeat the attempt with an account that has no business need for {process}.",
         "Access is refused and no sensitive data is shown, not even in an error."),
        ("Open the audit log and find the entries for both attempts.",
         "Both attempts are logged with user, timestamp and object."),
        ("Check the alternative entry points listed in the security concept.",
         "Each one applies the same control."),
    ],
    "authorization": [
        ("Assign only the role under test to the test user for {process}.",
         "The user holds exactly one role and the assignment is active."),
        ("Run {process} inside the permitted scope.",
         "The process completes and every required authorisation object is granted."),
        ("Repeat the run for the case {focus} is meant to prevent.",
         "The system refuses the action with an authorisation error."),
        ("Record the failed check from the authorisation trace or SU53.",
         "The refusal names the authorisation object and the field value."),
        ("Try to reach the same function through another transaction or app.",
         "Every alternative entry point applies the same check."),
    ],
    "data_migration": [
        ("Record the source record count and control totals for {process}.",
         "The source figures are signed off as the reconciliation baseline."),
        ("Run the load into {product} with the agreed migration object and mapping.",
         "The load completes and produces a log of loaded and rejected records."),
        ("Reconcile the loaded counts and control totals against the source.",
         "Loaded plus rejected equals the source count and the totals agree."),
        ("Spot-check the field mapping on the documented sample, covering {focus}.",
         "Every sampled field holds the correctly mapped and converted value."),
        ("Work through the error file, correct the rejects and reload them.",
         "Each rejected record has a stated reason and the reload closes the difference."),
    ],
}

_MOCK_FALLBACK_STEPS: list[tuple[str, str]] = [
    ("Prepare the preconditions listed for this test case.",
     "The starting state matches the preconditions."),
    ("Carry out {process} in {product} ({module}) covering {focus}.",
     "The process behaves as the process description states."),
    ("Record the result and compare it with the expected result below.",
     "The observed result matches the expected result."),
]


def _test_case_generation(
    payload: dict[str, Any], *, regenerated: bool = False
) -> dict[str, Any]:
    """Draft one test case per planned slot, with no API key and no network.

    Every case is built from the process context the caller supplied and from
    the slot the deterministic planner produced. The mock never invents a slot,
    never changes a priority and never adds an SAP transaction code that the
    context did not name - which are exactly the constraints the real providers
    are held to by the prompt.
    """
    context: dict[str, Any] = payload.get("context", {}) or {}
    slots: list[dict[str, Any]] = payload.get("slots", []) or []
    instruction = str(payload.get("reviewer_instruction", "") or "").strip()

    return {
        "test_cases": [
            _mock_test_case(context, slot, instruction=instruction, regenerated=regenerated)
            for slot in slots
            if isinstance(slot, dict) and slot.get("slot_id")
        ]
    }


def _mock_test_case(
    context: dict[str, Any],
    slot: dict[str, Any],
    *,
    instruction: str = "",
    regenerated: bool = False,
) -> dict[str, Any]:
    """Build one mock test case from the context and one planned slot."""
    process = str(context.get("business_process") or "the business process")
    product = str(context.get("sap_product") or "the SAP system")
    module = str(context.get("sap_module") or "the module")
    description = str(context.get("process_description") or "").strip()
    roles = [str(item) for item in (context.get("user_roles") or []) if str(item).strip()]
    integrations = [
        str(item) for item in (context.get("integrations") or []) if str(item).strip()
    ]
    systems = [str(item) for item in (context.get("systems_involved") or []) if str(item).strip()]
    rules = [str(item) for item in (context.get("business_rules") or []) if str(item).strip()]
    preconditions = [
        str(item) for item in (context.get("preconditions") or []) if str(item).strip()
    ]
    data_requirements = [
        str(item) for item in (context.get("test_data_requirements") or []) if str(item).strip()
    ]

    test_type = str(slot.get("test_type") or "sit")
    type_label = str(slot.get("test_type_label") or test_type.upper())
    focus = str(slot.get("focus") or "the standard path")

    values = {
        "process": process,
        "product": product,
        "module": module,
        "focus": focus,
        "role": roles[0] if roles else "the assigned business user",
        "integration": integrations[0] if integrations else "the connected external system",
        "system": systems[0] if systems else "the SAP test client",
    }

    outline = _MOCK_STEP_OUTLINES.get(test_type, _MOCK_FALLBACK_STEPS)
    steps = [
        {
            "action": action.format(**values),
            "expected_result": expected.format(**values),
        }
        for action, expected in outline
    ]

    first_sentence = description.split(".")[0].strip()
    objective = (
        f"Check that {process} in {product} ({module}) handles {focus} as described"
        + (f": {first_sentence}." if first_sentence else ".")
    )
    if instruction:
        objective += f" Reviewer instruction applied: {instruction}"

    case_preconditions = preconditions[:3] + [
        f"The test client is configured for {process} as described for this suite.",
    ]
    case_test_data = data_requirements[:3] + [
        f"One data set that exercises {focus}.",
    ]
    if rules:
        case_test_data.append(f"Values that satisfy the business rule: {rules[0]}")

    comments = (
        "Drafted by the mock AI provider from the process description entered in this "
        "application. No language model was called and nothing here has been executed in an "
        "SAP system."
    )
    if regenerated:
        comments = "Redrafted by the mock AI provider. " + comments

    return {
        "slot_id": slot.get("slot_id"),
        # Deliberately a different shape from the configured template title
        # ("<type>: <process> - <focus>"), so a reader can see at a glance
        # which cases were drafted and which the template had to fill.
        "title": f"{focus[:1].upper()}{focus[1:]} - {process} ({type_label})",
        "objective": objective,
        "preconditions": case_preconditions,
        "test_data": case_test_data,
        "steps": steps,
        "expected_result": (
            f"{process} behaves as described for {focus}, and the result agrees with the "
            f"business rules recorded for this suite."
        ),
        "comments": comments,
    }


# ---------------------------------------------------------------------------
# SAP Blueprint Generator
# ---------------------------------------------------------------------------

#: Three angles the mock writes about, per section that accepts drafted items.
#: They are deliberately shaped like a consultant's checklist rather than like
#: the configured fallback templates, so a reader can tell at a glance which
#: sections were drafted and which the template had to fill.
_MOCK_SECTION_ITEMS: dict[str, list[tuple[str, str, str]]] = {
    "scope": [
        ("Process delivery for the named modules",
         "The future-state process is delivered for {company_codes} within {modules}.",
         "Process"),
        ("Organisational rollout",
         "Delivery covers the organisational units recorded in this blueprint and no others.",
         "Organisation"),
    ],
    "out_of_scope": [
        ("Processes outside the described flow",
         "Anything the future-state process description does not cover stays on its current "
         "process until a later phase agrees otherwise.",
         "Process scope"),
        ("Historical data beyond the agreed cut",
         "Only the data the migration section names is loaded. Older history stays available "
         "in the source systems for reference.",
         "Data scope"),
        ("Reporting rebuilt after go-live",
         "Reporting beyond the requirements listed in this blueprint is handled as a separate "
         "piece of work.",
         "Reporting scope"),
    ],
    "assumptions": [
        ("The named organisational structure is stable",
         "No further company code, plant or purchasing organisation is added after design "
         "sign-off without a change decision.",
         "Organisation"),
        ("Business availability is committed",
         "The user groups named for {company} are released for design, test and training.",
         "Resourcing"),
    ],
    "process_steps": [
        ("Raise the request",
         "The role that owns the trigger creates the request in {sap_product}, using the data "
         "the future-state process describes.",
         "Step 1"),
        ("Check and approve",
         "The request is checked against the business rules and approved by the role the "
         "design names.",
         "Step 2"),
        ("Post the follow-on documents",
         "The follow-on documents the design calls for are created and posted.",
         "Step 3"),
        ("Close and report the outcome",
         "The process closes and the outcome reaches the reporting listed in this blueprint.",
         "Step 4"),
    ],
    "best_practice_alignment": [
        ("Start from the standard delivered process",
         "The design begins from the standard process for {modules} and records every "
         "departure with the objective it serves.",
         "Alignment"),
        ("Record departures as decisions",
         "Each departure carries a build cost and an upgrade cost, so each one needs a named "
         "approver.",
         "Departure"),
    ],
    "master_data": [
        ("Business partner data",
         "Owners, mandatory fields and the maintenance process after go-live are agreed before "
         "migration starts.",
         "Master data object"),
        ("Item and pricing data",
         "The views and condition records {modules} needs for the organisational units in "
         "scope.",
         "Master data object"),
        ("Ongoing governance",
         "A named owner maintains each object after go-live; unowned master data degrades "
         "faster than any configuration.",
         "Governance"),
    ],
    "configuration_requirements": [
        ("Enterprise structure and assignments",
         "The organisational units recorded in this blueprint are created and assigned so the "
         "process posts to the right place.",
         "Enterprise structure"),
        ("Document types and numbering",
         "Document types and number ranges the business can recognise and reconcile.",
         "Documents"),
        ("Approval behaviour",
         "The approval the process requires is enforced by configuration, not by convention.",
         "Process control"),
    ],
    "functional_requirements": [
        ("The responsible role can start the process unaided",
         "The role named in the process steps can raise the request in {sap_product} without "
         "leaving the system.",
         "Functional"),
        ("Business rules are enforced by the system",
         "A document that breaks a rule recorded for this process cannot be posted.",
         "Functional"),
        ("The outcome is visible the same day",
         "The result reaches the reporting listed in this blueprint on the day it is posted.",
         "Functional"),
    ],
    "nonfunctional_requirements": [
        ("Response time target to be agreed",
         "No response-time figure was supplied in the project request, so the target is "
         "recorded as one to agree with {company}.",
         "Performance"),
        ("Volumes to be confirmed",
         "Daily and peak document volumes are confirmed by the business before sizing is "
         "fixed.",
         "Capacity"),
        ("Traceability and retention",
         "Every posting is traceable to the user and document that caused it, and is retained "
         "for the statutory period.",
         "Compliance"),
    ],
    "data_migration": [
        ("Profile the sources before agreeing rules",
         "Each source is profiled so cleansing rules are agreed on evidence rather than on "
         "assumption.",
         "Approach"),
        ("Reconcile every load",
         "Each load is reconciled and signed off by the business owner named for the object.",
         "Control"),
    ],
    "controls": [
        ("Approval before commitment",
         "A document that commits {company} cannot proceed without the recorded approval.",
         "Preventive"),
        ("Segregation of duties",
         "The role that creates a document does not approve it.",
         "Preventive"),
        ("Periodic reconciliation",
         "Postings are reconciled on an agreed cycle against the source that triggered them.",
         "Detective"),
    ],
    "reporting_requirements": [
        ("Daily operational view",
         "Documents in flight, ageing and exceptions, for the team running the process.",
         "Operational"),
        ("Objective tracking for the sponsor",
         "A periodic view against the business objectives recorded in this blueprint.",
         "Management"),
    ],
    "test_strategy": [
        ("Unit and string testing by the builder",
         "Every configured object is demonstrated once by the consultant who built it.",
         "Test level"),
        ("System integration testing on migrated data",
         "The end-to-end process is tested across {modules} and every named integration.",
         "Test level"),
        ("Business-owned acceptance testing",
         "The business runs the process in its own words and signs off per scenario.",
         "Test level"),
    ],
    "sit_scenarios": [
        ("End-to-end happy path",
         "The process runs from trigger to close, and every follow-on document the design "
         "calls for is checked.",
         "SIT scenario"),
        ("Each named integration is exercised",
         "The process is run so that every integration recorded in this blueprint carries "
         "data, and the far side is checked.",
         "SIT scenario"),
        ("Errors stop the process with a usable message",
         "The errors the business rules are meant to catch are forced deliberately.",
         "SIT scenario"),
    ],
    "uat_scenarios": [
        ("A normal working day",
         "The business runs a typical case from start to finish and confirms it matches what "
         "they expect today.",
         "UAT scenario"),
        ("A case that needs approval",
         "A case above the approval threshold is raised, approved and completed.",
         "UAT scenario"),
        ("A mistake that has to be corrected",
         "A correction is made using only the tools the business will have after go-live.",
         "UAT scenario"),
    ],
    "training": [
        ("Role-based process training",
         "Each audience is trained on the job it does, using migrated data in a training "
         "client before cutover.",
         "Approach"),
        ("Reference material that survives go-live",
         "Short task guides are produced per audience so hypercare answers the same question "
         "once.",
         "Materials"),
    ],
    "cutover_activities": [
        ("Freeze the legacy process",
         "New transactions stop in the current systems and the ones in flight are completed.",
         "Cutover task"),
        ("Take the final extracts and load them",
         "Extracts are taken from the sources named in this blueprint and loaded, with counts "
         "recorded.",
         "Cutover task"),
        ("Reconcile and obtain sign-off",
         "The business owner for each object reconciles the load and signs it off.",
         "Cutover task"),
        ("Assign roles and open the system",
         "The roles recorded in this blueprint are assigned and the system is opened.",
         "Cutover task"),
    ],
    "hypercare": [
        ("A named contact per audience",
         "Each user group has a contact during hypercare who knows the process, not just the "
         "system.",
         "Support model"),
        ("Daily triage with the business",
         "Issues are classified daily and either fixed, worked around or accepted with a date.",
         "Rhythm"),
        ("Exit on criteria, not on a date",
         "Hypercare ends after a full business cycle with no open high-severity issue.",
         "Exit"),
    ],
    "risks": [
        ("Source data quality is unknown until it is profiled",
         "Cause: legacy data was never cleansed for this purpose. Consequence: cutover slips "
         "or the business goes live on data it does not trust.",
         "Data"),
        ("The people who know the process also run it",
         "Cause: business availability is finite. Consequence: the design records the wrong "
         "process.",
         "Resourcing"),
        ("Requirements surface after design sign-off",
         "Cause: scope grows. Consequence: rework in configuration, security and testing.",
         "Scope"),
    ],
    "dependencies": [
        ("Environments available on the assumed dates",
         "Development, test and training environments for {sap_product} are ready when the "
         "timeline assumes.",
         "Infrastructure"),
        ("Third-party readiness",
         "Any party on the far side of a named integration is ready to test when the plan "
         "needs them.",
         "External"),
    ],
    "open_decisions": [
        ("Standard process or deliberate departure",
         "Blocks the configuration requirements and the build estimate.",
         "Design decision"),
        ("Interface technology and ownership",
         "Blocks the interface specifications and the integration test plan.",
         "Architecture decision"),
        ("Single or phased cutover",
         "Blocks the cutover plan and the migration sequence.",
         "Programme decision"),
    ],
}

_MOCK_FALLBACK_SECTION_ITEMS: list[tuple[str, str, str]] = [
    ("Scope and ownership",
     "Records what this section covers for {company} and who owns it.",
     "Definition"),
    ("Prerequisites",
     "Lists what has to be in place before this section can be completed.",
     "Prerequisite"),
    ("Acceptance",
     "States how the project knows this section is complete and who accepts it.",
     "Acceptance"),
]


def _blueprint_generation(
    payload: dict[str, Any], *, regenerated: bool = False
) -> dict[str, Any]:
    """Draft one blueprint section per planned section, with no API key.

    Every section is written from the project request the caller supplied and
    from the section skeleton the deterministic planner produced. The mock never
    invents a section, never adds an organisational unit or an interface, and
    never names an SAP object the project request did not name - which are
    exactly the constraints the real providers are held to by the prompt.
    """
    project: dict[str, Any] = payload.get("project", {}) or {}
    sections: list[dict[str, Any]] = payload.get("sections", []) or []
    instruction = str(payload.get("reviewer_instruction", "") or "").strip()
    values = _blueprint_values(project)

    return {
        "sections": [
            _mock_blueprint_section(
                values, section, instruction=instruction, regenerated=regenerated
            )
            for section in sections
            if isinstance(section, dict) and section.get("section_key")
        ]
    }


def _blueprint_values(project: dict[str, Any]) -> dict[str, str]:
    """The project facts the mock is allowed to mention, and nothing else."""

    def _list(key: str) -> list[str]:
        return [str(item) for item in (project.get(key) or []) if str(item).strip()]

    def _join(items: list[str], fallback: str) -> str:
        if not items:
            return fallback
        if len(items) <= 4:
            return ", ".join(items)
        return ", ".join(items[:4]) + f" and {len(items) - 4} more"

    modules = _list("modules")
    company_codes = _list("company_codes")
    user_groups = _list("user_groups")
    return {
        "company": str(project.get("company") or "the customer"),
        "industry": str(project.get("industry") or "the industry recorded for this project"),
        "sap_product": str(project.get("sap_product") or "the SAP product in scope"),
        "modules": _join(modules, "the modules recorded for this project"),
        "primary_module": modules[0] if modules else "the lead module",
        "company_codes": _join(company_codes, "the company codes recorded for this project"),
        "primary_user_group": user_groups[0] if user_groups else "the responsible business role",
        "timeline": str(project.get("timeline") or "the timeline recorded for this project"),
    }


def _mock_blueprint_section(
    values: dict[str, str],
    section: dict[str, Any],
    *,
    instruction: str = "",
    regenerated: bool = False,
) -> dict[str, Any]:
    """Build one mock blueprint section from the project facts and the skeleton."""
    section_key = str(section.get("section_key") or "")
    title = str(section.get("title") or section_key.replace("_", " ").title())
    purpose = str(section.get("purpose") or "").strip()
    facts = [
        str(fact.get("title"))
        for fact in (section.get("facts_already_recorded") or [])
        if isinstance(fact, dict) and fact.get("title")
    ]
    wants_items = bool(section.get("wants_items"))
    max_items = int(section.get("max_items") or 0)

    sentences = [
        f"{title} for the {values['sap_product']} implementation at {values['company']} "
        f"({values['industry']}), covering {values['modules']} for {values['company_codes']}."
    ]
    if purpose:
        sentences.append(purpose.rstrip(".") + ".")
    if facts:
        shown = ", ".join(facts[:5])
        more = f" and {len(facts) - 5} further entries" if len(facts) > 5 else ""
        sentences.append(
            f"The entries recorded for this section come from the project request: {shown}{more}."
        )
    sentences.append(
        "This wording is a proposal drafted locally by the mock AI provider from the project "
        "request. No language model was called, and nothing here has been validated in a live "
        "SAP system: it requires review by qualified SAP professionals."
    )
    if instruction:
        sentences.append(f"Reviewer instruction applied: {instruction}")
    if regenerated:
        sentences.insert(0, "Redrafted section.")

    items: list[dict[str, Any]] = []
    if wants_items and max_items:
        outline = _MOCK_SECTION_ITEMS.get(section_key, _MOCK_FALLBACK_SECTION_ITEMS)
        for item_title, detail, category in outline[:max_items]:
            items.append(
                {
                    "title": item_title.format(**values),
                    "detail": detail.format(**values),
                    "category": category,
                    "reference": title,
                    "owner": "",
                    "rating": "",
                }
            )

    return {
        "section_key": section_key,
        "narrative": " ".join(sentences),
        "items": items,
    }
