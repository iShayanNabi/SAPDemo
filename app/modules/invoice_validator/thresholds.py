"""Typed, validated access to the Invoice Validator configuration.

Every tolerance, tax rate, freight cap, status list, severity band and rule
threshold lives in ``config/invoice_validator_rules.json`` and is validated here
at load time. Rules read values through this object, so retuning the validator
is a JSON edit, never a code change.

The four required tolerances (price, quantity, tax, freight) are first-class
here and can additionally be overridden per validation run through the API,
which is what powers the "tolerance settings" screen in the UI.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from pydantic import ValidationError as PydanticValidationError

from app.core.exceptions import ConfigurationError
from app.core.logging import get_logger
from app.schemas.common import Severity

logger = get_logger(__name__)

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config" / "invoice_validator_rules.json"

#: The four configurable tolerances the requirement calls for.
TOLERANCE_KEYS: tuple[str, ...] = ("price", "quantity", "tax", "freight")


class Tolerance(BaseModel):
    """An allowance expressed as a percentage and an absolute amount.

    A deviation is *out of tolerance* only when it exceeds **both** the absolute
    allowance and the percentage allowance. Requiring both prevents two classic
    false positives: a few cents of rounding on a large value (absolute guard),
    and a large percentage swing on a tiny value (percentage guard).
    """

    pct: float = Field(default=0.0, ge=0.0, description="Percentage allowance of the expected value.")
    abs: float = Field(default=0.0, ge=0.0, description="Absolute allowance in the invoice currency.")

    def exceeds(self, expected: float | None, actual: float | None) -> bool:
        """Return whether ``actual`` deviates from ``expected`` beyond this tolerance."""
        if expected is None or actual is None:
            return False
        abs_diff = abs(float(actual) - float(expected))
        pct_threshold = abs(float(expected)) * self.pct / 100.0
        return abs_diff > self.abs and abs_diff > pct_threshold


class Tolerances(BaseModel):
    """The four configurable tolerances."""

    price: Tolerance = Field(default_factory=lambda: Tolerance(pct=2.0, abs=1.0))
    quantity: Tolerance = Field(default_factory=lambda: Tolerance(pct=0.0, abs=0.0))
    tax: Tolerance = Field(default_factory=lambda: Tolerance(pct=1.0, abs=0.5))
    freight: Tolerance = Field(default_factory=lambda: Tolerance(pct=5.0, abs=5.0))

    def as_dict(self) -> dict[str, dict[str, float]]:
        return {key: getattr(self, key).model_dump() for key in TOLERANCE_KEYS}


class FreightPolicy(BaseModel):
    """The ceiling used by the freight-mismatch rule.

    Freight is flagged when it exceeds the larger of a flat cap and a percentage
    of the invoice subtotal - a supplier billing disproportionate freight.
    """

    max_pct: float = Field(default=10.0, ge=0.0, description="Freight as a percentage of subtotal.")
    flat_cap: float = Field(default=250.0, ge=0.0, description="Flat freight ceiling in base currency.")


class DuplicateSettings(BaseModel):
    """Parameters for the duplicate-invoice rule."""

    amount_tolerance_abs: float = Field(default=0.5, ge=0.0)
    date_window_days: int = Field(default=0, ge=0)


class SeverityEscalation(BaseModel):
    """Value bands that can raise an exception's severity."""

    enabled: bool = True
    high_value_base: float = 25_000.0
    critical_value_base: float = 100_000.0


class ReportingSettings(BaseModel):
    """Presentation defaults and the standing disclaimer."""

    max_matches_stored: int = Field(default=5000, ge=0)
    validation_disclaimer: str = ""


class RuleSettings(BaseModel):
    """Configuration of a single deterministic validation rule."""

    name: str
    category: str
    enabled: bool = True
    base_severity: Severity = Severity.MEDIUM
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)
    recommended_action: str = ""
    params: dict[str, Any] = Field(default_factory=dict)


class InvoiceValidatorConfig(BaseModel):
    """The complete, validated Invoice Validator configuration."""

    config_version: str
    description: str = ""
    base_currency: str = "EUR"
    currency_rates: dict[str, float] = Field(default_factory=lambda: {"EUR": 1.0})

    tolerances: Tolerances = Field(default_factory=Tolerances)
    expected_tax_rate: float = Field(default=0.19, ge=0.0, le=1.0)
    freight_policy: FreightPolicy = Field(default_factory=FreightPolicy)
    duplicate: DuplicateSettings = Field(default_factory=DuplicateSettings)
    closed_po_status_values: list[str] = Field(default_factory=list)
    future_date_grace_days: int = Field(default=0, ge=0)
    severity_value_escalation: SeverityEscalation = Field(default_factory=SeverityEscalation)
    reporting: ReportingSettings = Field(default_factory=ReportingSettings)
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
                f"Rule '{rule_id}' is not present in the invoice validator configuration.",
                details={"known_rules": sorted(self.rules)},
            ) from exc

    def param(self, rule_id: str, key: str, default: Any = None) -> Any:
        """Return a single parameter of ``rule_id``, or ``default``."""
        return self.rule(rule_id).params.get(key, default)

    def conversion_rate(self, currency: str | None) -> float:
        """Rate that converts ``currency`` into the base currency."""
        if not currency:
            return 1.0
        return float(self.currency_rates.get(str(currency).upper(), 1.0))

    def to_base_currency(self, amount: float | None, currency: str | None) -> float | None:
        """Convert an amount into the base currency, preserving ``None``."""
        if amount is None:
            return None
        return float(amount) * self.conversion_rate(currency)

    def is_closed_status(self, status: str | None) -> bool:
        """Return whether a PO status label counts as closed / delivery-complete."""
        if status is None:
            return False
        needle = str(status).strip().lower()
        if not needle:
            return False
        return needle in {value.strip().lower() for value in self.closed_po_status_values}

    def with_tolerances(self, tolerances: Tolerances) -> InvoiceValidatorConfig:
        """Return a copy of this configuration with different tolerances applied.

        Used to honour per-run tolerance overrides without mutating the cached
        default configuration.
        """
        return self.model_copy(update={"tolerances": tolerances})


def load_invoice_validator_config(path: Path | str | None = None) -> InvoiceValidatorConfig:
    """Load and validate the invoice validator configuration from ``path``."""
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not config_path.is_file():
        raise ConfigurationError(
            f"Invoice validator configuration file is missing: {config_path.name}"
        )
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigurationError(
            f"Invoice validator configuration is not valid JSON: {exc.msg} (line {exc.lineno})."
        ) from exc
    try:
        config = InvoiceValidatorConfig.model_validate(raw)
    except PydanticValidationError as exc:
        raise ConfigurationError(
            f"Invoice validator configuration failed validation: {exc.error_count()} problem(s).",
            details={"errors": exc.errors(include_url=False)[:10]},
        ) from exc

    logger.info(
        "Loaded invoice validator configuration v%s with %d rules",
        config.config_version, len(config.rules),
    )
    return config


@lru_cache(maxsize=1)
def get_invoice_validator_config() -> InvoiceValidatorConfig:
    """Return the cached default configuration."""
    return load_invoice_validator_config()
