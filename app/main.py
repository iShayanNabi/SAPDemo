"""FastAPI application entry point for the SAP AI Application Lab.

Run locally with::

    uvicorn app.main:app --reload

The exception handlers below guarantee that every error - expected or not -
leaves the API in the same envelope shape as a success, and that internal
detail (stack traces, file paths, provider payloads) stays in the logs.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.context import reset_request_id, set_request_id
from app.core.exceptions import AppError
from app.core.logging import configure_logging, get_logger
from app.models.session import init_db
from app.schemas.common import ApiResponse

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Prepare directories and the database schema on startup."""
    settings.ensure_directories()
    init_db()
    provider = settings.resolved_ai_provider()
    logger.info(
        "%s v%s started | environment=%s | ai_provider=%s%s",
        settings.app_name, settings.app_version, settings.environment, provider,
        " (mock mode - no API key needed)" if provider == "mock" else "",
    )
    yield
    logger.info("Shutting down")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Local API for the SAP AI Application Lab. Module 1: Purchase Order Risk Checker.\n\n"
        "Risk findings are produced by deterministic Python rules. AI is optional and only "
        "rewrites those findings in business language; it never decides risk. No module in this "
        "lab connects to a live SAP system."
    ),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS. The origin list comes from CORS_ORIGINS and defaults to the local
# Next.js and Streamlit ports. Credentials are only allowed for a *named* list -
# see Settings.cors_allow_credentials for why a wildcard must not carry them.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    expose_headers=["X-Request-ID", "Content-Disposition"],
    max_age=600,
)

if settings.cors_allows_any_origin and settings.environment != "local":
    logger.warning(
        "CORS_ORIGINS is '*' with ENVIRONMENT=%s. Credentials are disabled for "
        "cross-origin requests. Name the front end's origins before going public.",
        settings.environment,
    )


@app.middleware("http")
async def add_request_id(request: Request, call_next):  # type: ignore[no-untyped-def]
    """Attach a request id to every response for log correlation.

    The id goes three places: ``request.state`` for the exception handlers, a
    context variable so :class:`~app.schemas.common.ResponseMeta` can put the
    same value inside the envelope, and the ``X-Request-ID`` header.
    """
    request_id = uuid.uuid4().hex[:12]
    request.state.request_id = request_id
    token = set_request_id(request_id)
    try:
        response = await call_next(request)
    finally:
        reset_request_id(token)
    response.headers["X-Request-ID"] = request_id
    return response


def _error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, object],
    request_id: str | None,
) -> JSONResponse:
    """Render an error in exactly the envelope a success uses.

    Built from :class:`~app.schemas.common.ApiResponse` rather than a hand
    written dict. Hand written was how ``meta.timestamp`` came to exist on every
    success and on no failure: a client that renders "received at" from the
    envelope worked until the first error.
    """
    payload = ApiResponse[None].fail(
        code, message, details=details, request_id=request_id
    ).model_dump(mode="json")
    return JSONResponse(status_code=status_code, content=payload)


@app.exception_handler(AppError)
async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    """Translate an expected application error into the response envelope."""
    request_id = getattr(request.state, "request_id", None)
    logger.warning("%s on %s: %s", exc.code, request.url.path, exc.message)
    return _error_response(
        status_code=exc.http_status,
        code=exc.code,
        message=exc.message,
        details=exc.details,
        request_id=request_id,
    )


@app.exception_handler(StarletteHTTPException)
async def handle_http_exception(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Return Starlette's own errors (404, 405, ...) in the shared envelope.

    Without this, a mistyped URL returned ``{"detail": "Not Found"}`` - a second
    error shape a front end would have to special-case, produced by the one
    request every client makes by accident.
    """
    codes = {404: "not_found", 405: "method_not_allowed", 401: "unauthorized", 403: "forbidden"}
    return _error_response(
        status_code=exc.status_code,
        code=codes.get(exc.status_code, "http_error"),
        message=str(exc.detail) if exc.detail else "The request could not be completed.",
        details={},
        request_id=getattr(request.state, "request_id", None),
    )


@app.exception_handler(RequestValidationError)
async def handle_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Return FastAPI validation problems in the shared envelope."""
    return _error_response(
        status_code=422,
        code="request_validation_error",
        message="The request could not be validated.",
        details={"errors": jsonable_encoder(exc.errors()[:10])},
        request_id=getattr(request.state, "request_id", None),
    )


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    """Log the real error, return a safe message.

    Nothing is swallowed: the full traceback goes to the log with the request id
    so a developer can find it, while the client sees a generic message.
    """
    request_id = getattr(request.state, "request_id", None)
    logger.exception("Unhandled error on %s (request_id=%s)", request.url.path, request_id)
    return _error_response(
        status_code=500,
        code="internal_error",
        message="An unexpected error occurred. Check the server log for details.",
        details={},
        request_id=request_id,
    )


app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get("/", tags=["System"], summary="API index")
def index() -> dict[str, object]:
    """Return a small index of the available modules."""
    return {
        "app": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
        "modules": [
            {
                "id": "po_risk",
                "name": "Purchase Order Risk Checker",
                "status": "available",
                "base_path": f"{settings.api_v1_prefix}/po-risk",
            },
            {
                "id": "spend_analytics",
                "name": "Spend Analytics Dashboard",
                "status": "available",
                "base_path": f"{settings.api_v1_prefix}/spend",
            },
            {
                "id": "supplier_recommendation",
                "name": "Supplier Recommendation Engine",
                "status": "available",
                "base_path": f"{settings.api_v1_prefix}/supplier-recommendations",
            },
            {
                "id": "invoice_validator",
                "name": "Invoice Validator",
                "status": "available",
                "base_path": f"{settings.api_v1_prefix}/invoices",
            },
            {
                "id": "supplier_risk_copilot",
                "name": "Supplier Risk Copilot",
                "status": "available",
                "base_path": f"{settings.api_v1_prefix}/supplier-risk",
            },
            {
                "id": "contract_assistant",
                "name": "Contract Assistant",
                "status": "available",
                "base_path": f"{settings.api_v1_prefix}/contracts",
            },
            {
                "id": "inventory_predictor",
                "name": "Inventory Predictor",
                "status": "available",
                "base_path": f"{settings.api_v1_prefix}/inventory",
            },
            {
                "id": "test_case_generator",
                "name": "SAP Test Case Generator",
                "status": "available",
                "base_path": f"{settings.api_v1_prefix}/test-cases",
            },
        ],
        "planned_modules": ["blueprint_generator", "interview_coach"],
        "disclaimer": (
            "Demo application. Not connected to any SAP system; no output has been validated "
            "in a live SAP environment."
        ),
    }
