"""HTTP client used by the Streamlit pages.

The UI never imports business logic. It talks to the same FastAPI endpoints a
future React front end will call, which keeps the two interfaces honest: if
something is missing from the API, the Streamlit page cannot fake it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings

DEFAULT_TIMEOUT = 120.0


class ApiError(Exception):
    """Raised when the API returns an error envelope or is unreachable."""

    def __init__(self, message: str, *, code: str = "api_error", details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}


@dataclass
class ApiClient:
    """Thin wrapper around the PO risk endpoints."""

    base_url: str = settings.api_base_url
    timeout: float = DEFAULT_TIMEOUT

    # -- plumbing --------------------------------------------------------
    def _url(self, path: str) -> str:
        return f"{self.base_url.rstrip('/')}{settings.api_v1_prefix}{path}"

    def _unwrap(self, response: httpx.Response) -> Any:
        """Return ``data`` from the envelope or raise :class:`ApiError`."""
        try:
            body = response.json()
        except ValueError as exc:
            raise ApiError(f"The API returned a non-JSON response (HTTP {response.status_code}).") from exc

        if isinstance(body, dict) and body.get("success") is False:
            error = body.get("error") or {}
            raise ApiError(
                error.get("message", "The request failed."),
                code=error.get("code", "api_error"),
                details=error.get("details", {}),
            )
        if response.status_code >= 400:
            raise ApiError(f"The API returned HTTP {response.status_code}.")
        return body.get("data") if isinstance(body, dict) else body

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.request(method, self._url(path), **kwargs)
        except httpx.ConnectError as exc:
            raise ApiError(
                "Cannot reach the API. Start it with: uvicorn app.main:app --reload",
                code="connection_error",
            ) from exc
        except httpx.TimeoutException as exc:
            raise ApiError("The API did not respond in time.", code="timeout") from exc
        return self._unwrap(response)

    # -- endpoints -------------------------------------------------------
    def health(self) -> dict[str, Any]:
        """Return backend health information."""
        return self._request("GET", "/health")

    def ai_status(self) -> dict[str, Any]:
        """Return the active AI provider description."""
        return self._request("GET", "/po-risk/ai-status")

    def upload(self, filename: str, content: bytes, content_type: str) -> dict[str, Any]:
        """Upload a purchase order file and get the mapping suggestion."""
        return self._request(
            "POST", "/po-risk/upload", files={"file": (filename, content, content_type)}
        )

    def analyze(
        self,
        upload_id: str,
        *,
        overrides: dict[str, str] | None = None,
        generate_ai_summary: bool = True,
        rewrite_findings: bool = False,
        enabled_rules: list[str] | None = None,
    ) -> dict[str, Any]:
        """Run the risk analysis."""
        payload = {
            "upload_id": upload_id,
            "column_mapping_overrides": overrides or {},
            "generate_ai_summary": generate_ai_summary,
            "rewrite_findings": rewrite_findings,
            "enabled_rules": enabled_rules,
        }
        return self._request("POST", "/po-risk/analyze", json=payload)

    def list_analyses(self, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        """List previous analyses."""
        return self._request("GET", "/po-risk/analyses", params={"limit": limit, "offset": offset})

    def get_analysis(self, analysis_id: str) -> dict[str, Any]:
        """Fetch one analysis."""
        return self._request("GET", f"/po-risk/analyses/{analysis_id}")

    def findings(self, analysis_id: str, **filters: Any) -> dict[str, Any]:
        """Fetch findings with optional filters."""
        params = {key: value for key, value in filters.items() if value not in (None, [], "")}
        return self._request("GET", f"/po-risk/analyses/{analysis_id}/findings", params=params)

    def rules(self) -> list[dict[str, Any]]:
        """Fetch the rule catalogue."""
        return self._request("GET", "/po-risk/rules")

    def fields(self) -> list[dict[str, Any]]:
        """Fetch the canonical field catalogue."""
        return self._request("GET", "/po-risk/fields")

    def sample_info(self) -> dict[str, Any]:
        """Describe the bundled demo dataset."""
        return self._request("GET", "/po-risk/sample/info")

    def download_bytes(self, path: str, params: dict[str, Any] | None = None) -> bytes:
        """Download a binary payload (export or sample file)."""
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(self._url(path), params=params or {})
        except httpx.HTTPError as exc:
            raise ApiError("The download could not be completed.", code="download_error") from exc
        if response.status_code >= 400:
            self._unwrap(response)
        return response.content

    def export(self, analysis_id: str, export_format: str) -> bytes:
        """Download an analysis report."""
        return self.download_bytes(
            f"/po-risk/analyses/{analysis_id}/export", {"format": export_format}
        )

    def sample_file(self, file_format: str) -> bytes:
        """Download the bundled sample file."""
        return self.download_bytes("/po-risk/sample", {"format": file_format})

    # -- Spend Analytics Dashboard ---------------------------------------
    def spend_upload(self, filename: str, content: bytes, content_type: str) -> dict[str, Any]:
        """Upload a spend transaction file and get the mapping suggestion."""
        return self._request(
            "POST", "/spend/upload", files={"file": (filename, content, content_type)}
        )

    def spend_analyze(
        self,
        upload_id: str,
        *,
        overrides: dict[str, str] | None = None,
        filters: dict[str, Any] | None = None,
        generate_ai_summary: bool = True,
        top_n: int | None = None,
    ) -> dict[str, Any]:
        """Run the spend analysis."""
        payload: dict[str, Any] = {
            "upload_id": upload_id,
            "column_mapping_overrides": overrides or {},
            "filters": filters or {},
            "generate_ai_summary": generate_ai_summary,
        }
        if top_n:
            payload["top_n"] = top_n
        return self._request("POST", "/spend/analyze", json=payload)

    def spend_analysis(self, analysis_id: str) -> dict[str, Any]:
        """Fetch one spend analysis."""
        return self._request("GET", f"/spend/analyses/{analysis_id}")

    def spend_transactions(self, analysis_id: str, **filters: Any) -> dict[str, Any]:
        """Drill down into the transactions behind a figure."""
        params = {k: v for k, v in filters.items() if v not in (None, "", [])}
        return self._request("GET", f"/spend/analyses/{analysis_id}/transactions", params=params)

    def spend_opportunities(self, analysis_id: str, **filters: Any) -> dict[str, Any]:
        """Fetch the modelled savings opportunities."""
        params = {k: v for k, v in filters.items() if v not in (None, "", [])}
        return self._request("GET", f"/spend/analyses/{analysis_id}/opportunities", params=params)

    def spend_export(self, analysis_id: str, export_format: str) -> bytes:
        """Download a spend report."""
        return self.download_bytes(
            f"/spend/analyses/{analysis_id}/export", {"format": export_format}
        )

    def spend_fields(self) -> list[dict[str, Any]]:
        """Fetch the spend field catalogue."""
        return self._request("GET", "/spend/fields")

    def spend_savings_rules(self) -> list[dict[str, Any]]:
        """Fetch the savings rule catalogue with its assumptions."""
        return self._request("GET", "/spend/savings-rules")

    def spend_methodology(self) -> dict[str, Any]:
        """Fetch the calculation methodology."""
        return self._request("GET", "/spend/methodology")

    def spend_sample_info(self) -> dict[str, Any]:
        """Describe the bundled spend demo dataset."""
        return self._request("GET", "/spend/sample/info")

    def spend_sample_file(self, file_format: str) -> bytes:
        """Download the bundled spend sample file."""
        return self.download_bytes("/spend/sample", {"format": file_format})

    # -- Supplier Recommendation Engine ----------------------------------
    def supplier_upload(self, filename: str, content: bytes, content_type: str) -> dict[str, Any]:
        """Upload a supplier master file and load it into a catalogue."""
        return self._request(
            "POST", "/suppliers/upload", files={"file": (filename, content, content_type)}
        )

    def suppliers(self, **filters: Any) -> dict[str, Any]:
        """List suppliers in a catalogue, with optional filters."""
        params = {k: v for k, v in filters.items() if v not in (None, "", [])}
        return self._request("GET", "/suppliers", params=params)

    def supplier(self, supplier_id: str, catalog_id: str | None = None) -> dict[str, Any]:
        """Fetch one supplier."""
        params = {"catalog_id": catalog_id} if catalog_id else {}
        return self._request("GET", f"/suppliers/{supplier_id}", params=params)

    def supplier_catalogs(self) -> dict[str, Any]:
        """List the uploaded supplier catalogues."""
        return self._request("GET", "/suppliers/catalogs")

    def supplier_fields(self) -> list[dict[str, Any]]:
        """Fetch the supplier field catalogue."""
        return self._request("GET", "/suppliers/fields")

    def supplier_sample_info(self) -> dict[str, Any]:
        """Describe the bundled supplier demo catalogue."""
        return self._request("GET", "/suppliers/sample/info")

    def supplier_sample_file(self, file_format: str) -> bytes:
        """Download the bundled supplier sample file."""
        return self.download_bytes("/suppliers/sample", {"format": file_format})

    def recommend_suppliers(
        self,
        requirement: dict[str, Any],
        *,
        catalog_id: str | None = None,
        weights: dict[str, float] | None = None,
        top_n: int | None = None,
        generate_ai_summary: bool = True,
        include_ineligible: bool = True,
    ) -> dict[str, Any]:
        """Run a supplier recommendation."""
        payload: dict[str, Any] = {
            "requirement": requirement,
            "generate_ai_summary": generate_ai_summary,
            "include_ineligible": include_ineligible,
        }
        if catalog_id:
            payload["catalog_id"] = catalog_id
        if weights is not None:
            payload["weights"] = weights
        if top_n:
            payload["top_n"] = top_n
        return self._request("POST", "/supplier-recommendations/recommend", json=payload)

    def recommendation(self, recommendation_id: str) -> dict[str, Any]:
        """Fetch one recommendation."""
        return self._request("GET", f"/supplier-recommendations/{recommendation_id}")

    def recommendations(self, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        """List previous recommendations."""
        return self._request(
            "GET", "/supplier-recommendations", params={"limit": limit, "offset": offset}
        )

    def supplier_scoring(self) -> dict[str, Any]:
        """Fetch the documented scoring model."""
        return self._request("GET", "/supplier-recommendations/scoring")

    def recommendation_export(self, recommendation_id: str, export_format: str) -> bytes:
        """Download a recommendation report."""
        return self.download_bytes(
            f"/supplier-recommendations/{recommendation_id}/export", {"format": export_format}
        )

    # -- Invoice Validator -----------------------------------------------
    def invoice_upload(
        self, dataset: str, filename: str, content: bytes, content_type: str
    ) -> dict[str, Any]:
        """Upload one of the three files (invoices, purchase orders, goods receipts)."""
        return self._request(
            "POST",
            "/invoices/upload",
            data={"dataset": dataset},
            files={"file": (filename, content, content_type)},
        )

    def invoice_validate(
        self,
        invoice_upload_id: str,
        *,
        po_upload_id: str | None = None,
        gr_upload_id: str | None = None,
        invoice_mapping_overrides: dict[str, str] | None = None,
        po_mapping_overrides: dict[str, str] | None = None,
        gr_mapping_overrides: dict[str, str] | None = None,
        tolerances: dict[str, Any] | None = None,
        as_of_date: str | None = None,
        enabled_rules: list[str] | None = None,
        generate_ai_summary: bool = True,
    ) -> dict[str, Any]:
        """Run the three-way validation."""
        payload: dict[str, Any] = {
            "invoice_upload_id": invoice_upload_id,
            "generate_ai_summary": generate_ai_summary,
        }
        if po_upload_id:
            payload["po_upload_id"] = po_upload_id
        if gr_upload_id:
            payload["gr_upload_id"] = gr_upload_id
        if invoice_mapping_overrides:
            payload["invoice_mapping_overrides"] = invoice_mapping_overrides
        if po_mapping_overrides:
            payload["po_mapping_overrides"] = po_mapping_overrides
        if gr_mapping_overrides:
            payload["gr_mapping_overrides"] = gr_mapping_overrides
        if tolerances:
            payload["tolerances"] = tolerances
        if as_of_date:
            payload["as_of_date"] = as_of_date
        if enabled_rules:
            payload["enabled_rules"] = enabled_rules
        return self._request("POST", "/invoices/validate", json=payload)

    def invoice_validation(self, validation_id: str) -> dict[str, Any]:
        """Fetch one validation."""
        return self._request("GET", f"/invoices/validations/{validation_id}")

    def invoice_exceptions(self, validation_id: str, **filters: Any) -> dict[str, Any]:
        """Fetch exceptions with optional filters."""
        params = {key: value for key, value in filters.items() if value not in (None, "", [])}
        return self._request("GET", f"/invoices/validations/{validation_id}/exceptions", params=params)

    def invoice_rules(self) -> dict[str, Any]:
        """Fetch the invoice rule catalogue and active tolerances."""
        return self._request("GET", "/invoices/rules")

    def invoice_fields(self) -> dict[str, Any]:
        """Fetch the three canonical field catalogues."""
        return self._request("GET", "/invoices/fields")

    def invoice_sample_info(self) -> dict[str, Any]:
        """Describe the bundled demo invoice datasets."""
        return self._request("GET", "/invoices/sample/info")

    def invoice_sample_file(self, dataset: str, file_format: str) -> bytes:
        """Download one bundled demo invoice dataset."""
        return self.download_bytes("/invoices/sample", {"dataset": dataset, "format": file_format})

    def invoice_export(self, validation_id: str, export_format: str) -> bytes:
        """Download a validation report."""
        return self.download_bytes(
            f"/invoices/validations/{validation_id}/export", {"format": export_format}
        )

    # -- Supplier Risk Copilot -------------------------------------------
    def supplier_risk_upload(
        self,
        dataset: str,
        filename: str,
        content: bytes,
        content_type: str,
        *,
        dataset_id: str | None = None,
    ) -> dict[str, Any]:
        """Upload supplier risk profiles or the dated risk events."""
        data: dict[str, str] = {"dataset": dataset}
        if dataset_id:
            data["dataset_id"] = dataset_id
        return self._request(
            "POST",
            "/supplier-risk/upload",
            data=data,
            files={"file": (filename, content, content_type)},
        )

    def supplier_risk_datasets(self) -> dict[str, Any]:
        """List the uploaded supplier risk datasets."""
        return self._request("GET", "/supplier-risk/datasets")

    def supplier_risk_fields(self) -> list[dict[str, Any]]:
        """Fetch the supplier risk field catalogue."""
        return self._request("GET", "/supplier-risk/fields")

    def supplier_risk_scoring(self) -> dict[str, Any]:
        """Fetch the documented risk scoring model (categories, weights, bands)."""
        return self._request("GET", "/supplier-risk/scoring")

    def supplier_risk_ai_status(self) -> dict[str, Any]:
        """Report which AI provider the copilot would use."""
        return self._request("GET", "/supplier-risk/ai-status")

    def supplier_risk_sample_info(self) -> dict[str, Any]:
        """Describe the bundled fictional supplier risk demo dataset."""
        return self._request("GET", "/supplier-risk/sample/info")

    def supplier_risk_sample_file(self, dataset: str, file_format: str) -> bytes:
        """Download one bundled demo supplier risk file."""
        return self.download_bytes(
            "/supplier-risk/sample", {"dataset": dataset, "format": file_format}
        )

    def supplier_risk_calculate(
        self,
        *,
        dataset_id: str | None = None,
        weights: dict[str, float] | None = None,
        as_of_date: str | None = None,
        generate_ai_summary: bool = False,
    ) -> dict[str, Any]:
        """Run the risk model over a loaded dataset."""
        payload: dict[str, Any] = {"generate_ai_summary": generate_ai_summary}
        if dataset_id:
            payload["dataset_id"] = dataset_id
        if weights is not None:
            payload["weights"] = weights
        if as_of_date:
            payload["as_of_date"] = as_of_date
        return self._request("POST", "/supplier-risk/calculate", json=payload)

    def supplier_risk_assessments(self, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        """List previous risk assessments, newest first."""
        return self._request(
            "GET", "/supplier-risk/assessments", params={"limit": limit, "offset": offset}
        )

    def supplier_risk_assessment(self, assessment_id: str) -> dict[str, Any]:
        """Fetch one risk assessment with its ranked suppliers."""
        return self._request("GET", f"/supplier-risk/assessments/{assessment_id}")

    def supplier_risk_suppliers(self, **filters: Any) -> dict[str, Any]:
        """List assessed suppliers, highest risk first, with optional filters."""
        params = {key: value for key, value in filters.items() if value not in (None, "", [])}
        return self._request("GET", "/supplier-risk/suppliers", params=params)

    def supplier_risk_supplier(
        self, supplier_id: str, assessment_id: str | None = None
    ) -> dict[str, Any]:
        """Fetch one supplier's complete risk profile."""
        params = {"assessment_id": assessment_id} if assessment_id else {}
        return self._request("GET", f"/supplier-risk/suppliers/{supplier_id}", params=params)

    def supplier_risk_chat(
        self,
        question: str,
        *,
        assessment_id: str | None = None,
        supplier_id: str | None = None,
        generate_ai_summary: bool = False,
    ) -> dict[str, Any]:
        """Ask the copilot a question about the loaded supplier risk data."""
        payload: dict[str, Any] = {
            "question": question,
            "generate_ai_summary": generate_ai_summary,
        }
        if assessment_id:
            payload["assessment_id"] = assessment_id
        if supplier_id:
            payload["supplier_id"] = supplier_id
        return self._request("POST", "/supplier-risk/chat", json=payload)

    # -- Inventory Predictor ---------------------------------------------
    def inventory_upload(
        self, filename: str, content: bytes, content_type: str
    ) -> dict[str, Any]:
        """Upload an inventory history file and load it into a dataset."""
        return self._request(
            "POST", "/inventory/upload", files={"file": (filename, content, content_type)}
        )

    def inventory_datasets(self) -> dict[str, Any]:
        """List the uploaded inventory datasets."""
        return self._request("GET", "/inventory/datasets")

    def inventory_fields(self) -> list[dict[str, Any]]:
        """Fetch the inventory field catalogue."""
        return self._request("GET", "/inventory/fields")

    def inventory_methods(self) -> dict[str, Any]:
        """Fetch the documented forecasting methods, selection rules and policies."""
        return self._request("GET", "/inventory/methods")

    def inventory_sample_info(self) -> dict[str, Any]:
        """Describe the bundled fictional inventory demo dataset."""
        return self._request("GET", "/inventory/sample/info")

    def inventory_sample_file(self, file_format: str) -> bytes:
        """Download the bundled demo inventory history."""
        return self.download_bytes("/inventory/sample", {"format": file_format})

    def inventory_forecast(
        self,
        *,
        dataset_id: str | None = None,
        horizon_periods: int | None = None,
        confidence_level: float | None = None,
        model: str = "auto",
        as_of_date: str | None = None,
        materials: list[str] | None = None,
        plants: list[str] | None = None,
        generate_ai_summary: bool = False,
    ) -> dict[str, Any]:
        """Run the predictor over a loaded dataset."""
        payload: dict[str, Any] = {
            "model": model,
            "generate_ai_summary": generate_ai_summary,
        }
        if dataset_id:
            payload["dataset_id"] = dataset_id
        if horizon_periods:
            payload["horizon_periods"] = horizon_periods
        if confidence_level:
            payload["confidence_level"] = confidence_level
        if as_of_date:
            payload["as_of_date"] = as_of_date
        if materials:
            payload["materials"] = materials
        if plants:
            payload["plants"] = plants
        return self._request("POST", "/inventory/forecast", json=payload)

    def inventory_forecasts(self, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        """List previous forecast runs, newest first."""
        return self._request(
            "GET", "/inventory/forecasts", params={"limit": limit, "offset": offset}
        )

    def inventory_forecast_run(self, forecast_id: str, item_limit: int = 200) -> dict[str, Any]:
        """Fetch one forecast run with its materials."""
        return self._request(
            "GET", f"/inventory/forecasts/{forecast_id}", params={"item_limit": item_limit}
        )

    def inventory_items(self, forecast_id: str, **filters: Any) -> dict[str, Any]:
        """List materials inside a forecast run, with optional filters."""
        params = {key: value for key, value in filters.items() if value not in (None, "", [])}
        return self._request("GET", f"/inventory/forecasts/{forecast_id}/items", params=params)

    def inventory_item(
        self,
        forecast_id: str,
        material: str,
        plant: str,
        storage_location: str | None = None,
    ) -> dict[str, Any]:
        """Fetch one material's complete forecast."""
        params: dict[str, Any] = {"material": material, "plant": plant}
        if storage_location:
            params["storage_location"] = storage_location
        return self._request("GET", f"/inventory/forecasts/{forecast_id}/item", params=params)

    def inventory_export(self, forecast_id: str, export_format: str) -> bytes:
        """Download a forecast report."""
        return self.download_bytes(
            f"/inventory/forecasts/{forecast_id}/export", {"format": export_format}
        )

    # -- Contract Assistant ----------------------------------------------
    def contract_upload(
        self, filename: str, content: bytes, content_type: str
    ) -> dict[str, Any]:
        """Upload a contract document and extract its text."""
        return self._request(
            "POST", "/contracts/upload", files={"file": (filename, content, content_type)}
        )

    def contract_analyze(
        self,
        contract_id: str,
        *,
        as_of_date: str | None = None,
        enabled_rules: list[str] | None = None,
        generate_ai_summary: bool = False,
    ) -> dict[str, Any]:
        """Run the deterministic clause, date and risk analysis."""
        payload: dict[str, Any] = {"generate_ai_summary": generate_ai_summary}
        if as_of_date:
            payload["as_of_date"] = as_of_date
        if enabled_rules:
            payload["enabled_rules"] = enabled_rules
        return self._request("POST", f"/contracts/{contract_id}/analyze", json=payload)

    def contract(self, contract_id: str) -> dict[str, Any]:
        """Fetch one contract with its full analysis."""
        return self._request("GET", f"/contracts/{contract_id}")

    def contracts(self, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        """List uploaded contracts, newest first."""
        return self._request("GET", "/contracts", params={"limit": limit, "offset": offset})

    def contract_clauses(self, contract_id: str, **filters: Any) -> dict[str, Any]:
        """Fetch the clause table, with optional filters."""
        params = {key: value for key, value in filters.items() if value not in (None, "", [])}
        return self._request("GET", f"/contracts/{contract_id}/clauses", params=params)

    def contract_question(
        self, contract_id: str, question: str, *, generate_ai_summary: bool = False
    ) -> dict[str, Any]:
        """Ask a question about a contract and get an answer with citations."""
        return self._request(
            "POST",
            f"/contracts/{contract_id}/questions",
            json={"question": question, "generate_ai_summary": generate_ai_summary},
        )

    def contract_methodology(self) -> dict[str, Any]:
        """Fetch the clause catalogue, the risk rules and the confidence formula."""
        return self._request("GET", "/contracts/methodology")

    def contract_extractors(self) -> dict[str, Any]:
        """Report which document types can be read and whether OCR is configured."""
        return self._request("GET", "/contracts/extractors")

    def contract_sample_info(self) -> dict[str, Any]:
        """Describe the bundled fictional sample contracts."""
        return self._request("GET", "/contracts/sample/info")

    def contract_sample_file(self, name: str, file_format: str) -> bytes:
        """Download one bundled fictional contract."""
        return self.download_bytes("/contracts/sample", {"name": name, "format": file_format})

    def contract_export(self, contract_id: str, export_format: str) -> bytes:
        """Download a contract report."""
        return self.download_bytes(
            f"/contracts/{contract_id}/export", {"format": export_format}
        )
