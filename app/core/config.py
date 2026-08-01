"""Central application configuration.

Every tunable value in the SAP AI Application Lab is read from this module.
Nothing else in the codebase should call ``os.environ`` directly, and secrets
are never written to source control: they come from environment variables or a
local ``.env`` file which is git-ignored.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repository root = two levels above this file (app/core/config.py -> app -> root)
PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]

AIProviderName = Literal["mock", "anthropic", "openai"]
OcrProviderName = Literal["none", "local", "aws_textract", "azure_document_intelligence"]


def _extension_set(raw: str) -> set[str]:
    """Parse a comma separated extension list into a normalised set."""
    return {
        ext.strip().lower() if ext.strip().startswith(".") else f".{ext.strip().lower()}"
        for ext in raw.split(",")
        if ext.strip()
    }


class Settings(BaseSettings):
    """Application settings loaded from environment variables / ``.env``."""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ------------------------------------------------------------------
    # Application
    # ------------------------------------------------------------------
    app_name: str = "SAP AI Application Lab"
    app_version: str = "0.1.0"
    environment: Literal["local", "test", "staging", "production"] = "local"
    debug: bool = True
    api_v1_prefix: str = "/api/v1"

    # Comma separated list of origins allowed to call the API (future website).
    cors_origins: str = "http://localhost:3000,http://localhost:8501"

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = False

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------
    # SQLite by default. Any PostgreSQL URL works unchanged, e.g.
    # postgresql+psycopg://user:password@localhost:5432/sap_ai_lab
    database_url: str = f"sqlite:///{PROJECT_ROOT / 'data' / 'sap_ai_lab.db'}"
    database_echo: bool = False

    # ------------------------------------------------------------------
    # Storage paths
    # ------------------------------------------------------------------
    data_dir: Path = PROJECT_ROOT / "data"
    upload_dir: Path = PROJECT_ROOT / "data" / "uploads"
    export_dir: Path = PROJECT_ROOT / "data" / "exports"
    sample_dir: Path = PROJECT_ROOT / "data" / "sample"

    # ------------------------------------------------------------------
    # Upload security
    # ------------------------------------------------------------------
    max_upload_bytes: int = 25 * 1024 * 1024  # 25 MB
    max_rows_per_upload: int = 200_000
    allowed_upload_extensions: str = ".csv,.xlsx,.json"

    # ------------------------------------------------------------------
    # Document uploads (module 6 - Contract Assistant)
    # ------------------------------------------------------------------
    # Documents travel a separate allow list from the tabular uploads: a
    # contract is a PDF/DOCX/TXT, never a spreadsheet, and a spreadsheet module
    # must never start accepting PDFs because this list grew.
    allowed_document_extensions: str = ".pdf,.docx,.txt,.md"
    #: Image types that are only accepted when an OCR provider is configured.
    allowed_image_extensions: str = ".png,.jpg,.jpeg,.tif,.tiff"
    max_document_bytes: int = 20 * 1024 * 1024  # 20 MB
    max_document_pages: int = 400
    #: A page holding fewer characters than this is treated as image-only.
    min_chars_per_text_page: int = 40

    # ------------------------------------------------------------------
    # OCR providers
    # ------------------------------------------------------------------
    # ``none`` is the default and is what makes the lab runnable with no
    # credentials: scanned documents are reported honestly as unprocessable
    # rather than silently producing an empty analysis.
    ocr_provider: OcrProviderName = "none"
    ocr_language: str = "eng"
    aws_textract_region: str | None = None
    aws_access_key_id: str | None = Field(default=None, repr=False)
    aws_secret_access_key: str | None = Field(default=None, repr=False)
    azure_document_intelligence_endpoint: str | None = None
    azure_document_intelligence_key: str | None = Field(default=None, repr=False)

    # ------------------------------------------------------------------
    # AI providers
    # ------------------------------------------------------------------
    # Mock is the default. A real provider is only used when a key exists.
    ai_provider: AIProviderName = "mock"
    anthropic_api_key: str | None = Field(default=None, repr=False)
    openai_api_key: str | None = Field(default=None, repr=False)
    anthropic_model: str = "claude-sonnet-4-5"
    openai_model: str = "gpt-4o-mini"
    ai_timeout_seconds: float = 30.0
    ai_max_retries: int = 2
    ai_max_output_tokens: int = 1200
    ai_enabled: bool = True

    # ------------------------------------------------------------------
    # Streamlit -> FastAPI
    # ------------------------------------------------------------------
    api_base_url: str = "http://127.0.0.1:8000"

    @field_validator("data_dir", "upload_dir", "export_dir", "sample_dir")
    @classmethod
    def _resolve_path(cls, value: Path) -> Path:
        return Path(value).resolve()

    # ------------------------------------------------------------------
    # Derived helpers
    # ------------------------------------------------------------------
    @property
    def cors_origin_list(self) -> list[str]:
        """CORS origins as a list (the raw setting is a comma separated string)."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def cors_allows_any_origin(self) -> bool:
        """Whether ``CORS_ORIGINS`` was set to the ``*`` wildcard."""
        return "*" in self.cors_origin_list

    @property
    def cors_allow_credentials(self) -> bool:
        """Whether cookies and Authorization headers may cross origins.

        Never with a wildcard. ``Access-Control-Allow-Origin: *`` together with
        ``Access-Control-Allow-Credentials: true`` is a combination browsers
        reject outright, so the practical effect of setting both is that every
        cross-origin call fails and somebody spends an afternoon on it. The
        dangerous version is the one where a framework "helpfully" reflects the
        caller's origin instead of sending ``*`` - then any site on the internet
        can read a signed-in user's data.

        So: a wildcard means an open, credential-free API. A named origin list -
        which is what the future website will use - allows credentials.
        """
        return not self.cors_allows_any_origin

    @property
    def allowed_extension_set(self) -> set[str]:
        """Allowed upload extensions, normalised to lowercase with a leading dot."""
        return _extension_set(self.allowed_upload_extensions)

    @property
    def allowed_document_extension_set(self) -> set[str]:
        """Document extensions accepted by the Contract Assistant."""
        return _extension_set(self.allowed_document_extensions)

    @property
    def allowed_image_extension_set(self) -> set[str]:
        """Image extensions, only accepted when an OCR provider is configured."""
        return _extension_set(self.allowed_image_extensions)

    def resolved_ocr_provider(self) -> OcrProviderName:
        """Return the OCR provider that will actually be used.

        Like :meth:`resolved_ai_provider`, this falls back to ``none`` whenever
        the configured provider is missing its credentials, so a half-configured
        environment reports "OCR unavailable" instead of failing at request time.
        """
        if self.ocr_provider == "local":
            return "local"
        if (
            self.ocr_provider == "aws_textract"
            and self.aws_access_key_id
            and self.aws_secret_access_key
            and self.aws_textract_region
        ):
            return "aws_textract"
        if (
            self.ocr_provider == "azure_document_intelligence"
            and self.azure_document_intelligence_endpoint
            and self.azure_document_intelligence_key
        ):
            return "azure_document_intelligence"
        return "none"

    def resolved_ai_provider(self) -> AIProviderName:
        """Return the provider that will actually be used.

        Falls back to ``mock`` whenever AI is disabled or the configured
        provider has no API key. This is what makes the whole project runnable
        with no keys at all.
        """
        if not self.ai_enabled:
            return "mock"
        if self.ai_provider == "anthropic" and self.anthropic_api_key:
            return "anthropic"
        if self.ai_provider == "openai" and self.openai_api_key:
            return "openai"
        return "mock"

    def ensure_directories(self) -> None:
        """Create the runtime directories if they do not exist yet."""
        for directory in (self.data_dir, self.upload_dir, self.export_dir, self.sample_dir):
            directory.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings singleton."""
    settings = Settings()
    settings.ensure_directories()
    return settings


settings: Settings = get_settings()
