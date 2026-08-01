"""Schemas for the guided public demonstration.

These describe *plumbing*, not analysis. Nothing in this module computes a
finding, a score or a forecast - the demonstration loader hands a module the
bundled fictional file it would otherwise have received from an upload, and
gives back the identifiers the module's own analysis endpoint already expects.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import OutputOrigin


class DemoStatus(BaseModel):
    """How this deployment is configured, in terms safe to show a browser."""

    demo_mode: bool
    uploads_enabled: bool
    ai_provider: str
    ai_is_mock: bool
    banner_headline: str
    do_not_submit: list[str]
    disclaimer: str
    data_origin: OutputOrigin = OutputOrigin.DEMO_DATA
    site_name: str
    contact_email: str | None = None
    authentication: str


class DemoDatasetInfo(BaseModel):
    """One bundled file a demonstration uses."""

    key: str = Field(description="Which of the module's inputs this file is.")
    filename: str
    available: bool
    size_bytes: int | None = None


class DemoModuleInfo(BaseModel):
    """What the guided demonstration offers for one module."""

    module: str
    number: int
    name: str
    #: Whether ``POST /demo/load/{module}`` can ingest bundled data for it.
    loadable: bool
    #: Modules 8-10 take a structured request rather than a file, so their
    #: demonstration starts from a bundled *scenario* instead of an upload.
    input_style: str
    datasets: list[DemoDatasetInfo]
    business_question: str
    deterministic_summary: str
    ai_summary: str
    expected_output: str


class DemoLoadedDataset(BaseModel):
    """A bundled file that was ingested, and the handle it produced."""

    key: str
    filename: str
    identifier_name: str
    identifier: str
    row_count: int | None = None


class DemoLoadResponse(BaseModel):
    """Result of loading a module's bundled demonstration data."""

    module: str
    number: int
    name: str
    datasets: list[DemoLoadedDataset]
    #: The path of the module's own analysis endpoint, relative to the API
    #: prefix. The caller posts to it exactly as it would after an upload.
    analyze_path: str
    #: The identifiers that endpoint needs, ready to post. Identifiers only -
    #: any tuning parameter stays with the page that owns the widget for it.
    analyze_payload: dict[str, Any]
    #: Each module's *own* upload response, keyed by dataset key, exactly as its
    #: upload route would have returned it. A page that already renders a
    #: mapping preview from an upload can therefore render one here without a
    #: second request and without a parallel code path.
    uploads: dict[str, dict[str, Any]] = Field(default_factory=dict)
    #: Presets that belong to the *bundled dataset* rather than to a user's
    #: preference - an as-of date inside the sample's own date range, for
    #: instance. A page is free to ignore them.
    suggested_parameters: dict[str, Any] = Field(default_factory=dict)
    data_origin: OutputOrigin = OutputOrigin.DEMO_DATA
    notes: list[str] = Field(default_factory=list)
