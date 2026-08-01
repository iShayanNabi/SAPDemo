"""Streamlit page for the Invoice Validator.

Like every page in this app it contains no business logic: it uploads three
files (invoices, purchase orders, goods receipts), collects tolerances and calls
the FastAPI backend. All three-way matching and every exception decision happen
server-side.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

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
    format_currency,
    origin_badge,
    show_error,
)

st.set_page_config(page_title="Invoice Validator", page_icon="🧾", layout="wide")

client = ApiClient()

SEVERITY_COLORS = {"critical": "#B3261E", "high": "#E8710A", "medium": "#F2C037", "low": "#3B8C4E"}

DATASETS = [
    ("invoices", "Invoices", "🧾"),
    ("purchase_orders", "Purchase orders", "📄"),
    ("goods_receipts", "Goods receipts", "📦"),
]

st.title("Invoice Validator")
demo_banner(client)
explain_module("invoice_validator")
st.write(
    "Validate invoices against purchase orders and goods receipts with a transparent, deterministic "
    "three-way match. AI, when enabled, only summarises the exceptions - it never decides them."
)

with st.sidebar:
    st.header("Backend status")
    try:
        health = client.health()
        st.success(f"API reachable ({health['status']})")
        st.write(f"**AI provider:** {health['ai_provider']}" + (" (mock)" if health["ai_is_mock"] else ""))
    except ApiError as error:
        st.error(error.message)
        st.stop()


def _dataset_field_names(catalogue: dict, dataset: str) -> list[str]:
    return [""] + [f["name"] for f in catalogue.get(dataset, [])]


# ---------------------------------------------------------------------------
# 1. Upload the three files
# ---------------------------------------------------------------------------
st.header("1. Upload files")
st.caption("The invoice file is required. Purchase orders and goods receipts are optional but power the match.")

uploads = st.session_state.setdefault("iv_uploads", {})

col_load_demo, _ = st.columns([1, 3])
with col_load_demo:
    # All three datasets in one server-side load. The previous version
    # downloaded each sample and posted it back, which is an upload, and a
    # public demonstration refuses uploads - including its own demo button.
    loaded = load_demo_button(
        "invoice_validator", label="Load the demo datasets", key="iv_demo"
    )
    if loaded:
        for dataset, result in loaded["uploads"].items():
            uploads[dataset] = result
        st.success("Loaded the three demo datasets. Demo data - fictional, not from SAP.")

if not uploads_enabled(client):
    upload_disabled_notice("file")

upload_cols = st.columns(3)
for (dataset, label, icon), column in zip(DATASETS, upload_cols):
    with column:
        st.subheader(f"{icon} {label}")
        if uploads_enabled(client):
            picked = st.file_uploader(
                f"{label} file (CSV, XLSX, JSON)", type=["csv", "xlsx", "json"], key=f"file_{dataset}"
            )
            if picked is not None and st.button(f"Upload {label.lower()}", key=f"btn_{dataset}"):
                try:
                    result = client.invoice_upload(dataset, picked.name, picked.getvalue(), picked.type or "text/csv")
                    uploads[dataset] = result
                    st.success(f"Uploaded {result['row_count']} rows.")
                except ApiError as error:
                    show_error(error.message, error.details)
        current = uploads.get(dataset)
        if current:
            st.caption(f"`{current['upload_id'][:8]}` · {current['row_count']} rows")
            if current.get("missing_required_fields"):
                st.warning("Missing required: " + ", ".join(current["missing_required_fields"]))

if "invoices" not in uploads:
    st.info("Load the demo datasets to begin.", icon="👆")
    disclaimer()
    st.stop()


# ---------------------------------------------------------------------------
# 2. Previews and mapping screens
# ---------------------------------------------------------------------------
st.header("2. Previews and column mapping")
try:
    catalogue = client.invoice_fields()
except ApiError:
    catalogue = {"invoices": [], "purchase_orders": [], "goods_receipts": []}

mapping_overrides: dict[str, dict[str, str]] = {}
for dataset, label, icon in DATASETS:
    current = uploads.get(dataset)
    if not current:
        continue
    with st.expander(f"{icon} {label} — preview & mapping ({current['row_count']} rows)"):
        if current.get("preview_rows"):
            st.dataframe(pd.DataFrame(current["preview_rows"]), use_container_width=True, hide_index=True)
        st.markdown("**Column mapping** (auto-detected; adjust if needed)")
        field_names = _dataset_field_names(catalogue, dataset)
        suggested = current.get("suggested_mapping", {})
        overrides: dict[str, str] = {}
        cols = st.columns(3)
        for index, source in enumerate(current.get("detected_columns", [])):
            with cols[index % 3]:
                default = suggested.get(source, "")
                choice = st.selectbox(
                    source,
                    field_names,
                    index=field_names.index(default) if default in field_names else 0,
                    key=f"map_{dataset}_{source}",
                )
                if choice != suggested.get(source, ""):
                    overrides[source] = choice
        if overrides:
            mapping_overrides[dataset] = overrides


# ---------------------------------------------------------------------------
# 3. Tolerance settings
# ---------------------------------------------------------------------------
st.header("3. Tolerance settings")
try:
    rule_catalogue = client.invoice_rules()
    default_tol = rule_catalogue["tolerances"]
except ApiError:
    rule_catalogue, default_tol = {}, {"price": {}, "quantity": {}, "tax": {}, "freight": {}}

st.caption("A deviation is flagged only when it exceeds both the percentage and the absolute allowance.")
tolerances: dict[str, dict[str, float]] = {}
tol_cols = st.columns(4)
for column, key in zip(tol_cols, ["price", "quantity", "tax", "freight"]):
    with column:
        st.markdown(f"**{key.title()}**")
        pct = st.number_input(
            f"{key} %", min_value=0.0, value=float(default_tol.get(key, {}).get("pct", 0.0)),
            step=0.5, key=f"tol_pct_{key}",
        )
        absolute = st.number_input(
            f"{key} abs", min_value=0.0, value=float(default_tol.get(key, {}).get("abs", 0.0)),
            step=0.5, key=f"tol_abs_{key}",
        )
        tolerances[key] = {"pct": pct, "abs": absolute}


# ---------------------------------------------------------------------------
# 4. Validate
# ---------------------------------------------------------------------------
st.header("4. Validate")
c1, c2 = st.columns(2)
with c1:
    as_of = st.date_input("Validation reference date (for the future-date check)", value=date(2026, 6, 30))
with c2:
    generate_ai = st.checkbox("Generate an AI summary of the exceptions", value=True)

if st.button("Run validation", type="primary"):
    try:
        result = client.invoice_validate(
            uploads["invoices"]["upload_id"],
            po_upload_id=uploads.get("purchase_orders", {}).get("upload_id"),
            gr_upload_id=uploads.get("goods_receipts", {}).get("upload_id"),
            invoice_mapping_overrides=mapping_overrides.get("invoices"),
            po_mapping_overrides=mapping_overrides.get("purchase_orders"),
            gr_mapping_overrides=mapping_overrides.get("goods_receipts"),
            tolerances=tolerances,
            as_of_date=as_of.isoformat() if as_of else None,
            generate_ai_summary=generate_ai,
        )
        st.session_state["iv_validation"] = result
    except ApiError as error:
        show_error(error.message, error.details)

validation = st.session_state.get("iv_validation")
if not validation:
    disclaimer()
    st.stop()

validation_id = validation["validation_id"]
currency = validation["base_currency"]
kpis = validation.get("kpis", {})


# ---------------------------------------------------------------------------
# 5. Summary metrics
# ---------------------------------------------------------------------------
st.header("5. Results")
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Invoices", validation["invoice_count"])
m2.metric("Exceptions", validation["exceptions_count"])
m3.metric("Critical / High", f"{validation['critical_count']} / {validation['high_count']}")
m4.metric("Fully matched", kpis.get("fully_three_way_matched", "-"))
m5.metric("Exposure", format_currency(validation["estimated_exposure"], currency))

st.caption(
    f"Deterministic three-way match · engine v{validation['engine_version']} · "
    f"{kpis.get('exposure_note', '')}"
)

if validation.get("rule_errors"):
    st.warning(f"{len(validation['rule_errors'])} rule(s) reported an error; the others still ran.")

skipped = [e for e in validation.get("rule_executions", []) if e.get("skipped_reason") not in (None, "disabled")]
if skipped:
    st.info(
        "Skipped rules (missing dataset): "
        + ", ".join(f"{e['rule_id']} ({e['skipped_reason']})" for e in skipped)
    )

narrative = validation.get("ai_narrative") or {}
if narrative.get("summary"):
    st.subheader("Exception summary")
    st.info(f"{narrative['summary']}\n\n_Origin: {origin_badge(narrative.get('origin'))}_")
    for action in narrative.get("recommended_actions", []):
        st.markdown(f"- {action}")


# ---------------------------------------------------------------------------
# 6. Exception charts
# ---------------------------------------------------------------------------
st.subheader("Exception charts")
chart_cols = st.columns(2)
severity_counts = kpis.get("severity_counts", {})
if severity_counts:
    sev_df = pd.DataFrame(
        [{"Severity": k, "Count": v} for k, v in severity_counts.items() if v]
    )
    if not sev_df.empty:
        fig = px.bar(sev_df, x="Severity", y="Count", color="Severity",
                     color_discrete_map=SEVERITY_COLORS, title="Exceptions by severity")
        chart_cols[0].plotly_chart(fig, use_container_width=True)
rule_counts = kpis.get("rule_counts", [])
if rule_counts:
    rule_df = pd.DataFrame(rule_counts).sort_values("count", ascending=True)
    fig = px.bar(rule_df, x="count", y="rule_name", orientation="h", title="Exceptions by rule")
    chart_cols[1].plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# 7. Filters + exception table
# ---------------------------------------------------------------------------
st.subheader("Exceptions")
f1, f2, f3 = st.columns(3)
severity_filter = f1.multiselect("Severity", ["critical", "high", "medium", "low"])
rule_options = sorted({r["rule_id"] for r in rule_counts}) if rule_counts else []
rule_filter = f2.selectbox("Rule", ["(all)"] + rule_options)
supplier_filter = f3.text_input("Supplier ID contains")

try:
    exceptions = client.invoice_exceptions(
        validation_id,
        severity=severity_filter or None,
        rule_id=None if rule_filter == "(all)" else rule_filter,
        supplier_id=supplier_filter or None,
        limit=1000,
    )["exceptions"]
except ApiError as error:
    show_error(error.message, error.details)
    exceptions = []

if exceptions:
    table = pd.DataFrame([
        {
            "Severity": e["severity"].upper(),
            "Rule": e["rule_id"],
            "Type": e["exception_type"],
            "Invoice": e["invoice_number"],
            "Supplier": e["supplier_id"],
            "PO": e["po_number"],
            "Item": e["po_item"],
            "GR": e["gr_number"],
            "Expected": e["expected_value"],
            "Actual": e["actual_value"],
            "Difference": e["difference"],
            "Diff amount": e["difference_amount"],
            "Explanation": e["explanation"],
            "Recommended action": e["recommended_action"],
        }
        for e in exceptions
    ])
    st.dataframe(table, use_container_width=True, hide_index=True)
    st.caption(f"{len(exceptions)} exception(s) shown.")
else:
    st.success("No exceptions match the current filters.")


# ---------------------------------------------------------------------------
# 8. Three-way-match comparison
# ---------------------------------------------------------------------------
st.subheader("Three-way-match comparison")
matches = validation.get("three_way_matches", [])
if matches:
    status_filter = st.multiselect(
        "Status", ["matched", "exception", "unmatched"], default=["exception", "unmatched"]
    )
    filtered = [m for m in matches if not status_filter or m["status"] in status_filter]
    if filtered:
        match_df = pd.DataFrame([
            {
                "Invoice": m["invoice_number"],
                "Supplier": m["supplier_id"],
                "PO": m["po_number"],
                "Item": m["po_item"],
                "Inv qty": m["invoice_quantity"],
                "PO qty": m["po_quantity"],
                "Received": m["received_quantity"],
                "Accepted": m["accepted_quantity"],
                "Inv price": m["invoice_unit_price"],
                "PO price": m["po_unit_price"],
                "Matched PO": m["matched_po"],
                "Matched GR": m["matched_gr"],
                "Exceptions": m["exception_count"],
                "Status": m["status"],
            }
            for m in filtered[:500]
        ])
        st.dataframe(match_df, use_container_width=True, hide_index=True)
        st.caption(f"Showing {len(match_df)} of {len(matches)} invoice line(s).")
    else:
        st.caption("No invoice lines match the selected status.")


# ---------------------------------------------------------------------------
# 9. Supplier summary + export
# ---------------------------------------------------------------------------
supplier_summary = validation.get("supplier_summary", [])
if supplier_summary:
    with st.expander("Supplier summary"):
        st.dataframe(pd.DataFrame(supplier_summary), use_container_width=True, hide_index=True)

st.subheader("Export")
ec1, ec2, ec3 = st.columns(3)
for column, fmt, mime in (
    (ec1, "xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    (ec2, "csv", "text/csv"),
    (ec3, "json", "application/json"),
):
    with column:
        try:
            data = client.invoice_export(validation_id, fmt)
            st.download_button(
                f"Download {fmt.upper()}", data=data,
                file_name=f"invoice_validation_{validation_id[:8]}.{fmt}", mime=mime,
            )
        except ApiError as error:
            st.caption(f"{fmt.upper()} export unavailable: {error.message}")

st.caption(validation.get("disclaimer", ""))
disclaimer()
