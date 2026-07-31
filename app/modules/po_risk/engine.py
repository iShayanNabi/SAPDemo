"""The deterministic purchase order risk engine.

The engine executes every enabled rule against the canonical dataset, collects
the findings and computes aggregate KPIs. It contains no AI and no I/O, so the
same input always produces the same output - a property the tests rely on.

Failure handling: if one rule raises, the engine records the failure in
``rule_errors`` and continues with the remaining rules. Nothing is swallowed
silently; the error travels back to the API response and is written to the log.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from app.core.logging import get_logger
from app.schemas.common import Severity
from app.modules.po_risk.rules import RULE_CLASSES, RuleContext, RuleFinding
from app.modules.po_risk.thresholds import PoRiskConfig, get_rule_config

logger = get_logger(__name__)

ENGINE_VERSION = "1.0.0"

#: Points assigned per severity when computing the aggregate risk score.
SEVERITY_WEIGHTS: dict[Severity, int] = {
    Severity.LOW: 1,
    Severity.MEDIUM: 3,
    Severity.HIGH: 8,
    Severity.CRITICAL: 20,
}


@dataclass
class RuleExecution:
    """Bookkeeping for one rule run."""

    rule_id: str
    rule_name: str
    enabled: bool
    findings_count: int
    duration_ms: int
    error: str | None = None


@dataclass
class EngineResult:
    """Everything the engine produced for one dataset."""

    findings: list[RuleFinding]
    summary: dict[str, Any]
    supplier_risk: list[dict[str, Any]]
    executions: list[RuleExecution]
    engine_version: str = ENGINE_VERSION
    config_version: str = ""
    duration_ms: int = 0
    rule_errors: list[dict[str, str]] = field(default_factory=list)

    @property
    def findings_as_dicts(self) -> list[dict[str, Any]]:
        return [finding.to_dict() for finding in self.findings]


class RiskEngine:
    """Runs the configured rule set over a normalised dataset."""

    def __init__(self, config: PoRiskConfig | None = None) -> None:
        self.config = config or get_rule_config()

    def run(self, frame: pd.DataFrame, *, enabled_rules: list[str] | None = None) -> EngineResult:
        """Execute all rules against ``frame``.

        Args:
            frame: The canonical dataset produced by the normaliser.
            enabled_rules: Optional subset of rule ids to run. ``None`` runs
                every rule that is enabled in the configuration.
        """
        started = time.perf_counter()
        context = RuleContext(frame=frame, config=self.config)

        findings: list[RuleFinding] = []
        executions: list[RuleExecution] = []
        rule_errors: list[dict[str, str]] = []

        for rule_class in RULE_CLASSES:
            rule = rule_class(self.config)
            selected = enabled_rules is None or rule.rule_id in enabled_rules
            if not rule.enabled or not selected:
                executions.append(
                    RuleExecution(rule.rule_id, rule.name, enabled=False, findings_count=0, duration_ms=0)
                )
                continue

            rule_started = time.perf_counter()
            try:
                rule_findings = rule.evaluate(context)
            except Exception as exc:  # noqa: BLE001 - one bad rule must not kill the run
                duration = int((time.perf_counter() - rule_started) * 1000)
                message = f"{type(exc).__name__}: {exc}"
                logger.exception("Rule %s failed", rule.rule_id)
                executions.append(
                    RuleExecution(rule.rule_id, rule.name, True, 0, duration, error=message)
                )
                rule_errors.append({"rule_id": rule.rule_id, "error": message})
                continue

            duration = int((time.perf_counter() - rule_started) * 1000)
            findings.extend(rule_findings)
            executions.append(
                RuleExecution(rule.rule_id, rule.name, True, len(rule_findings), duration)
            )

        findings.sort(
            key=lambda f: (-f.severity.rank, -f.estimated_financial_exposure, f.rule_id)
        )
        summary = self._build_summary(frame, findings, executions)
        supplier_risk = self._build_supplier_risk(frame, findings)
        total_duration = int((time.perf_counter() - started) * 1000)

        logger.info(
            "Risk engine finished: %d findings from %d rules in %d ms",
            len(findings),
            sum(1 for e in executions if e.enabled),
            total_duration,
        )
        return EngineResult(
            findings=findings,
            summary=summary,
            supplier_risk=supplier_risk,
            executions=executions,
            config_version=self.config.config_version,
            duration_ms=total_duration,
            rule_errors=rule_errors,
        )

    # ------------------------------------------------------------------
    # Aggregations (all deterministic)
    # ------------------------------------------------------------------
    def _build_summary(
        self,
        frame: pd.DataFrame,
        findings: list[RuleFinding],
        executions: list[RuleExecution],
    ) -> dict[str, Any]:
        """Compute the KPI block shown on the dashboard."""
        severity_counts = {severity.value: 0 for severity in Severity}
        for finding in findings:
            severity_counts[finding.severity.value] += 1

        category_counts: dict[str, int] = {}
        rule_counts: dict[str, dict[str, Any]] = {}
        for finding in findings:
            category_counts[finding.risk_category] = category_counts.get(finding.risk_category, 0) + 1
            entry = rule_counts.setdefault(
                finding.rule_id,
                {"rule_id": finding.rule_id, "rule_name": finding.rule_name,
                 "category": finding.risk_category, "count": 0, "exposure": 0.0},
            )
            entry["count"] += 1
            entry["exposure"] += finding.estimated_financial_exposure

        values = pd.to_numeric(frame.get("total_value_base"), errors="coerce").fillna(0.0)
        total_value = float(values.sum())

        flagged_keys = {
            (f.po_number, f.po_item) for f in findings if f.po_number is not None
        }
        flagged_po_numbers = {f.po_number for f in findings if f.po_number is not None}
        flagged_value = float(
            values[frame["po_number"].isin(flagged_po_numbers)].sum()
        ) if "po_number" in frame.columns else 0.0

        weighted_points = sum(SEVERITY_WEIGHTS[f.severity] for f in findings)
        record_count = max(len(frame), 1)
        # Documented formula: 10 severity points per line item = score 100.
        risk_score = min(100.0, round(weighted_points / record_count * 10.0, 1))

        return {
            "record_count": int(len(frame)),
            "purchase_order_count": int(frame["po_number"].nunique()) if "po_number" in frame else 0,
            "supplier_count": int(frame["supplier_id"].nunique()) if "supplier_id" in frame else 0,
            "total_value_base": round(total_value, 2),
            "base_currency": self.config.base_currency,
            "findings_count": len(findings),
            "severity_counts": severity_counts,
            "category_counts": dict(sorted(category_counts.items())),
            "rule_counts": sorted(
                (
                    {**entry, "exposure": round(entry["exposure"], 2)}
                    for entry in rule_counts.values()
                ),
                key=lambda entry: -entry["count"],
            ),
            "flagged_line_items": len(flagged_keys),
            "flagged_purchase_orders": len(flagged_po_numbers),
            "flagged_value_base": round(flagged_value, 2),
            "flagged_value_share_pct": round(flagged_value / total_value * 100.0, 2)
            if total_value
            else 0.0,
            "estimated_exposure_base": round(
                sum(f.estimated_financial_exposure for f in findings), 2
            ),
            "exposure_note": (
                "Sum of per-finding exposure estimates. A line item can be flagged by several "
                "rules, so this figure is an upper bound, not a netted loss estimate."
            ),
            "risk_score": risk_score,
            "risk_score_method": (
                "weighted severity points (low=1, medium=3, high=8, critical=20) divided by the "
                "number of line items, multiplied by 10, capped at 100"
            ),
            "rules_executed": sum(1 for e in executions if e.enabled),
            "rules_disabled": sum(1 for e in executions if not e.enabled),
            "engine_version": ENGINE_VERSION,
            "config_version": self.config.config_version,
        }

    def _build_supplier_risk(
        self, frame: pd.DataFrame, findings: list[RuleFinding]
    ) -> list[dict[str, Any]]:
        """Per-supplier roll-up used by the supplier risk table."""
        if "supplier_id" not in frame.columns or frame["supplier_id"].isna().all():
            return []

        values = pd.to_numeric(frame["total_value_base"], errors="coerce").fillna(0.0)
        spend_by_supplier = values.groupby(frame["supplier_id"]).sum()
        lines_by_supplier = frame.groupby("supplier_id")["po_number"].count()
        total_spend = float(values.sum()) or 1.0

        rows: dict[str, dict[str, Any]] = {}
        for supplier_id, spend in spend_by_supplier.items():
            key = str(supplier_id)
            names = frame.loc[frame["supplier_id"] == supplier_id, "supplier_name"].dropna()
            rows[key] = {
                "supplier_id": key,
                "supplier_name": str(names.iloc[0]) if len(names) else None,
                "spend_base": round(float(spend), 2),
                "spend_share_pct": round(float(spend) / total_spend * 100.0, 2),
                "line_items": int(lines_by_supplier.get(supplier_id, 0)),
                "findings_count": 0,
                "critical_count": 0,
                "high_count": 0,
                "medium_count": 0,
                "low_count": 0,
                "estimated_exposure_base": 0.0,
                "top_risk_category": None,
            }

        categories: dict[str, dict[str, int]] = {}
        for finding in findings:
            if finding.supplier_id is None:
                continue
            row = rows.get(str(finding.supplier_id))
            if row is None:
                continue
            row["findings_count"] += 1
            row[f"{finding.severity.value}_count"] += 1
            row["estimated_exposure_base"] += finding.estimated_financial_exposure
            bucket = categories.setdefault(str(finding.supplier_id), {})
            bucket[finding.risk_category] = bucket.get(finding.risk_category, 0) + 1

        for supplier_id, row in rows.items():
            row["estimated_exposure_base"] = round(row["estimated_exposure_base"], 2)
            bucket = categories.get(supplier_id)
            if bucket:
                row["top_risk_category"] = max(bucket, key=lambda key: bucket[key])
            row["risk_points"] = (
                row["critical_count"] * SEVERITY_WEIGHTS[Severity.CRITICAL]
                + row["high_count"] * SEVERITY_WEIGHTS[Severity.HIGH]
                + row["medium_count"] * SEVERITY_WEIGHTS[Severity.MEDIUM]
                + row["low_count"] * SEVERITY_WEIGHTS[Severity.LOW]
            )

        return sorted(
            rows.values(),
            key=lambda row: (-row["risk_points"], -row["spend_base"]),
        )
