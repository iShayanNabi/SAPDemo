"""Turn an uploaded inventory history into typed records and forecastable series.

Two steps, deliberately separate:

``normalize_inventory_dataframe``
    Row-level. Uses the shared tabular pipeline (``build_canonical_frame`` ->
    ``coerce_types`` -> ``check_required_completeness``) so a bad cell becomes a
    reported data-quality issue rather than an exception, then adds the checks
    that only make sense for stock movements: a period whose balance does not
    add up, a negative quantity, demand that exceeds what was actually issued,
    an inbound delivery whose expected date has already passed.

``build_series``
    Series-level. Groups the rows by material / plant / storage location, infers
    the period granularity, lays every series out on a complete period grid and
    records which periods had no row at all.

The split matters because the two produce different kinds of warning. A row
problem is about the file; a series problem is about whether the series can be
forecast at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pandas as pd

from app.core.exceptions import ValidationError
from app.core.logging import get_logger
from app.modules.inventory.field_definitions import CANONICAL_FIELDS, REGISTRY
from app.modules.inventory.periods import PeriodGrid, infer_frequency
from app.modules.inventory.thresholds import InventoryConfig
from app.services.tabular.parsing import (
    DataQualityIssue,
    build_canonical_frame,
    check_required_completeness,
    coerce_types,
)

logger = get_logger(__name__)

__all__ = [
    "InventoryDataset",
    "InventorySeries",
    "NormalizedInventoryRecord",
    "OpenPurchaseOrder",
    "SeriesPeriod",
    "build_series",
    "normalize_inventory_dataframe",
    "series_key_of",
]

#: Separator used to build the readable series key. Chosen because SAP material
#: numbers, plants and storage locations never contain it.
SERIES_KEY_SEPARATOR = "|"


def _cell(value: Any) -> Any:
    """Return ``None`` for any pandas/NumPy null, otherwise the value."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _float(value: Any) -> float | None:
    value = _cell(value)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    value = _cell(value)
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _str(value: Any) -> str | None:
    value = _cell(value)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_date(value: Any) -> date | None:
    value = _cell(value)
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return pd.Timestamp(value).date()
    except (TypeError, ValueError):
        return None


def series_key_of(material: str, plant: str, storage_location: str | None) -> str:
    """Readable identifier of one forecastable series."""
    return SERIES_KEY_SEPARATOR.join([material, plant, storage_location or ""])


@dataclass
class NormalizedInventoryRecord:
    """One row of the uploaded history, typed."""

    row_number: int
    material: str
    plant: str
    period_date: date
    storage_location: str | None = None
    material_description: str | None = None
    starting_inventory: float | None = None
    ending_inventory: float | None = None
    demand: float | None = None
    receipts: float | None = None
    issues: float | None = None
    lead_time_days: int | None = None
    reorder_point: float | None = None
    safety_stock: float | None = None
    supplier_id: str | None = None
    supplier_name: str | None = None
    open_po_quantity: float | None = None
    po_expected_date: date | None = None

    @property
    def series_key(self) -> str:
        return series_key_of(self.material, self.plant, self.storage_location)

    def to_record(self) -> dict[str, Any]:
        """A JSON/DB-safe dict of every canonical field."""
        record: dict[str, Any] = {"row_number": self.row_number}
        for name in CANONICAL_FIELDS:
            value = getattr(self, name, None)
            record[name] = value.isoformat() if isinstance(value, date) else value
        return record


@dataclass
class SeriesPeriod:
    """One period of one series, after the grid has been filled."""

    index: int
    period_date: date
    demand: float
    observed: bool = True
    starting_inventory: float | None = None
    ending_inventory: float | None = None
    receipts: float | None = None
    issues: float | None = None
    row_numbers: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "period_date": self.period_date.isoformat(),
            "demand": self.demand,
            "observed": self.observed,
            "starting_inventory": self.starting_inventory,
            "ending_inventory": self.ending_inventory,
            "receipts": self.receipts,
            "issues": self.issues,
        }


@dataclass
class OpenPurchaseOrder:
    """A quantity already on order, and when it is expected."""

    quantity: float
    expected_date: date | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "quantity": self.quantity,
            "expected_date": self.expected_date.isoformat() if self.expected_date else None,
        }


@dataclass
class InventorySeries:
    """One material / plant / storage location laid out on a complete period grid."""

    series_key: str
    material: str
    plant: str
    storage_location: str | None
    material_description: str | None
    supplier_id: str | None
    supplier_name: str | None
    frequency: str
    median_gap_days: float
    frequency_inferred: bool
    grid: PeriodGrid
    periods: list[SeriesPeriod] = field(default_factory=list)
    lead_time_days: int | None = None
    reorder_point: float | None = None
    safety_stock: float | None = None
    open_purchase_orders: list[OpenPurchaseOrder] = field(default_factory=list)
    unscheduled_open_quantity: float = 0.0
    duplicate_period_count: int = 0
    row_count: int = 0

    # -- derived views the engine and the models work from ---------------
    @property
    def demand_values(self) -> list[float]:
        return [period.demand for period in self.periods]

    @property
    def observation_count(self) -> int:
        return len(self.periods)

    @property
    def observed_period_count(self) -> int:
        return sum(1 for period in self.periods if period.observed)

    @property
    def missing_period_indexes(self) -> list[int]:
        return [period.index for period in self.periods if not period.observed]

    @property
    def missing_period_dates(self) -> list[date]:
        return [period.period_date for period in self.periods if not period.observed]

    @property
    def missing_period_pct(self) -> float:
        if not self.periods:
            return 0.0
        return round(len(self.missing_period_indexes) / len(self.periods) * 100.0, 4)

    @property
    def first_period_date(self) -> date | None:
        return self.periods[0].period_date if self.periods else None

    @property
    def last_period_date(self) -> date | None:
        return self.periods[-1].period_date if self.periods else None

    @property
    def last_observed_period(self) -> SeriesPeriod | None:
        """The most recent period that actually came from a row."""
        for period in reversed(self.periods):
            if period.observed:
                return period
        return None

    @property
    def closing_inventory(self) -> float | None:
        """Stock on hand at the end of the history - the projection's starting point."""
        for period in reversed(self.periods):
            if period.ending_inventory is not None:
                return period.ending_inventory
        return None

    @property
    def closing_inventory_date(self) -> date | None:
        """End date of the period the closing inventory belongs to."""
        for period in reversed(self.periods):
            if period.ending_inventory is not None:
                return self.grid.end_date_at(period.index)
        return None

    @property
    def open_po_quantity_total(self) -> float:
        """Scheduled open quantity only - what the projection can actually place."""
        return float(sum(order.quantity for order in self.open_purchase_orders))

    @property
    def label(self) -> str:
        location = f" / {self.storage_location}" if self.storage_location else ""
        return f"{self.material} @ {self.plant}{location}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "series_key": self.series_key,
            "material": self.material,
            "material_description": self.material_description,
            "plant": self.plant,
            "storage_location": self.storage_location,
            "supplier_id": self.supplier_id,
            "supplier_name": self.supplier_name,
            "frequency": self.frequency,
            "median_gap_days": self.median_gap_days,
            "frequency_inferred": self.frequency_inferred,
            "observation_count": self.observation_count,
            "observed_period_count": self.observed_period_count,
            "missing_period_count": len(self.missing_period_indexes),
            "missing_period_dates": [item.isoformat() for item in self.missing_period_dates],
            "first_period_date": self.first_period_date.isoformat()
            if self.first_period_date
            else None,
            "last_period_date": self.last_period_date.isoformat()
            if self.last_period_date
            else None,
            "lead_time_days": self.lead_time_days,
            "reorder_point": self.reorder_point,
            "safety_stock": self.safety_stock,
            "closing_inventory": self.closing_inventory,
            "open_purchase_orders": [order.to_dict() for order in self.open_purchase_orders],
            "unscheduled_open_quantity": self.unscheduled_open_quantity,
            "duplicate_period_count": self.duplicate_period_count,
            "row_count": self.row_count,
            "history": [period.to_dict() for period in self.periods],
        }


@dataclass
class InventoryDataset:
    """The normalised history plus what went wrong loading it."""

    records: list[NormalizedInventoryRecord] = field(default_factory=list)
    issues: list[DataQualityIssue] = field(default_factory=list)
    applied_mapping: dict[str, str] = field(default_factory=dict)
    unmapped_columns: list[str] = field(default_factory=list)
    present_fields: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)

    @property
    def record_count(self) -> int:
        return len(self.records)

    @property
    def series_count(self) -> int:
        return len({record.series_key for record in self.records})

    def issues_as_dicts(self) -> list[dict[str, Any]]:
        return [issue.to_dict() for issue in self.issues]


# ---------------------------------------------------------------------------
# Row level
# ---------------------------------------------------------------------------


def normalize_inventory_dataframe(
    raw: pd.DataFrame,
    mapping: dict[str, str],
    config: InventoryConfig,
) -> InventoryDataset:
    """Normalise a raw inventory history frame into typed records."""
    if raw.empty:
        raise ValidationError("The inventory file contains no rows to load.")

    mapped_fields = set(mapping.values())
    missing_required = [name for name in REGISTRY.required if name not in mapped_fields]
    if missing_required:
        raise ValidationError(
            "The inventory file is missing required fields.",
            details={
                "missing_required_fields": missing_required,
                "labels": [REGISTRY.label(name) for name in missing_required],
            },
        )

    frame = build_canonical_frame(raw, mapping, REGISTRY)
    issues: list[DataQualityIssue] = []
    frame = coerce_types(frame, REGISTRY, issues)
    check_required_completeness(frame, REGISTRY, issues)

    records: list[NormalizedInventoryRecord] = []
    for row in frame.to_dict(orient="records"):
        material = _str(row.get("material"))
        plant = _str(row.get("plant"))
        period_date = _as_date(row.get("period_date"))
        if not material or not plant or period_date is None:
            # A row without a series key or a date cannot be placed on a time
            # axis. The completeness check above has already reported it.
            continue

        records.append(
            NormalizedInventoryRecord(
                row_number=_int(row.get("row_number")) or 0,
                material=material,
                plant=plant,
                storage_location=_str(row.get("storage_location")),
                period_date=period_date,
                material_description=_str(row.get("material_description")),
                starting_inventory=_float(row.get("starting_inventory")),
                ending_inventory=_float(row.get("ending_inventory")),
                demand=_float(row.get("demand")),
                receipts=_float(row.get("receipts")),
                issues=_float(row.get("issues")),
                lead_time_days=_int(row.get("lead_time_days")),
                reorder_point=_float(row.get("reorder_point")),
                safety_stock=_float(row.get("safety_stock")),
                supplier_id=_str(row.get("supplier_id")),
                supplier_name=_str(row.get("supplier_name")),
                open_po_quantity=_float(row.get("open_po_quantity")),
                po_expected_date=_as_date(row.get("po_expected_date")),
            )
        )

    if not records:
        raise ValidationError(
            "No row in the inventory file has a material, a plant and a date, so there is "
            "nothing to forecast."
        )

    _add_movement_checks(records, issues, config)

    present_fields = sorted(mapped_fields)
    missing_fields = [name for name in CANONICAL_FIELDS if name not in mapped_fields]

    logger.info(
        "Normalised %d inventory rows into %d series (%d mapped fields, %d data quality issues)",
        len(records),
        len({record.series_key for record in records}),
        len(present_fields),
        len(issues),
    )

    return InventoryDataset(
        records=records,
        issues=issues,
        applied_mapping=dict(mapping),
        unmapped_columns=[column for column in raw.columns if column not in mapping],
        present_fields=present_fields,
        missing_fields=missing_fields,
    )


def _add_movement_checks(
    records: list[NormalizedInventoryRecord],
    issues: list[DataQualityIssue],
    config: InventoryConfig,
) -> None:
    """Add the checks that only make sense for stock movements."""
    settings = config.data_quality

    def report(
        field_name: str, issue_type: str, message: str, rows: list[int], severity: str = "warning"
    ) -> None:
        if rows:
            issues.append(
                DataQualityIssue(
                    field_name=field_name,
                    issue_type=issue_type,
                    message=message.format(count=len(rows)),
                    affected_rows=len(rows),
                    sample_rows=sorted(rows)[:10],
                    severity=severity,
                )
            )

    negative_demand: list[int] = []
    negative_inventory: list[int] = []
    balance_mismatch: list[int] = []
    unfilled_demand: list[int] = []
    latest_period = max(record.period_date for record in records)
    stale_po: list[int] = []
    unscheduled_po: list[int] = []

    tolerance = settings.balance_tolerance
    gap_tolerance = settings.demand_issue_gap_tolerance_pct / 100.0

    for record in records:
        if settings.warn_on_negative_demand and record.demand is not None and record.demand < 0:
            negative_demand.append(record.row_number)

        if settings.warn_on_negative_inventory:
            for value in (record.starting_inventory, record.ending_inventory):
                if value is not None and value < 0:
                    negative_inventory.append(record.row_number)
                    break

        if (
            settings.warn_on_balance_mismatch
            and record.starting_inventory is not None
            and record.ending_inventory is not None
            and record.receipts is not None
            and record.issues is not None
        ):
            expected = record.starting_inventory + record.receipts - record.issues
            if abs(expected - record.ending_inventory) > tolerance:
                balance_mismatch.append(record.row_number)

        if (
            settings.warn_on_demand_issue_gap
            and record.demand is not None
            and record.issues is not None
            and record.demand > 0
        ):
            shortfall = record.demand - record.issues
            if shortfall > 0 and shortfall / record.demand > gap_tolerance:
                unfilled_demand.append(record.row_number)

        if record.open_po_quantity is not None and record.open_po_quantity > 0:
            if record.po_expected_date is None:
                unscheduled_po.append(record.row_number)
            elif settings.warn_on_past_po_expected_date and record.po_expected_date < latest_period:
                stale_po.append(record.row_number)

    report(
        "demand",
        "negative_demand",
        "{count} row(s) report a negative demand quantity. Negative demand is normally a "
        "return posted against consumption and distorts a forecast.",
        negative_demand,
    )
    report(
        "ending_inventory",
        "negative_inventory",
        "{count} row(s) report a negative stock level.",
        negative_inventory,
    )
    report(
        "ending_inventory",
        "balance_mismatch",
        "{count} period(s) do not balance: starting inventory plus receipts minus issues does "
        "not equal ending inventory.",
        balance_mismatch,
    )
    report(
        "issues",
        "unfilled_demand",
        "{count} period(s) issued materially less than was demanded, which usually means "
        "demand went unfilled. The forecast uses the demand column, not the issues column.",
        unfilled_demand,
    )
    report(
        "po_expected_date",
        "past_expected_date",
        "{count} open purchase-order quantity/quantities are expected on a date that has "
        "already passed. Overdue quantities are reported but are not added to the projected "
        "stock, because there is no reliable date to place them on.",
        stale_po,
    )
    report(
        "po_expected_date",
        "missing_expected_date",
        "{count} row(s) carry an open purchase-order quantity with no expected date. The "
        "quantity is reported but cannot be placed on the projection.",
        unscheduled_po,
    )


# ---------------------------------------------------------------------------
# Series level
# ---------------------------------------------------------------------------


def build_series(
    records: list[NormalizedInventoryRecord],
    config: InventoryConfig,
    as_of: date | None = None,
) -> list[InventorySeries]:
    """Group typed records into forecastable series on a complete period grid.

    Args:
        records: Typed rows from :func:`normalize_inventory_dataframe`.
        config: The validated inventory configuration.
        as_of: Reference date used to decide which open purchase-order
            quantities are still in the future. Defaults to the last period date
            of each series, so a historical file is analysed as at the end of its
            own history rather than as at today.
    """
    grouped: dict[str, list[NormalizedInventoryRecord]] = {}
    for record in records:
        grouped.setdefault(record.series_key, []).append(record)

    series: list[InventorySeries] = []
    for key in sorted(grouped):
        rows = sorted(grouped[key], key=lambda item: (item.period_date, item.row_number))
        built = _build_one_series(key, rows, config, as_of)
        if built is not None:
            series.append(built)

    logger.info("Built %d inventory series from %d rows", len(series), len(records))
    return series


def _build_one_series(
    series_key: str,
    rows: list[NormalizedInventoryRecord],
    config: InventoryConfig,
    as_of: date | None,
) -> InventorySeries | None:
    """Lay one material/plant/storage location out on its period grid."""
    if not rows:
        return None

    first = rows[0]
    dates = [row.period_date for row in rows]
    frequency, median_gap = infer_frequency(dates, config)
    grid = PeriodGrid.build(frequency, min(dates), config)

    # Fold the rows into their period buckets. Two rows in the same bucket are a
    # duplicate period: quantities add up, master data takes the later value.
    buckets: dict[int, SeriesPeriod] = {}
    duplicates = 0
    for row in rows:
        index = grid.index_of(row.period_date)
        bucket = buckets.get(index)
        if bucket is None:
            buckets[index] = SeriesPeriod(
                index=index,
                period_date=grid.date_at(index),
                demand=float(row.demand or 0.0),
                observed=True,
                starting_inventory=row.starting_inventory,
                ending_inventory=row.ending_inventory,
                receipts=row.receipts,
                issues=row.issues,
                row_numbers=[row.row_number],
            )
            continue

        duplicates += 1
        bucket.demand += float(row.demand or 0.0)
        bucket.receipts = _add_optional(bucket.receipts, row.receipts)
        bucket.issues = _add_optional(bucket.issues, row.issues)
        if row.ending_inventory is not None:
            bucket.ending_inventory = row.ending_inventory
        if bucket.starting_inventory is None:
            bucket.starting_inventory = row.starting_inventory
        bucket.row_numbers.append(row.row_number)

    # Fill the grid. A period with no row is not a zero: it is recorded as
    # unobserved so it can be reported, and only then given a value.
    lowest, highest = min(buckets), max(buckets)
    periods: list[SeriesPeriod] = []
    for index in range(lowest, highest + 1):
        bucket = buckets.get(index)
        if bucket is not None:
            periods.append(bucket)
            continue
        periods.append(
            SeriesPeriod(
                index=index,
                period_date=grid.date_at(index),
                demand=0.0,
                observed=False,
            )
        )

    if config.period.missing_period_fill == "interpolate":
        _interpolate_missing(periods)

    # Master data: the most recent non-empty value wins, because a material
    # master figure is a current fact and the newest row states it best.
    lead_time = _latest(rows, "lead_time_days")
    reorder_point = _latest(rows, "reorder_point")
    safety_stock = _latest(rows, "safety_stock")

    reference = as_of or grid.end_date_at(highest)
    open_orders, unscheduled = _collect_open_orders(rows, reference)

    return InventorySeries(
        series_key=series_key,
        material=first.material,
        plant=first.plant,
        storage_location=first.storage_location,
        material_description=_latest(rows, "material_description"),
        supplier_id=_latest(rows, "supplier_id"),
        supplier_name=_latest(rows, "supplier_name"),
        frequency=frequency,
        median_gap_days=median_gap,
        frequency_inferred=len(set(dates)) >= 2,
        grid=grid,
        periods=periods,
        lead_time_days=lead_time,
        reorder_point=reorder_point,
        safety_stock=safety_stock,
        open_purchase_orders=open_orders,
        unscheduled_open_quantity=unscheduled,
        duplicate_period_count=duplicates,
        row_count=len(rows),
    )


def _add_optional(current: float | None, addition: float | None) -> float | None:
    """Sum two optional quantities, keeping ``None`` when neither is present."""
    if current is None:
        return addition
    if addition is None:
        return current
    return current + addition


def _latest(records: list[NormalizedInventoryRecord], attribute: str) -> Any:
    """Most recent non-empty value of ``attribute`` across the series' rows."""
    for record in reversed(records):
        value = getattr(record, attribute, None)
        if value is not None and value != "":
            return value
    return None


def _interpolate_missing(periods: list[SeriesPeriod]) -> None:
    """Fill unobserved periods by linear interpolation between their neighbours.

    Only used when the configuration asks for it. The default is ``zero``,
    because in an inventory history a period with no movement row far more often
    means "nothing moved" than "the number was lost".
    """
    observed = [index for index, period in enumerate(periods) if period.observed]
    if len(observed) < 2:
        return
    for position, period in enumerate(periods):
        if period.observed:
            continue
        before = [index for index in observed if index < position]
        after = [index for index in observed if index > position]
        if not before or not after:
            continue
        left, right = before[-1], after[0]
        span = right - left
        weight = (position - left) / span
        period.demand = (
            periods[left].demand * (1 - weight) + periods[right].demand * weight
        )


def _collect_open_orders(
    records: list[NormalizedInventoryRecord], reference: date
) -> tuple[list[OpenPurchaseOrder], float]:
    """Read the open purchase-order position out of the rows.

    An open quantity is a *current* fact, not a historical one, and inventory
    extracts state it in two different ways: once on the latest row, or repeated
    unchanged on every row of the material. Taking one quantity per expected
    date - the largest seen - reads both shapes correctly, where summing would
    multiply a repeated quantity by the length of the history.

    Quantities whose expected date has already passed, and quantities with no
    expected date at all, are returned as the *unscheduled* total: they are
    reported to the user but never placed on the projection, because there is no
    honest date to place them on.
    """
    scheduled: dict[date, float] = {}
    unscheduled = 0.0
    unscheduled_seen: set[tuple[float, str]] = set()

    for record in records:
        quantity = record.open_po_quantity
        if quantity is None or quantity <= 0:
            continue
        expected = record.po_expected_date
        if expected is not None and expected >= reference:
            scheduled[expected] = max(scheduled.get(expected, 0.0), float(quantity))
            continue
        # Deduplicate a repeated overdue/undated quantity the same way.
        marker = (float(quantity), expected.isoformat() if expected else "")
        if marker in unscheduled_seen:
            continue
        unscheduled_seen.add(marker)
        unscheduled += float(quantity)

    orders = [
        OpenPurchaseOrder(quantity=quantity, expected_date=expected)
        for expected, quantity in sorted(scheduled.items())
    ]
    return orders, round(unscheduled, 6)
