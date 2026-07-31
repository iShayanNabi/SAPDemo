"""The purchasing requirement the engine scores suppliers against.

This is a plain dataclass shared by the eligibility and scoring layers. The
API-facing Pydantic request schema (``app/schemas/supplier_reco.py``) is
converted into one of these before the deterministic engine runs, so the engine
never depends on the HTTP contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.modules.supplier_reco.thresholds import SupplierRecoConfig


@dataclass
class Requirement:
    """A purchasing requirement to source."""

    material: str | None = None
    material_description: str | None = None
    material_group: str | None = None
    quantity: float | None = None
    unit_of_measure: str | None = None
    plant: str | None = None
    company_code: str | None = None
    required_delivery_date: date | None = None
    order_date: date | None = None
    target_price: float | None = None
    currency: str | None = None
    preferred_region: str | None = None
    risk_tolerance: str = "medium"
    sustainability_requirement: float | None = None
    contract_requirement: bool = False
    minimum_quality_score: float | None = None
    minimum_available_capacity: float | None = None

    def target_price_base(self, config: SupplierRecoConfig) -> float | None:
        """Target price converted into the base currency."""
        return config.to_base_currency(self.target_price, self.currency)

    def days_until_required(self) -> int | None:
        """Days between the order date and the required delivery date.

        Uses ``order_date`` when supplied. Returns ``None`` when either date is
        missing, so no downstream calculation depends on the wall-clock date.
        """
        if self.required_delivery_date is None or self.order_date is None:
            return None
        return (self.required_delivery_date - self.order_date).days
