"""Shared schemas used by every module of the lab.

Each API response uses the same envelope so a future React/Next.js front end
can implement one response handler for all modules::

    {"success": true, "data": {...}, "error": null, "meta": {...}}
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

DataT = TypeVar("DataT")


class OutputOrigin(str, Enum):
    """How a piece of output was produced.

    The project rule is that every value shown to a user is labelled with its
    origin so nobody mistakes a mock narrative for a validated SAP result.
    """

    RULE_BASED = "rule_based"
    AI_GENERATED = "ai_generated"
    MOCK_AI = "mock_ai"
    FORECAST = "forecast"
    DEMO_DATA = "demo_data"


class Severity(str, Enum):
    """Finding severity levels, ordered from least to most serious."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        """Numeric rank used for sorting and for aggregate risk scoring."""
        return {"low": 1, "medium": 2, "high": 3, "critical": 4}[self.value]


class ErrorPayload(BaseModel):
    """Machine readable error information."""

    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ResponseMeta(BaseModel):
    """Envelope metadata common to every response."""

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    request_id: str | None = None
    api_version: str = "v1"


class ApiResponse(BaseModel, Generic[DataT]):
    """Standard response envelope shared by all modules."""

    model_config = ConfigDict(populate_by_name=True)

    success: bool = True
    data: DataT | None = None
    error: ErrorPayload | None = None
    meta: ResponseMeta = Field(default_factory=ResponseMeta)

    @classmethod
    def ok(cls, data: DataT, request_id: str | None = None) -> "ApiResponse[DataT]":
        """Build a success envelope."""
        return cls(success=True, data=data, meta=ResponseMeta(request_id=request_id))

    @classmethod
    def fail(
        cls,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> "ApiResponse[DataT]":
        """Build an error envelope."""
        return cls(
            success=False,
            data=None,
            error=ErrorPayload(code=code, message=message, details=details or {}),
            meta=ResponseMeta(request_id=request_id),
        )


class PaginationMeta(BaseModel):
    """Pagination information for list endpoints."""

    total: int
    limit: int
    offset: int

    @property
    def has_more(self) -> bool:
        return self.offset + self.limit < self.total


class HealthStatus(BaseModel):
    """Payload for the health endpoint."""

    status: str = "ok"
    app_name: str
    version: str
    environment: str
    database_connected: bool
    ai_provider: str
    ai_is_mock: bool
