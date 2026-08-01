"""HTTP routes for the guided public demonstration.

Three routes, all thin:

``GET /demo/status``
    How this deployment is configured, in terms safe to render in a browser.
``GET /demo/modules``
    What the guided demonstration offers for each of the ten modules.
``POST /demo/load/{module}``
    Ingest a module's bundled fictional data and return the identifiers its own
    analysis endpoint already expects.

The load route exists because public demo mode removes the upload path, and a
demonstration with no way to get data in is a screenshot. It adds no analysis:
it reads ``data/sample/`` and calls the same ``handle_upload`` a real upload
reaches. It is available whether or not demo mode is on, because a developer
loading the bundled data with one call is useful either way.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path
from sqlalchemy.orm import Session

from app.api.openapi import COMMON_ERROR_RESPONSES
from app.core.demo import describe_demo_state
from app.core.logging import get_logger
from app.models.session import get_db
from app.schemas.common import ApiResponse
from app.schemas.demo import DemoLoadResponse, DemoModuleInfo, DemoStatus
from app.services.demo import describe_modules, load_module_demo

logger = get_logger(__name__)

router = APIRouter(prefix="/demo", tags=["Demonstration"], responses=COMMON_ERROR_RESPONSES)

DbSession = Annotated[Session, Depends(get_db)]


@router.get("/status", response_model=ApiResponse[DemoStatus], summary="Demonstration status")
def demo_status() -> ApiResponse[DemoStatus]:
    """Report whether this is a public demonstration, and what that changes.

    Needs no credential and carries none: every field is a boolean, a fixed
    string or a configured public address. This is what the Streamlit banner and
    the public website read to decide what to say.
    """
    return ApiResponse.ok(DemoStatus(**describe_demo_state()))  # type: ignore[arg-type]


@router.get(
    "/modules",
    response_model=ApiResponse[list[DemoModuleInfo]],
    summary="Guided demonstrations",
)
def demo_modules() -> ApiResponse[list[DemoModuleInfo]]:
    """Describe the guided demonstration for each of the ten modules.

    ``loadable`` is computed from the bundled files actually being present, so a
    checkout with a missing sample file reports it here rather than failing at
    the moment somebody presses the button.
    """
    return ApiResponse.ok(describe_modules())


@router.post(
    "/load/{module}",
    response_model=ApiResponse[DemoLoadResponse],
    summary="Load a module's bundled demonstration data",
)
def load_demo(
    db: DbSession,
    module: Annotated[str, Path(max_length=60, pattern="^[a-z_]+$")],
) -> ApiResponse[DemoLoadResponse]:
    """Ingest the bundled fictional data for one module.

    Returns the same identifiers an upload would have produced, so the page can
    post straight on to the module's analysis endpoint.
    """
    return ApiResponse.ok(load_module_demo(db, module))
