"""The guided demonstration catalogue.

One entry per module. Each entry says what the module is for, which bundled
fictional file it reads, which part of the answer is arithmetic and which part
is prose - and, for the seven modules that take a file, how to hand them that
file without an upload.

**No analysis happens here.** The loaders below call the same
``service.handle_upload`` that a real upload reaches, with bytes read from
``data/sample/``. That is the whole trick: a demonstration that goes through a
different code path is a demonstration of a different application.

The descriptive text is the authoritative copy. The public website mirrors it
in ``frontend/content/modules.ts``, and a test asserts the identifiers, numbers
and names agree, so the two cannot drift on anything load-bearing.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.demo import trusted_ingest
from app.core.exceptions import AppError
from app.core.logging import get_logger
from app.schemas.demo import (
    DemoDatasetInfo,
    DemoLoadedDataset,
    DemoLoadResponse,
    DemoModuleInfo,
)

logger = get_logger(__name__)

#: How a module receives its input. Modules 8-10 take a structured request
#: rather than a file, so "load the demo data" means "start from a bundled
#: scenario", which their own ``/sample`` endpoints already serve.
TABULAR = "tabular_upload"
DOCUMENT = "document_upload"
STRUCTURED = "structured_request"


class DemoNotAvailableError(AppError):
    """A demonstration was requested for something that cannot be loaded."""

    code = "demo_not_available"
    http_status = 404


@dataclass(frozen=True)
class DemoModuleSpec:
    """Everything the guided demonstration needs to know about one module."""

    key: str
    number: int
    name: str
    input_style: str
    #: ``{dataset key: bundled filename}``, in the order they are ingested.
    files: dict[str, str]
    business_question: str
    deterministic_summary: str
    ai_summary: str
    expected_output: str
    #: Ingests the bundled files and returns the handles the module's own
    #: analysis endpoint needs. ``None`` for the structured-request modules.
    loader: Callable[[Session, DemoModuleSpec], DemoLoadResponse] | None = None
    analyze_path: str = ""
    steps: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Reading a bundled file
# ---------------------------------------------------------------------------
def _sample_path(filename: str) -> Path:
    """Resolve a bundled sample file, refusing anything outside the directory."""
    from app.core.security import resolve_safe_path

    return resolve_safe_path(settings.sample_dir, filename)


def _sample_bytes(filename: str) -> bytes:
    """Read a bundled sample file, or explain exactly what is missing."""
    path = _sample_path(filename)
    if not path.is_file():
        raise DemoNotAvailableError(
            f"The bundled demonstration file '{filename}' is not present. Regenerate the "
            f"sample data with the matching scripts/generate_*_sample_data.py script.",
            details={"filename": filename},
        )
    return path.read_bytes()


def _loaded(
    spec: DemoModuleSpec,
    datasets: list[DemoLoadedDataset],
    *,
    analyze_payload: dict[str, object],
    uploads: dict[str, object] | None = None,
    suggested_parameters: dict[str, object] | None = None,
    notes: list[str] | None = None,
) -> DemoLoadResponse:
    """Assemble the response every loader returns."""
    return DemoLoadResponse(
        module=spec.key,
        number=spec.number,
        name=spec.name,
        datasets=datasets,
        analyze_path=spec.analyze_path,
        analyze_payload=analyze_payload,
        uploads=uploads or {},
        suggested_parameters=suggested_parameters or {},
        notes=notes or [],
    )


def _dump(result: object) -> dict[str, object]:
    """Serialise a module's own upload response for the page that renders it."""
    return result.model_dump(mode="json")  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# One loader per file-taking module
# ---------------------------------------------------------------------------
def _load_po_risk(db: Session, spec: DemoModuleSpec) -> DemoLoadResponse:
    from app.modules.po_risk import service

    name = spec.files["purchase_orders"]
    result = service.handle_upload(db, name, _sample_bytes(name))
    return _loaded(
        spec,
        [
            DemoLoadedDataset(
                key="purchase_orders",
                filename=name,
                identifier_name="upload_id",
                identifier=result.upload_id,
                row_count=result.row_count,
            )
        ],
        analyze_payload={"upload_id": result.upload_id},
        uploads={"purchase_orders": _dump(result)},
    )


def _load_spend(db: Session, spec: DemoModuleSpec) -> DemoLoadResponse:
    from app.modules.spend import service

    name = spec.files["transactions"]
    result = service.handle_upload(db, name, _sample_bytes(name))
    return _loaded(
        spec,
        [
            DemoLoadedDataset(
                key="transactions",
                filename=name,
                identifier_name="upload_id",
                identifier=result.upload_id,
                row_count=result.row_count,
            )
        ],
        analyze_payload={"upload_id": result.upload_id},
        uploads={"transactions": _dump(result)},
    )


def _load_supplier_reco(db: Session, spec: DemoModuleSpec) -> DemoLoadResponse:
    from app.modules.supplier_reco import service

    name = spec.files["suppliers"]
    result = service.handle_supplier_upload(db, name, _sample_bytes(name))
    return _loaded(
        spec,
        [
            DemoLoadedDataset(
                key="suppliers",
                filename=name,
                identifier_name="catalog_id",
                identifier=result.catalog_id,
                row_count=result.supplier_count,
            )
        ],
        analyze_payload={"catalog_id": result.catalog_id},
        uploads={"suppliers": _dump(result)},
        notes=[
            "The requirement to rank against (material, quantity, plant, dates, target price) "
            "is yours to set - the demonstration supplies the supplier catalogue only."
        ],
    )


def _load_invoice_validator(db: Session, spec: DemoModuleSpec) -> DemoLoadResponse:
    from app.modules.invoice_validator import service
    from app.schemas.invoice_validator import DatasetKind

    kinds = {
        "invoices": DatasetKind.INVOICES,
        "purchase_orders": DatasetKind.PURCHASE_ORDERS,
        "goods_receipts": DatasetKind.GOODS_RECEIPTS,
    }
    datasets: list[DemoLoadedDataset] = []
    payload: dict[str, object] = {}
    payload_keys = {
        "invoices": "invoice_upload_id",
        "purchase_orders": "po_upload_id",
        "goods_receipts": "gr_upload_id",
    }
    uploads: dict[str, object] = {}
    for key, kind in kinds.items():
        name = spec.files[key]
        result = service.handle_upload(db, kind, name, _sample_bytes(name))
        uploads[key] = _dump(result)
        datasets.append(
            DemoLoadedDataset(
                key=key,
                filename=name,
                identifier_name="upload_id",
                identifier=result.upload_id,
                row_count=result.row_count,
            )
        )
        payload[payload_keys[key]] = result.upload_id
    return _loaded(spec, datasets, analyze_payload=payload, uploads=uploads)


def _load_supplier_risk(db: Session, spec: DemoModuleSpec) -> DemoLoadResponse:
    from app.modules.supplier_risk import service
    from app.schemas.supplier_risk import RiskDatasetKind

    profiles_name = spec.files["profiles"]
    profiles = service.handle_upload(
        db, profiles_name, _sample_bytes(profiles_name), dataset=RiskDatasetKind.PROFILES
    )
    dataset_id = profiles.dataset_id
    datasets = [
        DemoLoadedDataset(
            key="profiles",
            filename=profiles_name,
            identifier_name="dataset_id",
            identifier=dataset_id or "",
            row_count=profiles.row_count,
        )
    ]

    events_name = spec.files["events"]
    events = service.handle_upload(
        db,
        events_name,
        _sample_bytes(events_name),
        dataset=RiskDatasetKind.EVENTS,
        dataset_id=dataset_id,
    )
    datasets.append(
        DemoLoadedDataset(
            key="events",
            filename=events_name,
            identifier_name="dataset_id",
            identifier=events.dataset_id or dataset_id or "",
            row_count=events.row_count,
        )
    )
    return _loaded(
        spec,
        datasets,
        analyze_payload={"dataset_id": dataset_id},
        uploads={"profiles": _dump(profiles), "events": _dump(events)},
    )


def _load_contracts(db: Session, spec: DemoModuleSpec) -> DemoLoadResponse:
    from app.modules.contract_assistant import service

    datasets: list[DemoLoadedDataset] = []
    uploads: dict[str, object] = {}
    first_id = ""
    for key, name in spec.files.items():
        result = service.handle_upload(db, name, _sample_bytes(name))
        uploads[key] = _dump(result)
        first_id = first_id or result.contract_id
        datasets.append(
            DemoLoadedDataset(
                key=key,
                filename=name,
                identifier_name="contract_id",
                identifier=result.contract_id,
                row_count=result.page_count,
            )
        )
    return _loaded(
        spec,
        datasets,
        analyze_payload={"contract_id": first_id},
        uploads=uploads,
        notes=[
            "Three fictional contracts are loaded. One of them contains a deliberate "
            "prompt-injection attempt, so the demonstration also shows how untrusted "
            "document text is neutralised before it is printed or sent to a provider."
        ],
    )


def _load_inventory(db: Session, spec: DemoModuleSpec) -> DemoLoadResponse:
    from app.modules.inventory import service

    name = spec.files["history"]
    result = service.handle_upload(db, name, _sample_bytes(name))
    # The as-of date comes from the file that was just read, never from a
    # constant. A hardcoded date silently becomes wrong the day the generator
    # is re-run, and an as-of date outside the history's range is how module 7
    # produced a reorder plan for a window it had no demand for.
    suggested: dict[str, object] = {"horizon_periods": 6}
    if result.history_end is not None:
        suggested["as_of_date"] = result.history_end.isoformat()
    return _loaded(
        spec,
        [
            DemoLoadedDataset(
                key="history",
                filename=name,
                identifier_name="dataset_id",
                identifier=result.dataset_id or "",
                row_count=result.row_count,
            )
        ],
        analyze_payload={"dataset_id": result.dataset_id},
        uploads={"history": _dump(result)},
        suggested_parameters=suggested,
    )


# ---------------------------------------------------------------------------
# The catalogue
# ---------------------------------------------------------------------------
DEMO_MODULES: tuple[DemoModuleSpec, ...] = (
    DemoModuleSpec(
        key="po_risk",
        number=1,
        name="Purchase Order Risk Checker",
        input_style=TABULAR,
        files={"purchase_orders": "sample_purchase_orders.csv"},
        analyze_path="/po-risk/analyze",
        loader=_load_po_risk,
        business_question=(
            "Which purchase order lines in this export deserve a buyer's attention before "
            "they are released?"
        ),
        deterministic_summary=(
            "Every finding, severity, exposure figure and confidence score is produced by "
            "configured Python rules reading the file. The thresholds live in JSON, so "
            "changing what counts as risky is a configuration edit, not a code change."
        ),
        ai_summary=(
            "AI writes an optional plain-language narrative *about* the findings. It cannot "
            "add, remove or reweight one, and its text is carried in separate fields."
        ),
        expected_output=(
            "A ranked list of findings with rule identifiers, evidence and recommended "
            "actions, plus supplier-level risk and data-quality issues. Exportable as XLSX, "
            "CSV or JSON."
        ),
        steps=(
            "Load the bundled fictional purchase order export.",
            "Review the suggested column mapping the reader inferred.",
            "Run the analysis and read the findings by severity.",
            "Download the report.",
        ),
    ),
    DemoModuleSpec(
        key="spend_analytics",
        number=2,
        name="Spend Analytics Dashboard",
        input_style=TABULAR,
        files={"transactions": "sample_spend_transactions.csv"},
        analyze_path="/spend/analyze",
        loader=_load_spend,
        business_question=(
            "Where is the money going, and which patterns in it look like leakage worth "
            "investigating?"
        ),
        deterministic_summary=(
            "All aggregation, concentration, maverick-spend detection, tail analysis and "
            "opportunity sizing is pandas arithmetic over the transactions. Reported "
            "averages are summed in Decimal, so the same input always gives the same figure."
        ),
        ai_summary=(
            "AI summarises the picture in business language. Every number in the dashboard "
            "exists before any provider is contacted."
        ),
        expected_output=(
            "Spend by category, supplier, plant and period; concentration measures; a list "
            "of estimated savings opportunities; drill-down to the underlying transactions."
        ),
        steps=(
            "Load the bundled fictional transaction file.",
            "Run the analysis.",
            "Read the KPI row, then drill into a category or supplier.",
            "Open an opportunity and check the transactions behind it.",
        ),
    ),
    DemoModuleSpec(
        key="supplier_recommendation",
        number=3,
        name="Supplier Recommendation Engine",
        input_style=TABULAR,
        files={"suppliers": "sample_suppliers.csv"},
        analyze_path="/supplier-recommendations/recommend",
        loader=_load_supplier_reco,
        business_question=(
            "Given a requirement - this material, this quantity, this plant, this date - "
            "which suppliers can actually serve it, and in what order?"
        ),
        deterministic_summary=(
            "Eligibility is a set of hard filters; ranking is a transparent weighted score "
            "over price, delivery, quality, capacity, risk and contract status. Every "
            "weight and every threshold is configuration, and each score shows its parts."
        ),
        ai_summary=(
            "AI explains why the leading supplier ranked where it did. The ranking itself is "
            "arithmetic and does not move."
        ),
        expected_output=(
            "The eligible suppliers in rank order, each with a score breakdown, the reasons "
            "any supplier was excluded, and the sensitivity of the ranking to the weights."
        ),
        steps=(
            "Load the bundled fictional supplier catalogue.",
            "Describe a requirement.",
            "Rank the suppliers and open a score breakdown.",
            "Change a weight and watch the order move.",
        ),
    ),
    DemoModuleSpec(
        key="invoice_validator",
        number=4,
        name="Invoice Validator",
        input_style=TABULAR,
        files={
            "invoices": "sample_invoices.csv",
            "purchase_orders": "sample_invoice_purchase_orders.csv",
            "goods_receipts": "sample_goods_receipts.csv",
        },
        analyze_path="/invoices/validate",
        loader=_load_invoice_validator,
        business_question=(
            "Which of these supplier invoices should not be paid as submitted?"
        ),
        deterministic_summary=(
            "A three-way match across invoices, purchase orders and goods receipts, plus "
            "duplicate detection, tolerance checks and cumulative over-billing. Each control "
            "has a distinct trigger so one problem raises one exception rather than three."
        ),
        ai_summary=(
            "AI drafts the explanation an AP clerk would send to the supplier. The exception "
            "and the amount are computed."
        ),
        expected_output=(
            "Per-invoice exceptions with severity, the documents compared, the amounts that "
            "disagreed, and a pay / hold / investigate recommendation."
        ),
        steps=(
            "Load the three bundled fictional datasets.",
            "Set the matching tolerances, or keep the configured defaults.",
            "Run the validation.",
            "Open an exception and read the three documents side by side.",
        ),
    ),
    DemoModuleSpec(
        key="supplier_risk_copilot",
        number=5,
        name="Supplier Risk Copilot",
        input_style=TABULAR,
        files={
            "profiles": "sample_supplier_risk_profiles.csv",
            "events": "sample_supplier_risk_events.csv",
        },
        analyze_path="/supplier-risk/calculate",
        loader=_load_supplier_risk,
        business_question=(
            "Across ten risk categories, which suppliers are exposed, and what is driving it?"
        ),
        deterministic_summary=(
            "A weighted score per category and an overall band, computed from the profile "
            "data and the dated internal events. Missing data is reported as missing rather "
            "than scored as zero."
        ),
        ai_summary=(
            "The copilot answers questions in prose, but every answer is grounded in the "
            "loaded records and carries citations back to them."
        ),
        expected_output=(
            "A scored supplier list with category breakdowns, the events behind each score, "
            "and a question-and-answer panel with citations."
        ),
        steps=(
            "Load the bundled fictional supplier profiles and risk events.",
            "Calculate the risk scores.",
            "Open a supplier and read the category breakdown.",
            "Ask the copilot a question and follow its citations.",
        ),
    ),
    DemoModuleSpec(
        key="contract_assistant",
        number=6,
        name="Contract Assistant",
        input_style=DOCUMENT,
        files={
            "msa": "sample_contract_msa_nordwind.pdf",
            "nda": "sample_contract_nda_meridian.pdf",
            "saas": "sample_contract_saas_helvetia.docx",
        },
        analyze_path="/contracts/{contract_id}/analyze",
        loader=_load_contracts,
        business_question=(
            "What does this contract actually commit us to, and where does each answer come "
            "from?"
        ),
        deterministic_summary=(
            "Clause detection, key dates, obligations and risk flags are pattern-based over "
            "per-page extracted text. Every extracted claim carries a page number, a section "
            "heading, an excerpt and a confidence score built from the evidence seen."
        ),
        ai_summary=(
            "AI answers questions about the contract and summarises it. It never supplies a "
            "date or a party name that extraction did not find."
        ),
        expected_output=(
            "Extracted clauses, dates, obligations and risks - each citing its page - plus a "
            "question-and-answer panel. A document with no extractable text is reported as "
            "needing OCR rather than analysed as empty."
        ),
        steps=(
            "Load the bundled fictional contracts.",
            "Analyse one and read the extracted clauses.",
            "Click a citation to see the page and excerpt it came from.",
            "Ask a question about the contract.",
        ),
    ),
    DemoModuleSpec(
        key="inventory_predictor",
        number=7,
        name="Inventory Predictor",
        input_style=TABULAR,
        files={"history": "sample_inventory_history.csv"},
        analyze_path="/inventory/forecast",
        loader=_load_inventory,
        business_question=(
            "Which materials will run short, on what date, and when should we reorder?"
        ),
        deterministic_summary=(
            "Five explainable statistical models are backtested per material on identical "
            "held-out periods, and the winner has to beat the simpler model by a stated "
            "margin. The stock projection walks real calendar days, so a shortage lands on a "
            "date rather than in a month. No AI produces any number."
        ),
        ai_summary=(
            "AI explains the forecast and the recommendation in planner's language. Every "
            "figure - and the choice of model - is statistical."
        ),
        expected_output=(
            "Per-material forecasts with the chosen model and why it won, projected stock "
            "levels, shortage dates, reorder recommendations and stock classifications."
        ),
        steps=(
            "Load the bundled fictional demand history.",
            "Run the forecast for the suggested horizon.",
            "Open a material and read which model was selected and why.",
            "Check the projected shortage date against the reorder trigger.",
        ),
    ),
    DemoModuleSpec(
        key="test_case_generator",
        number=8,
        name="SAP Test Case Generator",
        input_style=STRUCTURED,
        files={"processes": "sample_test_case_processes.json"},
        analyze_path="/test-cases/generate",
        business_question=(
            "We are testing this SAP process. What does the test suite need to cover?"
        ),
        deterministic_summary=(
            "How many cases each requested type gets, what each is called, which aspect it "
            "covers and how urgent it is are all decided before a provider is contacted. "
            "Step numbering, identifiers and the type allocation are code."
        ),
        ai_summary=(
            "AI drafts the wording of each case against that skeleton. If it fails, returns "
            "the wrong shape or leaves a field blank, the case is completed from templates "
            "and the repair is recorded on it."
        ),
        expected_output=(
            "An editable suite across eight test types, each case labelled with what produced "
            "it, with approval and execution tracking and CSV / XLSX / JSON / PDF export."
        ),
        steps=(
            "Start from a bundled fictional process, or describe your own.",
            "Choose the test types and the case count.",
            "Generate the suite.",
            "Edit a case, approve it, record a result and export.",
        ),
    ),
    DemoModuleSpec(
        key="blueprint_generator",
        number=9,
        name="SAP Blueprint Generator",
        input_style=STRUCTURED,
        files={"projects": "sample_blueprint_projects.json"},
        analyze_path="/blueprints/generate",
        business_question=(
            "What does a thirty-section implementation blueprint for this project look like?"
        ),
        deterministic_summary=(
            "The section list, organisational structure, module list, integration register, "
            "interface list, migration sources and security roles are computed from the "
            "project request. A section whose inputs are missing says which field to fill in "
            "rather than inventing content."
        ),
        ai_summary=(
            "AI drafts the prose of the remaining sections, in batches, so a failed batch "
            "costs six sections their wording and nothing else."
        ),
        expected_output=(
            "An editable, versioned blueprint with per-section approval, staleness flags when "
            "a section's inputs change after approval, version comparison, and Markdown / "
            "JSON / DOCX / PDF export."
        ),
        steps=(
            "Start from a bundled fictional project, or describe your own.",
            "Generate the blueprint.",
            "Edit the scope section and watch the sections that depended on it flag as stale.",
            "Save a version, compare it with the previous one, and export.",
        ),
    ),
    DemoModuleSpec(
        key="interview_coach",
        number=10,
        name="SAP Interview Coach",
        input_style=STRUCTURED,
        files={"questions": "sample_interview_questions.json"},
        analyze_path="/interviews/start",
        business_question=(
            "How well would this answer do in an SAP interview, and what is missing from it?"
        ),
        deterministic_summary=(
            "Every score is calculated from an explicit rubric by Python, with the matched "
            "keyword shown next to each credited concept. A dimension the question does not "
            "test is reported as not applicable rather than scored zero, and the clock never "
            "moves a mark."
        ),
        ai_summary=(
            "AI writes the coaching prose around a finished verdict. It is shown the labels, "
            "never the marking scheme, and it cannot change a score."
        ),
        expected_output=(
            "Per-answer scores across up to five dimensions with the evidence for each, "
            "session summaries, and a performance dashboard with weak areas and a study plan "
            "derived from the answers themselves."
        ),
        steps=(
            "Start a session on one or more tracks.",
            "Answer a question in your own words.",
            "Read the score, the matched keywords and the missing concepts.",
            "Complete the session and open the performance dashboard.",
        ),
    ),
)

_BY_KEY: dict[str, DemoModuleSpec] = {spec.key: spec for spec in DEMO_MODULES}


def get_module_spec(key: str) -> DemoModuleSpec:
    """Return one module's demonstration specification."""
    spec = _BY_KEY.get(key)
    if spec is None:
        raise DemoNotAvailableError(
            f"'{key}' is not one of the demonstration modules.",
            details={"known_modules": sorted(_BY_KEY)},
        )
    return spec


def describe_modules() -> list[DemoModuleInfo]:
    """Describe every module's demonstration, including which files are present."""
    described: list[DemoModuleInfo] = []
    for spec in DEMO_MODULES:
        datasets: list[DemoDatasetInfo] = []
        for key, filename in spec.files.items():
            path = _sample_path(filename)
            exists = path.is_file()
            datasets.append(
                DemoDatasetInfo(
                    key=key,
                    filename=filename,
                    available=exists,
                    size_bytes=path.stat().st_size if exists else None,
                )
            )
        described.append(
            DemoModuleInfo(
                module=spec.key,
                number=spec.number,
                name=spec.name,
                loadable=spec.loader is not None and all(d.available for d in datasets),
                input_style=spec.input_style,
                datasets=datasets,
                business_question=spec.business_question,
                deterministic_summary=spec.deterministic_summary,
                ai_summary=spec.ai_summary,
                expected_output=spec.expected_output,
            )
        )
    return described


def load_module_demo(db: Session, key: str) -> DemoLoadResponse:
    """Ingest one module's bundled demonstration data.

    Raises:
        DemoNotAvailableError: for an unknown module, a module that takes a
            structured request rather than a file, or a missing bundled file.
    """
    spec = get_module_spec(key)
    if spec.loader is None:
        raise DemoNotAvailableError(
            f"{spec.name} takes a structured request rather than a file, so there is "
            f"nothing to load. Start it from a bundled scenario instead.",
            details={"module": spec.key, "input_style": spec.input_style},
        )
    logger.info("Loading the bundled demonstration data for %s.", spec.key)
    # The bytes come from data/sample/, not from the request. Without this the
    # public demo's own Load Demo button is refused by the guard that exists to
    # refuse strangers' files - which is exactly what happened the first time
    # this ran.
    with trusted_ingest():
        return spec.loader(db, spec)
