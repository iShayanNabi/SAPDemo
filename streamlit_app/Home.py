"""Streamlit entry point for the SAP AI Application Lab.

Run with::

    streamlit run streamlit_app/Home.py

This interface is a temporary local test harness. Every page calls the FastAPI
backend over HTTP, so the same backend can later serve a React or Next.js site
without any business logic being rewritten.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from streamlit_app.components.api_client import ApiClient, ApiError  # noqa: E402
from streamlit_app.components.ui import disclaimer, origin_badge  # noqa: E402

st.set_page_config(page_title="SAP AI Application Lab", page_icon="🧪", layout="wide")

st.title("SAP AI Application Lab")
st.write(
    "A local workbench for SAP-focused AI applications. Each module runs entirely on your "
    "machine: no SAP credentials, no paid APIs and no AI API key are required."
)

client = ApiClient()

with st.sidebar:
    st.header("Backend status")
    try:
        health = client.health()
        st.success(f"API reachable ({health['status']})")
        st.write(f"**Version:** {health['version']}")
        st.write(f"**Environment:** {health['environment']}")
        st.write(f"**Database:** {'connected' if health['database_connected'] else 'unavailable'}")
        provider = health["ai_provider"]
        st.write(f"**AI provider:** {provider}" + (" (mock mode)" if health["ai_is_mock"] else ""))
    except ApiError as error:
        st.error(error.message)
        st.caption("Start the backend in a second terminal, then reload this page.")
        st.code("uvicorn app.main:app --reload", language="bash")

st.subheader("Modules")

modules = [
    ("1. Purchase Order Risk Checker", "Available", "Upload SAP-style PO data, detect risks with transparent rules, export reports."),
    ("2. Spend Analytics Dashboard", "Available", "Analyse spend, find leakage and savings opportunities, drill into transactions."),
    ("3. Supplier Recommendation Engine", "Available", "Rank eligible suppliers for a requirement with transparent weighted scoring."),
    ("4. Invoice Validator", "Available", "Three-way match invoices against POs and goods receipts with configurable tolerances."),
    ("5. Supplier Risk Copilot", "Planned", "Question answering over supplier risk data."),
    ("6. Contract Assistant", "Planned", "Clause extraction and contract summarisation."),
    ("7. Inventory Predictor", "Planned", "Statistical demand and stock forecasting."),
    ("8. SAP Test Case Generator", "Planned", "Generate test cases from process descriptions."),
    ("9. SAP Blueprint Generator", "Planned", "Draft configuration blueprints."),
    ("10. SAP Interview Coach", "Planned", "Practice questions and structured feedback."),
]

for name, status, description in modules:
    icon = "✅" if status == "Available" else "🕒"
    st.write(f"{icon} **{name}** - {status}. {description}")

st.info(
    "Open **PO Risk Checker** or **Spend Analytics** in the sidebar to use the modules that "
    "are implemented today.",
    icon="👈",
)

st.subheader("How the lab is put together")
st.markdown(
    """
| Layer | Location | Responsibility |
| --- | --- | --- |
| API | `app/api` | HTTP routes only |
| Business logic | `app/modules/<module>` | Rules, engine, orchestration |
| Services | `app/services` | Files, exports, AI providers |
| Data | `app/models`, `app/schemas` | Persistence and validation |
| UI (temporary) | `streamlit_app` | Calls the API over HTTP |

Risk decisions are always made by deterministic Python code. AI is optional and only rewrites
those results in business language; its output is labelled everywhere it appears.
"""
)

try:
    ai_status = client.ai_status()
    st.caption(
        f"Active AI provider: **{ai_status['resolved_provider']}** "
        f"({origin_badge('mock_ai' if ai_status['is_mock'] else 'ai_generated')}), "
        f"model `{ai_status['model']}`. API keys are read from environment variables only."
    )
except ApiError:
    pass

disclaimer()
