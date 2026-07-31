"""Typed, validated access to the Spend Analytics configuration.

Every threshold, classification list and savings assumption the module uses is
declared in ``config/spend_rules.json`` and validated here at load time. Rules
and metrics read values through this object, so retuning the dashboard is a
JSON edit rather than a code change.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError as PydanticValidationError

from app.core.exceptions import ConfigurationError
from app.core.logging import get_logger

logger = get_logger(__name__)

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config" / "spend_rules.json"


class MaverickDefinition(BaseModel):
    """How maverick spend is identified."""

    description: str = ""
    requires_no_contract: bool = True
    requires_non_preferred_supplier: bool = True


class UnderManagementDefinition(BaseModel):
    """How spend under management is identified."""

    description: str = ""
    counts_contracted: bool = True
    counts_preferred_supplier: bool = True


class ClassificationSettings(BaseModel):
    """Value lists that turn free-text status columns into booleans."""

    contracted_status_values: list[str] = Field(default_factory=list)
    non_contracted_status_values: list[str] = Field(default_factory=list)
    derive_contract_status_from_contract_number: bool = True
    preferred_status_values: list[str] = Field(default_factory=list)
    non_preferred_status_values: list[str] = Field(default_factory=list)
    maverick_definition: MaverickDefinition = Field(default_factory=MaverickDefinition)
    spend_under_management_definition: UnderManagementDefinition = Field(
        default_factory=UnderManagementDefinition
    )


class TailSpendSettings(BaseModel):
    """Pareto parameters for tail-spend classification."""

    description: str = ""
    cumulative_share_threshold_pct: float = Field(default=80.0, gt=0, le=100)
    small_supplier_share_pct: float = Field(default=0.5, ge=0, le=100)
    min_suppliers_for_classification: int = Field(default=5, ge=1)


class ConcentrationSettings(BaseModel):
    """Thresholds for supplier concentration measures."""

    description: str = ""
    top_supplier_share_warning_pct: float = 25.0
    top_five_share_warning_pct: float = 60.0
    hhi_moderate: float = 1500.0
    hhi_high: float = 2500.0
    category_concentration_warning_pct: float = 75.0
    min_category_spend_base: float = 50000.0


class PriceVarianceSettings(BaseModel):
    """How purchase price variance is measured."""

    description: str = ""
    comparison_basis: str = "baseline_price"
    fallback_basis: str = "material_median"
    min_observations: int = Field(default=4, ge=2)
    variance_alert_pct: float = 15.0
    high_variance_alert_pct: float = 30.0
    min_line_value_base: float = 250.0


class SavingsRuleSettings(BaseModel):
    """One configurable savings opportunity rule."""

    name: str
    enabled: bool = True
    description: str = ""
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    realization_factor: float = Field(default=0.5, ge=0.0, le=1.0)
    params: dict[str, Any] = Field(default_factory=dict)

    def param(self, key: str, default: Any = None) -> Any:
        """Read one parameter of this rule."""
        return self.params.get(key, default)


class ReportingSettings(BaseModel):
    """Presentation defaults and the standing savings disclaimer."""

    top_n_default: int = 10
    max_drilldown_rows: int = 1000
    monthly_trend_months: int = 24
    opportunity_disclaimer: str = ""


class SpendConfig(BaseModel):
    """The complete, validated Spend Analytics configuration."""

    config_version: str
    description: str = ""
    base_currency: str = "EUR"
    currency_rates: dict[str, float] = Field(default_factory=lambda: {"EUR": 1.0})
    classification: ClassificationSettings = Field(default_factory=ClassificationSettings)
    tail_spend: TailSpendSettings = Field(default_factory=TailSpendSettings)
    concentration: ConcentrationSettings = Field(default_factory=ConcentrationSettings)
    price_variance: PriceVarianceSettings = Field(default_factory=PriceVarianceSettings)
    savings_rules: dict[str, SavingsRuleSettings]
    reporting: ReportingSettings = Field(default_factory=ReportingSettings)

    # -- helpers ---------------------------------------------------------
    def conversion_rate(self, currency: str | None) -> float:
        """Rate that converts ``currency`` into the base currency."""
        if not currency:
            return 1.0
        return float(self.currency_rates.get(str(currency).upper(), 1.0))

    def to_base_currency(self, amount: float | None, currency: str | None) -> float:
        """Convert an amount into the base currency, treating ``None`` as zero."""
        if amount is None:
            return 0.0
        return float(amount) * self.conversion_rate(currency)

    def savings_rule(self, rule_id: str) -> SavingsRuleSettings:
        """Look up one savings rule, failing loudly when it is unknown."""
        try:
            return self.savings_rules[rule_id]
        except KeyError as exc:
            raise ConfigurationError(
                f"Savings rule '{rule_id}' is not defined in the spend configuration."
            ) from exc

    def is_savings_rule_enabled(self, rule_id: str) -> bool:
        """True when the rule exists and is switched on."""
        rule = self.savings_rules.get(rule_id)
        return bool(rule and rule.enabled)

    @property
    def enabled_savings_rules(self) -> list[str]:
        """IDs of every enabled savings rule, in configuration order."""
        return [rule_id for rule_id, rule in self.savings_rules.items() if rule.enabled]


def load_spend_config(path: Path | str | None = None) -> SpendConfig:
    """Load and validate the spend configuration from ``path``."""
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not config_path.is_file():
        raise ConfigurationError(
            f"Spend configuration file is missing: {config_path.name}"
        )
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigurationError(
            f"Spend configuration is not valid JSON: {exc.msg} (line {exc.lineno})"
        ) from exc
    try:
        config = SpendConfig.model_validate(raw)
    except PydanticValidationError as exc:
        raise ConfigurationError(
            f"Spend configuration failed validation: {exc.error_count()} problem(s).",
            details={"errors": exc.errors(include_url=False)[:10]},
        ) from exc

    logger.info(
        "Loaded spend configuration v%s with %d savings rules",
        config.config_version, len(config.savings_rules),
    )
    return config


@lru_cache(maxsize=1)
def get_spend_config() -> SpendConfig:
    """Return the cached default configuration."""
    return load_spend_config()
