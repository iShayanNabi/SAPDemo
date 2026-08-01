"""Streamlit page for the Supplier Recommendation Engine.

Like every page in this app it contains no business logic: it uploads a supplier
catalogue, collects a requirement and weights, and calls the FastAPI backend.
The deterministic scoring, eligibility and ranking all happen server-side.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
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

st.set_page_config(page_title="Supplier Recommendation Engine", page_icon="🤝", layout="wide")

client = ApiClient()

DIMENSIONS = [
    ("cost", "Cost"), ("delivery", "Delivery"), ("quality", "Quality"),
    ("capacity", "Capacity"), ("risk", "Risk"), ("esg", "ESG"),
    ("contract", "Contract"), ("geographic", "Geographic"),
    ("past_performance", "Past performance"),
]
SCORE_KEYS = [f"{key}_score" for key, _ in DIMENSIONS]

st.title("Supplier Recommendation Engine")
demo_banner(client)
explain_module("supplier_recommendation")
st.write(
    "Rank eligible suppliers for a purchasing requirement with a transparent, deterministic "
    "weighted-scoring model. AI, when enabled, only summarises the ranking - it never decides it."
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


# ---------------------------------------------------------------------------
# 1. Supplier catalogue
# ---------------------------------------------------------------------------
st.header("1. Supplier catalogue")

col_upload, col_sample = st.columns(2)
with col_upload:
    if not uploads_enabled(client):
        upload_disabled_notice("file")
    else:
        uploaded = st.file_uploader(
            "Upload a supplier master file (CSV, XLSX or JSON)", type=["csv", "xlsx", "json"]
        )
        if uploaded is not None and st.button("Load catalogue", type="primary"):
            try:
                result = client.supplier_upload(uploaded.name, uploaded.getvalue(), uploaded.type or "text/csv")
                if result.get("missing_required_fields"):
                    show_error(
                        "The file is missing required fields.",
                        {"missing_required_fields": result["missing_required_fields"]},
                    )
                else:
                    st.session_state["catalog_id"] = result["catalog_id"]
                    st.success(f"Loaded {result['supplier_count']} suppliers.")
            except ApiError as error:
                show_error(error.message, error.details)

with col_sample:
    st.caption("No file handy? Load the bundled fictional demo catalogue.")
    # Loaded server-side from data/sample/ rather than downloaded and posted
    # back: the round trip was an upload, and a public demonstration refuses
    # uploads - including this page's own demo button.
    loaded = load_demo_button(
        "supplier_recommendation", label="Use the demo catalogue", key="reco_demo"
    )
    if loaded:
        st.session_state["catalog_id"] = loaded["analyze_payload"]["catalog_id"]
        st.success(
            f"Loaded {loaded['datasets'][0]['row_count']} demo suppliers. "
            "Demo data - fictional, not from SAP."
        )

catalog_id = st.session_state.get("catalog_id")
if not catalog_id:
    st.info("Upload a supplier file or load the demo catalogue to begin.", icon="👆")
    disclaimer()
    st.stop()

try:
    supplier_list = client.suppliers(catalog_id=catalog_id, limit=1000)
    st.caption(f"Active catalogue `{catalog_id}` with {supplier_list['total']} suppliers.")
except ApiError as error:
    show_error(error.message, error.details)
    st.stop()


# ---------------------------------------------------------------------------
# 2. Requirement
# ---------------------------------------------------------------------------
st.header("2. Purchasing requirement")

with st.form("requirement_form"):
    c1, c2, c3 = st.columns(3)
    with c1:
        material = st.text_input("Material", value="MAT-1000")
        material_description = st.text_input("Material description", value="")
        material_group = st.text_input("Material group", value="")
        quantity = st.number_input("Quantity", min_value=0.0, value=100.0, step=1.0)
        unit_of_measure = st.text_input("Unit of measure", value="PC")
    with c2:
        plant = st.text_input("Plant", value="1010")
        company_code = st.text_input("Company code", value="1000")
        required_delivery_date = st.date_input("Required delivery date", value=date.today() + timedelta(days=60))
        order_date = st.date_input("Planned order date", value=date.today())
        preferred_region = st.text_input("Preferred region", value="EU")
    with c3:
        target_price = st.number_input("Target price (per unit)", min_value=0.0, value=120.0, step=1.0)
        currency = st.text_input("Currency", value="EUR")
        risk_tolerance = st.selectbox("Risk tolerance", ["low", "medium", "high"], index=1)
        contract_requirement = st.checkbox("Require an active contract", value=False)
        sustainability_requirement = st.number_input(
            "Minimum ESG score (0 = no requirement)", min_value=0.0, max_value=100.0, value=0.0
        )
    c4, c5 = st.columns(2)
    with c4:
        minimum_quality_score = st.number_input(
            "Minimum quality score (0 = no requirement)", min_value=0.0, max_value=100.0, value=0.0
        )
    with c5:
        minimum_available_capacity = st.number_input(
            "Minimum available capacity (0 = no requirement)", min_value=0.0, value=0.0, step=1.0
        )
    submitted_requirement = st.form_submit_button("Save requirement")

requirement = {
    "material": material or None,
    "material_description": material_description or None,
    "material_group": material_group or None,
    "quantity": quantity or None,
    "unit_of_measure": unit_of_measure or None,
    "plant": plant or None,
    "company_code": company_code or None,
    "required_delivery_date": required_delivery_date.isoformat() if required_delivery_date else None,
    "order_date": order_date.isoformat() if order_date else None,
    "target_price": target_price or None,
    "currency": currency or None,
    "preferred_region": preferred_region or None,
    "risk_tolerance": risk_tolerance,
    "sustainability_requirement": sustainability_requirement or None,
    "contract_requirement": contract_requirement,
    "minimum_quality_score": minimum_quality_score or None,
    "minimum_available_capacity": minimum_available_capacity or None,
}


# ---------------------------------------------------------------------------
# 3. Weights
# ---------------------------------------------------------------------------
st.header("3. Scoring weights")
st.caption("Set the importance of each dimension. The weights must sum to 100%.")

try:
    scoring = client.supplier_scoring()
    default_weights = scoring["default_weights"]
except ApiError:
    default_weights = {key: 0.0 for key, _ in DIMENSIONS}

weight_cols = st.columns(3)
weights: dict[str, float] = {}
for index, (key, label) in enumerate(DIMENSIONS):
    with weight_cols[index % 3]:
        weights[key] = st.number_input(
            f"{label} %", min_value=0.0, max_value=100.0,
            value=float(default_weights.get(key, 0.0)), step=1.0, key=f"w_{key}",
        )

weight_total = round(sum(weights.values()), 2)
if abs(weight_total - 100.0) < 0.01:
    st.success(f"Weights sum to {weight_total:g}% ✓")
    weights_valid = True
else:
    st.error(f"Weights sum to {weight_total:g}% - they must total 100% before you can run a recommendation.")
    weights_valid = False

with st.expander("How each dimension is scored"):
    try:
        for dim in scoring["dimensions"]:
            st.markdown(f"**{dim['label']}** (default {dim['default_weight']:g}%): {dim['formula']}")
        st.caption(scoring["normalization"])
    except (KeyError, NameError):
        st.caption("Scoring documentation is unavailable.")


# ---------------------------------------------------------------------------
# 4. Run
# ---------------------------------------------------------------------------
st.header("4. Recommendation")
generate_ai = st.checkbox("Generate an AI summary of the ranking", value=True)
top_n = st.slider("Show top N eligible suppliers", min_value=1, max_value=25, value=10)

if st.button("Recommend suppliers", type="primary", disabled=not weights_valid):
    try:
        recommendation = client.recommend_suppliers(
            requirement,
            catalog_id=catalog_id,
            weights=weights,
            top_n=top_n,
            generate_ai_summary=generate_ai,
        )
        st.session_state["recommendation"] = recommendation
    except ApiError as error:
        show_error(error.message, error.details)

recommendation = st.session_state.get("recommendation")
if not recommendation:
    disclaimer()
    st.stop()

currency_base = recommendation["base_currency"]
results = recommendation["results"]
eligible = [entry for entry in results if entry["is_eligible"]]
ineligible = [entry for entry in results if not entry["is_eligible"]]

m1, m2, m3, m4 = st.columns(4)
m1.metric("Suppliers assessed", recommendation["total_supplier_count"])
m2.metric("Eligible", recommendation["eligible_count"])
m3.metric("Ineligible", recommendation["ineligible_count"])
m4.metric("Top supplier", recommendation["top_supplier_id"] or "-")

st.caption(f"Rule-based ranking · scoring engine v{recommendation['scoring_engine_version']}")

# --- AI recommendation explanation -----------------------------------------
narrative = recommendation.get("ai_narrative") or {}
if narrative.get("summary"):
    st.subheader("Recommendation summary")
    st.info(f"{narrative['summary']}\n\n_Origin: {origin_badge(narrative.get('origin'))}_")
    if narrative.get("recommended_actions"):
        for action in narrative["recommended_actions"]:
            st.markdown(f"- {action}")

# --- Ranked cards ----------------------------------------------------------
st.subheader("Ranked suppliers")
for entry in eligible[:top_n]:
    with st.container(border=True):
        header = f"**#{entry['rank']} · {entry['supplier_name'] or entry['supplier_id']}** "
        header += f"({entry['supplier_id']}) — overall **{entry['overall_score']:g}/100**"
        st.markdown(header)
        cc1, cc2, cc3 = st.columns(3)
        cc1.metric("Estimated total cost", format_currency(entry.get("estimated_total_cost_base"), currency_base))
        cc2.metric("Estimated delivery", entry.get("estimated_delivery_date") or "-")
        cc3.metric("Contract", entry.get("contract_classification") or "-")
        if entry.get("explanation"):
            st.caption(entry["explanation"])
        adv_col, risk_col = st.columns(2)
        with adv_col:
            if entry.get("advantages"):
                st.markdown("**Advantages**")
                for item in entry["advantages"]:
                    st.markdown(f"- ✅ {item}")
        with risk_col:
            if entry.get("risks"):
                st.markdown("**Risks**")
                for item in entry["risks"]:
                    st.markdown(f"- ⚠️ {item}")

# --- Comparison table ------------------------------------------------------
st.subheader("Comparison table")
table_rows = []
for entry in results:
    row = {
        "Rank": entry["rank"] if entry["rank"] is not None else "-",
        "Supplier": entry["supplier_name"] or entry["supplier_id"],
        "Eligibility": entry["eligibility_status"],
        "Overall": entry["overall_score"],
    }
    for key, label in DIMENSIONS:
        row[label] = entry[f"{key}_score"]
    row["Est. total cost"] = entry.get("estimated_total_cost_base")
    row["Est. delivery"] = entry.get("estimated_delivery_date")
    table_rows.append(row)
st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

# --- Score breakdown + radar chart -----------------------------------------
st.subheader("Score breakdown")
if eligible:
    choices = {f"#{e['rank']} {e['supplier_name'] or e['supplier_id']}": e for e in eligible[:top_n]}
    picked = st.multiselect(
        "Compare suppliers on the radar chart",
        list(choices.keys()),
        default=list(choices.keys())[: min(3, len(choices))],
    )
    categories = [label for _, label in DIMENSIONS]
    figure = go.Figure()
    for name in picked:
        entry = choices[name]
        values = [entry[f"{key}_score"] for key, _ in DIMENSIONS]
        figure.add_trace(
            go.Scatterpolar(
                r=values + values[:1],
                theta=categories + categories[:1],
                fill="toself",
                name=name,
            )
        )
    figure.update_layout(
        polar={"radialaxis": {"visible": True, "range": [0, 100]}},
        showlegend=True,
        height=480,
    )
    st.plotly_chart(figure, use_container_width=True)

    breakdown = pd.DataFrame(
        [{"Supplier": choices[name]["supplier_name"] or choices[name]["supplier_id"],
          **{label: choices[name][f"{key}_score"] for key, label in DIMENSIONS}}
         for name in picked]
    )
    if not breakdown.empty:
        st.dataframe(breakdown, use_container_width=True, hide_index=True)

# --- Ineligible suppliers --------------------------------------------------
if ineligible:
    with st.expander(f"Ineligible suppliers ({len(ineligible)})"):
        for entry in ineligible:
            reasons = "; ".join(entry.get("ineligibility_reasons", []))
            st.markdown(f"- **{entry['supplier_name'] or entry['supplier_id']}**: {reasons}")

# --- Export controls -------------------------------------------------------
st.subheader("Export")
rec_id = recommendation["recommendation_id"]
ec1, ec2, ec3 = st.columns(3)
for column, fmt, mime in (
    (ec1, "xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    (ec2, "csv", "text/csv"),
    (ec3, "json", "application/json"),
):
    with column:
        try:
            data = client.recommendation_export(rec_id, fmt)
            st.download_button(
                f"Download {fmt.upper()}", data=data,
                file_name=f"supplier_recommendation_{rec_id[:8]}.{fmt}", mime=mime,
            )
        except ApiError as error:
            st.caption(f"{fmt.upper()} export unavailable: {error.message}")

st.caption(recommendation.get("disclaimer", ""))
disclaimer()
