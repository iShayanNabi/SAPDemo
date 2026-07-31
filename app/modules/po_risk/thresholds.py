"""Typed access to the PO risk rule configuration.

The JSON file ``config/po_risk_rules.json`` is the single place where
thresholds live. This module validates it with Pydantic and exposes small
helpers so a rule can ask for a parameter without knowing about file paths::

    config = load_rule_config()
    window = config.param("PO-R003", "window_days", 7)
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError as PydanticValidationError

from app.core.exceptions import ConfigurationError
from app.core.logging import get_logger
from app.schemas.common import Severity

logger = get_logger(__name__)

DEFAULT_CONFIG_PATH: Path = Path(__file__).resolve().parent / "config" / "po_risk_rules.json"


class HighRiskSupplier(BaseModel):
    """A supplier flagged by the compliance watch list."""

    supplier_id: str
    risk_level: Severity = Severity.HIGH
    reason: str = ""


class SeverityEscalation(BaseModel):
    """Value bands that can raise a finding's severity."""

    enabled: bool = True
    high_value_base: float = 100_000.0
    critical_value_base: float = 250_000.0


class RuleSettings(BaseModel):
    """Configuration of a single deterministic rule."""

    name: str
    category: str
    enabled: bool = True
    base_severity: Severity = Severity.MEDIUM
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    recommended_action: str = ""
    params: dict[str, Any] = Field(default_factory=dict)


class PoRiskConfig(BaseModel):
    """The complete, validated rule configuration."""

    config_version: str
    description: str = ""
    base_currency: str = "EUR"
    currency_rates: dict[str, float] = Field(default_factory=lambda: {"EUR": 1.0})
    approval_thresholds: list[float] = Field(default_factory=list)
    approved_status_values: list[str] = Field(default_factory=list)
    not_approved_status_values: list[str] = Field(default_factory=list)
    standard_payment_terms: list[str] = Field(default_factory=list)
    expected_currencies_by_company_code: dict[str, str] = Field(default_factory=dict)
    high_risk_suppliers: list[HighRiskSupplier] = Field(default_factory=list)
    severity_value_escalation: SeverityEscalation = Field(default_factory=SeverityEscalation)
    rules: dict[str, RuleSettings]

    # ------------------------------------------------------------------
    # Helpers used by the rules
    # ------------------------------------------------------------------
    def rule(self, rule_id: str) -> RuleSettings:
        """Return the settings for ``rule_id``."""
        try:
            return self.rules[rule_id]
        except KeyError as exc:
            raise ConfigurationError(
                f"Rule '{rule_id}' is not present in the risk configuration.",
                details={"known_rules": sorted(self.rules)},
            ) from exc

    def param(self, rule_id: str, key: str, default: Any = None) -> Any:
        """Return a single parameter of ``rule_id``, or ``default``."""
        return self.rule(rule_id).params.get(key, default)

    def is_enabled(self, rule_id: str) -> bool:
        """Return whether ``rule_id`` is switched on."""
        return rule_id in self.rules and self.rules[rule_id].enabled

    def conversion_rate(self, currency: str | None) -> float:
        """Return the rate that converts ``currency`` into the base currency."""
        if not currency:
            return 1.0
        return float(self.currency_rates.get(str(currency).upper(), 1.0))

    def to_base_currency(self, amount: float | None, currency: str | None) -> float:
        """Convert ``amount`` from ``currency`` into the configured base currency."""
        if amount is None:
            return 0.0
        return float(amount) * self.conversion_rate(currency)

    def high_risk_supplier_map(self) -> dict[str, HighRiskSupplier]:
        """Watch-list suppliers keyed by supplier id."""
        return {entry.supplier_id: entry for entry in self.high_risk_suppliers}

    def sorted_approval_thresholds(self) -> list[float]:
        """Approval thresholds in ascending order."""
        return sorted(self.approval_thresholds)


def load_rule_config(path: Path | str | None = None) -> PoRiskConfig:
    """Load and validate the rule configuration from ``path``."""
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not config_path.is_file():
        raise ConfigurationError(
            "The risk rule configuration file is missing.",
            details={"expected_path": str(config_path)},
        )
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigurationError(
            f"The risk rule configuration is not valid JSON: {exc.msg} (line {exc.lineno})."
        ) from exc

    try:
        return PoRiskConfig.model_validate(raw)
    except PydanticValidationError as exc:
        raise ConfigurationError(
            "The risk rule configuration failed validation.",
            details={"errors": exc.errors(include_url=False)[:10]},
        ) from exc


@lru_cache
def get_rule_config() -> PoRiskConfig:
    """Return the cached default configuration."""
    config = load_rule_config()
    logger.info(
        "Loaded PO risk configuration v%s with %d rules",
        config.config_version,
        len(config.rules),
    )
    return config
