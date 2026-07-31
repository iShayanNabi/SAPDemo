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
    def allowed_extension_set(self) -> set[str]:
        """Allowed upload extensions, normalised to lowercase with a leading dot."""
        return {
            ext.strip().lower() if ext.strip().startswith(".") else f".{ext.strip().lower()}"
            for ext in self.allowed_upload_extensions.split(",")
            if ext.strip()
        }

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
