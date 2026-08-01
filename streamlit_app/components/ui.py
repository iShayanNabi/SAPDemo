"""Small presentation helpers shared by the Streamlit pages.

These are formatting only. Anything that decides *what* is risky lives in the
backend; this module decides how a number is printed and which badge colour a
severity gets.
"""

from __future__ import annotations

import html
from typing import Any

import pandas as pd
import streamlit as st

SEVERITY_COLORS = {
    "critical": "#B3261E",
    "high": "#E8710A",
    "medium": "#F2C037",
    "low": "#3B8C4E",
}

SEVERITY_ORDER = ["critical", "high", "medium", "low"]

ORIGIN_LABELS = {
    "rule_based": "Rule-based",
    "ai_generated": "AI-generated",
    "mock_ai": "Mock AI output",
    "forecast": "Forecast output",
    "demo_data": "Demo data",
}


def escape_html(value: Any, *, default: str = "") -> str:
    """Escape a value for interpolation into an ``unsafe_allow_html`` string.

    Streamlit renders markdown safely by default; ``unsafe_allow_html=True``
    switches that off for the whole string, including any value substituted into
    it. Most of the badges in this app interpolate a fixed vocabulary - a
    severity, a band - and are safe by construction. Some do not: a contract
    citation prints the *section heading it found in the uploaded document*, and
    a document is untrusted input by this project's own rule.

    A clause heading reading ``<img src=x onerror=...>`` is not a hypothetical
    file - it is a one-line edit to a PDF somebody emails to a reviewer, and it
    lands in the reviewer's browser next to a page number that makes it look
    like a finding. Escape anything that came from a file, a model or a user
    before it goes into an HTML string; leave the markup this module writes
    itself alone.
    """
    if value is None:
        return default
    text = str(value)
    return html.escape(text, quote=True) if text else default


def format_currency(value: Any, currency: str = "EUR") -> str:
    """Format a number as an amount with a thousands separator."""
    try:
        return f"{float(value):,.2f} {currency}"
    except (TypeError, ValueError):
        return f"- {currency}"


def format_number(value: Any) -> str:
    """Format an integer-like value with a thousands separator."""
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "-"


def origin_badge(origin: str | None) -> str:
    """Return a short human label for an output origin."""
    if not origin:
        return "Not generated"
    return ORIGIN_LABELS.get(origin, origin)


def severity_badge(severity: str) -> str:
    """Return a coloured HTML badge for a severity value."""
    colour = SEVERITY_COLORS.get(severity.lower(), "#666666")
    return (
        f"<span style='background:{colour};color:#fff;padding:2px 8px;"
        f"border-radius:10px;font-size:0.75rem;'>{severity.upper()}</span>"
    )


def show_error(message: str, details: dict[str, Any] | None = None) -> None:
    """Render an error message with optional structured details."""
    st.error(message)
    if details:
        with st.expander("Error details"):
            st.json(details)


def findings_dataframe(findings: list[dict[str, Any]]) -> pd.DataFrame:
    """Flatten API findings into a table for display."""
    if not findings:
        return pd.DataFrame()
    rows = []
    for finding in findings:
        evidence = finding.get("evidence") or {}
        rows.append(
            {
                "Severity": finding.get("severity", "").upper(),
                "Rule": finding.get("rule_id"),
                "Risk category": finding.get("risk_category"),
                "PO": finding.get("po_number"),
                "Item": finding.get("po_item"),
                "Supplier": finding.get("supplier_id"),
                "Supplier name": finding.get("supplier_name"),
                "Explanation (rule-based)": finding.get("explanation"),
                "Recommended action": finding.get("recommended_action"),
                "Exposure": finding.get("estimated_financial_exposure"),
                "Currency": finding.get("exposure_currency"),
                "Confidence": finding.get("confidence_score"),
                "Origin": ORIGIN_LABELS.get(finding.get("output_origin", ""), ""),
                "AI explanation": finding.get("ai_explanation") or "",
                "Evidence": "; ".join(f"{k}={v}" for k, v in evidence.items()),
                "Finding ID": finding.get("finding_id"),
            }
        )
    frame = pd.DataFrame(rows)
    order = {severity.upper(): index for index, severity in enumerate(SEVERITY_ORDER)}
    frame["_order"] = frame["Severity"].map(order).fillna(9)
    return frame.sort_values(["_order", "Exposure"], ascending=[True, False]).drop(columns="_order")


def kpi_row(items: list[tuple[str, str, str | None]]) -> None:
    """Render a row of KPI cards: ``(label, value, help_text)``."""
    columns = st.columns(len(items))
    for column, (label, value, help_text) in zip(columns, items):
        with column:
            st.metric(label=label, value=value, help=help_text)


def disclaimer() -> None:
    """Render the standing project disclaimer."""
    st.caption(
        "This application analyses the file you upload. It is not connected to an SAP system, "
        "and no output has been validated in a live SAP environment. Risk findings come from "
        "deterministic Python rules; any AI text is labelled separately."
    )
