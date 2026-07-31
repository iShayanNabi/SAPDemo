"""Generate the fictional inventory history for the Inventory Predictor.

Run with::

    python scripts/generate_inventory_sample_data.py

Outputs (into ``data/sample/``):

* ``sample_inventory_history.csv``        - SAP technical column names
* ``sample_inventory_history.xlsx``       - business labels
* ``sample_inventory_history.json``       - canonical snake_case names
* ``inventory_scenario_manifest.json`` / ``INVENTORY_SCENARIO_MANIFEST.md``
* ``expected_inventory_baseline.json``    - what the current engine produces

**The data is entirely fictional.** Material numbers, descriptions, plants,
storage locations, suppliers, quantities, lead times and stock levels were
invented for this lab. Nothing comes from an SAP system or a real company, and
no external service is contacted by the generator or by the predictor.

Design principle: most materials are ordinary, well-behaved stock items whose
demand is steady and whose stock stays healthy. Fourteen *anchor* materials are
placed deliberately - one per testable behaviour of the predictor - so every
claim in the manifest can be asserted by the test suite.

Thirty monthly periods are generated (January 2024 to June 2026). That is not an
arbitrary number: Holt-Winters needs two complete seasons (24 monthly periods)
before it is offered at all, and the model selector then holds back two folds of
three periods to backtest on. Twenty-four periods would let the seasonal model
exist but leave nothing to test it with, so the dataset carries six more.

The supplier id range (``0000300001``..) is deliberately the same range modules 3
and 5 use, so the lab replenishes from the same fictional suppliers it
recommends and risk-scores.
"""

from __future__ import annotations

import json
import random
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.logging import get_logger  # noqa: E402
from app.modules.inventory.engine import run_forecast  # noqa: E402
from app.modules.inventory.field_definitions import (  # noqa: E402
    CANONICAL_FIELDS,
    REGISTRY,
)
from app.modules.inventory.normalizer import (  # noqa: E402
    build_series,
    normalize_inventory_dataframe,
)
from app.modules.inventory.thresholds import get_inventory_config  # noqa: E402
from app.services.files.readers import read_tabular  # noqa: E402
from app.services.tabular.mapping import suggest_mapping  # noqa: E402

logger = get_logger("generate_inventory_sample_data")

SEED = 20260901

#: Thirty monthly periods: two full seasons for Holt-Winters plus six periods
#: for the backtest to hold back.
FIRST_PERIOD = date(2024, 1, 1)
PERIOD_COUNT = 30

#: Reference date the projection is measured from - the day after the history
#: ends. Every date in the manifest is relative to this.
AS_OF_DATE = date(2026, 7, 1)

#: Horizon the recorded baseline uses.
BASELINE_HORIZON = 6

#: CSV uses SAP technical names, the way an inventory extract arrives.
TECHNICAL_HEADERS: dict[str, str] = {
    "material": "MATNR",
    "material_description": "MAKTX",
    "plant": "WERKS",
    "storage_location": "LGORT",
    "period_date": "BUDAT",
    "starting_inventory": "OPENING_STOCK",
    "ending_inventory": "LABST",
    "demand": "DEMAND",
    "receipts": "GR_QTY",
    "issues": "GI_QTY",
    "lead_time_days": "PLIFZ",
    "reorder_point": "MINBE",
    "safety_stock": "EISBE",
    "supplier_id": "LIFNR",
    "supplier_name": "NAME1",
    "open_po_quantity": "OPEN_PO_QTY",
    "po_expected_date": "EINDT",
}

#: XLSX uses the business labels from the field registry.
BUSINESS_HEADERS: dict[str, str] = {name: REGISTRY.label(name) for name in CANONICAL_FIELDS}


def month_at(offset: int) -> date:
    """Start date of the period ``offset`` months after the first period."""
    total = FIRST_PERIOD.year * 12 + (FIRST_PERIOD.month - 1) + offset
    return date(total // 12, total % 12 + 1, 1)


@dataclass
class MaterialSpec:
    """One fictional material in one plant, and how it is meant to behave."""

    material: str
    description: str
    plant: str
    storage_location: str
    supplier_id: str
    supplier_name: str
    lead_time_days: int
    reorder_point: float | None
    safety_stock: float | None
    pattern: str
    base_demand: float
    trend_per_period: float = 0.0
    seasonal_amplitude: float = 0.0
    seasonal_peak_month: int = 12
    noise: float = 0.05
    zero_probability: float = 0.0
    scenario_id: str | None = None
    #: Stock on hand the history is engineered to end on. ``None`` keeps the
    #: healthy level the replenishment simulation lands on by itself.
    final_stock_override: float | None = None
    open_po_quantity: float | None = None
    open_po_offset_days: int | None = None
    #: Period offsets that are deliberately absent from the file.
    missing_periods: tuple[int, ...] = ()
    #: Only this many periods are written, counted from the end of the history.
    period_limit: int | None = None
    #: Write no ending/starting inventory at all - a demand-only extract.
    omit_inventory: bool = False
    #: Period offsets whose ending inventory is deliberately inconsistent.
    balance_mismatch_periods: tuple[int, ...] = ()
    rows: list[dict[str, Any]] = field(default_factory=list)

    @property
    def series_key(self) -> str:
        return f"{self.material}|{self.plant}|{self.storage_location}"


SUPPLIERS: list[tuple[str, str]] = [
    ("0000300001", "Nordwind Industrieteile GmbH"),
    ("0000300004", "Baltic Precision Components AB"),
    ("0000300007", "Meridian Fasteners Ltd"),
    ("0000300012", "Ravenna Metalworks S.p.A."),
    ("0000300019", "Helvetia Flow Systems AG"),
]


def build_specs() -> list[MaterialSpec]:
    """The fictional material master. Anchors first, ordinary materials after."""
    return [
        # -- INV-S001: seasonal demand --------------------------------------
        MaterialSpec(
            material="100001",
            description="Bearing Assembly 50mm",
            plant="1000",
            storage_location="0001",
            supplier_id=SUPPLIERS[0][0],
            supplier_name=SUPPLIERS[0][1],
            lead_time_days=21,
            reorder_point=520.0,
            safety_stock=180.0,
            pattern="seasonal",
            base_demand=420.0,
            seasonal_amplitude=170.0,
            seasonal_peak_month=11,
            noise=0.03,
            scenario_id="INV-S001",
        ),
        # -- INV-S002: upward trend -----------------------------------------
        MaterialSpec(
            material="100002",
            description="Hydraulic Pump HP-200",
            plant="1000",
            storage_location="0001",
            supplier_id=SUPPLIERS[4][0],
            supplier_name=SUPPLIERS[4][1],
            lead_time_days=35,
            reorder_point=300.0,
            safety_stock=90.0,
            pattern="trend",
            base_demand=120.0,
            trend_per_period=9.0,
            noise=0.03,
            scenario_id="INV-S002",
        ),
        # -- INV-S003: stable demand ----------------------------------------
        MaterialSpec(
            material="100003",
            description="Steel Bracket A1",
            plant="1000",
            storage_location="0001",
            supplier_id=SUPPLIERS[2][0],
            supplier_name=SUPPLIERS[2][1],
            lead_time_days=14,
            reorder_point=400.0,
            safety_stock=150.0,
            pattern="stable",
            base_demand=300.0,
            noise=0.04,
            scenario_id="INV-S003",
        ),
        # -- INV-S004: intermittent demand ----------------------------------
        MaterialSpec(
            material="100004",
            description="Gearbox Seal Kit",
            plant="1000",
            storage_location="0002",
            supplier_id=SUPPLIERS[1][0],
            supplier_name=SUPPLIERS[1][1],
            lead_time_days=28,
            reorder_point=40.0,
            safety_stock=20.0,
            pattern="intermittent",
            base_demand=45.0,
            noise=0.45,
            zero_probability=0.72,
            scenario_id="INV-S004",
        ),
        # -- INV-S005: shortage inside the horizon --------------------------
        MaterialSpec(
            material="100005",
            description="Control Valve CV-12",
            plant="1000",
            storage_location="0001",
            supplier_id=SUPPLIERS[3][0],
            supplier_name=SUPPLIERS[3][1],
            lead_time_days=30,
            reorder_point=260.0,
            safety_stock=110.0,
            pattern="stable",
            base_demand=210.0,
            noise=0.05,
            final_stock_override=95.0,
            scenario_id="INV-S005",
        ),
        # -- INV-S006: overstock --------------------------------------------
        MaterialSpec(
            material="100006",
            description="Filter Cartridge FC-9",
            plant="1000",
            storage_location="0001",
            supplier_id=SUPPLIERS[2][0],
            supplier_name=SUPPLIERS[2][1],
            lead_time_days=10,
            reorder_point=150.0,
            safety_stock=60.0,
            pattern="stable",
            base_demand=90.0,
            noise=0.05,
            final_stock_override=4200.0,
            scenario_id="INV-S006",
        ),
        # -- INV-S007: slow moving ------------------------------------------
        MaterialSpec(
            material="100007",
            description="Drive Belt DB-45",
            plant="2000",
            storage_location="0001",
            supplier_id=SUPPLIERS[0][0],
            supplier_name=SUPPLIERS[0][1],
            lead_time_days=21,
            reorder_point=60.0,
            safety_stock=30.0,
            pattern="slow",
            base_demand=18.0,
            noise=0.25,
            zero_probability=0.25,
            final_stock_override=340.0,
            scenario_id="INV-S007",
        ),
        # -- INV-S008: dead stock -------------------------------------------
        MaterialSpec(
            material="100008",
            description="Legacy Relay LR-3",
            plant="2000",
            storage_location="0001",
            supplier_id=SUPPLIERS[1][0],
            supplier_name=SUPPLIERS[1][1],
            lead_time_days=45,
            reorder_point=25.0,
            safety_stock=10.0,
            pattern="dead",
            base_demand=30.0,
            noise=0.2,
            final_stock_override=260.0,
            scenario_id="INV-S008",
        ),
        # -- INV-S009: missing periods --------------------------------------
        MaterialSpec(
            material="100009",
            description="Coolant Pump CP-7",
            plant="2000",
            storage_location="0001",
            supplier_id=SUPPLIERS[4][0],
            supplier_name=SUPPLIERS[4][1],
            lead_time_days=28,
            reorder_point=180.0,
            safety_stock=70.0,
            pattern="stable",
            base_demand=140.0,
            noise=0.06,
            missing_periods=(7, 8, 19),
            scenario_id="INV-S009",
        ),
        # -- INV-S010: too little history -----------------------------------
        MaterialSpec(
            material="100010",
            description="Sensor Module SM-4",
            plant="2000",
            storage_location="0001",
            supplier_id=SUPPLIERS[3][0],
            supplier_name=SUPPLIERS[3][1],
            lead_time_days=21,
            reorder_point=80.0,
            safety_stock=40.0,
            pattern="stable",
            base_demand=65.0,
            noise=0.08,
            period_limit=3,
            scenario_id="INV-S010",
        ),
        # -- INV-S011: open purchase order expected too late ----------------
        MaterialSpec(
            material="100011",
            description="Timing Chain TC-8",
            plant="2000",
            storage_location="0002",
            supplier_id=SUPPLIERS[0][0],
            supplier_name=SUPPLIERS[0][1],
            lead_time_days=42,
            reorder_point=340.0,
            safety_stock=120.0,
            pattern="stable",
            base_demand=260.0,
            noise=0.05,
            final_stock_override=150.0,
            open_po_quantity=900.0,
            open_po_offset_days=95,
            scenario_id="INV-S011",
        ),
        # -- INV-S012: demand only, no stock column -------------------------
        MaterialSpec(
            material="100012",
            description="Weld Wire WW-2",
            plant="3000",
            storage_location="0001",
            supplier_id=SUPPLIERS[2][0],
            supplier_name=SUPPLIERS[2][1],
            lead_time_days=14,
            reorder_point=None,
            safety_stock=None,
            pattern="stable",
            base_demand=520.0,
            noise=0.07,
            omit_inventory=True,
            scenario_id="INV-S012",
        ),
        # -- INV-S013: periods that do not balance --------------------------
        MaterialSpec(
            material="100013",
            description="Pressure Switch PS-6",
            plant="3000",
            storage_location="0001",
            supplier_id=SUPPLIERS[4][0],
            supplier_name=SUPPLIERS[4][1],
            lead_time_days=21,
            reorder_point=120.0,
            safety_stock=50.0,
            pattern="stable",
            base_demand=95.0,
            noise=0.05,
            balance_mismatch_periods=(12, 21),
            scenario_id="INV-S013",
        ),
        # -- INV-S014: the same material in a second plant ------------------
        MaterialSpec(
            material="100001",
            description="Bearing Assembly 50mm",
            plant="3000",
            storage_location="0001",
            supplier_id=SUPPLIERS[1][0],
            supplier_name=SUPPLIERS[1][1],
            lead_time_days=17,
            reorder_point=190.0,
            safety_stock=70.0,
            pattern="stable",
            base_demand=140.0,
            noise=0.05,
            scenario_id="INV-S014",
        ),
        # -- ordinary materials ---------------------------------------------
        MaterialSpec(
            material="100014",
            description="Hex Bolt M12x60",
            plant="3000",
            storage_location="0001",
            supplier_id=SUPPLIERS[2][0],
            supplier_name=SUPPLIERS[2][1],
            lead_time_days=12,
            reorder_point=900.0,
            safety_stock=350.0,
            pattern="stable",
            base_demand=780.0,
            noise=0.06,
        ),
        MaterialSpec(
            material="100015",
            description="Cabinet Fan CF-11",
            plant="3000",
            storage_location="0002",
            supplier_id=SUPPLIERS[3][0],
            supplier_name=SUPPLIERS[3][1],
            lead_time_days=24,
            reorder_point=210.0,
            safety_stock=80.0,
            pattern="seasonal",
            base_demand=160.0,
            seasonal_amplitude=55.0,
            seasonal_peak_month=7,
            noise=0.05,
        ),
    ]


class InventorySampleGenerator:
    """Builds the fictional inventory history."""

    def __init__(self, seed: int = SEED) -> None:
        self.random = random.Random(seed)
        self.specs = build_specs()

    # -- demand ----------------------------------------------------------
    def _demand_for(self, spec: MaterialSpec, offset: int) -> float:
        """Demand in one period, from the material's documented pattern."""
        month = month_at(offset).month

        if spec.pattern == "dead":
            # Demand stops entirely part-way through the history and never
            # returns - the point of the dead-stock anchor.
            if offset >= PERIOD_COUNT - 14:
                return 0.0
            level = spec.base_demand
        elif spec.pattern == "intermittent":
            if self.random.random() < spec.zero_probability:
                return 0.0
            level = spec.base_demand
        elif spec.pattern == "slow":
            if self.random.random() < spec.zero_probability:
                return 0.0
            level = spec.base_demand
        else:
            level = spec.base_demand + spec.trend_per_period * offset

        if spec.seasonal_amplitude:
            # A cosine peaking in the configured month: an additive season, the
            # shape the additive Holt-Winters model is built for.
            from math import cos, pi

            phase = 2 * pi * ((month - spec.seasonal_peak_month) % 12) / 12
            level += spec.seasonal_amplitude * cos(phase)

        noise = self.random.gauss(0.0, spec.noise) if spec.noise else 0.0
        return max(0.0, round(level * (1.0 + noise), 0))

    # -- build -----------------------------------------------------------
    def build(self) -> None:
        """Generate every material's rows."""
        for spec in self.specs:
            self._build_one(spec)

    def _build_one(self, spec: MaterialSpec) -> None:
        """Simulate one material's demand, receipts and stock, period by period."""
        demands = [self._demand_for(spec, offset) for offset in range(PERIOD_COUNT)]

        # Start with roughly three periods of cover, then replenish whenever the
        # opening stock is below the reorder point - an ordinary min/max policy.
        reorder_point = spec.reorder_point or (spec.base_demand * 1.5)
        stock = round(max(spec.base_demand * 3.0, reorder_point * 1.4), 0)
        order_quantity = round(max(spec.base_demand * 3.0, reorder_point), 0)

        rows: list[dict[str, Any]] = []
        for offset, demand in enumerate(demands):
            opening = stock
            receipts = 0.0
            if opening < reorder_point:
                receipts = order_quantity
            issues = min(demand, opening + receipts)
            ending = opening + receipts - issues
            rows.append(
                {
                    "offset": offset,
                    "period_date": month_at(offset),
                    "starting_inventory": opening,
                    "receipts": receipts,
                    "issues": issues,
                    "demand": demand,
                    "ending_inventory": ending,
                }
            )
            stock = ending

        # Materials without a scenario of their own are left holding about five
        # periods of cover, which is what an ordinary, well-run item looks like:
        # no shortage in the near term, but still needing a replenishment order
        # inside a six-period horizon.
        if spec.final_stock_override is None and not spec.omit_inventory:
            spec.final_stock_override = round(spec.base_demand * 5.0, 0)

        self._apply_final_stock(spec, rows)
        self._apply_balance_mismatch(spec, rows)

        if spec.period_limit:
            rows = rows[-spec.period_limit :]
        if spec.missing_periods:
            rows = [row for row in rows if row["offset"] not in spec.missing_periods]

        spec.rows = rows

    def _apply_final_stock(self, spec: MaterialSpec, rows: list[dict[str, Any]]) -> None:
        """Land the history on the stock position the scenario needs.

        The receipts of the final period are adjusted rather than the ending
        balance, so ``opening + receipts - issues = ending`` still holds. A
        scenario that broke the balance to reach its target would trip the
        loader's own balance check and stop being a clean anchor.
        """
        if spec.final_stock_override is None or not rows:
            return
        final = rows[-1]
        final["ending_inventory"] = spec.final_stock_override
        final["receipts"] = round(
            spec.final_stock_override - final["starting_inventory"] + final["issues"], 2
        )
        if final["receipts"] < 0:
            # Never write a negative receipt: take the shortfall out of the
            # opening balance of the last period instead, and carry it back.
            deficit = -final["receipts"]
            final["receipts"] = 0.0
            final["starting_inventory"] = round(final["starting_inventory"] - deficit, 2)
            if len(rows) > 1:
                previous = rows[-2]
                previous["ending_inventory"] = final["starting_inventory"]
                previous["receipts"] = round(
                    previous["ending_inventory"]
                    - previous["starting_inventory"]
                    + previous["issues"],
                    2,
                )
                if previous["receipts"] < 0:
                    previous["receipts"] = 0.0
                    previous["starting_inventory"] = round(
                        previous["ending_inventory"] + previous["issues"], 2
                    )

    def _apply_balance_mismatch(self, spec: MaterialSpec, rows: list[dict[str, Any]]) -> None:
        """Break the period balance on purpose, for the data-quality anchor."""
        for row in rows:
            if row["offset"] in spec.balance_mismatch_periods:
                row["ending_inventory"] = round(row["ending_inventory"] + 37.0, 2)

    # -- output ----------------------------------------------------------
    def canonical_frame(self) -> pd.DataFrame:
        """Every row of every material, with canonical field names."""
        records: list[dict[str, Any]] = []
        for spec in self.specs:
            last_offset = spec.rows[-1]["offset"] if spec.rows else 0
            for row in spec.rows:
                record: dict[str, Any] = {
                    "material": spec.material,
                    "material_description": spec.description,
                    "plant": spec.plant,
                    "storage_location": spec.storage_location,
                    "period_date": row["period_date"].isoformat(),
                    "starting_inventory": None if spec.omit_inventory else row["starting_inventory"],
                    "ending_inventory": None if spec.omit_inventory else row["ending_inventory"],
                    "demand": row["demand"],
                    "receipts": row["receipts"],
                    "issues": row["issues"],
                    "lead_time_days": spec.lead_time_days,
                    "reorder_point": spec.reorder_point,
                    "safety_stock": spec.safety_stock,
                    "supplier_id": spec.supplier_id,
                    "supplier_name": spec.supplier_name,
                    "open_po_quantity": None,
                    "po_expected_date": None,
                }
                # The open purchase-order position is a current fact, so it is
                # stated once, on the last row of the material.
                if (
                    spec.open_po_quantity
                    and spec.open_po_offset_days is not None
                    and row["offset"] == last_offset
                ):
                    record["open_po_quantity"] = spec.open_po_quantity
                    record["po_expected_date"] = (
                        AS_OF_DATE + timedelta(days=spec.open_po_offset_days)
                    ).isoformat()
                records.append(record)

        frame = pd.DataFrame(records, columns=list(CANONICAL_FIELDS))
        return frame

    def write(self, output_dir: Path) -> dict[str, Any]:
        """Write the three file formats plus the manifest."""
        output_dir.mkdir(parents=True, exist_ok=True)
        frame = self.canonical_frame()

        csv_frame = frame.rename(columns=TECHNICAL_HEADERS)
        csv_frame.to_csv(output_dir / "sample_inventory_history.csv", index=False)

        xlsx_frame = frame.rename(columns=BUSINESS_HEADERS)
        xlsx_frame.to_excel(
            output_dir / "sample_inventory_history.xlsx", index=False, sheet_name="Inventory"
        )

        (output_dir / "sample_inventory_history.json").write_text(
            json.dumps(
                {"records": frame.where(pd.notna(frame), None).to_dict(orient="records")},
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

        manifest = self.manifest(frame)
        (output_dir / "inventory_scenario_manifest.json").write_text(
            json.dumps(manifest, indent=2, default=str), encoding="utf-8"
        )
        (output_dir / "INVENTORY_SCENARIO_MANIFEST.md").write_text(
            _manifest_markdown(frame, manifest), encoding="utf-8"
        )

        return {
            "rows": len(frame),
            "series": len(self.specs),
            "materials": frame["material"].nunique(),
            "plants": frame["plant"].nunique(),
            "periods": PERIOD_COUNT,
            "scenarios": len(manifest["scenarios"]),
        }

    def manifest(self, frame: pd.DataFrame) -> dict[str, Any]:
        """The documented anchors, in the shape the tests read."""
        return {
            "generated_with_seed": SEED,
            "as_of_date": AS_OF_DATE.isoformat(),
            "baseline_horizon_periods": BASELINE_HORIZON,
            "history_start": FIRST_PERIOD.isoformat(),
            "history_end": month_at(PERIOD_COUNT - 1).isoformat(),
            "period_count": PERIOD_COUNT,
            "frequency": "monthly",
            "row_count": int(len(frame)),
            "series_count": len(self.specs),
            "material_count": int(frame["material"].nunique()),
            "plant_count": int(frame["plant"].nunique()),
            "data_origin": "demo_data",
            "scenarios": SCENARIOS,
        }


#: What every anchor is for, and what the engine must do with it. The test suite
#: reads this file and asserts each expectation against a real forecast run.
SCENARIOS: list[dict[str, Any]] = [
    {
        "scenario_id": "INV-S001",
        "name": "Seasonal demand",
        "material": "100001",
        "plant": "1000",
        "description": (
            "Demand follows a repeating annual shape peaking in November, on a steady level, "
            "with 3% noise. Thirty monthly periods give two complete seasons plus the periods "
            "the backtest holds back."
        ),
        "expects": (
            "Holt-Winters is eligible and wins the backtest, so 'holt_winters_seasonal' is the "
            "selected model and the forecast reproduces the seasonal shape."
        ),
        "assert": {"model": "holt_winters_seasonal", "status": "forecast"},
    },
    {
        "scenario_id": "INV-S002",
        "name": "Upward trend",
        "material": "100002",
        "plant": "1000",
        "description": (
            "Demand rises by about 9 units every period from a base of 120, with no seasonal "
            "component."
        ),
        "expects": (
            "A trend-aware model is selected - Holt - and the forecast keeps rising rather than "
            "flattening at the last level."
        ),
        "assert": {"model": "holt_linear_trend", "status": "forecast", "forecast_rising": True},
    },
    {
        "scenario_id": "INV-S003",
        "name": "Stable demand",
        "material": "100003",
        "plant": "1000",
        "description": "Demand sits at about 300 units with 4% noise, no trend and no season.",
        "expects": (
            "A level-only method is selected - a moving average or simple exponential smoothing "
            "- never a trend or seasonal model."
        ),
        "assert": {
            "model_in": [
                "simple_moving_average",
                "weighted_moving_average",
                "simple_exponential_smoothing",
            ],
            "status": "forecast",
        },
    },
    {
        "scenario_id": "INV-S004",
        "name": "Intermittent demand",
        "material": "100004",
        "plant": "1000",
        "description": (
            "Demand occurs in roughly one period in four and is variable when it does occur."
        ),
        "expects": (
            "The demand profile is classified as intermittent or lumpy, the trend and seasonal "
            "models are ruled ineligible with a stated reason, and MAPE is unavailable because "
            "the comparison window contains zero-demand periods."
        ),
        "assert": {
            "is_intermittent": True,
            "model_in": [
                "simple_moving_average",
                "weighted_moving_average",
                "simple_exponential_smoothing",
            ],
            "seasonal_model_ineligible": True,
        },
    },
    {
        "scenario_id": "INV-S005",
        "name": "Shortage inside the horizon",
        "material": "100005",
        "plant": "1000",
        "description": (
            "Steady demand of about 210 a month against a closing stock of 95 units and no open "
            "purchase order."
        ),
        "expects": (
            "A shortage date is predicted inside the horizon, an order is flagged as needed "
            "immediately, and a reorder quantity is recommended."
        ),
        "assert": {
            "has_shortage": True,
            "shortage_within_horizon": True,
            "order_urgency": "immediate",
        },
    },
    {
        "scenario_id": "INV-S006",
        "name": "Overstock",
        "material": "100006",
        "plant": "1000",
        "description": (
            "Steady demand of about 90 a month against a closing stock of 4,200 units - well "
            "over three years of cover."
        ),
        "expects": (
            "Days of cover exceed the critical overstock threshold, the overstock risk is high, "
            "an excess quantity is quantified and no shortage is predicted."
        ),
        "assert": {"overstock_risk": "high", "has_shortage": False, "has_excess_quantity": True},
    },
    {
        "scenario_id": "INV-S007",
        "name": "Slow-moving stock",
        "material": "100007",
        "plant": "2000",
        "description": (
            "Demand of about 18 units occurs in three periods out of four, against a stock "
            "level that turns over well under twice a year."
        ),
        "expects": "The material is classified as slow-moving.",
        "assert": {"is_slow_moving": True},
    },
    {
        "scenario_id": "INV-S008",
        "name": "Dead stock",
        "material": "100008",
        "plant": "2000",
        "description": (
            "Demand stops completely fourteen periods before the end of the history, while 260 "
            "units remain on hand."
        ),
        "expects": (
            "The material is flagged as dead stock, with at least twelve consecutive "
            "zero-demand periods and stock still on hand."
        ),
        "assert": {"is_dead_stock": True, "min_trailing_zero_periods": 12},
    },
    {
        "scenario_id": "INV-S009",
        "name": "Missing periods",
        "material": "100009",
        "plant": "2000",
        "description": (
            "Three periods (August and September 2024, August 2025) have no row in the file at "
            "all."
        ),
        "expects": (
            "The gaps are detected, reported as a 'missing_periods' warning, and filled so the "
            "periods either side keep their real positions on the time axis - the history is "
            "still thirty periods long."
        ),
        "assert": {"missing_period_count": 3, "warning_code": "missing_periods"},
    },
    {
        "scenario_id": "INV-S010",
        "name": "Too little history",
        "material": "100010",
        "plant": "2000",
        "description": "Only the last three periods of history are present.",
        "expects": (
            "The material is returned with status 'insufficient_data' and an explanatory "
            "warning rather than being dropped or forecast from three points."
        ),
        "assert": {"status": "insufficient_data", "warning_code": "insufficient_history"},
    },
    {
        "scenario_id": "INV-S011",
        "name": "Open purchase order expected too late",
        "material": "100011",
        "plant": "2000",
        "description": (
            "Closing stock of 150 units against demand of about 260 a month, with 900 units on "
            "order but not expected for 95 days."
        ),
        "expects": (
            "A shortage is predicted before the delivery arrives, and the recommendation is to "
            "expedite the existing order rather than to raise another one."
        ),
        "assert": {"has_shortage": True, "expedite_recommended": True},
    },
    {
        "scenario_id": "INV-S012",
        "name": "Demand only, no stock column",
        "material": "100012",
        "plant": "3000",
        "description": "The extract carries demand and movements but no inventory balances.",
        "expects": (
            "The demand forecast and its accuracy are still produced, the projection reports "
            "itself unavailable with a reason, and no shortage date or reorder quantity is "
            "invented."
        ),
        "assert": {
            "status": "forecast",
            "projection_available": False,
            "warning_code": "no_ending_inventory",
        },
    },
    {
        "scenario_id": "INV-S013",
        "name": "Periods that do not balance",
        "material": "100013",
        "plant": "3000",
        "description": (
            "Two periods have an ending inventory 37 units above what starting inventory plus "
            "receipts minus issues gives."
        ),
        "expects": (
            "The loader raises a file-level 'balance_mismatch' data-quality issue naming the "
            "affected rows, and still forecasts the material."
        ),
        "assert": {"file_issue_type": "balance_mismatch", "status": "forecast"},
    },
    {
        "scenario_id": "INV-S014",
        "name": "Same material, second plant",
        "material": "100001",
        "plant": "3000",
        "description": (
            "Material 100001 is also stocked in plant 3000, where demand is lower, steadier and "
            "has no seasonal shape."
        ),
        "expects": (
            "The two plants are forecast as separate series with their own models - the seasonal "
            "model wins in plant 1000 and a level-only method wins in plant 3000."
        ),
        "assert": {"separate_series": True, "model_not": "holt_winters_seasonal"},
    },
]


# ---------------------------------------------------------------------------
# baseline
# ---------------------------------------------------------------------------
def load_generated_run(output_dir: Path, horizon: int = BASELINE_HORIZON):
    """Read the written CSV back through the real reader, mapper and normaliser.

    Deliberately *not* the in-memory rows: module 3 learned the hard way that a
    value can survive in memory and change meaning on the CSV round trip, so the
    recorded baseline has to come from the same path the API takes.
    """
    config = get_inventory_config()
    content = (output_dir / "sample_inventory_history.csv").read_bytes()
    read_result = read_tabular(content, ".csv")
    mapping = suggest_mapping(read_result.source_columns, REGISTRY)
    dataset = normalize_inventory_dataframe(read_result.dataframe, mapping.mapping, config)
    series = build_series(dataset.records, config, as_of=AS_OF_DATE)
    result = run_forecast(
        series, config, as_of=AS_OF_DATE, horizon_periods=horizon
    )
    return dataset, series, result


def write_observed_baseline(output_dir: Path, horizon: int = BASELINE_HORIZON) -> dict[str, Any]:
    """Run the engine over the written files and record what it produced."""
    config = get_inventory_config()
    dataset, _series, result = load_generated_run(output_dir, horizon)

    items = sorted(result.items, key=lambda item: (item.material, item.plant))
    baseline = {
        "note": (
            "Observed output of the current inventory engine on the generated data set with the "
            "default configuration, read back from the written CSV through the real reader, "
            "mapper and normaliser. Used by the test suite to detect unintended changes in the "
            "engine or the generator."
        ),
        "seed": SEED,
        "as_of_date": AS_OF_DATE.isoformat(),
        "horizon_periods": horizon,
        "config_version": config.config_version,
        "engine_version": result.engine_version,
        "row_count": dataset.record_count,
        "data_quality_issue_types": sorted({issue.issue_type for issue in dataset.issues}),
        "summary": result.summary_payload(),
        "series": [
            {
                "material": item.material,
                "plant": item.plant,
                "status": item.status,
                "model": item.model,
                "pattern": item.selection.profile.pattern if item.selection else None,
                "total_forecast_demand": item.total_forecast_demand,
                "predicted_shortage_date": (
                    item.predicted_shortage_date.isoformat()
                    if item.predicted_shortage_date
                    else None
                ),
                "recommended_reorder_date": (
                    item.recommended_reorder_date.isoformat()
                    if item.recommended_reorder_date
                    else None
                ),
                "recommended_reorder_quantity": item.recommended_reorder_quantity,
                "recommended_safety_stock": item.recommended_safety_stock,
                "movement_class": item.movement_class,
                "is_slow_moving": item.is_slow_moving,
                "is_dead_stock": item.is_dead_stock,
                "overstock_risk": item.overstock_risk,
                "expedite_recommended": item.projection.reorder.expedite_recommended,
                "missing_period_count": item.missing_period_count,
                "rmse": (
                    item.accuracy_headline().rmse if item.accuracy_headline() else None
                ),
                "smape": (
                    item.accuracy_headline().smape if item.accuracy_headline() else None
                ),
            }
            for item in items
        ],
    }
    (output_dir / "expected_inventory_baseline.json").write_text(
        json.dumps(baseline, indent=2, default=str), encoding="utf-8"
    )
    return baseline


# ---------------------------------------------------------------------------
# manifest
# ---------------------------------------------------------------------------
def _manifest_markdown(frame: pd.DataFrame, manifest: dict[str, Any]) -> str:
    lines = [
        "# Inventory sample data - scenario manifest",
        "",
        "**Origin: demo data.** These records are fictional. They were generated by "
        "`scripts/generate_inventory_sample_data.py` and do not come from any SAP system or "
        "real company. No external service is contacted by the generator or by the Inventory "
        "Predictor.",
        "",
        f"- Rows: {manifest['row_count']:,}",
        f"- Material/plant/storage-location series: {manifest['series_count']}",
        f"- Materials: {manifest['material_count']} across {manifest['plant_count']} plants",
        f"- Periods: {manifest['period_count']} monthly buckets, "
        f"`{manifest['history_start']}` to `{manifest['history_end']}`",
        f"- Reference date (`as_of`): `{manifest['as_of_date']}`",
        f"- Baseline horizon: {manifest['baseline_horizon_periods']} periods",
        f"- Random seed: `{manifest['generated_with_seed']}` (regenerating reproduces the "
        "identical data set)",
        "",
        "## Why thirty periods",
        "",
        "Holt-Winters is not offered until a series has two complete seasons - 24 monthly "
        "periods. The model selector then holds back two folds of three periods to backtest "
        "on. A 24-period dataset would let the seasonal model *exist* while leaving nothing to "
        "test it with, so every series carries six periods more than the minimum.",
        "",
        "## Files",
        "",
        "| File | Contents |",
        "| --- | --- |",
        "| `sample_inventory_history.csv` | One row per material/plant/period, SAP technical "
        "headers |",
        "| `sample_inventory_history.xlsx` | The same rows with business labels |",
        "| `sample_inventory_history.json` | The same rows with canonical field names |",
        "| `expected_inventory_baseline.json` | What the current engine produces from them |",
        "",
        "## Anchor materials",
        "",
        "Most materials are ordinary stock items: steady demand, healthy stock, no drama. The "
        "anchors below are placed deliberately, one per testable behaviour of the predictor.",
        "",
    ]
    for scenario in manifest["scenarios"]:
        lines.extend(
            [
                f"### {scenario['scenario_id']} - {scenario['name']}",
                "",
                f"- Material `{scenario['material']}` in plant `{scenario['plant']}`",
                f"- {scenario['description']}",
                f"- **Expected effect:** {scenario['expects']}",
                "",
            ]
        )

    lines.extend(
        [
            "## Reading the columns",
            "",
            "`MINBE` and `EISBE` are the reorder point and safety stock **currently held in the "
            "material master**. They are not inputs to the forecast: the predictor calculates "
            "its own from the demand variability and the lead time and reports both, so the two "
            "can be compared. `LABST` is the stock on hand at the end of the period and is the "
            "opening position of the projection.",
            "",
            "Empty cells are genuinely empty. The generator never writes the words `None`, "
            "`null`, `NA` or `-` as a value, because the shared file reader treats those as null "
            "placeholders and a scenario written that way would silently disappear on the round "
            "trip through CSV.",
            "",
            "The open purchase-order quantity is stated **once, on the material's last row**, "
            "because it is a current fact rather than a historical one. The loader also handles "
            "the other common extract shape, where the same open quantity is repeated on every "
            "row, by taking one quantity per expected date rather than summing them.",
            "",
            "## How the test suite uses this file",
            "",
            "The module 7 integration tests load these files through the real reader, mapper and "
            "normaliser, run a forecast for `as_of` "
            f"`{manifest['as_of_date']}` over "
            f"{manifest['baseline_horizon_periods']} periods, and assert that each anchor behaves "
            "as documented, that the portfolio figures reproduce "
            "`expected_inventory_baseline.json`, and that repeated runs over the same files are "
            "identical.",
            "",
            "## A note on the figures",
            "",
            "Every forecast, confidence range, projected stock level, shortage date, reorder "
            "date, reorder quantity and safety-stock figure is produced by the deterministic "
            "statistical models in `app/modules/inventory`, not by an AI model. They are "
            "planning estimates, not commitments, and nothing here has been validated in a live "
            "SAP environment.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    """Generate the data set, then record the baseline the engine produces from it."""
    generator = InventorySampleGenerator()
    generator.build()
    stats = generator.write(settings.sample_dir)
    baseline = write_observed_baseline(settings.sample_dir)

    logger.info(
        "Generated %d inventory rows across %d series and %d scenarios",
        stats["rows"],
        stats["series"],
        stats["scenarios"],
    )
    print(json.dumps(stats, indent=2))

    summary = baseline["summary"]
    print(
        f"forecast: {summary['forecast_count']}/{summary['series_count']} forecast | "
        f"shortages {summary['shortage_count']} | reorder now {summary['reorder_now_count']} | "
        f"overstock {summary['overstock_count']} | dead stock {summary['dead_stock_count']} | "
        f"insufficient data {summary['insufficient_data_count']}"
    )
    print("models: " + json.dumps(summary["model_usage"]))
    print("anchors:")
    for entry in baseline["series"]:
        print(
            f"  {entry['material']} @ {entry['plant']}: {entry['status']:17s} "
            f"{str(entry['model']):28s} pattern={str(entry['pattern']):13s} "
            f"shortage={str(entry['predicted_shortage_date']):12s} "
            f"class={entry['movement_class']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
