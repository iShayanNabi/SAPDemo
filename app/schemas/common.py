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

from app.core.context import get_request_id

DataT = TypeVar("DataT")

#: The single place the API version string is written.
API_VERSION = "v1"


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
    """Finding severity levels, ordered from least to most serious.

    This is the vocabulary for a *finding about the data*: a risk, an invoice
    exception, a contract risk. It is not the vocabulary for a message about the
    processing itself - see :class:`IssueSeverity`.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        """Numeric rank used for sorting and for aggregate risk scoring."""
        return {"low": 1, "medium": 2, "high": 3, "critical": 4}[self.value]


class IssueSeverity(str, Enum):
    """How serious a *processing* message is: a data quality issue or a warning.

    Deliberately a different vocabulary from :class:`Severity`. "This purchase
    order is a critical risk" and "three rows had no delivery date" are not
    points on one scale, and a UI that colours both from one legend ends up
    printing a data-quality note in the same red as a fraud finding.

    Three values, and the distinction that matters is the last one:

    ``info``
        Worth knowing, changes nothing about the result.
    ``warning``
        The result is still produced, but it rests on an assumption
        (a default lead time, a filled gap, a deduplicated row).
    ``error``
        Part of the output could **not** be produced. The analysis still
        returns - one broken series never costs the others their forecast -
        but something the caller asked for is missing and says so.

    Before this existed the same field carried ``info``, ``warning`` and
    ``high`` - the last borrowed from the finding scale - so a client could not
    build a legend that covered its own field.
    """

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"

    @property
    def rank(self) -> int:
        """Numeric rank used for sorting and for filtering."""
        return {"info": 1, "warning": 2, "error": 3}[self.value]


class AnalysisStatus(str, Enum):
    """The lifecycle of one analysis run, shared by every module that has one.

    Every module in the lab runs its analysis synchronously today, so a caller
    sees ``completed`` (or an error envelope) on the same request. The states
    exist anyway because they are the seam a background worker slots into: a
    website uploading a 200,000 row file will want ``pending`` -> ``running``
    -> ``completed`` and a poll in between, and that must not be a new
    vocabulary invented per module at the point somebody adds the queue.
    """

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        """Whether the run has finished, successfully or not."""
        return self in {AnalysisStatus.COMPLETED, AnalysisStatus.FAILED}


class DataQualityIssueSchema(BaseModel):
    """A non-fatal problem found while loading or normalising a file.

    Defined once here because six modules report the same thing and used to say
    it three different ways: ``po_risk`` published ``field``, ``inventory``
    published ``field`` through an alias, ``supplier_risk`` declared
    ``field_name`` with no alias at all, and ``spend``, ``invoice_validator``
    and ``supplier_reco`` published an untyped ``dict`` that no generated client
    could describe. A front end rendering "3 rows had no delivery date" had to
    branch on which module it was talking to.

    The wire name is ``field``, which is what the shared
    :class:`app.services.tabular.parsing.DataQualityIssue` has always emitted.
    ``field_name`` is accepted when constructing one in Python, because that is
    what the dataclass attribute is called.

    The divergence was not cosmetic: ``supplier_risk`` built this schema
    directly from that dataclass's dict, so the first upload containing an
    unparseable number returned HTTP 500 instead of the issue list it exists to
    produce. The demo file is clean, so nothing ever hit it.
    """

    model_config = ConfigDict(populate_by_name=True)

    field_name: str = Field(
        alias="field", description="The canonical field the problem was found in."
    )
    issue_type: str = Field(description="Machine readable problem category.")
    message: str = Field(description="A human readable explanation, safe to show a user.")
    affected_rows: int = Field(ge=0, description="How many rows carry the problem.")
    sample_rows: list[int] = Field(
        default_factory=list, description="Up to ten example row numbers, 1-based."
    )
    severity: IssueSeverity = IssueSeverity.WARNING


class ErrorPayload(BaseModel):
    """Machine readable error information."""

    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ResponseMeta(BaseModel):
    """Envelope metadata common to every response.

    All three fields are present on every response, success or failure. The
    ``request_id`` defaults to the id the middleware minted for the current
    request (the same value as the ``X-Request-ID`` header), so a user can read
    it off a response that *succeeded but looked wrong* and a developer can find
    the matching log line. Outside a request - a script, a test constructing a
    schema directly - it is simply ``None``.
    """

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    request_id: str | None = Field(default_factory=get_request_id)
    api_version: str = API_VERSION


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
        return cls(success=True, data=data, meta=_meta(request_id))

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
            meta=_meta(request_id),
        )


def _meta(request_id: str | None) -> ResponseMeta:
    """Build envelope metadata, letting the context supply a missing id.

    Passing ``request_id=None`` explicitly would *override* the default factory
    with ``None``, which is the opposite of what "the caller did not say" means.
    """
    if request_id is None:
        return ResponseMeta()
    return ResponseMeta(request_id=request_id)


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
