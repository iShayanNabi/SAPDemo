"""Streamlit page for the Spend Analytics Dashboard.

A thin client over the FastAPI backend:

    upload -> preview -> mapping -> filters -> analyse -> dashboard
           -> drill-down -> opportunities -> export

Every figure shown here was calculated by the backend. The page performs no
spend logic of its own - it formats and it charts, nothing else.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from streamlit_app.components.api_client import ApiClient, ApiError  # noqa: E402
from streamlit_app.components.ui import (  # noqa: E402
    disclaimer,
    format_currency,
    format_number,
    kpi_row,
    origin_badge,
    show_error,
)

st.set_page_config(page_title="Spend Analytics", page_icon="📊", layout="wide")

client = ApiClient()

MEDIA_TYPES = {
    ".csv": "text/csv",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".json": "application/json",
}

FILTER_FIELDS = [
    ("supplier_id", "Supplier"),
    ("material", "Material"),
    ("material_group", "Material group"),
    ("category", "Category"),
    ("subcategory", "Subcategory"),
    ("plant", "Plant"),
    ("company_code", "Company code"),
    ("purchasing_org", "Purchasing organisation"),
    ("purchasing_group", "Purchasing group"),
    ("currency", "Currency"),
    ("contract_status", "Contract status"),
    ("preferred_supplier_status", "Preferred supplier status"),
]

for key in ("spend_upload", "spend_analysis", "spend_filters"):
    st.session_state.setdefault(key, None)


# ---------------------------------------------------------------------------
# Explanation
# ---------------------------------------------------------------------------
st.title("Spend Analytics Dashboard")
st.write(
    "Upload procurement transactions to analyse spend, measure contract coverage and "
    "concentration, drill into any figure, and review modelled savings opportunities."
)

with st.expander("What this module does and does not do", expanded=False):
    st.markdown(
        """
**Does**

- Accepts CSV, XLSX and JSON, reusing the purchase order field contract from the PO Risk Checker
  and adding transaction date, category, subcategory, contract status, preferred supplier status,
  baseline price, current price and payment status.
- Calculates every metric deterministically in base currency: total spend, contracted and
  non-contracted spend, maverick spend, spend under management, supplier concentration (HHI),
  top supplier and top-five share, tail spend, price variance and estimated savings.
- Lets you filter on 12 dimensions plus a date range, and drill from any chart into the exact
  transactions behind it.

**Does not**

- Connect to an SAP system. Everything comes from the file you upload.
- Use AI to calculate anything. The optional narrative only describes figures already computed.
- Promise savings. Every opportunity is a **modelled estimate** under documented assumptions -
  not negotiated, not committed and not validated in SAP.
        """
    )


# ---------------------------------------------------------------------------
# 1. Load data
# ---------------------------------------------------------------------------
st.header("1. Load data")
sample_column, upload_column = st.columns([1, 2])

with sample_column:
    st.subheader("Sample file")
    try:
        info = client.spend_sample_info()
    except ApiError as error:
        show_error(error.message, error.details)
        st.stop()

    if info.get("available"):
        st.caption(
            f"Fictional demo dataset: {format_number(info['row_count'])} transactions over "
            f"{info.get('months_covered', 0)} months with {info.get('scenario_count', 0)} "
            "documented scenarios. **Demo data - not from SAP.**"
        )
        sample_format = st.radio("Format", ["csv", "xlsx", "json"], horizontal=True, key="spend_fmt")
        try:
            st.download_button(
                f"Download sample .{sample_format}",
                data=client.spend_sample_file(sample_format),
                file_name=f"sample_spend_transactions.{sample_format}",
                mime=MEDIA_TYPES[f".{sample_format}"],
                use_container_width=True,
            )
        except ApiError as error:
            st.warning(error.message)
    else:
        st.warning("No sample file yet. Generate it with:")
        st.code("python scripts/generate_spend_sample_data.py", language="bash")

with upload_column:
    st.subheader("Upload your file")
    uploaded = st.file_uploader(
        "CSV, XLSX or JSON (max 25 MB)", type=["csv", "xlsx", "json"], key="spend_file"
    )
    if uploaded is not None and st.button("Validate and preview", type="primary"):
        with st.spinner("Validating file and detecting columns..."):
            try:
                extension = Path(uploaded.name).suffix.lower()
                st.session_state["spend_upload"] = client.spend_upload(
                    uploaded.name, uploaded.getvalue(), MEDIA_TYPES.get(extension, "text/csv")
                )
                st.session_state["spend_analysis"] = None
                st.success("File accepted.")
            except ApiError as error:
                st.session_state["spend_upload"] = None
                show_error(error.message, error.details)

upload = st.session_state.get("spend_upload")

if upload:
    # -----------------------------------------------------------------------
    # 2. Preview and mapping
    # -----------------------------------------------------------------------
    st.header("2. Review the data")
    kpi_row(
        [
            ("Rows", format_number(upload["row_count"]), "Transactions detected"),
            ("Columns", format_number(upload["column_count"]), None),
            ("Fields mapped", format_number(len(upload["suggested_mapping"])), None),
            ("Size", f"{upload['size_bytes'] / 1024:,.0f} KB", None),
        ]
    )
    for note in upload.get("parser_notes", []):
        st.caption(f"Parser: {note}")

    st.subheader("Preview")
    st.dataframe(pd.DataFrame(upload["preview_rows"]), use_container_width=True, height=240)

    with st.expander("Column mapping", expanded=bool(upload["missing_required_fields"])):
        st.caption(
            "Spend analysis needs a document number, a supplier, a date (transaction or order) "
            "and a value basis (a total, or quantity and unit price). Everything else is optional."
        )
        try:
            field_catalogue = client.spend_fields()
        except ApiError as error:
            show_error(error.message)
            st.stop()

        field_names = [""] + [field["name"] for field in field_catalogue]
        field_labels = {
            field["name"]: f"{field['label']}{' *' if field['required'] else ''}"
            for field in field_catalogue
        }
        confidence_by_column = {
            suggestion["source_column"]: suggestion
            for suggestion in upload["mapping_suggestions"]
        }

        overrides: dict[str, str] = {}
        detected = upload["detected_columns"]
        for start in range(0, len(detected), 3):
            row_columns = st.columns(3)
            for widget, source_column in zip(row_columns, detected[start : start + 3]):
                with widget:
                    current = upload["suggested_mapping"].get(source_column, "")
                    index = field_names.index(current) if current in field_names else 0
                    selected = st.selectbox(
                        f"`{source_column}`",
                        options=field_names,
                        index=index,
                        format_func=lambda n: "(ignore column)" if not n else field_labels[n],
                        key=f"spendmap_{source_column}",
                    )
                    suggestion = confidence_by_column.get(source_column)
                    if suggestion:
                        st.caption(
                            f"auto: {suggestion['strategy']} · "
                            f"confidence {suggestion['confidence']:.2f}"
                        )
                    if selected != current:
                        overrides[source_column] = selected
        st.session_state["spend_overrides"] = overrides

    if upload["missing_required_fields"]:
        st.error(
            "The file is missing required information: "
            + ", ".join(upload["missing_required_fields"])
            + ". Correct the mapping above."
        )

    # -----------------------------------------------------------------------
    # 3. Filters
    # -----------------------------------------------------------------------
    st.header("3. Filters")
    st.caption(
        "Filters are applied before every calculation, so the KPI cards, the charts, the "
        "drill-downs and the opportunity list all describe the same slice of spend."
    )

    previous = st.session_state.get("spend_analysis") or {}
    options = previous.get("filter_options", {})

    date_columns = st.columns(2)
    with date_columns[0]:
        date_from = st.date_input("From", value=None, key="spend_date_from")
    with date_columns[1]:
        date_to = st.date_input("To", value=None, key="spend_date_to")

    if not options:
        st.caption(
            "Run the analysis once to load the available values for the remaining filters "
            "from your data."
        )

    selections: dict[str, list[str]] = {}
    for start in range(0, len(FILTER_FIELDS), 3):
        widgets = st.columns(3)
        for widget, (field_name, label) in zip(widgets, FILTER_FIELDS[start : start + 3]):
            with widget:
                values = options.get(field_name, [])
                selections[field_name] = st.multiselect(
                    label, options=values, default=[], key=f"spendfilter_{field_name}",
                    disabled=not values,
                )

    # -----------------------------------------------------------------------
    # 4. Run
    # -----------------------------------------------------------------------
    st.header("4. Run the analysis")
    option_column, button_column = st.columns([2, 1])
    with option_column:
        generate_summary = st.checkbox("Generate AI narrative (labelled)", value=True)
        top_n = st.slider("Rows per top-N chart", min_value=5, max_value=30, value=10)
    with button_column:
        run = st.button(
            "Run analysis",
            type="primary",
            disabled=bool(upload["missing_required_fields"]),
            use_container_width=True,
        )

    if run:
        progress = st.progress(0, text="Reading and mapping the file...")
        try:
            filters: dict[str, object] = {
                name: values for name, values in selections.items() if values
            }
            if date_from:
                filters["date_from"] = str(date_from)
            if date_to:
                filters["date_to"] = str(date_to)

            progress.progress(40, text="Calculating metrics and breakdowns...")
            st.session_state["spend_analysis"] = client.spend_analyze(
                upload["upload_id"],
                overrides=st.session_state.get("spend_overrides", {}),
                filters=filters,
                generate_ai_summary=generate_summary,
                top_n=top_n,
            )
            progress.progress(100, text="Done.")
        except ApiError as error:
            progress.empty()
            show_error(error.message, error.details)

analysis = st.session_state.get("spend_analysis")

if analysis:
    metrics = analysis["metrics"]
    currency = metrics["base_currency"]
    analytics = analysis["analytics"]

    # -----------------------------------------------------------------------
    # 5. KPI cards
    # -----------------------------------------------------------------------
    st.header("5. Results")
    st.caption(
        f"Analysis `{analysis['analysis_id']}` · config v{analysis['config_version']} · "
        f"metrics v{analysis['metrics_version']} · {analysis['duration_ms']} ms · "
        f"{format_number(analysis['filtered_record_count'])} of "
        f"{format_number(analysis['record_count'])} transactions after filters · "
        f"{analysis['period_start']} to {analysis['period_end']}"
    )

    if analysis.get("applied_filter", {}).get("values") or analysis["applied_filter"].get("date_from"):
        st.info(f"Filters applied: {analysis['applied_filter']}", icon="🔎")

    kpi_row([
        ("Total spend", format_currency(metrics["total_spend"], currency), None),
        ("Purchase orders", format_number(metrics["purchase_order_count"]), None),
        ("Line items", format_number(metrics["line_item_count"]), None),
        ("Suppliers", format_number(metrics["supplier_count"]), None),
    ])
    kpi_row([
        ("Average PO value", format_currency(metrics["average_po_value"], currency), None),
        ("Median PO value", format_currency(metrics["median_po_value"], currency), None),
        ("Contracted spend", f"{metrics['contracted_spend_pct']:.1f}%",
         format_currency(metrics["contracted_spend"], currency)),
        ("Spend under management", f"{metrics['spend_under_management_pct']:.1f}%",
         "Contracted, or with a preferred supplier"),
    ])
    kpi_row([
        ("Maverick spend", format_currency(metrics["maverick_spend"], currency),
         f"{metrics['maverick_spend_pct']:.1f}% of total - no contract and non-preferred supplier"),
        ("Supplier concentration",
         f"{metrics['supplier_concentration_hhi']:,.0f} ({metrics['supplier_concentration_level']})",
         "Herfindahl-Hirschman Index, 0-10,000"),
        ("Top supplier share", f"{metrics['top_supplier_share_pct']:.1f}%",
         metrics.get("top_supplier_id")),
        ("Top 5 share", f"{metrics['top_five_supplier_share_pct']:.1f}%", None),
    ])
    kpi_row([
        ("Tail spend", format_currency(metrics["tail_spend"], currency),
         f"{metrics['tail_spend_pct']:.1f}% across {metrics['tail_supplier_count']} suppliers"),
        ("Price variance", format_currency(metrics["price_variance_base"], currency),
         f"{metrics['price_variance_line_count']} lines vs baseline or material median"),
        ("Estimated savings", format_currency(metrics["estimated_savings_opportunity"], currency),
         "MODELLED estimate - not guaranteed"),
        ("Currencies", format_number(len(metrics["spend_by_currency"])), None),
    ])

    st.warning(
        "Estimated savings are modelled from this data under documented assumptions. They are "
        "opportunities to investigate, not guaranteed, negotiated or committed savings.",
        icon="⚠️",
    )

    if analysis.get("savings_errors"):
        st.error("Some savings rules could not be executed; the other results are unaffected.")
        st.json(analysis["savings_errors"])

    if analysis.get("data_quality_issues"):
        with st.expander(f"Data quality warnings ({len(analysis['data_quality_issues'])})"):
            st.dataframe(pd.DataFrame(analysis["data_quality_issues"]), use_container_width=True)

    narrative = analysis.get("ai_narrative", {})
    if narrative.get("available"):
        st.subheader("Narrative")
        st.caption(
            f"{origin_badge(narrative.get('origin'))} · provider `{narrative.get('provider')}` · "
            f"prompt `{narrative.get('prompt_version')}`. This text describes the figures above; "
            "it does not produce them."
        )
        st.info(narrative["summary"])
        narrative_columns = st.columns(2)
        with narrative_columns[0]:
            if narrative.get("key_findings"):
                st.write("**Key findings**")
                for item in narrative["key_findings"]:
                    st.write(f"- {item}")
        with narrative_columns[1]:
            if narrative.get("recommended_actions"):
                st.write("**Suggested actions**")
                for item in narrative["recommended_actions"]:
                    st.write(f"- {item}")
    elif narrative.get("error"):
        st.warning(f"No AI narrative: {narrative['error']} The figures above are complete.")

    # -----------------------------------------------------------------------
    # 6. Charts
    # -----------------------------------------------------------------------
    st.header("6. Analytics")

    monthly = analytics.get("monthly_spend", [])
    if monthly:
        st.subheader("Monthly spend")
        monthly_frame = pd.DataFrame(monthly)
        figure = px.bar(
            monthly_frame, x="value", y="spend_base",
            labels={"value": "Month", "spend_base": f"Spend ({currency})"},
        )
        figure.add_scatter(
            x=monthly_frame["value"], y=monthly_frame["maverick_spend_base"],
            mode="lines+markers", name="Maverick spend",
        )
        figure.update_layout(height=380, margin=dict(t=20, b=10))
        st.plotly_chart(figure, use_container_width=True)

    chart_left, chart_right = st.columns(2)
    chart_specs = [
        (chart_left, "spend_by_supplier", "Spend by supplier", "supplier_id"),
        (chart_right, "spend_by_category", "Spend by category", "value"),
    ]
    for column, key, title, label_key in chart_specs:
        rows = analytics.get(key, [])
        with column:
            st.subheader(title)
            if rows:
                frame = pd.DataFrame(rows)
                frame["label"] = frame[label_key].astype(str)
                figure = px.bar(
                    frame.sort_values("spend_base"), x="spend_base", y="label",
                    orientation="h", labels={"spend_base": f"Spend ({currency})", "label": ""},
                )
                figure.update_layout(height=380, margin=dict(t=20, b=10))
                st.plotly_chart(figure, use_container_width=True)
            else:
                st.info("No data for this breakdown.")

    breakdown_left, breakdown_right = st.columns(2)
    for column, key, title in (
        (breakdown_left, "spend_by_material_group", "Spend by material group"),
        (breakdown_right, "spend_by_plant", "Spend by plant"),
    ):
        rows = analytics.get(key, [])
        with column:
            st.subheader(title)
            if rows:
                frame = pd.DataFrame(rows)
                figure = px.pie(frame, names="value", values="spend_base", hole=0.45)
                figure.update_layout(height=360, margin=dict(t=20, b=10))
                st.plotly_chart(figure, use_container_width=True)
            else:
                st.info("No data for this breakdown.")

    st.subheader("Spend by currency")
    st.dataframe(pd.DataFrame(metrics["spend_by_currency"]), use_container_width=True,
                 hide_index=True)

    # -----------------------------------------------------------------------
    # 7. Breakdown tables
    # -----------------------------------------------------------------------
    st.header("7. Detailed breakdowns")
    table_specs = [
        ("spend_by_supplier", "Suppliers"),
        ("top_materials", "Top materials"),
        ("spend_by_company_code", "Company codes"),
        ("spend_by_purchasing_org", "Purchasing organisations"),
        ("tail_spend_suppliers", "Tail suppliers"),
        ("supplier_concentration", "Concentration by material group"),
        ("contract_leakage", "Contract leakage"),
        ("maverick_spend", "Maverick spend"),
        ("purchase_price_variance", "Purchase price variance"),
    ]
    tabs = st.tabs([label for _key, label in table_specs])
    for tab, (key, label) in zip(tabs, table_specs):
        with tab:
            rows = analytics.get(key, [])
            if rows:
                st.dataframe(pd.DataFrame(rows), use_container_width=True, height=340,
                             hide_index=True)
            else:
                st.info(f"No {label.lower()} to report for this data slice.")

    # -----------------------------------------------------------------------
    # 8. Drill-down
    # -----------------------------------------------------------------------
    st.header("8. Drill into transactions")
    st.caption(
        "Pick any dimension and value to see exactly the transactions behind that figure."
    )
    drill_columns = st.columns([1, 2, 1])
    dimension_options = {
        "supplier": "spend_by_supplier",
        "category": "spend_by_category",
        "material_group": "spend_by_material_group",
        "material": "top_materials",
        "plant": "spend_by_plant",
        "company_code": "spend_by_company_code",
        "spend_month": "monthly_spend",
    }
    with drill_columns[0]:
        dimension = st.selectbox("Dimension", list(dimension_options))
    with drill_columns[1]:
        source_rows = analytics.get(dimension_options[dimension], [])
        values = [str(row.get("value")) for row in source_rows]
        value = st.selectbox("Value", values) if values else None
    with drill_columns[2]:
        drill_limit = st.number_input("Rows", min_value=10, max_value=1000, value=100, step=10)

    if value:
        try:
            drill = client.spend_transactions(
                analysis["analysis_id"], dimension=dimension, value=value, limit=int(drill_limit)
            )
            st.caption(
                f"{format_number(drill['total'])} transactions worth "
                f"{format_currency(drill['total_spend_base'], currency)} - showing "
                f"{len(drill['transactions'])}."
            )
            st.dataframe(pd.DataFrame(drill["transactions"]), use_container_width=True, height=380)
        except ApiError as error:
            show_error(error.message, error.details)

    # -----------------------------------------------------------------------
    # 9. Savings opportunities
    # -----------------------------------------------------------------------
    st.header("9. Savings opportunities")
    st.caption(
        "Every row is a modelled estimate. The method column states the arithmetic so you can "
        "check the figure rather than trust it."
    )
    opportunities = analysis.get("opportunities", [])
    if opportunities:
        opportunity_frame = pd.DataFrame(opportunities)
        summary = (
            opportunity_frame.groupby(["rule_id", "rule_name"])["estimated_saving_base"]
            .agg(["count", "sum"])
            .reset_index()
            .rename(columns={"count": "Opportunities", "sum": f"Estimated ({currency})"})
        )
        st.dataframe(summary, use_container_width=True, hide_index=True)

        display_columns = [
            "rule_id", "title", "scope", "scope_value", "addressable_spend_base",
            "gross_saving_base", "realization_factor", "estimated_saving_base", "confidence",
            "transaction_count",
        ]
        st.dataframe(
            opportunity_frame[display_columns].rename(
                columns={
                    "rule_id": "Rule", "title": "Opportunity", "scope": "Scope",
                    "scope_value": "Scope value",
                    "addressable_spend_base": f"Addressable ({currency})",
                    "gross_saving_base": f"Gross ({currency})",
                    "realization_factor": "Realization",
                    "estimated_saving_base": f"Estimated ({currency})",
                    "confidence": "Confidence", "transaction_count": "Transactions",
                }
            ),
            use_container_width=True,
            height=340,
            hide_index=True,
        )

        with st.expander("Inspect one opportunity and its arithmetic"):
            labels = {
                f"{o['rule_id']} · {o['title'][:70]}": o for o in opportunities
            }
            chosen = st.selectbox("Opportunity", list(labels))
            selected = labels[chosen]
            st.write(f"**Description:** {selected['description']}")
            st.write(f"**Method:** {selected['method']}")
            st.json(selected["evidence"])
    else:
        st.info("No savings opportunity cleared the configured thresholds for this data slice.")

    # -----------------------------------------------------------------------
    # 10. Export
    # -----------------------------------------------------------------------
    st.header("10. Download the report")
    export_columns = st.columns(3)
    export_specs = [
        ("Excel workbook (.xlsx)", "xlsx", MEDIA_TYPES[".xlsx"]),
        ("Transactions (.csv)", "csv", "text/csv"),
        ("Full payload (.json)", "json", "application/json"),
    ]
    for column, (label, export_format, media_type) in zip(export_columns, export_specs):
        with column:
            try:
                st.download_button(
                    label,
                    data=client.spend_export(analysis["analysis_id"], export_format),
                    file_name=f"spend_analysis_{analysis['analysis_id'][:8]}.{export_format}",
                    mime=media_type,
                    use_container_width=True,
                )
            except ApiError as error:
                st.warning(error.message)

    # -----------------------------------------------------------------------
    # 11. Methodology
    # -----------------------------------------------------------------------
    st.header("11. Methodology")
    methodology = analysis.get("methodology", {})
    with st.expander("How every figure is calculated", expanded=False):
        st.markdown(
            f"""
**Calculation basis** - {methodology.get('calculation_basis')}. Metrics version
**{methodology.get('metrics_version')}**, configuration version
**{methodology.get('config_version')}**. All values are converted to
**{methodology.get('base_currency')}** before aggregation.

**Maverick spend** - {methodology.get('maverick_definition')}

**Spend under management** - {methodology.get('spend_under_management_definition')}

**Tail spend** - {methodology.get('tail_spend_definition')}

**Supplier concentration** - {methodology.get('concentration_definition')}

**Price variance** - {methodology.get('price_variance_definition')}

**Savings** - {methodology.get('savings_disclaimer')}

**Disclaimer** - {methodology.get('data_disclaimer')}
            """
        )
        st.write("**Currency rates used:**")
        st.json(methodology.get("currency_rates", {}))

    with st.expander("Savings rules and their assumptions"):
        try:
            rules = pd.DataFrame(client.spend_savings_rules())
            st.dataframe(rules, use_container_width=True, hide_index=True)
            st.caption(
                "Assumptions live in `app/modules/spend/config/spend_rules.json`. Change a value "
                "there and the next analysis uses it - no code change needed."
            )
        except ApiError as error:
            show_error(error.message)

    with st.expander("Column mapping applied"):
        st.json(analysis["applied_mapping"])
        if analysis.get("unmapped_columns"):
            st.write("**Ignored source columns:**", analysis["unmapped_columns"])

disclaimer()
