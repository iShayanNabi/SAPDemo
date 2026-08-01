"""Load the bundled demo data so every page has something to show.

Run with::

    python scripts/seed_database.py              # seed everything
    python scripts/seed_database.py --modules po_risk spend
    python scripts/seed_database.py --list       # what can be seeded
    python scripts/seed_database.py --yes        # do not ask before adding to a
                                                 # database that already has data

It drives the **real HTTP API in-process** rather than calling the service layer
directly. That is deliberate: a seed script that reached past the API would keep
working after an endpoint broke, and the first person to notice would be
somebody following the README. Everything here is a request a user could make by
hand, so if the seed succeeds the demo works.

No server needs to be running - the app is mounted in-process through FastAPI's
test client, which only needs ``httpx`` and is already a dependency.

The data is entirely fictional and lives in ``data/sample/``. Nothing is
downloaded and no credentials are needed: the AI provider stays in mock mode
unless a key is configured, and every seeded analysis is deterministic.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import settings  # noqa: E402

SAMPLE_DIR = PROJECT_ROOT / "data" / "sample"
V1 = settings.api_v1_prefix

CSV = "text/csv"
PDF = "application/pdf"


class SeedError(RuntimeError):
    """A seeding step did not produce what the demo needs."""


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------
def _data(response: Any, what: str) -> Any:
    """Unwrap the shared envelope, or explain what failed."""
    if response.status_code >= 400:
        try:
            error = response.json().get("error", {})
            detail = error.get("message") or response.text[:200]
        except ValueError:  # pragma: no cover - a non-JSON error body
            detail = response.text[:200]
        raise SeedError(f"{what} failed (HTTP {response.status_code}): {detail}")
    body = response.json()
    if not body.get("success"):
        raise SeedError(f"{what} failed: {body.get('error', {}).get('message')}")
    return body["data"]


def _sample(name: str) -> bytes:
    path = SAMPLE_DIR / name
    if not path.is_file():
        raise SeedError(
            f"{name} is missing from data/sample/. Run the matching "
            f"scripts/generate_*_sample_data.py first."
        )
    return path.read_bytes()


def _upload(client, url: str, name: str, *, mime: str = CSV, **form: str) -> dict:
    return _data(
        client.post(url, data=form or None, files={"file": (name, _sample(name), mime)}),
        f"uploading {name}",
    )


# ---------------------------------------------------------------------------
# One seeder per module
# ---------------------------------------------------------------------------
def seed_po_risk(client) -> str:
    uploaded = _upload(client, f"{V1}/po-risk/upload", "sample_purchase_orders.csv")
    analysis = _data(
        client.post(
            f"{V1}/po-risk/analyze",
            json={"upload_id": uploaded["upload_id"], "generate_ai_summary": True},
        ),
        "running the purchase order risk analysis",
    )
    return f"{analysis['findings_count']} findings over {analysis['record_count']} lines"


def seed_spend(client) -> str:
    uploaded = _upload(client, f"{V1}/spend/upload", "sample_spend_transactions.csv")
    analysis = _data(
        client.post(
            f"{V1}/spend/analyze",
            json={"upload_id": uploaded["upload_id"], "generate_ai_summary": True},
        ),
        "running the spend analysis",
    )
    metrics = analysis["metrics"]
    return (
        f"{metrics['total_spend']:,.0f} {metrics['base_currency']} of spend, "
        f"{len(analysis['opportunities'])} opportunities"
    )


def seed_supplier_reco(client) -> str:
    catalogue = _upload(client, f"{V1}/suppliers/upload", "sample_suppliers.csv")
    recommendation = _data(
        client.post(
            f"{V1}/supplier-recommendations/recommend",
            json={
                "catalog_id": catalogue["catalog_id"],
                "requirement": {
                    "material": "MAT-1000",
                    "quantity": 100,
                    "plant": "1010",
                    "preferred_region": "EU",
                    "required_delivery_date": "2026-10-01",
                    "order_date": "2026-08-01",
                    "target_price": 120,
                    "currency": "EUR",
                    "risk_tolerance": "medium",
                },
                "generate_ai_summary": True,
            },
        ),
        "ranking suppliers",
    )
    return (
        f"{catalogue['supplier_count']} suppliers, "
        f"{recommendation['eligible_count']} eligible for MAT-1000"
    )


def seed_invoice_validator(client) -> str:
    invoices = _upload(
        client, f"{V1}/invoices/upload", "sample_invoices.csv", dataset="invoices"
    )
    orders = _upload(
        client,
        f"{V1}/invoices/upload",
        "sample_invoice_purchase_orders.csv",
        dataset="purchase_orders",
    )
    receipts = _upload(
        client, f"{V1}/invoices/upload", "sample_goods_receipts.csv", dataset="goods_receipts"
    )
    validation = _data(
        client.post(
            f"{V1}/invoices/validate",
            json={
                "invoice_upload_id": invoices["upload_id"],
                "po_upload_id": orders["upload_id"],
                "gr_upload_id": receipts["upload_id"],
                "generate_ai_summary": True,
            },
        ),
        "three-way matching the invoices",
    )
    return f"{validation['exceptions_count']} exceptions over {validation['invoice_count']} invoices"


def seed_supplier_risk(client) -> str:
    profiles = _upload(
        client,
        f"{V1}/supplier-risk/upload",
        "sample_supplier_risk_profiles.csv",
        dataset="profiles",
    )
    _upload(
        client,
        f"{V1}/supplier-risk/upload",
        "sample_supplier_risk_events.csv",
        dataset="events",
        dataset_id=profiles["dataset_id"],
    )
    assessment = _data(
        client.post(
            f"{V1}/supplier-risk/calculate",
            json={"dataset_id": profiles["dataset_id"], "generate_ai_summary": True},
        ),
        "scoring supplier risk",
    )
    return f"{len(assessment['suppliers'])} suppliers scored"


def seed_contracts(client) -> str:
    documents = [
        "sample_contract_msa_nordwind.pdf",
        "sample_contract_nda_meridian.pdf",
        "sample_contract_saas_helvetia.docx",
    ]
    analysed = 0
    for name in documents:
        mime = PDF if name.endswith(".pdf") else (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        uploaded = _upload(client, f"{V1}/contracts/upload", name, mime=mime)
        _data(
            client.post(
                f"{V1}/contracts/{uploaded['contract_id']}/analyze",
                json={"generate_ai_summary": True},
            ),
            f"analysing {name}",
        )
        analysed += 1
    return f"{analysed} contracts analysed"


def seed_inventory(client) -> str:
    dataset = _upload(client, f"{V1}/inventory/upload", "sample_inventory_history.csv")
    forecast = _data(
        client.post(
            f"{V1}/inventory/forecast",
            json={
                "dataset_id": dataset["dataset_id"],
                "horizon_periods": 6,
                "as_of_date": "2026-07-01",
                "generate_ai_summary": True,
            },
        ),
        "forecasting demand",
    )
    summary = forecast["summary"]
    return (
        f"{summary['forecast_count']} materials forecast, "
        f"{summary['shortage_count']} predicted shortages"
    )


def seed_test_cases(client) -> str:
    suite = _data(
        client.post(
            f"{V1}/test-cases/generate",
            json={
                "context": {
                    "sap_product": "SAP S/4HANA 2023",
                    "sap_module": "MM",
                    "business_process": "Procure to Pay - standard purchase order",
                    "process_description": (
                        "A requisition becomes a purchase order, the warehouse posts a goods "
                        "receipt and accounts payable posts the supplier invoice before the "
                        "payment run settles it."
                    ),
                    "preconditions": ["Vendor 100234 exists and is not blocked"],
                    "business_rules": ["Orders above 10,000 EUR need a second release"],
                    "systems_involved": ["SAP S/4HANA", "SAP Ariba Buying"],
                    "integrations": ["Ariba requisition replication", "Bank payment file"],
                    "user_roles": ["Requisitioner", "Purchasing buyer", "AP clerk"],
                    "test_data_requirements": ["Vendor 100234", "Material 100001"],
                },
                "test_case_count": 12,
                "test_types": ["sit", "uat", "negative", "integration", "regression"],
                "suite_name": "Procure to Pay - demo suite",
                "use_ai": True,
            },
        ),
        "generating the test suite",
    )
    return f"{len(suite['test_cases'])} test cases in '{suite['name']}'"


def seed_blueprints(client) -> str:
    blueprint = _data(
        client.post(
            f"{V1}/blueprints/generate",
            json={
                "project": {
                    "company": "Nordwind Logistics GmbH",
                    "industry": "Wholesale distribution",
                    "sap_product": "SAP S/4HANA 2023, private cloud edition",
                    "modules": ["MM", "FI", "SD"],
                    "business_objectives": [
                        "Cut the time from requisition to purchase order",
                        "Remove the manual three-way match",
                    ],
                    "current_process": (
                        "Requisitions are raised on paper, keyed into a legacy system and "
                        "emailed to the supplier as a PDF."
                    ),
                    "desired_process": (
                        "Requisitions are raised in SAP, released by the value based release "
                        "strategy and sent to the supplier electronically."
                    ),
                    "countries": ["Germany", "Poland"],
                    "locations": ["Hamburg distribution centre"],
                    "company_codes": ["1000", "2000"],
                    "plants": ["1010", "2010"],
                    "purchasing_organizations": ["1000"],
                    "systems_involved": ["SAP S/4HANA", "Legacy warehouse system"],
                    "integrations": ["Purchase order transmission", "Payment file to the bank"],
                    "data_sources": ["Legacy purchasing system"],
                    "user_groups": ["Requisitioner", "Purchasing buyer", "AP clerk"],
                    "timeline": "Design Q1, build Q2, go-live Q3",
                    "constraints": ["The warehouse system cannot change this year"],
                    "assumptions": ["The group vendor register stays the master for supplier data"],
                },
                "blueprint_name": "Nordwind S/4HANA blueprint - demo",
                "use_ai": True,
            },
        ),
        "generating the blueprint",
    )
    return f"{len(blueprint['sections'])} sections in '{blueprint['name']}'"


def seed_interviews(client) -> str:
    session = _data(
        client.post(
            f"{V1}/interviews/start",
            json={
                "tracks": ["sap_mm", "sap_integration"],
                "mode": "practice",
                "question_count": 5,
                "seed": 20260801,
                "candidate_name": "Demo candidate",
                "session_name": "Demo practice session",
            },
        ),
        "starting the interview session",
    )
    answer = (
        "Goods receipt and invoice receipt are matched through the GR/IR clearing account. "
        "The purchase order, the goods receipt and the supplier invoice form the three-way "
        "match, so the company only settles invoices for goods it actually received. An aged "
        "GR/IR balance means one of the three documents is missing, which is why the account "
        "is reconciled at period close."
    )
    answered = 0
    for _ in range(session["summary"]["question_count"]):
        result = _data(
            client.post(
                f"{V1}/interviews/{session['session_id']}/answer",
                json={"answer_text": answer, "seconds_spent": 120},
            ),
            "submitting an interview answer",
        )
        answered += 1
        if result["next_question"] is None:
            break
    _data(
        client.post(f"{V1}/interviews/{session['session_id']}/complete", json={}),
        "completing the interview session",
    )
    return f"1 session, {answered} answers scored"


#: Ordered so the output reads like the module list in the README.
SEEDERS: dict[str, Callable[[Any], str]] = {
    "po_risk": seed_po_risk,
    "spend": seed_spend,
    "supplier_reco": seed_supplier_reco,
    "invoice_validator": seed_invoice_validator,
    "supplier_risk": seed_supplier_risk,
    "contracts": seed_contracts,
    "inventory": seed_inventory,
    "test_cases": seed_test_cases,
    "blueprints": seed_blueprints,
    "interviews": seed_interviews,
}

LABELS = {
    "po_risk": "1. Purchase Order Risk Checker",
    "spend": "2. Spend Analytics Dashboard",
    "supplier_reco": "3. Supplier Recommendation Engine",
    "invoice_validator": "4. Invoice Validator",
    "supplier_risk": "5. Supplier Risk Copilot",
    "contracts": "6. Contract Assistant",
    "inventory": "7. Inventory Predictor",
    "test_cases": "8. SAP Test Case Generator",
    "blueprints": "9. SAP Blueprint Generator",
    "interviews": "10. SAP Interview Coach",
}


def existing_row_count() -> int:
    """How many analyses of any kind the database already holds."""
    from sqlalchemy import func, select

    from app.models import (
        Blueprint,
        Contract,
        InterviewSession,
        InventoryForecast,
        InvoiceValidation,
        PoAnalysis,
        SpendAnalysis,
        SupplierRecommendation,
        SupplierRiskAssessment,
        TestSuite,
    )
    from app.models.session import SessionLocal

    models = [
        PoAnalysis, SpendAnalysis, SupplierRecommendation, InvoiceValidation,
        SupplierRiskAssessment, Contract, InventoryForecast, TestSuite,
        Blueprint, InterviewSession,
    ]
    total = 0
    with SessionLocal() as session:
        for model in models:
            total += session.execute(select(func.count()).select_from(model)).scalar_one()
    return total


def main() -> int:
    """Seed the demo data."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--modules",
        nargs="*",
        choices=sorted(SEEDERS),
        help="Seed only these modules (default: all ten).",
    )
    parser.add_argument("--list", action="store_true", help="List what can be seeded and exit.")
    parser.add_argument(
        "--yes", action="store_true", help="Do not ask before adding to a non-empty database."
    )
    parser.add_argument(
        "--if-empty",
        action="store_true",
        help=(
            "Do nothing, successfully, when the database already holds analyses. This is "
            "what a container start uses: seeding must happen on a fresh volume and must "
            "not happen on a restart."
        ),
    )
    args = parser.parse_args()

    if args.list:
        print("Seedable modules:\n")
        for key in SEEDERS:
            print(f"  {key:20} {LABELS[key]}")
        return 0

    print("SAP AI Application Lab - seeding the demo data\n")
    provider = settings.resolved_ai_provider()
    print(f"  AI provider: {provider}" + (" (mock, no key needed)" if provider == "mock" else ""))
    print(f"  Sample data: {SAMPLE_DIR}\n")

    if not SAMPLE_DIR.is_dir():
        print("data/sample/ does not exist. Run the scripts/generate_*_sample_data.py scripts.")
        return 2

    try:
        already = existing_row_count()
    except Exception as exc:  # noqa: BLE001 - a missing schema is the common case
        print(f"The database is not ready ({type(exc).__name__}).")
        print("Run: alembic upgrade head    (or: python scripts/reset_demo.py --yes)")
        return 2

    if already and args.if_empty:
        # Exit 0, not 1: on a restart this is the expected outcome, and a
        # container start script that treats "already seeded" as a failure
        # either stops booting or teaches everybody to ignore its exit code.
        print(f"The database already holds {already} analysis record(s); nothing to seed.")
        return 0

    if already and not args.yes:
        print(f"The database already holds {already} analysis record(s).")
        if not sys.stdin.isatty():
            print("Re-run with --yes to add another set, or reset first:")
            print("  python scripts/reset_demo.py --yes --seed")
            return 1
        if input("Seed another set on top? [y/N] ").strip().lower() not in {"y", "yes"}:
            print("Nothing was changed.")
            return 1

    # Imported here so `--list` and `--help` stay instant.
    from fastapi.testclient import TestClient

    from app.core.demo import trusted_ingest
    from app.main import app

    selected = args.modules or list(SEEDERS)
    failures: list[str] = []

    # These uploads carry bytes read from data/sample/, not from a request, so
    # they are permitted even while public demo mode is refusing client
    # uploads. Without this the demo hostname would come up with an empty
    # database and no way to fill it.
    with TestClient(app) as client, trusted_ingest():
        health = client.get(f"{V1}/health")
        if health.status_code != 200:
            print(f"The API did not start cleanly (HTTP {health.status_code}).")
            return 2

        for key in selected:
            label = LABELS[key]
            started = time.perf_counter()
            print(f"  {label:42}", end=" ", flush=True)
            try:
                summary = SEEDERS[key](client)
            except SeedError as exc:
                print(f"FAILED\n      {exc}")
                failures.append(key)
            except Exception as exc:  # noqa: BLE001 - reported, never hidden
                print(f"FAILED\n      {type(exc).__name__}: {exc}")
                failures.append(key)
            else:
                elapsed = time.perf_counter() - started
                print(f"ok   {summary}  ({elapsed:.1f}s)")

    print()
    if failures:
        print(f"{len(failures)} module(s) could not be seeded: {', '.join(failures)}")
        return 1

    print(f"Seeded {len(selected)} module(s).\n")
    print("Next:")
    print("  uvicorn app.main:app --reload         then open http://127.0.0.1:8000/docs")
    print("  streamlit run streamlit_app/Home.py   then open http://localhost:8501")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
