"""Check that a local installation is complete and working.

Run with::

    python scripts/verify_setup.py

Checks the Python version, the required packages, the writable directories, the
rule configuration, the database and the AI provider - then prints a short
report with the next command to run. Exit code 0 means everything is ready.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

REQUIRED_PACKAGES = [
    "fastapi", "uvicorn", "pydantic", "pydantic_settings", "sqlalchemy", "alembic",
    "pandas", "numpy", "sklearn", "statsmodels", "openpyxl", "pypdf", "docx",
    "httpx", "streamlit", "plotly", "pytest",
]

PASS, FAIL, WARN = "  [ok]", "  [FAIL]", "  [warn]"


def main() -> int:
    """Run every check and report the outcome."""
    problems: list[str] = []
    warnings: list[str] = []

    print("SAP AI Application Lab - setup check\n")

    # 1. Python version
    print("Python")
    version = sys.version_info
    if version >= (3, 12):
        print(f"{PASS} Python {version.major}.{version.minor}.{version.micro}")
    else:
        print(f"{FAIL} Python {version.major}.{version.minor} found, 3.12+ required")
        problems.append("Install Python 3.12 or newer.")

    # 2. Packages
    print("\nPackages")
    missing = []
    for package in REQUIRED_PACKAGES:
        try:
            importlib.import_module(package)
        except ImportError:
            missing.append(package)
    if missing:
        print(f"{FAIL} missing: {', '.join(missing)}")
        problems.append("Run: pip install -r requirements.txt")
    else:
        print(f"{PASS} all {len(REQUIRED_PACKAGES)} required packages import")

    if problems:
        _report(problems, warnings)
        return 1

    from app.core.config import settings
    from app.models.session import engine, init_db
    from app.modules.po_risk.rules import RULE_IDS
    from app.modules.po_risk.thresholds import get_rule_config
    from app.modules.spend.thresholds import get_spend_config
    from app.modules.supplier_reco.thresholds import get_supplier_reco_config
    from app.services.ai.factory import describe_active_provider

    # 3. Directories
    print("\nDirectories")
    settings.ensure_directories()
    for label, directory in (
        ("data", settings.data_dir), ("uploads", settings.upload_dir),
        ("exports", settings.export_dir), ("sample", settings.sample_dir),
    ):
        writable = directory.is_dir()
        try:
            probe = directory / ".write_probe"
            probe.write_text("x", encoding="utf-8")
            probe.unlink()
        except OSError:
            writable = False
        print(f"{PASS if writable else FAIL} {label}: {directory}")
        if not writable:
            problems.append(f"Make {directory} writable.")

    # 4. Rule configuration
    print("\nRule configuration")
    try:
        config = get_rule_config()
        enabled = sum(1 for rule in config.rules.values() if rule.enabled)
        print(f"{PASS} version {config.config_version}: {enabled}/{len(config.rules)} rules enabled")
        undefined = set(RULE_IDS) - set(config.rules)
        if undefined:
            print(f"{FAIL} rules without configuration: {sorted(undefined)}")
            problems.append("Fix app/modules/po_risk/config/po_risk_rules.json")
    except Exception as exc:  # noqa: BLE001
        print(f"{FAIL} {exc}")
        problems.append("Fix the rule configuration file.")

    try:
        spend_config = get_spend_config()
        enabled_savings = len(spend_config.enabled_savings_rules)
        print(
            f"{PASS} spend configuration v{spend_config.config_version}: "
            f"{enabled_savings}/{len(spend_config.savings_rules)} savings rules enabled"
        )
    except Exception as exc:  # noqa: BLE001
        print(f"{FAIL} {exc}")
        problems.append("Fix app/modules/spend/config/spend_rules.json")

    try:
        reco_config = get_supplier_reco_config()
        reco_config.validate_weights(reco_config.default_weights)
        print(
            f"{PASS} supplier recommendation configuration v{reco_config.config_version}: "
            f"default weights sum to {reco_config.default_weights.total():g}%"
        )
    except Exception as exc:  # noqa: BLE001
        print(f"{FAIL} {exc}")
        problems.append("Fix app/modules/supplier_reco/config/supplier_reco_rules.json")

    try:
        from app.modules.invoice_validator.rules import RULE_IDS as INVOICE_RULE_IDS
        from app.modules.invoice_validator.thresholds import get_invoice_validator_config

        invoice_config = get_invoice_validator_config()
        enabled_rules = sum(1 for rule in invoice_config.rules.values() if rule.enabled)
        print(
            f"{PASS} invoice validator configuration v{invoice_config.config_version}: "
            f"{enabled_rules}/{len(invoice_config.rules)} rules enabled"
        )
        undefined_invoice = set(INVOICE_RULE_IDS) - set(invoice_config.rules)
        if undefined_invoice:
            print(f"{FAIL} invoice rules without configuration: {sorted(undefined_invoice)}")
            problems.append("Fix app/modules/invoice_validator/config/invoice_validator_rules.json")
    except Exception as exc:  # noqa: BLE001
        print(f"{FAIL} {exc}")
        problems.append("Fix app/modules/invoice_validator/config/invoice_validator_rules.json")

    # 5. Database
    print("\nDatabase")
    try:
        init_db()
        with engine.connect():
            pass
        print(f"{PASS} connected ({settings.database_url.split('://')[0]}) and schema ensured")
    except Exception as exc:  # noqa: BLE001
        print(f"{FAIL} {type(exc).__name__}")
        problems.append("Check DATABASE_URL in your .env file.")

    # 6. AI provider
    print("\nAI provider")
    provider = describe_active_provider()
    if provider["is_mock"]:
        print(f"{PASS} mock mode active - no API key needed")
    else:
        print(f"{PASS} {provider['resolved_provider']} ({provider['model']})")

    # 7. Sample data
    print("\nSample data")
    for label, filename, script in (
        ("PO risk", "sample_purchase_orders.csv", "scripts/generate_sample_data.py"),
        ("spend", "sample_spend_transactions.csv", "scripts/generate_spend_sample_data.py"),
        ("suppliers", "sample_suppliers.csv", "scripts/generate_supplier_sample_data.py"),
        ("invoices", "sample_invoices.csv", "scripts/generate_invoice_sample_data.py"),
    ):
        sample = settings.sample_dir / filename
        if sample.is_file():
            rows = sum(1 for _ in sample.open(encoding="utf-8")) - 1
            print(f"{PASS} {label}: {rows:,} demo rows available")
        else:
            print(f"{WARN} {label}: not generated yet")
            warnings.append(f"Run: python {script}")

    _report(problems, warnings)
    return 1 if problems else 0


def _report(problems: list[str], warnings: list[str]) -> None:
    """Print the closing summary."""
    print("\n" + "-" * 60)
    if problems:
        print("Setup incomplete:")
        for problem in problems:
            print(f"  - {problem}")
        return
    if warnings:
        print("Setup usable, with recommendations:")
        for warning in warnings:
            print(f"  - {warning}")
    else:
        print("Setup complete.")
    print("\nNext steps:")
    print("  1. uvicorn app.main:app --reload            # API on http://127.0.0.1:8000/docs")
    print("  2. streamlit run streamlit_app/Home.py      # UI  on http://localhost:8501")
    print("  3. pytest                                   # run the test suite")


if __name__ == "__main__":
    raise SystemExit(main())
