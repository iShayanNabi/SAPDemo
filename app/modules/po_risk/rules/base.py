"""Building blocks for the deterministic risk rules.

A rule is a small class with one job: look at the canonical dataset and return
:class:`RuleFinding` objects. Rules never call an AI model, never touch the
database and never read files - which is exactly why they are cheap to unit
test and fully reproducible.

Anything a rule needs beyond the raw rows (material price statistics, contract
usage, supplier spend shares) is computed once per analysis by
:class:`RuleContext` and cached.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from functools import cached_property
from typing import Any

import numpy as np
import pandas as pd

from app.core.logging import get_logger
from app.schemas.common import OutputOrigin, Severity
from app.modules.po_risk.thresholds import PoRiskConfig

logger = get_logger(__name__)


@dataclass
class RuleFinding:
    """One deterministic risk finding.

    ``output_origin`` is always ``rule_based``: the risk determination itself is
    never made by an AI model. Optional AI narratives are attached later and
    kept in separate fields.
    """

    rule_id: str
    rule_name: str
    risk_category: str
    severity: Severity
    explanation: str
    recommended_action: str
    confidence_score: float
    estimated_financial_exposure: float
    exposure_currency: str = "EUR"
    po_number: str | None = None
    po_item: str | None = None
    supplier_id: str | None = None
    supplier_name: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    output_origin: OutputOrigin = OutputOrigin.RULE_BASED

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe representation used by exports and the API layer."""
        return {
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "risk_category": self.risk_category,
            "severity": self.severity.value,
            "po_number": self.po_number,
            "po_item": self.po_item,
            "supplier_id": self.supplier_id,
            "supplier_name": self.supplier_name,
            "explanation": self.explanation,
            "evidence": _json_safe(self.evidence),
            "recommended_action": self.recommended_action,
            "confidence_score": round(float(self.confidence_score), 3),
            "estimated_financial_exposure": round(float(self.estimated_financial_exposure), 2),
            "exposure_currency": self.exposure_currency,
            "output_origin": self.output_origin.value,
        }


def _json_safe(value: Any) -> Any:
    """Recursively convert numpy/pandas scalars into plain Python values."""
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return round(float(value), 6)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


class RuleContext:
    """Shared, pre-computed view of the dataset handed to every rule."""

    def __init__(self, frame: pd.DataFrame, config: PoRiskConfig) -> None:
        self.frame = frame
        self.config = config
        self.base_currency = config.base_currency

    # ------------------------------------------------------------------
    # Derived views - each computed at most once per analysis
    # ------------------------------------------------------------------
    @cached_property
    def priced_rows(self) -> pd.DataFrame:
        """Rows that have a usable unit price and quantity."""
        frame = self.frame
        mask = (
            frame["unit_price_base"].notna()
            & (pd.to_numeric(frame["unit_price_base"], errors="coerce") > 0)
            & frame["quantity"].notna()
        )
        return frame[mask]

    @cached_property
    def material_price_stats(self) -> pd.DataFrame:
        """Median/std of the base-currency unit price per material."""
        rows = self.priced_rows.dropna(subset=["material"])
        if rows.empty:
            return pd.DataFrame(columns=["median_price", "observations", "min_price", "max_price"])
        grouped = rows.groupby("material")["unit_price_base"]
        stats = pd.DataFrame(
            {
                "median_price": grouped.median(),
                "observations": grouped.count(),
                "min_price": grouped.min(),
                "max_price": grouped.max(),
            }
        )
        return stats

    @cached_property
    def material_quantity_stats(self) -> pd.DataFrame:
        """Median ordered quantity per material."""
        rows = self.frame.dropna(subset=["material", "quantity"])
        if rows.empty:
            return pd.DataFrame(columns=["median_quantity", "observations"])
        grouped = rows.groupby("material")["quantity"]
        return pd.DataFrame({"median_quantity": grouped.median(), "observations": grouped.count()})

    @cached_property
    def contracted_material_suppliers(self) -> dict[str, dict[str, int]]:
        """Materials that are bought under a contract -> {supplier_id: line count}."""
        rows = self.frame.dropna(subset=["material", "contract_number", "supplier_id"])
        result: dict[str, dict[str, int]] = {}
        for (material, supplier), group in rows.groupby(["material", "supplier_id"]):
            result.setdefault(str(material), {})[str(supplier)] = int(len(group))
        return result

    @cached_property
    def po_header_values(self) -> pd.DataFrame:
        """Aggregated header level view: one row per purchase order."""
        rows = self.frame.dropna(subset=["po_number"])
        if rows.empty:
            return pd.DataFrame()
        aggregated = rows.groupby("po_number").agg(
            total_value_base=("total_value_base", "sum"),
            supplier_id=("supplier_id", "first"),
            supplier_name=("supplier_name", "first"),
            order_date=("order_date", "min"),
            material_group=("material_group", "first"),
            approval_status=("approval_status", "first"),
            currency=("currency", "first"),
            item_count=("po_item", "count"),
            created_by=("created_by", "first"),
        )
        return aggregated.reset_index()

    @cached_property
    def supplier_names(self) -> dict[str, str]:
        """supplier_id -> supplier_name (first non-null occurrence)."""
        rows = self.frame.dropna(subset=["supplier_id"])
        mapping: dict[str, str] = {}
        for supplier_id, group in rows.groupby("supplier_id"):
            names = group["supplier_name"].dropna()
            if len(names):
                mapping[str(supplier_id)] = str(names.iloc[0])
        return mapping

    @cached_property
    def material_group_spend(self) -> pd.DataFrame:
        """Spend per material group and supplier, with the supplier share."""
        rows = self.frame.dropna(subset=["material_group", "supplier_id"])
        if rows.empty:
            return pd.DataFrame(columns=["material_group", "supplier_id", "spend", "share_pct"])
        by_pair = (
            rows.groupby(["material_group", "supplier_id"])["total_value_base"].sum().reset_index()
        )
        by_group = rows.groupby("material_group")["total_value_base"].sum()
        by_pair = by_pair.rename(columns={"total_value_base": "spend"})
        by_pair["group_spend"] = by_pair["material_group"].map(by_group)
        by_pair["share_pct"] = np.where(
            by_pair["group_spend"] > 0, by_pair["spend"] / by_pair["group_spend"] * 100.0, 0.0
        )
        return by_pair

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def supplier_name_for(self, supplier_id: Any) -> str | None:
        """Look up a supplier name by id."""
        if supplier_id is None or (isinstance(supplier_id, float) and pd.isna(supplier_id)):
            return None
        return self.supplier_names.get(str(supplier_id))

    def escalate_severity(self, base: Severity, exposure_base: float) -> Severity:
        """Raise ``base`` when the exposed value crosses a configured band."""
        escalation = self.config.severity_value_escalation
        if not escalation.enabled:
            return base
        if exposure_base >= escalation.critical_value_base:
            return max(base, Severity.CRITICAL, key=lambda s: s.rank)
        if exposure_base >= escalation.high_value_base:
            return max(base, Severity.HIGH, key=lambda s: s.rank)
        return base

    def is_approved(self, status: Any) -> bool:
        """Return whether an approval status counts as released."""
        if status is None or (isinstance(status, float) and pd.isna(status)):
            return False
        return str(status).strip().lower() in {
            value.lower() for value in self.config.approved_status_values
        }


class BaseRule:
    """Base class for every deterministic rule.

    Subclasses set ``rule_id`` and implement :meth:`evaluate`.
    """

    rule_id: str = ""

    def __init__(self, config: PoRiskConfig) -> None:
        self.config = config
        self.settings = config.rule(self.rule_id)

    # -- convenience accessors -------------------------------------------------
    @property
    def name(self) -> str:
        return self.settings.name

    @property
    def category(self) -> str:
        return self.settings.category

    @property
    def base_severity(self) -> Severity:
        return self.settings.base_severity

    @property
    def confidence(self) -> float:
        return float(self.settings.confidence)

    @property
    def enabled(self) -> bool:
        return bool(self.settings.enabled)

    @property
    def action(self) -> str:
        return self.settings.recommended_action

    def param(self, key: str, default: Any = None) -> Any:
        """Return a configured parameter of this rule."""
        return self.settings.params.get(key, default)

    # -- API -------------------------------------------------------------------
    def evaluate(self, context: RuleContext) -> list[RuleFinding]:  # pragma: no cover - abstract
        """Return the findings this rule detects in ``context``."""
        raise NotImplementedError

    def make_finding(
        self,
        *,
        explanation: str,
        evidence: dict[str, Any],
        exposure: float,
        severity: Severity | None = None,
        confidence: float | None = None,
        po_number: Any = None,
        po_item: Any = None,
        supplier_id: Any = None,
        supplier_name: Any = None,
        recommended_action: str | None = None,
    ) -> RuleFinding:
        """Create a finding pre-filled with this rule's metadata."""
        return RuleFinding(
            rule_id=self.rule_id,
            rule_name=self.name,
            risk_category=self.category,
            severity=severity or self.base_severity,
            explanation=explanation,
            recommended_action=recommended_action or self.action,
            confidence_score=self.confidence if confidence is None else confidence,
            estimated_financial_exposure=float(max(exposure, 0.0)),
            po_number=_as_optional_str(po_number),
            po_item=_as_optional_str(po_item),
            supplier_id=_as_optional_str(supplier_id),
            supplier_name=_as_optional_str(supplier_name),
            evidence=evidence,
        )


def _as_optional_str(value: Any) -> str | None:
    """Convert a cell value to ``str`` unless it is missing."""
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    if pd.isna(value) if not isinstance(value, (str, int, bool)) else False:
        return None
    return str(value)
