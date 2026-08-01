"""Aggregates every v1 route module.

Future modules (spend analytics, invoice validator, ...) register their routers
here, which keeps ``main.py`` unchanged as the lab grows.
"""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app.api.v1 import (
    blueprints,
    contracts,
    interviews,
    inventory,
    invoice_validator,
    po_risk,
    spend,
    supplier_reco,
    supplier_risk,
    test_cases,
)
from app.core.auth import CurrentPrincipal, describe_auth_state, tenant_scope
from app.core.config import settings
from app.core.logging import get_logger
from app.models.session import engine
from app.schemas.common import ApiResponse, HealthStatus

logger = get_logger(__name__)

api_router = APIRouter()


@api_router.get(
    "/health",
    response_model=ApiResponse[HealthStatus],
    tags=["System"],
    summary="Health check",
)
def health() -> ApiResponse[HealthStatus]:
    """Report application, database and AI provider status.

    Needs no credential and never will: this is what a container healthcheck,
    a load balancer and an uptime monitor poll, and none of them can log in.
    ``status`` is ``ok`` or ``degraded`` - degraded means the API is up but the
    database is not answering, which is a different action from "down".
    """
    database_connected = True
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - reported, never raised to the client
        logger.error("Database health check failed: %s", type(exc).__name__)
        database_connected = False

    resolved_provider = settings.resolved_ai_provider()
    return ApiResponse.ok(
        HealthStatus(
            status="ok" if database_connected else "degraded",
            app_name=settings.app_name,
            version=settings.app_version,
            environment=settings.environment,
            database_connected=database_connected,
            ai_provider=resolved_provider,
            ai_is_mock=resolved_provider == "mock",
        )
    )


@api_router.get(
    "/auth-status",
    response_model=ApiResponse[dict[str, object]],
    tags=["System"],
    summary="Authentication configuration",
)
def auth_status(principal: CurrentPrincipal) -> ApiResponse[dict[str, object]]:
    """Report how authentication is configured, and who the caller resolved to.

    There is no authentication today - every request resolves to the local demo
    principal, which holds every role. This endpoint exists so that is a stated
    fact a front-end developer can read rather than something they infer from
    requests happening to succeed, and so the seam is visible in the API itself.

    See ``docs/API_AUTHENTICATION_PLAN.md`` for the model this will grow into.
    """
    return ApiResponse.ok(
        {
            **describe_auth_state(),
            "principal": {
                "subject": principal.subject,
                "display_name": principal.display_name,
                "is_anonymous": principal.is_anonymous,
                "roles": sorted(role.value for role in principal.roles),
                **tenant_scope(principal),
            },
        }
    )


api_router.include_router(po_risk.router)
api_router.include_router(spend.router)
api_router.include_router(supplier_reco.suppliers_router)
api_router.include_router(supplier_reco.recommendations_router)
api_router.include_router(invoice_validator.router)
api_router.include_router(supplier_risk.router)
api_router.include_router(contracts.router)
api_router.include_router(inventory.router)
api_router.include_router(test_cases.router)
api_router.include_router(blueprints.router)
api_router.include_router(interviews.router)
