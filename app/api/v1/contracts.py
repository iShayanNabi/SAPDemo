"""HTTP routes for the Contract Assistant.

Routes stay thin: validate input, call the service layer, wrap the result in
the shared envelope. All business logic lives in
``app/modules/contract_assistant``.

The six routes the module is specified around:

* ``POST /contracts/upload``                    - upload and extract text
* ``POST /contracts/{contract_id}/analyze``     - run the deterministic analysis
* ``GET  /contracts/{contract_id}``             - the full analysis
* ``GET  /contracts/{contract_id}/clauses``     - the clause table
* ``POST /contracts/{contract_id}/questions``   - ask a question, get citations
* ``GET  /contracts/{contract_id}/export``      - download the report

plus the supporting endpoints a UI needs: the contract list, the clause and
rule catalogue, the extractor/OCR capability report, the AI provider status and
the bundled sample contracts.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import FileValidationError
from app.core.logging import get_logger
from app.core.security import resolve_safe_path
from app.models.session import get_db
from app.modules.contract_assistant import service
from app.schemas.common import ApiResponse
from app.schemas.contract_assistant import (
    AnalyzeContractRequest,
    ClauseListResponse,
    ContractAnswerSchema,
    ContractDetailSchema,
    ContractListResponse,
    ContractMethodologySchema,
    ContractQuestionRequest,
    ContractSampleDataInfo,
    ContractUploadResponse,
    ExportFormat,
)
from app.services.ai.factory import describe_active_provider
from app.services.documents.factory import describe_extractors
from app.services.exports.contract_report_builder import (
    build_contract_csv_report,
    build_contract_json_report,
    build_contract_xlsx_report,
)

logger = get_logger(__name__)

DbSession = Annotated[Session, Depends(get_db)]

EXPORT_MEDIA_TYPES = {
    ExportFormat.CSV: "text/csv",
    ExportFormat.JSON: "application/json",
    ExportFormat.XLSX: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

SAMPLE_MEDIA_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "txt": "text/plain",
}

router = APIRouter(prefix="/contracts", tags=["Contract Assistant"])


# ---------------------------------------------------------------------------
# Upload and analyse
# ---------------------------------------------------------------------------


@router.post(
    "/upload",
    response_model=ApiResponse[ContractUploadResponse],
    summary="Upload a contract document",
)
async def upload(
    db: DbSession,
    file: Annotated[UploadFile, File(description="Text-based PDF, DOCX or TXT contract")],
) -> ApiResponse[ContractUploadResponse]:
    """Validate a contract document, store it and extract its text.

    Text-based PDF, DOCX and TXT work with no OCR provider. A scanned document
    is accepted, reported as ``needs_ocr`` and explained - never silently
    analysed as an empty contract.
    """
    content = await file.read()
    if not content:
        raise FileValidationError("The uploaded document is empty.")
    if len(content) > settings.max_document_bytes:
        raise FileValidationError(
            f"The document exceeds the {settings.max_document_bytes // (1024 * 1024)} MB limit."
        )
    return ApiResponse.ok(service.handle_upload(db, file.filename or "contract", content))


@router.post(
    "/{contract_id}/analyze",
    response_model=ApiResponse[ContractDetailSchema],
    summary="Analyse an uploaded contract",
)
def analyze(
    db: DbSession, contract_id: str, request: AnalyzeContractRequest | None = None
) -> ApiResponse[ContractDetailSchema]:
    """Extract clauses, dates, obligations and risks from a stored contract.

    Every result is produced by deterministic rules. The optional AI narrative
    only explains them and lands in its own fields.
    """
    return ApiResponse.ok(
        service.analyze(db, contract_id, request or AnalyzeContractRequest())
    )


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=ApiResponse[ContractListResponse],
    summary="List uploaded contracts",
)
def list_contracts(
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ApiResponse[ContractListResponse]:
    """Return uploaded contracts, newest first."""
    total, contracts = service.list_contracts(db, limit=limit, offset=offset)
    return ApiResponse.ok(
        ContractListResponse(total=total, limit=limit, offset=offset, contracts=contracts)
    )


@router.get(
    "/methodology",
    response_model=ApiResponse[ContractMethodologySchema],
    summary="Clause catalogue, rules and settings",
)
def methodology() -> ApiResponse[ContractMethodologySchema]:
    """Return the clause types, the risk rules and the confidence formula."""
    return ApiResponse.ok(service.get_methodology())


@router.get(
    "/extractors",
    response_model=ApiResponse[dict[str, Any]],
    summary="Supported documents and OCR availability",
)
def extractors() -> ApiResponse[dict[str, Any]]:
    """Report which document types can be read, and whether OCR is configured.

    Credentials are never included - only whether each provider is installed
    and configured.
    """
    return ApiResponse.ok(describe_extractors())


@router.get(
    "/ai-status", response_model=ApiResponse[dict[str, Any]], summary="Active AI provider"
)
def ai_status() -> ApiResponse[dict[str, Any]]:
    """Report which AI provider is active. API keys are never included."""
    return ApiResponse.ok(describe_active_provider())


@router.get("/sample", summary="Download a bundled demo contract")
def download_sample(
    name: Annotated[str, Query(max_length=80, description="Sample contract stem")],
    file_format: Annotated[str, Query(alias="format", pattern="^(pdf|docx|txt)$")] = "pdf",
) -> Response:
    """Download one bundled fictional contract."""
    path = resolve_safe_path(settings.sample_dir, f"{name}.{file_format}")
    if not path.is_file():
        raise FileValidationError(
            "That sample contract has not been generated yet. "
            "Run: python scripts/generate_contract_sample_data.py",
            details={"requested": f"{name}.{file_format}"},
        )
    return Response(
        content=path.read_bytes(),
        media_type=SAMPLE_MEDIA_TYPES[file_format],
        headers={"Content-Disposition": f'attachment; filename="{path.name}"'},
    )


@router.get(
    "/sample/info",
    response_model=ApiResponse[ContractSampleDataInfo],
    summary="Demo contract set info",
)
def sample_info() -> ApiResponse[ContractSampleDataInfo]:
    """Describe the bundled fictional contracts and their manifest."""
    import json as json_module

    manifest_path = settings.sample_dir / "contract_scenario_manifest.json"
    if not manifest_path.is_file():
        return ApiResponse.ok(ContractSampleDataInfo(available=False))

    manifest = json_module.loads(manifest_path.read_text(encoding="utf-8"))
    contracts = manifest.get("contracts", [])
    return ApiResponse.ok(
        ContractSampleDataInfo(
            available=True,
            contract_count=len(contracts),
            scenario_count=len(manifest.get("scenarios", [])),
            as_of_date=manifest.get("as_of_date"),
            formats=list(manifest.get("formats", [])),
            contracts=[
                {
                    "name": item.get("name"),
                    "title": item.get("title"),
                    "summary": item.get("summary"),
                    "formats": item.get("formats", []),
                }
                for item in contracts
            ],
        )
    )


@router.get(
    "/{contract_id}",
    response_model=ApiResponse[ContractDetailSchema],
    summary="Get one contract analysis",
)
def get_contract(db: DbSession, contract_id: str) -> ApiResponse[ContractDetailSchema]:
    """Return the contract with its clauses, dates, obligations and risks."""
    return ApiResponse.ok(service.get_contract(db, contract_id))


@router.get(
    "/{contract_id}/clauses",
    response_model=ApiResponse[ClauseListResponse],
    summary="Get the clause table",
)
def get_clauses(
    db: DbSession,
    contract_id: str,
    present_only: Annotated[bool, Query()] = False,
    clause_type: Annotated[str | None, Query(max_length=40)] = None,
    min_confidence: Annotated[float | None, Query(ge=0.0, le=1.0)] = None,
) -> ApiResponse[ClauseListResponse]:
    """Return the extracted clauses, each with page, heading, excerpt and confidence."""
    return ApiResponse.ok(
        service.list_clauses(
            db,
            contract_id,
            present_only=present_only,
            clause_type=clause_type,
            min_confidence=min_confidence,
        )
    )


@router.post(
    "/{contract_id}/questions",
    response_model=ApiResponse[ContractAnswerSchema],
    summary="Ask a question about a contract",
)
def ask_question(
    db: DbSession, contract_id: str, request: ContractQuestionRequest
) -> ApiResponse[ContractAnswerSchema]:
    """Answer a question from the extracted clauses, citing page and heading.

    The answer is produced deterministically from what was extracted. When the
    contract does not cover the question, the assistant says so rather than
    producing a plausible sentence.
    """
    return ApiResponse.ok(service.ask(db, contract_id, request))


@router.get("/{contract_id}/export", summary="Download the contract report")
def export_contract(
    db: DbSession,
    contract_id: str,
    file_format: Annotated[ExportFormat, Query(alias="format")] = ExportFormat.XLSX,
) -> Response:
    """Download the analysis as XLSX, CSV or JSON."""
    payload = service.build_export_payload(db, contract_id)

    if file_format is ExportFormat.JSON:
        content = build_contract_json_report(payload)
    elif file_format is ExportFormat.CSV:
        content = build_contract_csv_report(payload.get("clauses", []))
    else:
        content = build_contract_xlsx_report(payload)

    filename = f"contract_{contract_id[:8]}.{file_format.value}"
    return Response(
        content=content,
        media_type=EXPORT_MEDIA_TYPES[file_format],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
