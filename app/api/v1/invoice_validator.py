"""HTTP routes for the Invoice Validator.

Routes stay thin: validate input, call the service layer, wrap the result in the
shared envelope. All business logic lives in ``app/modules/invoice_validator``.

The upload route accepts a ``dataset`` form field so the same endpoint profiles
invoices, purchase orders and goods receipts against the correct field registry.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import FileValidationError
from app.core.logging import get_logger
from app.models.session import get_db
from app.modules.invoice_validator import service
from app.schemas.common import ApiResponse
from app.schemas.invoice_validator import (
    DatasetFieldCatalogue,
    DatasetKind,
    ExceptionListResponse,
    ExportFormat,
    InvoiceUploadResponse,
    RuleCatalogueSchema,
    SampleDataInfo,
    ValidateRequest,
    ValidationDetailSchema,
    ValidationListResponse,
)
from app.services.ai.factory import describe_active_provider
from app.services.files.uploads import read_upload_within_limit

logger = get_logger(__name__)

router = APIRouter(prefix="/invoices", tags=["Invoice Validator"])

DbSession = Annotated[Session, Depends(get_db)]

MEDIA_TYPES = {
    "csv": "text/csv",
    "json": "application/json",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

#: dataset -> sample file stem
_SAMPLE_STEMS = {
    DatasetKind.INVOICES: "sample_invoices",
    DatasetKind.PURCHASE_ORDERS: "sample_invoice_purchase_orders",
    DatasetKind.GOODS_RECEIPTS: "sample_goods_receipts",
}


@router.post("/upload", response_model=ApiResponse[InvoiceUploadResponse], summary="Upload a file")
async def upload_file(
    db: DbSession,
    dataset: Annotated[DatasetKind, Form(description="invoices | purchase_orders | goods_receipts")],
    file: Annotated[UploadFile, File(description="CSV, XLSX or JSON file for the chosen dataset")],
) -> ApiResponse[InvoiceUploadResponse]:
    """Validate a file, store it and suggest a column mapping for the dataset."""
    content = await read_upload_within_limit(file)
    result = service.handle_upload(db, dataset, file.filename or "upload", content)
    return ApiResponse.ok(result)


@router.post(
    "/validate", response_model=ApiResponse[ValidationDetailSchema], summary="Validate invoices"
)
def validate(db: DbSession, request: ValidateRequest) -> ApiResponse[ValidationDetailSchema]:
    """Three-way match the uploaded invoices and raise deterministic exceptions."""
    return ApiResponse.ok(service.validate(db, request))


@router.get(
    "/validations", response_model=ApiResponse[ValidationListResponse], summary="List validations"
)
def list_validations(
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ApiResponse[ValidationListResponse]:
    """Return previous validations, newest first."""
    total, validations = service.list_validations(db, limit=limit, offset=offset)
    return ApiResponse.ok(
        ValidationListResponse(total=total, limit=limit, offset=offset, validations=validations)
    )


@router.get(
    "/validations/{validation_id}",
    response_model=ApiResponse[ValidationDetailSchema],
    summary="Get one validation",
)
def get_validation(db: DbSession, validation_id: str) -> ApiResponse[ValidationDetailSchema]:
    """Return KPIs, supplier summary, three-way-match rows and the AI narrative."""
    return ApiResponse.ok(service.get_validation(db, validation_id))


@router.get(
    "/validations/{validation_id}/exceptions",
    response_model=ApiResponse[ExceptionListResponse],
    summary="List exceptions",
)
def list_exceptions(
    db: DbSession,
    validation_id: str,
    severity: Annotated[list[str] | None, Query(description="low|medium|high|critical")] = None,
    rule_id: Annotated[str | None, Query(max_length=20)] = None,
    exception_type: Annotated[str | None, Query(max_length=40)] = None,
    category: Annotated[str | None, Query(max_length=40)] = None,
    supplier_id: Annotated[str | None, Query(max_length=20)] = None,
    invoice_number: Annotated[str | None, Query(max_length=40)] = None,
    po_number: Annotated[str | None, Query(max_length=20)] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ApiResponse[ExceptionListResponse]:
    """Return a filtered, paginated list of exceptions."""
    total, exceptions = service.list_exceptions(
        db,
        validation_id,
        severity=severity,
        rule_id=rule_id,
        exception_type=exception_type,
        category=category,
        supplier_id=supplier_id,
        invoice_number=invoice_number,
        po_number=po_number,
        limit=limit,
        offset=offset,
    )
    return ApiResponse.ok(
        ExceptionListResponse(
            validation_id=validation_id, total=total, limit=limit, offset=offset, exceptions=exceptions
        )
    )


@router.get("/validations/{validation_id}/export", summary="Download a report")
def export_validation(
    db: DbSession,
    validation_id: str,
    export_format: Annotated[ExportFormat, Query(alias="format")] = ExportFormat.XLSX,
) -> Response:
    """Download the validation as XLSX, CSV or JSON."""
    content, filename, media_type = service.export_validation(db, validation_id, export_format)
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/fields", response_model=ApiResponse[DatasetFieldCatalogue], summary="Field catalogue")
def get_fields() -> ApiResponse[DatasetFieldCatalogue]:
    """Return the canonical fields for all three datasets and their SAP aliases."""
    return ApiResponse.ok(service.get_field_catalogue())


@router.get("/rules", response_model=ApiResponse[RuleCatalogueSchema], summary="Rule catalogue")
def get_rules() -> ApiResponse[RuleCatalogueSchema]:
    """Return every configured rule with the active tolerances and policies."""
    return ApiResponse.ok(service.get_rule_catalogue())


@router.get("/sample", summary="Download a demo dataset")
def download_sample(
    dataset: Annotated[DatasetKind, Query()] = DatasetKind.INVOICES,
    file_format: Annotated[str, Query(alias="format", pattern="^(csv|xlsx|json)$")] = "csv",
) -> Response:
    """Download one of the bundled fictional demo files."""
    from app.core.security import resolve_safe_path

    stem = _SAMPLE_STEMS[dataset]
    path = resolve_safe_path(settings.sample_dir, f"{stem}.{file_format}")
    if not path.is_file():
        raise FileValidationError(
            "The invoice sample datasets have not been generated yet. "
            "Run: python scripts/generate_invoice_sample_data.py",
        )
    return Response(
        content=path.read_bytes(),
        media_type=MEDIA_TYPES[file_format],
        headers={"Content-Disposition": f'attachment; filename="{path.name}"'},
    )


@router.get("/sample/info", response_model=ApiResponse[SampleDataInfo], summary="Demo dataset info")
def sample_info() -> ApiResponse[SampleDataInfo]:
    """Describe the bundled demo invoice datasets and their scenario manifest."""
    import csv as csv_module
    import json as json_module

    invoices = settings.sample_dir / "sample_invoices.csv"
    receipts = settings.sample_dir / "sample_goods_receipts.csv"
    purchase_orders = settings.sample_dir / "sample_invoice_purchase_orders.csv"
    manifest_path = settings.sample_dir / "invoice_scenario_manifest.json"

    if not invoices.is_file():
        return ApiResponse.ok(SampleDataInfo(available=False))

    def _rows(path) -> int | None:
        if not path.is_file():
            return None
        with path.open(encoding="utf-8") as handle:
            return sum(1 for _ in csv_module.reader(handle)) - 1

    scenario_count = None
    if manifest_path.is_file():
        manifest = json_module.loads(manifest_path.read_text(encoding="utf-8"))
        scenario_count = len(manifest.get("scenarios", []))

    return ApiResponse.ok(
        SampleDataInfo(
            available=True,
            invoice_count=_rows(invoices),
            goods_receipt_count=_rows(receipts),
            purchase_order_line_count=_rows(purchase_orders),
            scenario_count=scenario_count,
        )
    )


@router.get("/ai-status", response_model=ApiResponse[dict[str, Any]], summary="Active AI provider")
def ai_status() -> ApiResponse[dict[str, Any]]:
    """Report which AI provider is active. API keys are never included."""
    return ApiResponse.ok(describe_active_provider())
