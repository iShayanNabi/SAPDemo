"""Streamlit page for the Inventory Predictor.

Like every page in this app it contains no business logic: it uploads the
inventory history, asks the FastAPI backend to forecast it, and renders what
comes back. Every forecast value, confidence bound, projected stock level,
shortage date, reorder quantity and accuracy metric is computed server-side by
the statistical models in ``app/modules/inventory``.

**No number on this page was produced by an AI model.** The optional narrative
is clearly labelled and lives in its own section.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from streamlit_app.components.api_client import ApiClient, ApiError  # noqa: E402
from streamlit_app.components.ui import disclaimer, origin_badge, show_error  # noqa: E402

st.set_page_config(page_title="Inventory Predictor", page_icon="📦", layout="wide")

client = ApiClient()

MODEL_OPTIONS = {
    "auto": "Automatic (chosen per material by backtesting)",
    "simple_moving_average": "Simple moving average",
    "weighted_moving_average": "Weighted moving average",
    "simple_exponential_smoothing": "Simple exponential smoothing",
    "holt_linear_trend": "Holt linear trend",
    "holt_winters_seasonal": "Holt-Winters additive seasonal",
}

URGENCY_ICONS = {"immediate": "🔴", "scheduled": "🟡", "not_required": "🟢"}
OVERSTOCK_ICONS = {"high": "🔴", "medium": "🟠", "none": "🟢"}
SEVERITY_ICONS = {"high": "🔴", "warning": "🟠", "info": "🔵"}

st.title("Inventory Predictor")
st.write(
    "Forecast demand from an inventory history with explainable statistical models, project the "
    "stock level forward day by day, and get a reorder plan. The model is chosen per material by "
    "backtesting it on periods it has not seen, and every figure comes with the assumptions "
    "behind it."
)
st.caption(
    "Forecasts are statistical estimates with a stated confidence range, not commitments. "
    "No language model produces any number on this page."
)

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
# Formatting helpers (no forecasting logic lives here)
# ---------------------------------------------------------------------------
def _number(value: Any, decimals: int = 1) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):,.{decimals}f}"
    except (TypeError, ValueError):
        return str(value)


def _plain(value: Any) -> str:
    if value is None or value == "":
        return "-"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def _metric_or_dash(value: Any, suffix: str = "") -> str:
    return "-" if value is None else f"{_number(value)}{suffix}"


def _item_label(item: dict[str, Any]) -> str:
    description = item.get("material_description") or ""
    location = f"/{item['storage_location']}" if item.get("storage_location") else ""
    return f"{item['material']} @ {item['plant']}{location} — {description}"


# ---------------------------------------------------------------------------
# 1. Upload
# ---------------------------------------------------------------------------
st.header("1. Load an inventory history")

sample_col, upload_col = st.columns([1, 2])

with sample_col:
    try:
        sample = client.inventory_sample_info()
    except ApiError:
        sample = {"available": False}

    if sample.get("available"):
        st.caption(
            f"Demo dataset ({origin_badge('demo_data')}): {sample.get('row_count', 0):,} rows, "
            f"{sample.get('series_count') or '-'} material/plant series, "
            f"{sample.get('period_count') or '-'} monthly periods "
            f"({sample.get('history_start')} to {sample.get('history_end')})."
        )
        for file_format in ("csv", "xlsx", "json"):
            try:
                payload = client.inventory_sample_file(file_format)
            except ApiError as error:
                # Say which format is unavailable and why. A button that
                # silently fails to appear looks like a page that is still
                # loading, and the user waits for it.
                st.caption(f"Demo .{file_format} is unavailable: {error.message}")
                continue
            st.download_button(
                f"Download demo .{file_format}",
                data=payload,
                file_name=f"sample_inventory_history.{file_format}",
                key=f"inv_sample_{file_format}",
            )
    else:
        st.caption(
            "No demo dataset yet. Generate it with: "
            "`python scripts/generate_inventory_sample_data.py`"
        )

with upload_col:
    uploaded = st.file_uploader(
        "Inventory history (CSV, XLSX or JSON)",
        type=["csv", "xlsx", "json"],
        key="inventory_upload",
        help=(
            "One row per material, plant and period, with the demand for that period. "
            "Stock levels, lead times, reorder points, safety stock, supplier and open "
            "purchase-order columns are all optional and each adds to what can be reported."
        ),
    )
    if uploaded is not None and st.button("Load file", type="primary"):
        try:
            with st.spinner("Reading the history and detecting the period granularity..."):
                st.session_state["inventory_dataset"] = client.inventory_upload(
                    uploaded.name, uploaded.getvalue(), uploaded.type or "text/csv"
                )
            st.session_state.pop("inventory_forecast", None)
        except ApiError as error:
            show_error(error.message, error.details)

dataset = st.session_state.get("inventory_dataset")

if dataset:
    if not dataset.get("is_analyzable"):
        st.error(
            "The file is missing required columns: "
            + ", ".join(dataset.get("missing_required_fields", []))
        )
        st.caption(
            "A forecast needs at least a material, a plant, a date and a demand quantity."
        )
    else:
        columns = st.columns(5)
        columns[0].metric("Rows", f"{dataset['row_count']:,}")
        columns[1].metric("Material/plant series", dataset.get("series_count", 0))
        columns[2].metric("Materials", dataset.get("material_count", 0))
        columns[3].metric("Plants", dataset.get("plant_count", 0))
        columns[4].metric("Period", (dataset.get("frequency") or "-").title())
        st.caption(
            f"History runs {dataset.get('history_start')} to {dataset.get('history_end')}. "
            "The period granularity was inferred from the gaps between the dates in the file."
        )

    with st.expander("Column mapping and preview"):
        st.write("**Mapped columns**")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Source column": item["source_column"],
                        "Mapped to": item["canonical_field"],
                        "Confidence": item["confidence"],
                        "How": item["strategy"],
                    }
                    for item in dataset.get("suggestions", [])
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )
        if dataset.get("unmapped_columns"):
            st.caption("Ignored columns: " + ", ".join(dataset["unmapped_columns"]))
        st.write("**First rows**")
        st.dataframe(pd.DataFrame(dataset.get("preview", [])), use_container_width=True)

    if dataset.get("data_quality_issues"):
        with st.expander(
            f"Data-quality warnings from the file ({len(dataset['data_quality_issues'])})",
            expanded=False,
        ):
            for issue in dataset["data_quality_issues"]:
                icon = SEVERITY_ICONS.get(issue.get("severity", "warning"), "🟠")
                st.write(f"{icon} **{issue['issue_type']}** — {issue['message']}")
                if issue.get("sample_rows"):
                    st.caption(
                        "Example rows: "
                        + ", ".join(str(row) for row in issue["sample_rows"][:10])
                    )


# ---------------------------------------------------------------------------
# 2. Forecast settings
# ---------------------------------------------------------------------------
if dataset and dataset.get("is_analyzable"):
    st.header("2. Forecast settings")

    try:
        methods = client.inventory_methods()
    except ApiError:
        methods = {}

    available_levels = (methods.get("forecast", {}) or {}).get(
        "available_confidence_levels", [0.8, 0.9, 0.95, 0.99]
    )
    default_horizon = (methods.get("forecast", {}) or {}).get("default_horizon_periods", 6)
    max_horizon = (methods.get("forecast", {}) or {}).get("max_horizon_periods", 36)

    series_options = dataset.get("series", [])
    materials = sorted({item["material"] for item in series_options})
    plants = sorted({item["plant"] for item in series_options})

    setting_columns = st.columns(4)
    horizon = setting_columns[0].slider(
        "Forecast horizon (periods)", 1, int(max_horizon), int(default_horizon)
    )
    confidence = setting_columns[1].select_slider(
        "Confidence level",
        options=available_levels,
        value=0.95 if 0.95 in available_levels else available_levels[-1],
        format_func=lambda value: f"{float(value):.0%}",
    )
    model_choice = setting_columns[2].selectbox(
        "Model",
        options=list(MODEL_OPTIONS),
        format_func=lambda key: MODEL_OPTIONS[key],
        help=(
            "Automatic backtests every eligible method per material and picks the winner. "
            "A forced method that cannot be applied to a material falls back to automatic "
            "selection for that material and says so."
        ),
    )
    generate_narrative = setting_columns[3].checkbox(
        "Add AI narrative",
        value=False,
        help="Explains the computed results in business language. It never produces a number.",
    )

    filter_columns = st.columns(2)
    material_filter = filter_columns[0].multiselect("Materials (all if empty)", materials)
    plant_filter = filter_columns[1].multiselect("Plants (all if empty)", plants)

    if st.button("Run forecast", type="primary"):
        try:
            with st.spinner("Backtesting the models and projecting the stock..."):
                st.session_state["inventory_forecast"] = client.inventory_forecast(
                    dataset_id=dataset["dataset_id"],
                    horizon_periods=horizon,
                    confidence_level=float(confidence),
                    model=model_choice,
                    materials=material_filter or None,
                    plants=plant_filter or None,
                    generate_ai_summary=generate_narrative,
                )
        except ApiError as error:
            show_error(error.message, error.details)


# ---------------------------------------------------------------------------
# 3. Results
# ---------------------------------------------------------------------------
run = st.session_state.get("inventory_forecast")

if run:
    summary = run["summary"]
    st.header("3. Results")

    kpi = st.columns(6)
    kpi[0].metric("Materials forecast", f"{summary['forecast_count']}/{summary['series_count']}")
    kpi[1].metric("Projected shortages", summary["shortage_count"])
    kpi[2].metric("Order now", summary["reorder_now_count"])
    kpi[3].metric("Overstock risk", summary["overstock_count"])
    kpi[4].metric("Dead stock", summary["dead_stock_count"])
    kpi[5].metric("Too little history", summary["insufficient_data_count"])

    st.caption(
        f"Horizon {run['horizon_periods']} periods · confidence {run['confidence_level']:.0%} · "
        f"service level {run['service_level']:.0%} · model "
        f"{MODEL_OPTIONS.get(run.get('requested_model') or 'auto', 'Automatic')} · "
        f"selection metric {(run.get('selection_metric') or '').upper()} · "
        f"engine {run['engine_version']} · config {run['config_version']} · "
        f"{origin_badge('forecast')}"
    )

    items = run.get("items", [])

    tabs = st.tabs(
        [
            "Shortage alerts",
            "Reorder plan",
            "Material detail",
            "Accuracy",
            "Data quality",
            "Export",
        ]
    )

    # -- shortage alerts --------------------------------------------------
    with tabs[0]:
        shortages = [item for item in items if item.get("predicted_shortage_date")]
        if not shortages:
            st.success("No material is projected to run out of stock inside the horizon.")
        else:
            st.write(
                f"**{len(shortages)} material(s)** are projected to run out inside the horizon. "
                "Dates are interpolated inside the period from the forecast demand rate, so they "
                "are real dates rather than a month name."
            )
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Material": item["material"],
                            "Description": item.get("material_description"),
                            "Plant": item["plant"],
                            "Runs out": item["predicted_shortage_date"],
                            "Days away": item.get("days_to_shortage"),
                            "Stock on hand": item.get("opening_inventory"),
                            "Lowest projected": item.get("minimum_projected_inventory"),
                            "Order urgency": (item.get("order_urgency") or "").replace("_", " "),
                            "Expedite open PO": "Yes" if item.get("expedite_recommended") else "",
                            "Model": item.get("model_label"),
                        }
                        for item in shortages
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )
            expedites = [item for item in shortages if item.get("expedite_recommended")]
            if expedites:
                st.warning(
                    f"{len(expedites)} material(s) run out **before** their reorder point is "
                    "reached, because quantity already on order is expected too late. The action "
                    "there is to pull the existing delivery forward, not to raise another order."
                )

    # -- reorder plan -----------------------------------------------------
    with tabs[1]:
        reorders = [item for item in items if item.get("recommended_reorder_date")]
        if not reorders:
            st.info("No material needs a replenishment order inside the horizon.")
        else:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "": URGENCY_ICONS.get(item.get("order_urgency") or "", ""),
                            "Material": item["material"],
                            "Description": item.get("material_description"),
                            "Plant": item["plant"],
                            "Supplier": item.get("supplier_id"),
                            "Order on": item["recommended_reorder_date"],
                            "Quantity": item.get("recommended_reorder_quantity"),
                            "Reorder point (calculated)": item.get("calculated_reorder_point"),
                            "Safety stock (recommended)": item.get("recommended_safety_stock"),
                            "Runs out": item.get("predicted_shortage_date"),
                        }
                        for item in reorders
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )
            st.caption(
                "Quantities are order-up-to levels: forecast demand over the lead time plus the "
                "review period, plus safety stock, minus the projected inventory position on the "
                "reorder date. The full arithmetic for any material is in the Material detail tab."
            )

        stock_health = [
            item
            for item in items
            if item.get("overstock_risk") not in (None, "none")
            or item.get("is_dead_stock")
            or item.get("is_slow_moving")
        ]
        if stock_health:
            st.subheader("Slow-moving, dead and overstocked")
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "": OVERSTOCK_ICONS.get(item.get("overstock_risk") or "none", ""),
                            "Material": item["material"],
                            "Plant": item["plant"],
                            "Movement class": (item.get("movement_class") or "").replace("_", " "),
                            "Slow moving": "Yes" if item.get("is_slow_moving") else "",
                            "Dead stock": "Yes" if item.get("is_dead_stock") else "",
                            "Overstock risk": item.get("overstock_risk"),
                            "Days of cover": item.get("days_of_cover"),
                            "Annual turnover": item.get("annual_turnover"),
                            "Stock on hand": item.get("opening_inventory"),
                        }
                        for item in stock_health
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )

    # -- material detail --------------------------------------------------
    with tabs[2]:
        if not items:
            st.info("This run produced no materials.")
        else:
            selected_label = st.selectbox(
                "Material",
                options=[_item_label(item) for item in items],
                key="inventory_detail_pick",
            )
            selected = items[[_item_label(item) for item in items].index(selected_label)]

            try:
                detail = client.inventory_item(
                    run["forecast_id"],
                    selected["material"],
                    selected["plant"],
                    selected.get("storage_location"),
                )
            except ApiError as error:
                show_error(error.message, error.details)
                detail = None

            if detail:
                if detail["status"] == "insufficient_data":
                    st.warning(
                        f"This material has {detail['history_period_count']} period(s) of "
                        "history, which is too few to forecast. It is reported rather than "
                        "estimated."
                    )
                else:
                    head = st.columns(4)
                    head[0].metric("Model used", detail.get("model_label") or "-")
                    head[1].metric(
                        "Forecast demand (horizon)",
                        _number(detail.get("total_forecast_demand")),
                    )
                    head[2].metric(
                        "Stock on hand",
                        _number((detail.get("projection") or {}).get("opening_inventory")),
                    )
                    head[3].metric(
                        "Runs out",
                        _plain((detail.get("projection") or {}).get("predicted_shortage_date")),
                    )

                    history = detail.get("history", [])
                    forecast_points = detail.get("forecast", [])
                    projection = detail.get("projection") or {}
                    projected = projection.get("periods", [])

                    figure = go.Figure()
                    figure.add_trace(
                        go.Scatter(
                            x=[point["period_date"] for point in history],
                            y=[point["demand"] for point in history],
                            name="Demand (actual)",
                            mode="lines+markers",
                            line={"color": "#1F3864"},
                        )
                    )
                    if forecast_points:
                        figure.add_trace(
                            go.Scatter(
                                x=[point["period_date"] for point in forecast_points],
                                y=[point["upper"] for point in forecast_points],
                                name=f"Upper {detail['confidence_level']:.0%}",
                                mode="lines",
                                line={"width": 0},
                                showlegend=False,
                            )
                        )
                        figure.add_trace(
                            go.Scatter(
                                x=[point["period_date"] for point in forecast_points],
                                y=[point["lower"] for point in forecast_points],
                                name=f"Confidence range ({detail['confidence_level']:.0%})",
                                mode="lines",
                                line={"width": 0},
                                fill="tonexty",
                                fillcolor="rgba(232,113,10,0.20)",
                            )
                        )
                        figure.add_trace(
                            go.Scatter(
                                x=[point["period_date"] for point in forecast_points],
                                y=[point["demand"] for point in forecast_points],
                                name="Demand (forecast)",
                                mode="lines+markers",
                                line={"color": "#E8710A", "dash": "dash"},
                            )
                        )
                    figure.update_layout(
                        title="Demand history and forecast",
                        xaxis_title="Period",
                        yaxis_title="Quantity",
                        height=420,
                        legend={"orientation": "h", "y": -0.2},
                    )
                    st.plotly_chart(figure, use_container_width=True)

                    if projected:
                        stock_figure = go.Figure()
                        stock_figure.add_trace(
                            go.Scatter(
                                x=[point["period_date"] for point in history],
                                y=[point["ending_inventory"] for point in history],
                                name="Stock (actual)",
                                mode="lines",
                                line={"color": "#1F3864"},
                            )
                        )
                        stock_figure.add_trace(
                            go.Scatter(
                                x=[point["period_date"] for point in projected],
                                y=[point["projected_ending_high"] for point in projected],
                                mode="lines",
                                line={"width": 0},
                                showlegend=False,
                            )
                        )
                        stock_figure.add_trace(
                            go.Scatter(
                                x=[point["period_date"] for point in projected],
                                y=[point["projected_ending_low"] for point in projected],
                                name="Range from the demand interval",
                                mode="lines",
                                line={"width": 0},
                                fill="tonexty",
                                fillcolor="rgba(59,140,78,0.18)",
                            )
                        )
                        stock_figure.add_trace(
                            go.Scatter(
                                x=[point["period_date"] for point in projected],
                                y=[point["projected_ending"] for point in projected],
                                name="Stock (projected)",
                                mode="lines+markers",
                                line={"color": "#3B8C4E", "dash": "dash"},
                            )
                        )
                        reorder = projection.get("reorder", {}) or {}
                        if reorder.get("effective_safety_stock"):
                            stock_figure.add_hline(
                                y=reorder["effective_safety_stock"],
                                line_dash="dot",
                                line_color="#E8710A",
                                annotation_text="Safety stock",
                            )
                        if reorder.get("calculated_reorder_point"):
                            stock_figure.add_hline(
                                y=reorder["calculated_reorder_point"],
                                line_dash="dot",
                                line_color="#B3261E",
                                annotation_text="Reorder point (calculated)",
                            )
                        stock_figure.add_hline(y=0, line_color="#B3261E")
                        stock_figure.update_layout(
                            title="Stock level: history and projection",
                            xaxis_title="Period",
                            yaxis_title="Quantity",
                            height=420,
                            legend={"orientation": "h", "y": -0.2},
                        )
                        st.plotly_chart(stock_figure, use_container_width=True)
                    elif not projection.get("available"):
                        st.info(projection.get("unavailable_reason") or "No stock projection.")

                    reorder = projection.get("reorder", {}) or {}
                    st.subheader("Recommendation")
                    rec = st.columns(4)
                    rec[0].metric(
                        "Reorder on", _plain(reorder.get("recommended_reorder_date"))
                    )
                    rec[1].metric(
                        "Order quantity",
                        _metric_or_dash(reorder.get("recommended_reorder_quantity")),
                    )
                    rec[2].metric(
                        "Reorder point (calculated)",
                        _metric_or_dash(reorder.get("calculated_reorder_point")),
                    )
                    rec[3].metric(
                        "Safety stock (recommended)",
                        _metric_or_dash(reorder.get("recommended_safety_stock")),
                    )
                    if reorder.get("expedite_recommended"):
                        st.warning(reorder.get("expedite_reason"))
                    if reorder.get("rationale"):
                        with st.expander("How these numbers were calculated"):
                            for line in reorder["rationale"]:
                                st.write(f"- {line}")

                    st.subheader("Model")
                    st.write(
                        f"**{detail.get('model_label')}** "
                        f"({(detail.get('selection') or {}).get('selection_basis', '')}) — "
                        f"parameters: {detail.get('model_parameters')}"
                    )
                    if detail.get("model_assumptions"):
                        with st.expander("What this model assumes about the demand"):
                            for line in detail["model_assumptions"]:
                                st.write(f"- {line}")
                    if detail.get("model_notes"):
                        for line in detail["model_notes"]:
                            st.caption(line)

                    candidates = (detail.get("selection") or {}).get("candidates", [])
                    if candidates:
                        with st.expander("Every model that was considered"):
                            st.dataframe(
                                pd.DataFrame(
                                    [
                                        {
                                            "": "✅" if item.get("selected") else "",
                                            "Model": item["label"],
                                            "Eligible": "Yes" if item["eligible"] else "No",
                                            "Backtest score": item.get("score"),
                                            "Folds": item.get("folds"),
                                            "Held-out periods": item.get("holdout_periods"),
                                            "Why not used": item.get("ineligible_reason") or "",
                                        }
                                        for item in candidates
                                    ]
                                ),
                                use_container_width=True,
                                hide_index=True,
                            )
                            for note in (detail.get("selection") or {}).get("notes", []):
                                st.caption(note)

                    profile = (detail.get("selection") or {}).get("demand_profile", {})
                    if profile:
                        st.caption(
                            f"Demand pattern: **{profile.get('pattern')}** · zero-demand periods "
                            f"{profile.get('zero_period_pct')}% · seasonal strength "
                            f"{_plain(profile.get('seasonal_strength'))}"
                        )

                if detail.get("warnings"):
                    st.subheader("Warnings for this material")
                    for warning in detail["warnings"]:
                        icon = SEVERITY_ICONS.get(warning.get("severity", "warning"), "🟠")
                        st.write(f"{icon} {warning['message']}")

    # -- accuracy ---------------------------------------------------------
    with tabs[3]:
        accuracy = summary.get("accuracy_summary", {}) or {}
        cols = st.columns(5)
        cols[0].metric("Mean MAE", _metric_or_dash(accuracy.get("mean_mae")))
        cols[1].metric("Mean RMSE", _metric_or_dash(accuracy.get("mean_rmse")))
        cols[2].metric("Mean sMAPE", _metric_or_dash(accuracy.get("mean_smape"), "%"))
        cols[3].metric("Mean MAPE", _metric_or_dash(accuracy.get("mean_mape"), "%"))
        cols[4].metric("Mean MASE", _metric_or_dash(accuracy.get("mean_mase")))
        st.caption(
            "MAPE is only reported for materials whose comparison window has no zero-demand "
            f"period ({int(accuracy.get('series_with_mape') or 0)} of "
            f"{summary['forecast_count']}); it is undefined when demand is zero. sMAPE and MASE "
            "cover the rest. MASE below 1 means the model beat a naive same-as-last-period "
            "forecast."
        )
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Material": item["material"],
                        "Plant": item["plant"],
                        "Model": item.get("model_label"),
                        "Measured on": item.get("accuracy_basis"),
                        "MAE": item.get("mae"),
                        "RMSE": item.get("rmse"),
                        "MAPE %": item.get("mape"),
                        "sMAPE %": item.get("smape"),
                        "MASE": item.get("mase"),
                    }
                    for item in items
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )
        if summary.get("model_usage"):
            st.write("**Models chosen**")
            st.dataframe(
                pd.DataFrame(
                    [
                        {"Model": MODEL_OPTIONS.get(name, name), "Materials": count}
                        for name, count in summary["model_usage"].items()
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )

    # -- data quality -----------------------------------------------------
    with tabs[4]:
        issues = run.get("data_quality_issues", [])
        if issues:
            st.subheader("File level")
            for issue in issues:
                icon = SEVERITY_ICONS.get(issue.get("severity", "warning"), "🟠")
                st.write(f"{icon} **{issue['issue_type']}** — {issue['message']}")
        warning_counts = summary.get("warning_counts", {}) or {}
        if warning_counts:
            st.subheader("Material level")
            st.dataframe(
                pd.DataFrame(
                    [
                        {"Warning": code.replace("_", " "), "Materials": count}
                        for code, count in warning_counts.items()
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )
            st.caption("Open a material in the detail tab to read its warnings in full.")
        if run.get("series_errors"):
            st.subheader("Materials that could not be forecast")
            st.dataframe(pd.DataFrame(run["series_errors"]), use_container_width=True)
        if not issues and not warning_counts and not run.get("series_errors"):
            st.success("No data-quality problems were found in this file.")

    # -- export -----------------------------------------------------------
    with tabs[5]:
        st.write(
            "The workbook holds six sheets: summary, per-material results, the long-format "
            "forecast table (one row per material per period, with the confidence range and the "
            "projected stock), the reorder plan, the data-quality log and the methodology."
        )
        export_columns = st.columns(3)
        for column, file_format in zip(export_columns, ("xlsx", "csv", "json")):
            with column:
                try:
                    column.download_button(
                        f"Download .{file_format}",
                        data=client.inventory_export(run["forecast_id"], file_format),
                        file_name=f"inventory_forecast_{run['forecast_id'][:8]}.{file_format}",
                        key=f"inv_export_{file_format}",
                    )
                except ApiError as error:
                    show_error(error.message, error.details)

    narrative = run.get("ai_narrative") or {}
    if narrative.get("available"):
        st.subheader(f"Narrative ({origin_badge(narrative.get('origin'))})")
        st.info(
            "This text explains the figures above. It never produced any of them - every "
            "number came from the statistical engine."
        )
        st.write(narrative["summary"])
        if narrative.get("key_findings"):
            st.write("**Key findings**")
            for finding in narrative["key_findings"]:
                st.write(f"- {finding}")
        if narrative.get("recommended_actions"):
            st.write("**Recommended actions**")
            for action in narrative["recommended_actions"]:
                st.write(f"- {action}")
    elif narrative.get("error"):
        st.caption(f"The AI narrative was unavailable: {narrative['error']}")

    if run.get("disclaimer"):
        st.caption(run["disclaimer"])

disclaimer()
