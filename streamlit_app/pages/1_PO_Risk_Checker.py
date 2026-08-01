"""Streamlit page for the Purchase Order Risk Checker.

The page is a thin client over the FastAPI backend:

    upload -> preview -> mapping -> analyse -> dashboard -> export

Every number displayed here was computed by the backend rule engine. The page
performs no risk logic of its own.
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
    SEVERITY_COLORS,
    SEVERITY_ORDER,
    disclaimer,
    findings_dataframe,
    format_currency,
    format_number,
    kpi_row,
    origin_badge,
    show_error,
)

st.set_page_config(page_title="PO Risk Checker", page_icon="🔍", layout="wide")

client = ApiClient()

MEDIA_TYPES = {
    ".csv": "text/csv",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".json": "application/json",
}

for key in ("upload", "analysis", "mapping_overrides"):
    st.session_state.setdefault(key, {} if key == "mapping_overrides" else None)


# ---------------------------------------------------------------------------
# 1. Explanation
# ---------------------------------------------------------------------------
st.title("Purchase Order Risk Checker")
st.write(
    "Upload an SAP-style purchase order extract. The application validates the file, maps your "
    "columns onto a canonical model, runs 20 transparent risk rules and produces a findings "
    "report you can download."
)

with st.expander("What this module does and does not do", expanded=False):
    st.markdown(
        """
**Does**

- Accepts CSV, XLSX and JSON exports and maps common SAP column names automatically
  (`EBELN`, `LIFNR`, `MENGE`, `NETPR`, ...).
- Applies 20 deterministic rules covering duplicates, split purchases, threshold avoidance,
  pricing, contract compliance, approvals, delivery dates, data quality and supplier risk.
- Shows the evidence and the configured threshold behind every finding.
- Optionally adds an AI executive summary, which is clearly labelled and never changes the
  risk decision.

**Does not**

- Connect to an SAP system. Everything comes from the file you upload.
- Use AI to decide what is risky. Every finding is reproducible Python code.
- Claim any recommendation has been validated in a live SAP environment.
        """
    )

try:
    ai_status = client.ai_status()
    if ai_status["is_mock"]:
        st.info(
            "AI is running in **mock mode** - no API key is configured, so narrative text is "
            "generated locally from the rule results and labelled *Mock AI output*.",
            icon="🤖",
        )
except ApiError as error:
    show_error(error.message, error.details)
    st.stop()


# ---------------------------------------------------------------------------
# 2. Sample file + upload
# ---------------------------------------------------------------------------
st.header("1. Load data")
sample_column, upload_column = st.columns([1, 2])

with sample_column:
    st.subheader("Sample file")
    try:
        info = client.sample_info()
    except ApiError:
        info = {"available": False}

    if info.get("available"):
        st.caption(
            f"Fictional demo dataset: {format_number(info['row_count'])} line items with "
            f"{info.get('anomaly_count', 0)} documented anomalies. **Demo data - not from SAP.**"
        )
        sample_format = st.radio("Format", ["csv", "xlsx", "json"], horizontal=True, key="sample_fmt")
        try:
            st.download_button(
                f"Download sample .{sample_format}",
                data=client.sample_file(sample_format),
                file_name=f"sample_purchase_orders.{sample_format}",
                mime=MEDIA_TYPES[f".{sample_format}"],
                use_container_width=True,
            )
        except ApiError as error:
            st.warning(error.message)
    else:
        st.warning("No sample file yet. Generate it with:")
        st.code("python scripts/generate_sample_data.py", language="bash")

with upload_column:
    st.subheader("Upload your file")
    uploaded = st.file_uploader(
        "CSV, XLSX or JSON (max 25 MB)", type=["csv", "xlsx", "json"], key="po_file"
    )
    if uploaded is not None and st.button("Validate and preview", type="primary"):
        with st.spinner("Validating file and detecting columns..."):
            try:
                extension = Path(uploaded.name).suffix.lower()
                st.session_state["upload"] = client.upload(
                    uploaded.name, uploaded.getvalue(), MEDIA_TYPES.get(extension, "text/csv")
                )
                st.session_state["analysis"] = None
                st.session_state["mapping_overrides"] = {}
                st.success("File accepted.")
            except ApiError as error:
                st.session_state["upload"] = None
                show_error(error.message, error.details)

upload = st.session_state.get("upload")

if upload:
    # -----------------------------------------------------------------------
    # 3. Preview + 4/5. Mapping
    # -----------------------------------------------------------------------
    st.header("2. Review the data")
    kpi_row(
        [
            ("Rows", format_number(upload["row_count"]), "Data rows detected in the file"),
            ("Columns", format_number(upload["column_count"]), None),
            ("Fields mapped", format_number(len(upload["suggested_mapping"])), "Columns matched to canonical fields"),
            ("Size", f"{upload['size_bytes'] / 1024:,.0f} KB", None),
        ]
    )
    for note in upload.get("parser_notes", []):
        st.caption(f"Parser: {note}")

    st.subheader("Preview (first rows)")
    st.dataframe(pd.DataFrame(upload["preview_rows"]), use_container_width=True, height=260)

    st.subheader("Column mapping")
    st.caption(
        "Suggestions are produced by exact SAP alias matching first, then token matching, then "
        "fuzzy similarity. Correct anything that looks wrong before running the analysis."
    )

    try:
        field_catalogue = client.fields()
    except ApiError as error:
        show_error(error.message)
        st.stop()

    field_names = [""] + [field["name"] for field in field_catalogue]
    field_labels = {field["name"]: f"{field['label']}{' *' if field['required'] else ''}"
                    for field in field_catalogue}
    confidence_by_column = {
        suggestion["source_column"]: suggestion for suggestion in upload["mapping_suggestions"]
    }

    overrides: dict[str, str] = {}
    columns_per_row = 3
    detected = upload["detected_columns"]
    for start in range(0, len(detected), columns_per_row):
        row_columns = st.columns(columns_per_row)
        for column_widget, source_column in zip(row_columns, detected[start : start + columns_per_row]):
            with column_widget:
                current = upload["suggested_mapping"].get(source_column, "")
                index = field_names.index(current) if current in field_names else 0
                selected = st.selectbox(
                    f"`{source_column}`",
                    options=field_names,
                    index=index,
                    format_func=lambda name: "(ignore column)" if not name else field_labels[name],
                    key=f"map_{source_column}",
                )
                suggestion = confidence_by_column.get(source_column)
                if suggestion:
                    st.caption(
                        f"auto: {suggestion['strategy']} · confidence {suggestion['confidence']:.2f}"
                    )
                if selected != current:
                    overrides[source_column] = selected

    st.session_state["mapping_overrides"] = overrides

    missing = [
        field["label"]
        for field in field_catalogue
        if field["required"]
        and field["name"] not in {**upload["suggested_mapping"], **overrides}.values()
    ]
    if missing:
        st.error(f"Required fields are not mapped yet: {', '.join(missing)}")

    # -----------------------------------------------------------------------
    # 6-8. Run the analysis
    # -----------------------------------------------------------------------
    st.header("3. Run the risk analysis")
    option_column, button_column = st.columns([2, 1])
    with option_column:
        generate_summary = st.checkbox("Generate AI executive summary (labelled)", value=True)
        rewrite = st.checkbox(
            "Also rewrite the most severe findings in business language", value=False,
            help="Adds one AI call per finding, up to ten. Works in mock mode too.",
        )
    with button_column:
        run = st.button("Run analysis", type="primary", disabled=bool(missing), use_container_width=True)

    if run:
        progress = st.progress(0, text="Reading the file...")
        try:
            progress.progress(30, text="Applying column mapping and validating data types...")
            result = client.analyze(
                upload["upload_id"],
                overrides=st.session_state["mapping_overrides"],
                generate_ai_summary=generate_summary,
                rewrite_findings=rewrite,
            )
            progress.progress(90, text="Building the summary...")
            st.session_state["analysis"] = result
            progress.progress(100, text="Done.")
        except ApiError as error:
            progress.empty()
            show_error(error.message, error.details)

analysis = st.session_state.get("analysis")

if analysis:
    kpis = analysis["kpis"]
    severity_counts = kpis.get("severity_counts", {})
    currency = analysis["base_currency"]

    # -----------------------------------------------------------------------
    # 9. Summary dashboard
    # -----------------------------------------------------------------------
    st.header("4. Results")
    st.caption(
        f"Analysis `{analysis['analysis_id']}` · rule config v{analysis['config_version']} · "
        f"engine v{analysis['engine_version']} · completed in {analysis['duration_ms']} ms"
    )

    kpi_row(
        [
            ("Risk score", f"{kpis.get('risk_score', 0):.1f}/100", kpis.get("risk_score_method")),
            ("Findings", format_number(analysis["findings_count"]), "All rule-based"),
            ("Critical", format_number(severity_counts.get("critical", 0)), None),
            ("High", format_number(severity_counts.get("high", 0)), None),
        ]
    )
    kpi_row(
        [
            ("Line items", format_number(analysis["record_count"]), None),
            ("Purchase orders", format_number(analysis["purchase_order_count"]), None),
            ("Total value", format_currency(analysis["total_value"], currency), None),
            ("Estimated exposure", format_currency(analysis["estimated_exposure"], currency),
             kpis.get("exposure_note")),
        ]
    )

    if analysis.get("rule_errors"):
        st.warning(
            "Some rules could not be executed. The remaining results are unaffected.",
            icon="⚠️",
        )
        st.json(analysis["rule_errors"])

    if analysis.get("data_quality_issues"):
        with st.expander(f"Data quality warnings ({len(analysis['data_quality_issues'])})"):
            st.dataframe(pd.DataFrame(analysis["data_quality_issues"]), use_container_width=True)

    narrative = analysis.get("ai_narrative", {})
    if narrative.get("available"):
        st.subheader("Executive summary")
        st.caption(
            f"{origin_badge(narrative.get('origin'))} · provider `{narrative.get('provider')}` · "
            f"prompt `{narrative.get('prompt_version')}`. This text restates the rule-based "
            "results; it does not decide risk."
        )
        st.info(narrative["summary"])
        summary_columns = st.columns(2)
        with summary_columns[0]:
            if narrative.get("key_risks"):
                st.write("**Key risks**")
                for item in narrative["key_risks"]:
                    st.write(f"- {item}")
        with summary_columns[1]:
            if narrative.get("recommended_actions"):
                st.write("**Suggested actions**")
                for item in narrative["recommended_actions"]:
                    st.write(f"- {item}")
        if narrative.get("input_tokens") is not None:
            st.caption(
                f"Tokens in/out: {narrative.get('input_tokens')}/{narrative.get('output_tokens')} · "
                f"estimated cost: ${narrative.get('estimated_cost_usd') or 0:.4f}"
            )
    elif narrative.get("error"):
        st.warning(f"No AI summary: {narrative['error']} The rule results below are complete.")

    # -----------------------------------------------------------------------
    # Charts
    # -----------------------------------------------------------------------
    chart_left, chart_right = st.columns(2)
    with chart_left:
        st.subheader("Findings by severity")
        severity_frame = pd.DataFrame(
            [{"Severity": key.capitalize(), "Findings": severity_counts.get(key, 0)}
             for key in SEVERITY_ORDER]
        )
        figure = px.bar(
            severity_frame, x="Severity", y="Findings", color="Severity",
            color_discrete_map={k.capitalize(): v for k, v in SEVERITY_COLORS.items()},
        )
        figure.update_layout(showlegend=False, height=340, margin={"t": 10, "b": 10})
        st.plotly_chart(figure, use_container_width=True)

    with chart_right:
        st.subheader("Findings by risk category")
        category_counts = kpis.get("category_counts", {})
        if category_counts:
            category_frame = pd.DataFrame(
                [{"Category": key, "Findings": value} for key, value in category_counts.items()]
            ).sort_values("Findings", ascending=True)
            figure = px.bar(category_frame, x="Findings", y="Category", orientation="h")
            figure.update_layout(height=340, margin={"t": 10, "b": 10})
            st.plotly_chart(figure, use_container_width=True)
        else:
            st.info("No findings were raised for this dataset.")

    if kpis.get("rule_counts"):
        st.subheader("Findings per rule")
        rule_frame = pd.DataFrame(kpis["rule_counts"]).rename(
            columns={"rule_id": "Rule", "rule_name": "Name", "category": "Category",
                     "count": "Findings", "exposure": f"Exposure ({currency})"}
        )
        st.dataframe(rule_frame, use_container_width=True, hide_index=True)

    # -----------------------------------------------------------------------
    # Supplier risk table
    # -----------------------------------------------------------------------
    st.subheader("Supplier risk")
    supplier_rows = analysis.get("supplier_risk", [])
    if supplier_rows:
        supplier_frame = pd.DataFrame(supplier_rows)
        supplier_frame = supplier_frame[supplier_frame["findings_count"] > 0].rename(
            columns={
                "supplier_id": "Supplier", "supplier_name": "Name",
                "spend_base": f"Spend ({currency})", "spend_share_pct": "Spend share %",
                "line_items": "Lines", "findings_count": "Findings",
                "critical_count": "Critical", "high_count": "High",
                "medium_count": "Medium", "low_count": "Low",
                "estimated_exposure_base": f"Exposure ({currency})",
                "risk_points": "Risk points", "top_risk_category": "Top category",
            }
        )
        st.dataframe(supplier_frame.head(25), use_container_width=True, hide_index=True)
        st.caption("Suppliers with at least one finding, ordered by weighted severity points.")
    else:
        st.info("No supplier level risk was aggregated for this dataset.")

    # -----------------------------------------------------------------------
    # 10. Detailed findings with filters
    # -----------------------------------------------------------------------
    st.header("5. Detailed findings")
    filter_columns = st.columns(4)
    with filter_columns[0]:
        severity_filter = st.multiselect("Severity", SEVERITY_ORDER, default=[])
    with filter_columns[1]:
        rule_options = [""] + [entry["rule_id"] for entry in kpis.get("rule_counts", [])]
        rule_filter = st.selectbox("Rule", rule_options, format_func=lambda v: v or "All rules")
    with filter_columns[2]:
        supplier_options = [""] + sorted({row["supplier_id"] for row in supplier_rows
                                          if row.get("findings_count")})
        supplier_filter = st.selectbox(
            "Supplier", supplier_options, format_func=lambda v: v or "All suppliers"
        )
    with filter_columns[3]:
        po_filter = st.text_input("Purchase order", placeholder="e.g. 4500123")

    try:
        findings_payload = client.findings(
            analysis["analysis_id"],
            severity=severity_filter or None,
            rule_id=rule_filter or None,
            supplier_id=supplier_filter or None,
            po_number=po_filter.strip() or None,
            limit=500,
        )
        findings = findings_payload["findings"]
        st.caption(
            f"Showing {len(findings)} of {findings_payload['total']} matching findings. "
            "Every row is rule-based; the AI column is optional commentary."
        )
        if findings:
            st.dataframe(findings_dataframe(findings), use_container_width=True, height=420)
            with st.expander("Inspect one finding in full"):
                labels = {
                    f"{f['severity'].upper()} · {f['rule_id']} · PO {f['po_number']}": f
                    for f in findings[:200]
                }
                chosen = st.selectbox("Finding", list(labels))
                st.json(labels[chosen])
        else:
            st.info("No findings match the current filters.")
    except ApiError as error:
        show_error(error.message, error.details)

    # -----------------------------------------------------------------------
    # 11. Export
    # -----------------------------------------------------------------------
    st.header("6. Download the report")
    export_columns = st.columns(3)
    export_specs = [
        ("Excel workbook (.xlsx)", "xlsx", MEDIA_TYPES[".xlsx"]),
        ("Findings (.csv)", "csv", "text/csv"),
        ("Full payload (.json)", "json", "application/json"),
    ]
    for column, (label, export_format, media_type) in zip(export_columns, export_specs):
        with column:
            try:
                st.download_button(
                    label,
                    data=client.export(analysis["analysis_id"], export_format),
                    file_name=f"po_risk_report_{analysis['analysis_id'][:8]}.{export_format}",
                    mime=media_type,
                    use_container_width=True,
                )
            except ApiError as error:
                st.warning(error.message)

    # -----------------------------------------------------------------------
    # Methodology
    # -----------------------------------------------------------------------
    st.header("7. Technical methodology")
    with st.expander("How findings are produced", expanded=False):
        methodology = analysis.get("methodology", {})
        st.markdown(
            f"""
**Pipeline** - the file is validated (extension, size, magic bytes), parsed, mapped onto
{len(analysis['applied_mapping'])} canonical fields, type-checked, and then evaluated by the rule
engine. Values are converted into the base currency (**{methodology.get('base_currency')}**) before
any comparison so orders in different currencies are comparable.

**Risk determination** - {methodology.get('risk_determination')}.
Rule configuration version **{methodology.get('config_version')}**,
engine version **{methodology.get('engine_version')}**.

**Risk score** - {methodology.get('risk_score_method')}.

**Estimated exposure** - {methodology.get('exposure_note')}

**AI role** - {methodology.get('ai_role')}.

**Disclaimer** - {methodology.get('data_disclaimer')}
            """
        )
        st.write("**Approval thresholds:**", methodology.get("approval_thresholds"))
        st.write("**Currency rates used:**")
        st.json(methodology.get("currency_rates", {}))

    with st.expander("Rule catalogue and configured thresholds"):
        try:
            catalogue = pd.DataFrame(client.rules())
            st.dataframe(
                catalogue.rename(
                    columns={
                        "rule_id": "Rule", "name": "Name", "category": "Category",
                        "enabled": "Enabled", "base_severity": "Base severity",
                        "confidence": "Confidence", "params": "Thresholds",
                        "recommended_action": "Recommended action",
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )
            st.caption(
                "Thresholds live in `app/modules/po_risk/config/po_risk_rules.json`. "
                "Change a value there and the next analysis uses it - no code change needed."
            )
        except ApiError as error:
            show_error(error.message)

    with st.expander("Column mapping actually applied"):
        st.json(analysis["applied_mapping"])
        if analysis.get("unmapped_columns"):
            st.write("**Ignored source columns:**", analysis["unmapped_columns"])

disclaimer()
