"""Streamlit page for the Supplier Risk Copilot.

Like every page in this app it contains no business logic: it uploads the
supplier risk profiles (and the optional dated risk events), asks the FastAPI
backend to calculate the risk assessment, and renders what comes back. Every
score, band, trend and recommended action is computed server-side by the
deterministic scoring model in ``app/modules/supplier_risk``.

The risk scale is **0 = no risk, 100 = maximum risk**.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from streamlit_app.components.api_client import ApiClient, ApiError  # noqa: E402
from streamlit_app.components.demo import (  # noqa: E402
    demo_banner,
    explain_module,
    load_demo_button,
    upload_disabled_notice,
    uploads_enabled,
)
from streamlit_app.components.ui import (  # noqa: E402
    disclaimer,
    escape_html,
    format_currency,
    origin_badge,
    show_error,
)

st.set_page_config(page_title="Supplier Risk Copilot", page_icon="🛡️", layout="wide")

client = ApiClient()

BAND_COLORS = {
    "low": "#3B8C4E",
    "medium": "#F2C037",
    "high": "#E8710A",
    "critical": "#B3261E",
}
BAND_ORDER = ["low", "medium", "high", "critical"]

PRIORITY_ICONS = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}

SAMPLE_FILES = {
    "profiles": "sample_supplier_risk_profiles.csv",
    "events": "sample_supplier_risk_events.csv",
}

EXAMPLE_QUESTION_TEMPLATES = [
    "Show supplier {supplier}'s risk",
    "Why is this supplier high risk?",
    "Which suppliers have the most delivery issues?",
    "Which suppliers have contracts expiring soon?",
    "Which alternative supplier has lower risk?",
    "What action should procurement take?",
]

st.title("Supplier Risk Copilot")
demo_banner(client)
explain_module("supplier_risk_copilot")
st.write(
    "Score every supplier across ten risk categories with a transparent, deterministic model, "
    "then ask questions about the result. Answers are built from the uploaded internal records "
    "and cite them; AI, when enabled, only rephrases what the model already computed."
)
st.caption("Risk scale: **0 = no risk, 100 = maximum risk**. Bands: low · medium · high · critical.")

with st.sidebar:
    st.header("Backend status")
    try:
        health = client.health()
        st.success(f"API reachable ({health['status']})")
        st.write(
            f"**AI provider:** {health['ai_provider']}"
            + (" (mock)" if health["ai_is_mock"] else "")
        )
    except ApiError as error:
        st.error(error.message)
        st.stop()


# ---------------------------------------------------------------------------
# Small presentation helpers (formatting only - no risk logic lives here)
# ---------------------------------------------------------------------------
def _band_colour(band: str | None) -> str:
    return BAND_COLORS.get((band or "").lower(), "#666666")


def _score(value: Any, suffix: str = "") -> str:
    """Format a numeric score, or ``-`` when the model could not compute one."""
    if value is None:
        return "-"
    try:
        return f"{float(value):,.1f}{suffix}"
    except (TypeError, ValueError):
        return str(value)


def _plain(value: Any) -> str:
    """Format any optional value for display."""
    if value is None or value == "":
        return "-"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def _supplier_label(entry: dict[str, Any]) -> str:
    name = entry.get("supplier_name") or entry.get("supplier_id")
    score = _score(entry.get("overall_score"))
    band = (entry.get("overall_band") or "not scored").upper()
    return f"{name} ({entry['supplier_id']}) — {score}, {band}"


def _event_table(events: list[dict[str, Any]], empty_message: str) -> None:
    """Render a list of dated internal records, or say plainly there are none."""
    if not events:
        st.caption(empty_message)
        return
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Event ID": event.get("event_id"),
                    "Type": event.get("event_type"),
                    "Date": event.get("event_date"),
                    "Reference": event.get("reference"),
                    "Severity": event.get("severity"),
                    "Description": event.get("description"),
                    "Amount": event.get("amount"),
                    "Amount (base)": event.get("amount_base"),
                    "Currency": event.get("currency"),
                }
                for event in events
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )


# ---------------------------------------------------------------------------
# 1. Load supplier risk data
# ---------------------------------------------------------------------------
st.header("1. Load supplier risk data")
st.caption(
    "The supplier risk profile file is required. The risk event file is optional: it adds the "
    "dated delivery, quality, invoice and compliance records behind the trend and the citations."
)

demo_col, info_col = st.columns([1, 2])
with demo_col:
    # Both files load server-side from data/sample/. Downloading each sample
    # and posting it back is an upload, and a public demonstration refuses
    # uploads - which would have broken this page's own demo button.
    loaded = load_demo_button("supplier_risk_copilot", label="Load the demo dataset", key="sr_demo")
    if loaded:
        st.session_state["sr_dataset_id"] = loaded["analyze_payload"]["dataset_id"]
        st.session_state["sr_profiles_upload"] = loaded["uploads"]["profiles"]
        st.session_state["sr_events_upload"] = loaded["uploads"]["events"]
        st.session_state.pop("sr_assessment", None)
        st.success(
            f"Loaded {loaded['uploads']['profiles'].get('supplier_count', 0)} demo suppliers "
            f"and {loaded['uploads']['events'].get('event_count', 0)} risk events. "
            "Demo data - fictional, not from SAP."
        )

with info_col:
    try:
        sample_info = client.supplier_risk_sample_info()
        if sample_info.get("available"):
            st.caption(
                f"Bundled fictional dataset: {sample_info.get('supplier_count')} suppliers, "
                f"{sample_info.get('event_count')} risk events, "
                f"{sample_info.get('scenario_count')} documented scenarios "
                f"(as of {sample_info.get('as_of_date')}). "
                f"Origin: {origin_badge(sample_info.get('data_origin'))}."
            )
        else:
            st.caption(
                "The demo dataset has not been generated yet. Run: "
                "`python scripts/generate_supplier_risk_sample_data.py`"
            )
    except ApiError as error:
        st.caption(f"Demo dataset info unavailable: {error.message}")

if not uploads_enabled(client):
    upload_disabled_notice("file")
else:
    upload_cols = st.columns(2)
    with upload_cols[0]:
        st.subheader("🏢 Supplier risk profiles")
        picked_profiles = st.file_uploader(
            "Profile file (CSV, XLSX, JSON)", type=["csv", "xlsx", "json"], key="sr_file_profiles"
        )
        if picked_profiles is not None and st.button("Upload profiles", key="sr_btn_profiles"):
            try:
                result = client.supplier_risk_upload(
                    "profiles",
                    picked_profiles.name,
                    picked_profiles.getvalue(),
                    picked_profiles.type or "text/csv",
                )
                st.session_state["sr_dataset_id"] = result.get("dataset_id")
                st.session_state["sr_profiles_upload"] = result
                st.session_state.pop("sr_assessment", None)
                st.session_state.pop("sr_events_upload", None)
                st.success(f"Loaded {result.get('supplier_count', 0)} suppliers.")
            except ApiError as error:
                show_error(error.message, error.details)

    with upload_cols[1]:
        st.subheader("📌 Risk events (optional)")
        picked_events = st.file_uploader(
            "Event file (CSV, XLSX, JSON)", type=["csv", "xlsx", "json"], key="sr_file_events"
        )
        events_disabled = not st.session_state.get("sr_dataset_id")
        if events_disabled:
            st.caption("Upload the profile file first - events attach to a dataset.")
        if picked_events is not None and st.button(
            "Upload events", key="sr_btn_events", disabled=events_disabled
        ):
            try:
                result = client.supplier_risk_upload(
                    "events",
                    picked_events.name,
                    picked_events.getvalue(),
                    picked_events.type or "text/csv",
                    dataset_id=st.session_state.get("sr_dataset_id"),
                )
                st.session_state["sr_events_upload"] = result
                st.session_state.pop("sr_assessment", None)
                st.success(f"Loaded {result.get('event_count', 0)} risk events.")
            except ApiError as error:
                show_error(error.message, error.details)

for state_key, label in (("sr_profiles_upload", "Profiles"), ("sr_events_upload", "Events")):
    upload = st.session_state.get(state_key)
    if not upload:
        continue
    with st.expander(f"{label} — {upload.get('filename', '')} ({upload.get('row_count', 0)} rows)"):
        if upload.get("missing_required_fields"):
            st.warning("Missing required fields: " + ", ".join(upload["missing_required_fields"]))
        if upload.get("unmapped_columns"):
            st.caption("Unmapped columns: " + ", ".join(upload["unmapped_columns"]))
        if upload.get("notes"):
            for note in upload["notes"]:
                st.caption(note)
        if upload.get("data_quality_issues"):
            st.dataframe(
                pd.DataFrame(upload["data_quality_issues"]),
                use_container_width=True,
                hide_index=True,
            )
        if upload.get("preview"):
            st.dataframe(pd.DataFrame(upload["preview"]), use_container_width=True, hide_index=True)

dataset_id = st.session_state.get("sr_dataset_id")
if not dataset_id and not st.session_state.get("sr_assessment"):
    st.info("Upload a supplier risk profile file (or load the demo dataset) to begin.", icon="👆")
    disclaimer()
    st.stop()

with st.expander("How the risk model works"):
    try:
        scoring = client.supplier_risk_scoring()
        st.caption(
            f"Config {scoring.get('config_version')} · engine {scoring.get('engine_version')} · "
            f"{scoring.get('scale')} · weights total {scoring.get('weight_total')}"
        )
        categories_doc = scoring.get("categories", [])
        if categories_doc:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Category": item.get("label"),
                            "Default weight %": item.get("default_weight"),
                            "Metrics": len(item.get("metrics", [])),
                            "Description": item.get("description"),
                        }
                        for item in categories_doc
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )
        if scoring.get("risk_bands"):
            st.markdown(
                "**Bands:** "
                + " · ".join(
                    f"{band.get('label')} {band.get('min_score')}-{band.get('max_score')}"
                    for band in scoring["risk_bands"]
                )
            )
        if scoring.get("missing_data", {}).get("description"):
            st.caption(scoring["missing_data"]["description"])
    except ApiError as error:
        st.caption(f"The scoring documentation is unavailable: {error.message}")


# ---------------------------------------------------------------------------
# 2. Calculate the risk assessment
# ---------------------------------------------------------------------------
st.header("2. Calculate risk")

with st.form("sr_calculate_form"):
    form_cols = st.columns(3)
    with form_cols[0]:
        use_as_of = st.checkbox("Use a specific as-of date", value=False)
    with form_cols[1]:
        as_of_date = st.date_input(
            "As-of date (contract expiry and trend windows)", value=date.today()
        )
    with form_cols[2]:
        generate_ai = st.checkbox("Generate an AI summary", value=False)
    calculate_clicked = st.form_submit_button("Calculate supplier risk", type="primary")

if calculate_clicked:
    try:
        assessment = client.supplier_risk_calculate(
            dataset_id=dataset_id,
            as_of_date=as_of_date.isoformat() if (use_as_of and as_of_date) else None,
            generate_ai_summary=generate_ai,
        )
        st.session_state["sr_assessment"] = assessment
        st.session_state["sr_assessment_id"] = assessment["assessment_id"]
        st.session_state["sr_chat_history"] = []
    except ApiError as error:
        show_error(error.message, error.details)

assessment = st.session_state.get("sr_assessment")
if not assessment:
    st.info("Run the calculation to score the loaded suppliers.", icon="▶️")
    disclaimer()
    st.stop()

assessment_id = assessment["assessment_id"]
summary = assessment.get("summary", {})
base_currency = assessment.get("base_currency", "EUR")

k1, k2, k3, k4, k5, k6 = st.columns(6)
k1.metric("Suppliers assessed", summary.get("supplier_count", 0))
k2.metric("Average overall risk", _score(summary.get("average_overall_score")))
k3.metric("Critical", summary.get("band_counts", {}).get("critical", 0))
k4.metric("High", summary.get("band_counts", {}).get("high", 0))
k5.metric("Contracts expiring", summary.get("contracts_expiring_count", 0))
k6.metric("Limited data", summary.get("limited_data_count", 0))

st.caption(
    f"Rule-based scoring · engine v{assessment.get('engine_version')} · "
    f"config {assessment.get('config_version')} · as of {assessment.get('as_of_date')} · "
    f"{summary.get('event_count', 0)} risk events · {assessment.get('duration_ms', 0)} ms"
)

if assessment.get("rule_errors"):
    st.warning(
        f"{len(assessment['rule_errors'])} scoring rule(s) reported an error; the rest still ran."
    )
    with st.expander("Rule errors"):
        st.json(assessment["rule_errors"])

band_counts = summary.get("band_counts", {})
if band_counts:
    band_frame = pd.DataFrame(
        [
            {"Band": band, "Suppliers": band_counts.get(band, 0)}
            for band in BAND_ORDER
            if band_counts.get(band)
        ]
    )
    if not band_frame.empty:
        st.plotly_chart(
            px.bar(
                band_frame,
                x="Band",
                y="Suppliers",
                color="Band",
                color_discrete_map=BAND_COLORS,
                title="Portfolio by risk band (rule-based)",
            ),
            use_container_width=True,
        )

narrative = assessment.get("ai_narrative") or {}
if narrative.get("summary"):
    st.subheader("AI portfolio narrative")
    st.info(
        f"{narrative['summary']}\n\n_Origin: {origin_badge(narrative.get('origin'))}"
        f" · provider: {narrative.get('provider') or 'n/a'}"
        f" · prompt {narrative.get('prompt_version') or 'n/a'}_"
    )
    for finding in narrative.get("key_findings", []):
        st.markdown(f"- {finding}")
    for action in narrative.get("recommended_actions", []):
        st.markdown(f"- 👉 {action}")
    st.caption("The narrative above is generated text. Every number on this page is rule-based.")
elif narrative.get("error"):
    st.caption(f"The AI narrative could not be generated: {narrative['error']}")


# ---------------------------------------------------------------------------
# 3. Choose a supplier
# ---------------------------------------------------------------------------
st.header("3. Supplier")

filter_cols = st.columns(3)
band_filter = filter_cols[0].selectbox("Risk band", ["(all)", *BAND_ORDER], key="sr_band_filter")
expiring_only = filter_cols[1].checkbox("Only contracts expiring soon", value=False)
country_filter = filter_cols[2].text_input("Country (exact code)", value="")

try:
    supplier_page = client.supplier_risk_suppliers(
        assessment_id=assessment_id,
        band=None if band_filter == "(all)" else band_filter,
        country=country_filter or None,
        expiring_only=expiring_only or None,
        limit=1000,
    )
    suppliers = supplier_page.get("suppliers", [])
except ApiError as error:
    show_error(error.message, error.details)
    suppliers = []

if not suppliers:
    st.info("No assessed supplier matches the current filters.")
    st.caption(assessment.get("disclaimer", ""))
    disclaimer()
    st.stop()

st.caption(f"{supplier_page.get('total', len(suppliers))} supplier(s) match, highest risk first.")

st.dataframe(
    pd.DataFrame(
        [
            {
                "Rank": entry.get("rank"),
                "Supplier": entry.get("supplier_name") or entry.get("supplier_id"),
                "ID": entry.get("supplier_id"),
                "Overall risk": entry.get("overall_score"),
                "Band": (entry.get("overall_band") or "").upper(),
                "Trend": entry.get("trend_direction"),
                "Country": entry.get("country"),
                "Category": entry.get("spend_category"),
                "Spend (base)": entry.get("total_spend_base"),
                "Contract": entry.get("contract_status"),
                "Expires": entry.get("contract_expiration"),
                "Expiring soon": entry.get("contract_expiring_soon"),
                "OTD %": entry.get("on_time_delivery_rate"),
                "Late deliveries": entry.get("late_delivery_count"),
                "Invoice exceptions": entry.get("invoice_exception_count"),
                "Data completeness %": entry.get("data_completeness_pct"),
                "Limited data": entry.get("limited_data"),
            }
            for entry in suppliers
        ]
    ),
    use_container_width=True,
    hide_index=True,
)

options = {_supplier_label(entry): entry["supplier_id"] for entry in suppliers}
selected_label = st.selectbox("Selected supplier", list(options.keys()), key="sr_selected")
selected_supplier_id = options[selected_label]

try:
    profile = client.supplier_risk_supplier(selected_supplier_id, assessment_id=assessment_id)
except ApiError as error:
    show_error(error.message, error.details)
    profile = None


# ---------------------------------------------------------------------------
# 4. Supplier risk profile
# ---------------------------------------------------------------------------
if profile:
    st.header("4. Risk profile")
    profile_name = profile.get("supplier_name") or profile["supplier_id"]
    st.subheader(f"{profile_name} ({profile['supplier_id']})")

    head_cols = st.columns(4)
    head_cols[0].metric("Overall risk (0-100)", _score(profile.get("overall_score")))
    head_cols[1].metric("Band", (profile.get("overall_band") or "-").upper())
    head_cols[2].metric("Rank", _plain(profile.get("rank")))
    head_cols[3].metric("Data completeness", _score(profile.get("data_completeness_pct"), "%"))

    st.markdown(
        f"<span style='background:{_band_colour(profile.get('overall_band'))};color:#fff;"
        f"padding:3px 10px;border-radius:10px;'>"
        f"{escape_html(profile.get('overall_band') or 'not scored').upper()} RISK</span>",
        unsafe_allow_html=True,
    )
    meta_bits = [
        f"Country: {_plain(profile.get('country'))}",
        f"Spend category: {_plain(profile.get('spend_category'))}",
        f"Materials: {', '.join(profile.get('materials_supplied', [])) or '-'}",
        f"Regions: {', '.join(profile.get('regions_served', [])) or '-'}",
    ]
    st.caption(" · ".join(meta_bits))
    if profile.get("limited_data"):
        st.warning(
            "This supplier is flagged as limited data: some categories could not be scored, so "
            "the overall risk rests on fewer inputs."
        )

    # --- Risk category breakdown -------------------------------------------
    st.markdown("### Risk categories")
    categories = profile.get("categories", [])
    if categories:
        category_rows = [
            {
                "Category": item.get("label") or item.get("category"),
                "Score": item.get("score"),
                "Band": (item.get("band") or "not scored"),
                "Weight %": item.get("weight"),
                "Normalised weight %": item.get("normalized_weight"),
                "Contribution": item.get("contribution"),
                "Data available": item.get("data_available"),
                "Missing metrics": ", ".join(item.get("missing_metrics", [])),
            }
            for item in categories
        ]
        st.dataframe(pd.DataFrame(category_rows), use_container_width=True, hide_index=True)

        chart_rows = [row for row in category_rows if row["Score"] is not None]
        if chart_rows:
            chart_frame = pd.DataFrame(chart_rows).sort_values("Score", ascending=True)
            figure = px.bar(
                chart_frame,
                x="Score",
                y="Category",
                orientation="h",
                color="Band",
                color_discrete_map=BAND_COLORS,
                range_x=[0, 100],
                title="Category risk scores (0 = no risk, 100 = maximum risk)",
            )
            figure.update_layout(height=460)
            st.plotly_chart(figure, use_container_width=True)
        unscored = profile.get("unscored_categories", [])
        if unscored:
            st.caption("Not scored (no data in the uploaded records): " + ", ".join(unscored))
    else:
        st.caption("This assessment produced no category breakdown for the supplier.")

    # --- Transparent scoring detail ----------------------------------------
    st.markdown("### How each category score was calculated")
    st.caption(
        "Every metric shows the raw value that was read, the weight it carries, the 0-100 risk it "
        "normalised to and the points it contributed. Nothing here is estimated by AI."
    )
    for item in categories:
        label = item.get("label") or item.get("category")
        header = (
            f"{label} — score {_score(item.get('score'))} "
            f"({(item.get('band') or 'not scored').upper()}), "
            f"weight {_score(item.get('weight'), '%')}, "
            f"contribution {_score(item.get('contribution'))}"
        )
        with st.expander(header):
            if item.get("description"):
                st.caption(item["description"])
            metrics = item.get("metrics", [])
            if metrics:
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "Metric": metric.get("label") or metric.get("metric"),
                                "Raw value": _plain(metric.get("raw_value")),
                                "Unit": metric.get("unit"),
                                "Direction": metric.get("direction"),
                                "Weight": metric.get("weight"),
                                "Normalised weight": metric.get("normalized_weight"),
                                "Normalised score (0-100)": metric.get("normalized_score"),
                                "Contribution": metric.get("contribution"),
                                "Available": metric.get("available"),
                                "Basis": metric.get("basis"),
                                "Note": metric.get("note"),
                            }
                            for metric in metrics
                        ]
                    ),
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.caption("No metric for this category was present in the uploaded records.")
            if item.get("missing_metrics"):
                st.caption("Missing metrics: " + ", ".join(item["missing_metrics"]))

    # --- Trend --------------------------------------------------------------
    st.markdown("### Risk trend")
    trend = profile.get("trend") or {}
    if trend.get("data_available"):
        t1, t2, t3 = st.columns(3)
        t1.metric("Direction", _plain(trend.get("direction")).title())
        t2.metric(
            "Recent vs previous weight",
            f"{_score(trend.get('recent_weight'))} vs {_score(trend.get('previous_weight'))}",
            delta=_score(trend.get("delta")),
        )
        t3.metric(
            "Events (recent / previous)",
            f"{trend.get('recent_event_count', 0)} / {trend.get('previous_event_count', 0)}",
        )
        st.caption(
            f"{trend.get('basis', '')} · window {trend.get('window_days', 0)} days · "
            f"{origin_badge(trend.get('output_origin'))}"
        )
    else:
        st.caption(
            trend.get("basis")
            or "No dated risk events were loaded, so no trend could be calculated."
        )

    # --- Supporting metrics -------------------------------------------------
    st.markdown("### Supporting metrics")
    s1, s2, s3, s4 = st.columns(4)
    s1.metric(
        "Total spend",
        format_currency(profile.get("total_spend_base"), profile.get("currency") or base_currency),
    )
    s2.metric("Purchase orders", _plain(profile.get("purchase_order_count")))
    s3.metric("Open POs", _plain(profile.get("open_purchase_order_count")))
    s4.metric("On-time delivery", _score(profile.get("on_time_delivery_rate"), "%"))
    s5, s6, s7, s8 = st.columns(4)
    s5.metric("Late deliveries", _plain(profile.get("late_delivery_count")))
    s6.metric("Deliveries", _plain(profile.get("delivery_count")))
    s7.metric("Quality score", _score(profile.get("quality_score")))
    s8.metric("Defect rate", _score(profile.get("defect_rate"), "%"))
    s9, s10, s11, s12 = st.columns(4)
    s9.metric("Quality incidents", _plain(profile.get("quality_incident_count")))
    s10.metric(
        "Invoices / exceptions",
        f"{_plain(profile.get('invoice_count'))} / "
        f"{_plain(profile.get('invoice_exception_count'))}",
    )
    s11.metric("ESG score", _score(profile.get("esg_score")))
    s12.metric("Credit score", _score(profile.get("credit_score")))
    st.caption(
        f"Disputed invoices: {_plain(profile.get('disputed_invoice_count'))} · "
        f"compliance findings: {_plain(profile.get('compliance_finding_count'))} · "
        f"risk events on file: {profile.get('event_count', 0)}"
    )

    # --- Contracts ----------------------------------------------------------
    st.markdown("### Contracts")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Status", _plain(profile.get("contract_status")))
    c2.metric("Expiration", _plain(profile.get("contract_expiration")))
    c3.metric("Days to expiry", _plain(profile.get("days_to_contract_expiry")))
    c4.metric("Active contracts", _plain(profile.get("active_contract_count")))
    st.caption(f"Contract number: {_plain(profile.get('contract_number'))}")
    if profile.get("contract_expiring_soon"):
        st.warning("This contract is inside the configured expiry warning window.")

    # --- Underlying records -------------------------------------------------
    st.markdown("### Underlying records")
    record_tabs = st.tabs(["Delivery issues", "Invoice issues", "Quality issues", "Compliance"])
    with record_tabs[0]:
        _event_table(
            profile.get("delivery_issues", []),
            "No delivery issues are recorded for this supplier in the loaded events.",
        )
    with record_tabs[1]:
        _event_table(
            profile.get("invoice_issues", []),
            "No invoice issues are recorded for this supplier in the loaded events.",
        )
    with record_tabs[2]:
        _event_table(
            profile.get("quality_issues", []),
            "No quality issues are recorded for this supplier in the loaded events.",
        )
    with record_tabs[3]:
        _event_table(
            profile.get("compliance_issues", []),
            "No compliance findings are recorded for this supplier in the loaded events.",
        )

    # --- Recommended actions ------------------------------------------------
    st.markdown("### Recommended actions")
    actions = profile.get("actions", [])
    if actions:
        for action in actions:
            icon = PRIORITY_ICONS.get((action.get("priority") or "").lower(), "•")
            st.markdown(
                f"{icon} **{(action.get('priority') or '').upper()} · "
                f"{action.get('category_label') or action.get('category')}** — "
                f"{action.get('action')}"
            )
            st.caption(
                f"Triggered by: {action.get('trigger')} · {origin_badge(action.get('output_origin'))}"
            )
    else:
        st.caption("The rules produced no recommended action for this supplier.")


# ---------------------------------------------------------------------------
# 4b. Export
# ---------------------------------------------------------------------------
st.header("4b. Export the assessment")
st.caption(
    "The workbook carries the portfolio, every supplier's category scores with the weight and "
    "contribution behind them, the evidence each score rests on, the categories that could not "
    "be scored, the recommended actions and the methodology. Every format carries the "
    "disclaimer, including the one specific to this module: no external data source contributed "
    "to any score."
)

scope_whole = f"Whole portfolio ({len(suppliers)} suppliers)"
scope_one = f"Selected supplier only ({selected_supplier_id})" if selected_supplier_id else None
export_scope = st.radio(
    "Scope",
    [scope for scope in (scope_whole, scope_one) if scope],
    horizontal=True,
    key="sr_export_scope",
)
export_supplier_id = selected_supplier_id if export_scope == scope_one else None

export_columns = st.columns(3)
for column, fmt, mime in (
    (export_columns[0], "xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    (export_columns[1], "csv", "text/csv"),
    (export_columns[2], "json", "application/json"),
):
    with column:
        try:
            data = client.supplier_risk_export(assessment_id, fmt, supplier_id=export_supplier_id)
        except ApiError as error:
            st.caption(f"{fmt.upper()} export unavailable: {error.message}")
            continue
        suffix = f"_{export_supplier_id}" if export_supplier_id else ""
        st.download_button(
            f"Download {fmt.upper()}",
            data=data,
            file_name=f"supplier_risk_{assessment_id[:8]}{suffix}.{fmt}",
            mime=mime,
            key=f"sr_export_{fmt}",
        )


# ---------------------------------------------------------------------------
# 5. Copilot chat
# ---------------------------------------------------------------------------
st.header("5. Copilot")
st.caption(
    f"Questions are answered from assessment `{assessment_id[:8]}` for the selected supplier "
    f"`{selected_supplier_id}`. Answers are deterministic and cite the records they used; when "
    "the information is not in the loaded records the copilot says so."
)

history: list[dict[str, Any]] = st.session_state.setdefault("sr_chat_history", [])

chat_cols = st.columns([3, 1])
with chat_cols[1]:
    chat_ai = st.checkbox("AI rephrasing", value=False, key="sr_chat_ai")
    if st.button("Clear conversation", key="sr_clear_chat"):
        st.session_state["sr_chat_history"] = []
        st.rerun()

example_questions = [
    template.format(supplier=selected_supplier_id) for template in EXAMPLE_QUESTION_TEMPLATES
]

with chat_cols[0], st.expander("Example questions", expanded=not history):
    example_cols = st.columns(2)
    for index, question in enumerate(example_questions):
        if example_cols[index % 2].button(question, key=f"sr_example_{index}"):
            st.session_state["sr_pending_question"] = question
            st.rerun()


def _render_answer(payload: dict[str, Any]) -> None:
    """Render one copilot answer with its citations and follow-ups."""
    if payload.get("data_available", True):
        st.markdown(payload.get("answer", ""))
    else:
        st.warning(payload.get("answer", ""))
        if payload.get("unavailable_reason"):
            st.caption(f"Reason: {payload['unavailable_reason']}")

    citations = payload.get("citations", [])
    with st.expander(f"Citations ({len(citations)})"):
        if citations:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Source": citation.get("source"),
                            "Record type": citation.get("record_type"),
                            "Record ID": citation.get("record_id"),
                            "Field": citation.get("field_name"),
                            "Value": _plain(citation.get("value")),
                            "Detail": citation.get("detail"),
                        }
                        for citation in citations
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.caption("This answer cites no individual record.")

    chat_narrative = payload.get("ai_narrative") or {}
    if chat_narrative.get("summary"):
        st.info(
            f"{chat_narrative['summary']}\n\n"
            f"_Origin: {origin_badge(chat_narrative.get('origin'))} - "
            "a rephrasing of the computed answer above._"
        )

    st.caption(
        f"Intent: `{payload.get('intent', 'unknown')}` · "
        f"suppliers referenced: {', '.join(payload.get('suppliers_referenced', [])) or 'none'} · "
        f"{origin_badge(payload.get('output_origin'))}"
    )


for message in history:
    with st.chat_message(message["role"]):
        if message["role"] == "user":
            st.markdown(message["content"])
        else:
            _render_answer(message["payload"])

if history and history[-1]["role"] == "assistant":
    suggestions = history[-1]["payload"].get("follow_up_suggestions", [])
    if suggestions:
        st.caption("Follow-up suggestions")
        suggestion_cols = st.columns(min(len(suggestions), 3))
        for index, suggestion in enumerate(suggestions):
            column = suggestion_cols[index % len(suggestion_cols)]
            if column.button(suggestion, key=f"sr_followup_{len(history)}_{index}"):
                st.session_state["sr_pending_question"] = suggestion
                st.rerun()

typed_question = st.chat_input("Ask the copilot about supplier risk")
question = typed_question or st.session_state.pop("sr_pending_question", None)

if question:
    try:
        answer_payload = client.supplier_risk_chat(
            question,
            assessment_id=assessment_id,
            supplier_id=selected_supplier_id,
            generate_ai_summary=chat_ai,
        )
        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "payload": answer_payload})
        st.session_state["sr_chat_history"] = history
        st.rerun()
    except ApiError as error:
        show_error(error.message, error.details)


# ---------------------------------------------------------------------------
# 6. Disclaimers
# ---------------------------------------------------------------------------
st.caption(assessment.get("disclaimer", ""))
if history and history[-1]["role"] == "assistant":
    st.caption(history[-1]["payload"].get("disclaimer", ""))
disclaimer()
