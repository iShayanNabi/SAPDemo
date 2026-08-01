"""HTTP routes for the SAP Blueprint Generator.

Routes stay thin: validate input, call the service layer, wrap the result in the
shared envelope. All business logic lives in ``app/modules/blueprint_generator``.

The six routes the module is specified around:

* ``POST   /blueprints/generate``                                  - generate
* ``GET    /blueprints/{blueprint_id}``                            - read
* ``PUT    /blueprints/{blueprint_id}``                            - edit
* ``POST   /blueprints/{blueprint_id}/sections/{section_id}/regenerate``
* ``GET    /blueprints/{blueprint_id}/versions``                   - history
* ``GET    /blueprints/{blueprint_id}/export``                     - download

plus the endpoints an editable, reviewable document needs: edit one section,
approve one section, add a custom section, delete a custom section, save a
version, read a version, compare two versions, list blueprints, and the
catalogue that lets a client render the project form and the section navigator.

Route order matters here: the static paths (``/catalog``, ``/ai-status``,
``/sample``) are declared before ``/{blueprint_id}``, and
``/versions/compare`` before ``/versions/{version_number}``, otherwise FastAPI
would match "catalog" as a blueprint id and "compare" as a version number.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.openapi import COMMON_ERROR_RESPONSES
from app.core.logging import get_logger
from app.models.session import get_db
from app.modules.blueprint_generator import service
from app.schemas.blueprint import (
    ApproveSectionRequest,
    BlueprintCatalogueSchema,
    BlueprintListResponse,
    BlueprintSampleInfo,
    BlueprintSchema,
    BlueprintSectionSchema,
    BlueprintVersionSchema,
    CreateSectionRequest,
    CreateVersionRequest,
    DeleteSectionResponse,
    ExportFormat,
    GenerateBlueprintRequest,
    RegenerateSectionRequest,
    UpdateBlueprintRequest,
    UpdateSectionRequest,
    VersionComparisonSchema,
    VersionListResponse,
)
from app.schemas.common import ApiResponse
from app.services.ai.factory import describe_active_provider
from app.services.exports.blueprint_report_builder import (
    build_blueprint_docx_report,
    build_blueprint_json_report,
    build_blueprint_markdown_report,
    build_blueprint_pdf_report,
)

logger = get_logger(__name__)

DbSession = Annotated[Session, Depends(get_db)]

EXPORT_MEDIA_TYPES = {
    ExportFormat.MARKDOWN: "text/markdown; charset=utf-8",
    ExportFormat.JSON: "application/json",
    ExportFormat.DOCX: (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ),
    ExportFormat.PDF: "application/pdf",
}

EXPORT_EXTENSIONS = {
    ExportFormat.MARKDOWN: "md",
    ExportFormat.JSON: "json",
    ExportFormat.DOCX: "docx",
    ExportFormat.PDF: "pdf",
}

router = APIRouter(
    prefix="/blueprints",
    tags=["SAP Blueprint Generator"],
    # The error shapes every route in this module can return, documented
    # once so a generated client writes its error handling against the
    # contract rather than against whatever it happened to hit first.
    responses=COMMON_ERROR_RESPONSES,
)


# ---------------------------------------------------------------------------
# Generate
# ---------------------------------------------------------------------------


@router.post(
    "/generate",
    response_model=ApiResponse[BlueprintSchema],
    summary="Generate an SAP implementation blueprint",
)
def generate(
    db: DbSession, request: GenerateBlueprintRequest
) -> ApiResponse[BlueprintSchema]:
    """Generate a complete blueprint from a structured project request.

    The section list, the section order, the organisational structure, the
    module list, the integration register, the interface list, the migration
    sources and the security roles are computed by deterministic Python before
    any provider is called. If the provider is unavailable, or ``use_ai`` is
    false, the configured templates write every section - the document is
    complete either way, and each section says which produced it.

    A section whose required project fields are empty is returned as
    ``needs_input`` with the missing field named, never filled with invention.

    The result is a **proposed** blueprint requiring review by qualified SAP
    professionals. No configuration described in it has been validated against a
    live SAP system.
    """
    return ApiResponse.ok(service.generate(db, request))


# ---------------------------------------------------------------------------
# Catalogue and samples (declared before /{blueprint_id})
# ---------------------------------------------------------------------------


@router.get(
    "/catalog",
    response_model=ApiResponse[BlueprintCatalogueSchema],
    summary="Sections, project fields and the deterministic rules",
)
def catalog() -> ApiResponse[BlueprintCatalogueSchema]:
    """Return the supported sections and how the generator makes its decisions."""
    return ApiResponse.ok(service.get_catalogue())


@router.get(
    "/ai-status", response_model=ApiResponse[dict[str, Any]], summary="Active AI provider"
)
def ai_status() -> ApiResponse[dict[str, Any]]:
    """Report which AI provider is active. API keys are never included."""
    return ApiResponse.ok(describe_active_provider())


@router.get(
    "/sample/info",
    response_model=ApiResponse[BlueprintSampleInfo],
    summary="Demo project definitions",
)
def sample_info() -> ApiResponse[BlueprintSampleInfo]:
    """Describe the bundled fictional SAP project definitions."""
    return ApiResponse.ok(service.sample_info())


@router.get(
    "/sample",
    response_model=ApiResponse[dict[str, Any]],
    summary="Load one demo project definition",
)
def sample(
    name: Annotated[str, Query(max_length=80, description="Demo project name")],
) -> ApiResponse[dict[str, Any]]:
    """Return one fictional project definition, ready to post to ``/generate``."""
    return ApiResponse.ok(service.load_sample_project(name))


@router.get(
    "",
    response_model=ApiResponse[BlueprintListResponse],
    summary="List generated blueprints",
)
def list_blueprints(
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ApiResponse[BlueprintListResponse]:
    """Return generated blueprints, newest first."""
    total, blueprints = service.list_blueprints(db, limit=limit, offset=offset)
    return ApiResponse.ok(
        BlueprintListResponse(
            total=total, limit=limit, offset=offset, blueprints=blueprints
        )
    )


# ---------------------------------------------------------------------------
# One blueprint
# ---------------------------------------------------------------------------


@router.get(
    "/{blueprint_id}",
    response_model=ApiResponse[BlueprintSchema],
    summary="Get one blueprint with its sections",
)
def get_blueprint(db: DbSession, blueprint_id: str) -> ApiResponse[BlueprintSchema]:
    """Return the blueprint, its summary and every section."""
    return ApiResponse.ok(service.get_blueprint(db, blueprint_id))


@router.put(
    "/{blueprint_id}",
    response_model=ApiResponse[BlueprintSchema],
    summary="Edit one blueprint",
)
def update_blueprint(
    db: DbSession, blueprint_id: str, request: UpdateBlueprintRequest
) -> ApiResponse[BlueprintSchema]:
    """Apply a partial edit to the blueprint's own fields.

    Sending ``project`` replaces the project request, which is how a section
    waiting for an input gets unblocked. The sections whose items are computed
    from the request are rebuilt from the new values and their approvals are
    cleared - a blueprint whose organisational structure disagrees with its own
    project request would be worse than one that is out of date.
    """
    return ApiResponse.ok(service.update_blueprint(db, blueprint_id, request))


@router.get("/{blueprint_id}/export", summary="Download the blueprint")
def export_blueprint(
    db: DbSession,
    blueprint_id: str,
    file_format: Annotated[
        ExportFormat, Query(alias="format")
    ] = ExportFormat.MARKDOWN,
) -> Response:
    """Download the blueprint as Markdown, JSON, DOCX or PDF.

    Every format carries the disclaimer, the provenance of each section and the
    sections that are still waiting for project input.
    """
    payload = service.build_export_payload(db, blueprint_id)

    if file_format is ExportFormat.JSON:
        content = build_blueprint_json_report(payload)
    elif file_format is ExportFormat.DOCX:
        content = build_blueprint_docx_report(payload)
    elif file_format is ExportFormat.PDF:
        content = build_blueprint_pdf_report(payload)
    else:
        content = build_blueprint_markdown_report(payload)

    filename = f"blueprint_{blueprint_id[:8]}.{EXPORT_EXTENSIONS[file_format]}"
    return Response(
        content=content,
        media_type=EXPORT_MEDIA_TYPES[file_format],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


@router.post(
    "/{blueprint_id}/sections",
    response_model=ApiResponse[BlueprintSectionSchema],
    status_code=201,
    summary="Add a custom section",
)
def add_section(
    db: DbSession, blueprint_id: str, request: CreateSectionRequest
) -> ApiResponse[BlueprintSectionSchema]:
    """Add one custom section, optionally positioned after an existing one."""
    return ApiResponse.ok(service.add_section(db, blueprint_id, request))


@router.get(
    "/{blueprint_id}/sections/{section_id}",
    response_model=ApiResponse[BlueprintSectionSchema],
    summary="Get one section",
)
def get_section(
    db: DbSession, blueprint_id: str, section_id: str
) -> ApiResponse[BlueprintSectionSchema]:
    """Return one section by its identifier (``BP-SCOPE``), its key (``scope``) or its id."""
    return ApiResponse.ok(service.get_section(db, blueprint_id, section_id))


@router.put(
    "/{blueprint_id}/sections/{section_id}",
    response_model=ApiResponse[BlueprintSectionSchema],
    summary="Edit one section",
)
def update_section(
    db: DbSession, blueprint_id: str, section_id: str, request: UpdateSectionRequest
) -> ApiResponse[BlueprintSectionSchema]:
    """Apply a partial edit. Only the fields present in the body are changed.

    Editing the content (title, narrative or items) clears any approval and
    returns the section to draft, just as regenerating does - the approval
    described the words that were replaced. Editing only the status or the
    comments leaves the approval in place.
    """
    return ApiResponse.ok(service.update_section(db, blueprint_id, section_id, request))


@router.delete(
    "/{blueprint_id}/sections/{section_id}",
    response_model=ApiResponse[DeleteSectionResponse],
    summary="Delete one custom section",
)
def delete_section(
    db: DbSession, blueprint_id: str, section_id: str
) -> ApiResponse[DeleteSectionResponse]:
    """Delete one custom section. The standard sections cannot be deleted."""
    return ApiResponse.ok(service.delete_section(db, blueprint_id, section_id))


@router.post(
    "/{blueprint_id}/sections/{section_id}/regenerate",
    response_model=ApiResponse[BlueprintSectionSchema],
    summary="Regenerate one section",
)
def regenerate_section(
    db: DbSession,
    blueprint_id: str,
    section_id: str,
    request: RegenerateSectionRequest | None = None,
) -> ApiResponse[BlueprintSectionSchema]:
    """Redraft one section's wording, keeping its place in the document.

    The approval is cleared, because it belonged to the wording that was
    replaced. The section's factual items are recomputed from the project
    request, never redrafted.
    """
    return ApiResponse.ok(
        service.regenerate_section(
            db, blueprint_id, section_id, request or RegenerateSectionRequest()
        )
    )


@router.post(
    "/{blueprint_id}/sections/{section_id}/approve",
    response_model=ApiResponse[BlueprintSectionSchema],
    summary="Approve or un-approve one section",
)
def approve_section(
    db: DbSession, blueprint_id: str, section_id: str, request: ApproveSectionRequest
) -> ApiResponse[BlueprintSectionSchema]:
    """Record a review decision against one section."""
    return ApiResponse.ok(service.approve_section(db, blueprint_id, section_id, request))


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------


@router.get(
    "/{blueprint_id}/versions",
    response_model=ApiResponse[VersionListResponse],
    summary="List saved versions",
)
def list_versions(db: DbSession, blueprint_id: str) -> ApiResponse[VersionListResponse]:
    """Return the version history, newest first."""
    return ApiResponse.ok(service.list_versions(db, blueprint_id))


@router.post(
    "/{blueprint_id}/versions",
    response_model=ApiResponse[BlueprintVersionSchema],
    status_code=201,
    summary="Save the current state as a version",
)
def create_version(
    db: DbSession, blueprint_id: str, request: CreateVersionRequest | None = None
) -> ApiResponse[BlueprintVersionSchema]:
    """Freeze the blueprint's current sections as an immutable version."""
    return ApiResponse.ok(
        service.create_version(db, blueprint_id, request or CreateVersionRequest())
    )


@router.get(
    "/{blueprint_id}/versions/compare",
    response_model=ApiResponse[VersionComparisonSchema],
    summary="Compare two versions",
)
def compare_versions(
    db: DbSession,
    blueprint_id: str,
    from_version: Annotated[int, Query(alias="from", ge=0)],
    to_version: Annotated[int, Query(alias="to", ge=0)] = 0,
) -> ApiResponse[VersionComparisonSchema]:
    """Compare two saved versions, section by section.

    Version ``0`` means "the blueprint as it stands now", so
    ``?from=2&to=0`` answers the question a reviewer asks most often: what have
    I changed since I last saved?
    """
    return ApiResponse.ok(
        service.compare_versions(db, blueprint_id, from_version, to_version)
    )


@router.get(
    "/{blueprint_id}/versions/{version_number}",
    response_model=ApiResponse[BlueprintVersionSchema],
    summary="Get one saved version",
)
def get_version(
    db: DbSession, blueprint_id: str, version_number: int
) -> ApiResponse[BlueprintVersionSchema]:
    """Return one saved version with its full section snapshot.

    Version ``0`` returns the live document in the same shape, without saving it.
    """
    return ApiResponse.ok(service.get_version(db, blueprint_id, version_number))
