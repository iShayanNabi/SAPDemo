"""Shared pytest fixtures.

The environment variables are set *before* any application module is imported,
because ``app.core.config`` builds its settings singleton at import time. Each
test session therefore gets its own throwaway SQLite database and its own
upload/export directories - the developer's local data is never touched.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

TEST_ROOT = Path(tempfile.mkdtemp(prefix="sap_ai_lab_tests_"))

os.environ["ENVIRONMENT"] = "test"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_ROOT / 'test.db'}"
os.environ["DATA_DIR"] = str(TEST_ROOT / "data")
os.environ["UPLOAD_DIR"] = str(TEST_ROOT / "uploads")
os.environ["EXPORT_DIR"] = str(TEST_ROOT / "exports")
os.environ["AI_PROVIDER"] = "mock"
os.environ["LOG_LEVEL"] = "WARNING"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import PROJECT_ROOT, settings  # noqa: E402
from app.main import app  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models.session import SessionLocal, engine, init_db  # noqa: E402
from app.modules.po_risk.thresholds import PoRiskConfig, get_rule_config  # noqa: E402
from app.modules.spend.thresholds import SpendConfig, get_spend_config  # noqa: E402
from app.modules.supplier_reco.thresholds import (  # noqa: E402
    SupplierRecoConfig,
    get_supplier_reco_config,
)

SAMPLE_DIR = PROJECT_ROOT / "data" / "sample"


@pytest.fixture(scope="session", autouse=True)
def _prepare_database():
    """Create the schema once, remove the temporary tree afterwards."""
    settings.ensure_directories()
    init_db()
    yield
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    shutil.rmtree(TEST_ROOT, ignore_errors=True)


@pytest.fixture
def db_session() -> Session:
    """A database session for service level tests."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="session")
def api_client() -> TestClient:
    """A FastAPI test client sharing the test database."""
    with TestClient(app) as client:
        yield client


@pytest.fixture(scope="session")
def rule_config() -> PoRiskConfig:
    """The default rule configuration."""
    return get_rule_config()


@pytest.fixture(scope="session")
def spend_config() -> SpendConfig:
    """The default spend analytics configuration."""
    return get_spend_config()


@pytest.fixture(scope="session")
def spend_sample_csv_path() -> Path:
    """Path of the generated spend sample CSV."""
    path = SAMPLE_DIR / "sample_spend_transactions.csv"
    if not path.is_file():
        pytest.skip("Run 'python scripts/generate_spend_sample_data.py' first.")
    return path


@pytest.fixture(scope="session")
def spend_sample_xlsx_path() -> Path:
    """Path of the generated spend sample XLSX."""
    path = SAMPLE_DIR / "sample_spend_transactions.xlsx"
    if not path.is_file():
        pytest.skip("Run 'python scripts/generate_spend_sample_data.py' first.")
    return path


@pytest.fixture(scope="session")
def spend_sample_json_path() -> Path:
    """Path of the generated spend sample JSON."""
    path = SAMPLE_DIR / "sample_spend_transactions.json"
    if not path.is_file():
        pytest.skip("Run 'python scripts/generate_spend_sample_data.py' first.")
    return path


@pytest.fixture(scope="session")
def supplier_reco_config() -> SupplierRecoConfig:
    """The default supplier recommendation configuration."""
    return get_supplier_reco_config()


@pytest.fixture(scope="session")
def supplier_sample_csv_path() -> Path:
    """Path of the generated supplier sample CSV."""
    path = SAMPLE_DIR / "sample_suppliers.csv"
    if not path.is_file():
        pytest.skip("Run 'python scripts/generate_supplier_sample_data.py' first.")
    return path


@pytest.fixture(scope="session")
def supplier_sample_xlsx_path() -> Path:
    """Path of the generated supplier sample XLSX."""
    path = SAMPLE_DIR / "sample_suppliers.xlsx"
    if not path.is_file():
        pytest.skip("Run 'python scripts/generate_supplier_sample_data.py' first.")
    return path


@pytest.fixture(scope="session")
def supplier_sample_json_path() -> Path:
    """Path of the generated supplier sample JSON."""
    path = SAMPLE_DIR / "sample_suppliers.json"
    if not path.is_file():
        pytest.skip("Run 'python scripts/generate_supplier_sample_data.py' first.")
    return path


@pytest.fixture(scope="session")
def supplier_scenario_manifest() -> dict:
    """The documented supplier anchors and the canonical requirement."""
    import json

    path = SAMPLE_DIR / "supplier_scenario_manifest.json"
    if not path.is_file():
        pytest.skip("Run 'python scripts/generate_supplier_sample_data.py' first.")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def supplier_baseline() -> dict:
    """The recorded engine output for the canonical requirement."""
    import json

    path = SAMPLE_DIR / "expected_supplier_baseline.json"
    if not path.is_file():
        pytest.skip("Run 'python scripts/generate_supplier_sample_data.py' first.")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def spend_scenario_manifest() -> dict:
    """The documented spend scenarios."""
    import json

    path = SAMPLE_DIR / "spend_scenario_manifest.json"
    if not path.is_file():
        pytest.skip("Run 'python scripts/generate_spend_sample_data.py' first.")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def invoice_validator_config():
    """The default invoice validator configuration."""
    from app.modules.invoice_validator.thresholds import get_invoice_validator_config

    return get_invoice_validator_config()


def _invoice_sample(name: str) -> Path:
    path = SAMPLE_DIR / name
    if not path.is_file():
        pytest.skip("Run 'python scripts/generate_invoice_sample_data.py' first.")
    return path


@pytest.fixture(scope="session")
def invoice_sample_csv_path() -> Path:
    """Path of the generated invoices CSV."""
    return _invoice_sample("sample_invoices.csv")


@pytest.fixture(scope="session")
def invoice_sample_xlsx_path() -> Path:
    """Path of the generated invoices XLSX."""
    return _invoice_sample("sample_invoices.xlsx")


@pytest.fixture(scope="session")
def invoice_po_sample_csv_path() -> Path:
    """Path of the generated purchase orders CSV."""
    return _invoice_sample("sample_invoice_purchase_orders.csv")


@pytest.fixture(scope="session")
def goods_receipt_sample_csv_path() -> Path:
    """Path of the generated goods receipts CSV."""
    return _invoice_sample("sample_goods_receipts.csv")


@pytest.fixture(scope="session")
def invoice_scenario_manifest() -> dict:
    """The documented invoice anchors and reference date."""
    import json

    return json.loads(_invoice_sample("invoice_scenario_manifest.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def invoice_baseline() -> dict:
    """The recorded engine output for the sample datasets."""
    import json

    return json.loads(_invoice_sample("expected_invoice_baseline.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def supplier_risk_config():
    """The default supplier risk configuration."""
    from app.modules.supplier_risk.thresholds import get_supplier_risk_config

    return get_supplier_risk_config()


def _supplier_risk_sample(name: str) -> Path:
    path = SAMPLE_DIR / name
    if not path.is_file():
        pytest.skip("Run 'python scripts/generate_supplier_risk_sample_data.py' first.")
    return path


@pytest.fixture(scope="session")
def supplier_risk_sample_csv_path() -> Path:
    """Path of the generated supplier risk profiles CSV."""
    return _supplier_risk_sample("sample_supplier_risk_profiles.csv")


@pytest.fixture(scope="session")
def supplier_risk_sample_xlsx_path() -> Path:
    """Path of the generated supplier risk profiles XLSX."""
    return _supplier_risk_sample("sample_supplier_risk_profiles.xlsx")


@pytest.fixture(scope="session")
def supplier_risk_event_sample_csv_path() -> Path:
    """Path of the generated supplier risk events CSV."""
    return _supplier_risk_sample("sample_supplier_risk_events.csv")


@pytest.fixture(scope="session")
def supplier_risk_scenario_manifest() -> dict:
    """The documented supplier risk anchors and the reference date."""
    import json

    path = _supplier_risk_sample("supplier_risk_scenario_manifest.json")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def supplier_risk_baseline() -> dict:
    """The recorded engine output for the supplier risk sample dataset."""
    import json

    path = _supplier_risk_sample("expected_supplier_risk_baseline.json")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def inventory_config():
    """The default Inventory Predictor configuration."""
    from app.modules.inventory.thresholds import get_inventory_config

    return get_inventory_config()


def _inventory_sample(name: str) -> Path:
    path = SAMPLE_DIR / name
    if not path.is_file():
        pytest.skip("Run 'python scripts/generate_inventory_sample_data.py' first.")
    return path


@pytest.fixture(scope="session")
def inventory_sample_csv_path() -> Path:
    """Path of the generated inventory history CSV."""
    return _inventory_sample("sample_inventory_history.csv")


@pytest.fixture(scope="session")
def inventory_sample_xlsx_path() -> Path:
    """Path of the generated inventory history XLSX."""
    return _inventory_sample("sample_inventory_history.xlsx")


@pytest.fixture(scope="session")
def inventory_sample_json_path() -> Path:
    """Path of the generated inventory history JSON."""
    return _inventory_sample("sample_inventory_history.json")


@pytest.fixture(scope="session")
def inventory_scenario_manifest() -> dict:
    """The documented inventory anchors and the reference date."""
    import json

    path = _inventory_sample("inventory_scenario_manifest.json")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def inventory_baseline() -> dict:
    """The recorded engine output for the inventory sample dataset."""
    import json

    path = _inventory_sample("expected_inventory_baseline.json")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def contract_config():
    """The default Contract Assistant configuration."""
    from app.modules.contract_assistant.thresholds import get_contract_config

    return get_contract_config()


def _contract_sample(name: str) -> Path:
    path = SAMPLE_DIR / name
    if not path.is_file():
        pytest.skip("Run 'python scripts/generate_contract_sample_data.py' first.")
    return path


@pytest.fixture(scope="session")
def contract_sample_dir() -> Path:
    """The directory holding the bundled fictional contracts."""
    _contract_sample("contract_scenario_manifest.json")
    return SAMPLE_DIR


@pytest.fixture(scope="session")
def contract_sample_pdf_path() -> Path:
    """Path of the generated MSA sample as a text-based PDF."""
    return _contract_sample("sample_contract_msa_nordwind.pdf")


@pytest.fixture(scope="session")
def contract_sample_docx_path() -> Path:
    """Path of the generated MSA sample as a Word document."""
    return _contract_sample("sample_contract_msa_nordwind.docx")


@pytest.fixture(scope="session")
def contract_sample_txt_path() -> Path:
    """Path of the generated MSA sample as plain text."""
    return _contract_sample("sample_contract_msa_nordwind.txt")


@pytest.fixture(scope="session")
def hostile_contract_pdf_path() -> Path:
    """Path of the contract carrying prompt-injection bait."""
    return _contract_sample("sample_contract_hostile_calder.pdf")


@pytest.fixture(scope="session")
def contract_scenario_manifest() -> dict:
    """The documented contract scenarios and the reference date."""
    import json

    return json.loads(
        _contract_sample("contract_scenario_manifest.json").read_text(encoding="utf-8")
    )


@pytest.fixture(scope="session")
def contract_baseline() -> dict:
    """The recorded engine output for the bundled sample contracts."""
    import json

    return json.loads(
        _contract_sample("expected_contract_baseline.json").read_text(encoding="utf-8")
    )


@pytest.fixture(scope="session")
def test_case_config():
    """The default Test Case Generator configuration."""
    from app.modules.test_case_generator.thresholds import get_test_case_config

    return get_test_case_config()


def _test_case_sample(name: str) -> Path:
    path = SAMPLE_DIR / name
    if not path.is_file():
        pytest.skip("Run 'python scripts/generate_test_case_sample_data.py' first.")
    return path


@pytest.fixture(scope="session")
def test_case_processes() -> dict:
    """The bundled fictional SAP process definitions."""
    import json

    path = _test_case_sample("sample_test_case_processes.json")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def test_case_manifest() -> dict:
    """The documented test case generator scenarios."""
    import json

    path = _test_case_sample("test_case_scenario_manifest.json")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def test_case_baseline() -> dict:
    """The recorded deterministic output for the demo processes."""
    import json

    path = _test_case_sample("expected_test_case_baseline.json")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def sample_csv_path() -> Path:
    """Path of the generated sample CSV, skipping tests when it is absent."""
    path = SAMPLE_DIR / "sample_purchase_orders.csv"
    if not path.is_file():
        pytest.skip("Run 'python scripts/generate_sample_data.py' to create the sample dataset.")
    return path


@pytest.fixture(scope="session")
def sample_xlsx_path() -> Path:
    """Path of the generated sample XLSX."""
    path = SAMPLE_DIR / "sample_purchase_orders.xlsx"
    if not path.is_file():
        pytest.skip("Run 'python scripts/generate_sample_data.py' to create the sample dataset.")
    return path


@pytest.fixture(scope="session")
def sample_json_path() -> Path:
    """Path of the generated sample JSON."""
    path = SAMPLE_DIR / "sample_purchase_orders.json"
    if not path.is_file():
        pytest.skip("Run 'python scripts/generate_sample_data.py' to create the sample dataset.")
    return path


@pytest.fixture(scope="session")
def anomaly_manifest_path() -> Path:
    """Path of the anomaly manifest."""
    path = SAMPLE_DIR / "anomaly_manifest.csv"
    if not path.is_file():
        pytest.skip("Run 'python scripts/generate_sample_data.py' to create the sample dataset.")
    return path
