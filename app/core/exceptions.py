"""Application exception hierarchy.

Every exception carries a machine readable ``code`` plus a *safe* message that
can be shown to a user. Internal detail (stack traces, file system paths,
provider payloads) stays in the logs and never travels to the client.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base class for all expected application errors."""

    code: str = "app_error"
    http_status: int = 400

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        code: str | None = None,
        http_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}
        if code:
            self.code = code
        if http_status:
            self.http_status = http_status

    def to_dict(self) -> dict[str, Any]:
        """Serialise into the API error envelope."""
        return {"code": self.code, "message": self.message, "details": self.details}


class ValidationError(AppError):
    """Input failed validation (bad columns, bad types, bad request body)."""

    code = "validation_error"
    http_status = 422


class FileValidationError(AppError):
    """An uploaded file was rejected (extension, size, structure, emptiness)."""

    code = "file_validation_error"
    http_status = 400


class UnsafePathError(AppError):
    """A filename or path escaped its allowed directory."""

    code = "unsafe_path"
    http_status = 400


class NotFoundError(AppError):
    """A requested resource does not exist."""

    code = "not_found"
    http_status = 404


class AnalysisError(AppError):
    """The risk analysis pipeline failed."""

    code = "analysis_error"
    http_status = 500


class AIProviderError(AppError):
    """An AI provider call failed, timed out, or returned unusable output.

    This is never fatal for the product: the deterministic rule results are
    always returned, only the optional narrative enrichment is missing.
    """

    code = "ai_provider_error"
    http_status = 502


class ConfigurationError(AppError):
    """The rule configuration or environment is invalid."""

    code = "configuration_error"
    http_status = 500
