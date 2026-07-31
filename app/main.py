"""FastAPI application entry point for the SAP AI Application Lab.

Run locally with::

    uvicorn app.main:app --reload

The exception handlers below guarantee that every error - expected or not -
leaves the API in the same envelope shape as a success, and that internal
detail (stack traces, file paths, provider payloads) stays in the logs.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.exceptions import AppError
from app.core.logging import configure_logging, get_logger
from app.models.session import init_db

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_request_id(request: Request, call_next):  # type: ignore[no-untyped-def]
    """Attach a request id to every response for log correlation."""
    request_id = uuid.uuid4().hex[:12]
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(AppError)
async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    """Translate an expected application error into the response envelope."""
    request_id = getattr(request.state, "request_id", None)
    logger.warning("%s on %s: %s", exc.code, request.url.path, exc.message)
    return JSONResponse(
        status_code=exc.http_status,
        content={
            "success": False,
            "data": None,
            "error": exc.to_dict(),
            "meta": {"request_id": request_id, "api_version": "v1"},
        },
    )


@app.exception_handler(RequestValidationError)
async def handle_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Return FastAPI validation problems in the shared envelope."""
    request_id = getattr(request.state, "request_id", None)
    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "data": None,
            "error": {
                "code": "request_validation_error",
                "message": "The request could not be validated.",
                "details": {"errors": exc.errors()[:10]},
            },
            "meta": {"request_id": request_id, "api_version": "v1"},
        },
    )


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    """Log the real error, return a safe message.

    Nothing is swallowed: the full traceback goes to the log with the request id
    so a developer can find it, while the client sees a generic message.
    """
    request_id = getattr(request.state, "request_id", None)
    logger.exception("Unhandled error on %s (request_id=%s)", request.url.path, request_id)
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "data": None,
            "error": {
                "code": "internal_error",
                "message": "An unexpected error occurred. Check the server log for details.",
                "details": {"request_id": request_id},
            },
            "meta": {"request_id": request_id, "api_version": "v1"},
        },
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
        ],
        "planned_modules": [
            "supplier_risk_copilot", "contract_assistant", "inventory_predictor",
            "test_case_generator", "blueprint_generator", "interview_coach",
        ],
        "disclaimer": (
            "Demo application. Not connected to any SAP system; no output has been validated "
            "in a live SAP environment."
        ),
    }
