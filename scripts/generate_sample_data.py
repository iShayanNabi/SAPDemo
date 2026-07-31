"""Generate the fictional SAP-style demo dataset for the PO Risk Checker.

Run with::

    python scripts/generate_sample_data.py

Outputs (into ``data/sample/``):

* ``sample_purchase_orders.csv``   - SAP technical column names (EBELN, LIFNR, ...)
* ``sample_purchase_orders.xlsx``  - business labels ("Purchase Order Number", ...)
* ``sample_purchase_orders.json``  - canonical snake_case names
* ``anomaly_manifest.csv`` / ``.json`` / ``ANOMALY_MANIFEST.md``

The three file formats deliberately use three different header conventions so
the automatic column mapper can be exercised against all of them.

**The data is entirely fictional.** Supplier names, materials and numbers were
invented for this lab. Nothing here comes from an SAP system or a real company.

Design principle: the "clean" population is generated so that it does *not*
trigger any rule (prices jitter only +/-5%, orders per supplier are spaced at
least 16 days apart, delivery delays stay inside the grace period, and so on).
Every finding the engine reports should therefore trace back to a deliberately
injected anomaly listed in the manifest.
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
from app.modules.po_risk.field_definitions import CANONICAL_FIELDS, FIELD_BY_NAME  # noqa: E402
from app.modules.po_risk.thresholds import get_rule_config  # noqa: E402

logger = get_logger("generate_sample_data")

SEED = 20260101
SUPPLIER_COUNT = 55
MATERIAL_COUNT = 90
PO_PER_SUPPLIER = (8, 12)
ITEMS_PER_PO = (1, 4)
START_DATE = date(2025, 1, 6)
END_DATE = date(2025, 12, 22)

#: Written into the CSV export; demonstrates SAP technical name mapping.
SAP_TECHNICAL_HEADERS = {
    "po_number": "EBELN",
    "po_item": "EBELP",
    "supplier_id": "LIFNR",
    "supplier_name": "NAME1",
    "material": "MATNR",
    "material_description": "TXZ01",
    "material_group": "MATKL",
    "company_code": "BUKRS",
    "purchasing_org": "EKORG",
    "purchasing_group": "EKGRP",
    "plant": "WERKS",
    "quantity": "MENGE",
    "unit_of_measure": "MEINS",
    "unit_price": "NETPR",
    "currency": "WAERS",
    "total_value": "NETWR",
    "order_date": "BEDAT",
    "requested_delivery_date": "EINDT",
    "actual_delivery_date": "BUDAT",
    "contract_number": "KONNR",
    "payment_terms": "ZTERM",
    "approval_status": "FRGKE",
    "created_by": "ERNAM",
    "changed_by": "AENAM",
    "change_count": "CHANGE_COUNT",
}

COMPANY_CODES = [
    {"company_code": "1000", "currency": "EUR", "purchasing_org": "1000", "plants": ["1010", "1020"]},
    {"company_code": "2000", "currency": "USD", "purchasing_org": "2000", "plants": ["2010", "2020"]},
    {"company_code": "3000", "currency": "GBP", "purchasing_org": "3000", "plants": ["3010"]},
    {"company_code": "4000", "currency": "CHF", "purchasing_org": "4000", "plants": ["4010"]},
]

PURCHASING_GROUPS = ["P01", "P02", "P03", "P04", "P05", "P06"]
PAYMENT_TERMS = ["NT30", "NT45", "NT60", "Z030", "Z045", "Z060"]
BUYERS = [f"BUYER{index:02d}" for index in range(1, 13)]

MATERIAL_GROUPS = [
    ("MG10", "Electrical components", ("PC", "EA"), (12.0, 480.0)),
    ("MG15", "Mechanical parts", ("PC", "EA"), (8.0, 950.0)),
    ("MG20", "Raw steel and metals", ("KG", "TO"), (1.4, 22.0)),
    ("MG25", "Packaging materials", ("PC", "CAR"), (0.4, 12.0)),
    ("MG30", "Chemicals and lubricants", ("L", "KG"), (3.5, 65.0)),
    ("MG35", "Office and facility supplies", ("PC", "BOX"), (2.0, 90.0)),
    ("MG40", "IT hardware", ("PC", "EA"), (95.0, 2400.0)),
    ("MG45", "Maintenance services", ("H", "EA"), (55.0, 220.0)),
    ("MG50", "Logistics and freight", ("EA", "H"), (75.0, 900.0)),
    ("MG55", "Laboratory equipment", ("PC", "EA"), (140.0, 3200.0)),
    ("MG60", "Safety equipment", ("PC", "BOX"), (9.0, 260.0)),
    ("MG90", "Specialised tooling", ("PC", "EA"), (320.0, 4200.0)),
]

#: MG90 is deliberately single-sourced so PO-R018 has a documented target.
CONCENTRATED_GROUP = "MG90"

SUPPLIER_NAME_PARTS_A = [
    "Nordwind", "Bluepeak", "Vertex", "Ravenna", "Kestrel", "Alpenrose", "Silverline", "Bramble",
    "Cobalt", "Driftwood", "Ember", "Fairmont", "Granite", "Harbourview", "Ironwood", "Juniper",
    "Larkspur", "Meridian", "Northgate", "Orchard", "Pinnacle", "Quarry", "Redstone", "Summit",
    "Thornbury", "Umbra", "Valemont", "Westford", "Yarrow", "Zenith", "Ashford", "Belmont",
    "Cresthill", "Dunmore", "Eastvale", "Foxglove", "Glenmore", "Hollowbrook", "Inverness",
    "Kingsley", "Lakeshore", "Milbrook", "Norwood", "Oakfield", "Pemberton", "Ridgeway",
    "Stonebridge", "Tallowood", "Ullswater", "Vinemount", "Whitfield", "Yardley", "Zephyr",
    "Alderford", "Bexley",
]
SUPPLIER_NAME_PARTS_B = [
    "Industrie GmbH", "Supply Ltd", "Components SA", "Trading BV", "Manufacturing AG",
    "Technologies Oy", "Materials SpA", "Engineering Sp. z o.o.", "Logistics AS", "Systems Inc",
]

MATERIAL_NOUNS = [
    "bearing", "gasket", "relay", "connector", "valve", "bracket", "sensor", "filter", "coupling",
    "actuator", "housing", "spindle", "cartridge", "membrane", "adapter", "clamp", "pulley",
    "seal ring", "terminal block", "control unit",
]
MATERIAL_ADJECTIVES = [
    "stainless", "high-temperature", "industrial", "precision", "heavy-duty", "compact",
    "insulated", "reinforced", "modular", "low-friction",
]


@dataclass
class Supplier:
    """A fictional supplier."""

    supplier_id: str
    name: str
    company_code: str
    currency: str
    purchasing_org: str
    plants: list[str]
    payment_terms: str


@dataclass
class Material:
    """A fictional material with its price band and contracted suppliers."""

    material: str
    description: str
    material_group: str
    unit_of_measure: str
    base_price: float
    supplier_ids: list[str] = field(default_factory=list)
    contracted: bool = True

    def contract_number(self, supplier_id: str) -> str | None:
        """Deterministic contract id for a contracted supplier/material pair."""
        if not self.contracted:
            return None
        suffix = f"{int(self.material.split('-')[1]) % 900 + 100:03d}"
        return f"46{supplier_id[-4:]}{suffix}"


@dataclass
class ManifestEntry:
    """One documented, deliberately injected anomaly."""

    record_identifier: str
    po_number: str
    po_item: str | None
    expected_rule_id: str
    expected_risk: str
    expected_severity: str
    severity_may_escalate: str
    reason: str
    #: What the finding is attached to: a purchase order or a supplier.
    #: Portfolio level rules (PO-R018) report against a supplier, not a document.
    expected_scope: str = "purchase_order"
    supplier_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_identifier": self.record_identifier,
            "po_number": self.po_number,
            "po_item": self.po_item or "",
            "supplier_id": self.supplier_id,
            "expected_rule_id": self.expected_rule_id,
            "expected_risk": self.expected_risk,
            "expected_severity": self.expected_severity,
            "expected_scope": self.expected_scope,
            "severity_may_escalate": self.severity_may_escalate,
            "reason": self.reason,
        }


class SampleDataGenerator:
    """Builds the demo dataset and its anomaly manifest."""

    def __init__(self, seed: int = SEED) -> None:
        self.random = random.Random(seed)
        self.suppliers: list[Supplier] = []
        self.materials: list[Material] = []
        self.rows: list[dict[str, Any]] = []
        self.manifest: list[ManifestEntry] = []
        self._po_sequence = 4500000
        # Rows already used by an injection. Locking them keeps one injected
        # anomaly from silently overwriting another.
        self._locked: set[tuple[str, str]] = set()

    # ------------------------------------------------------------------
    # Master data
    # ------------------------------------------------------------------
    def build_suppliers(self) -> None:
        for index in range(SUPPLIER_COUNT):
            company = COMPANY_CODES[index % len(COMPANY_CODES)]
            supplier_id = f"{100001 + index:010d}"
            name = (
                f"{SUPPLIER_NAME_PARTS_A[index % len(SUPPLIER_NAME_PARTS_A)]} "
                f"{self.random.choice(SUPPLIER_NAME_PARTS_B)}"
            )
            self.suppliers.append(
                Supplier(
                    supplier_id=supplier_id,
                    name=name,
                    company_code=company["company_code"],
                    currency=company["currency"],
                    purchasing_org=company["purchasing_org"],
                    plants=list(company["plants"]),
                    payment_terms=self.random.choice(PAYMENT_TERMS),
                )
            )

    def build_materials(self) -> None:
        supplier_ids = [supplier.supplier_id for supplier in self.suppliers]
        concentrated_supplier = supplier_ids[7]

        for index in range(MATERIAL_COUNT):
            group_code, group_name, units, price_band = MATERIAL_GROUPS[index % len(MATERIAL_GROUPS)]
            material = f"MAT-{100000 + index * 7}"
            description = (
                f"{self.random.choice(MATERIAL_ADJECTIVES).capitalize()} "
                f"{self.random.choice(MATERIAL_NOUNS)} type {index % 40 + 1}"
            )
            base_price = round(self.random.uniform(*price_band), 2)
            # Roughly one material in six is bought free-text (no contract).
            contracted = index % 6 != 0

            if group_code == CONCENTRATED_GROUP:
                suppliers_for_material = [concentrated_supplier]
            else:
                suppliers_for_material = self.random.sample(supplier_ids, self.random.choice([2, 3]))

            self.materials.append(
                Material(
                    material=material,
                    description=f"{description} ({group_name})",
                    material_group=group_code,
                    unit_of_measure=self.random.choice(units),
                    base_price=base_price,
                    supplier_ids=suppliers_for_material,
                    contracted=contracted,
                )
            )

    # ------------------------------------------------------------------
    # Clean population
    # ------------------------------------------------------------------
    def _next_po_number(self) -> str:
        self._po_sequence += 1
        return str(self._po_sequence)

    def _materials_for_supplier(self, supplier_id: str) -> list[Material]:
        return [m for m in self.materials if supplier_id in m.supplier_ids]

    def _supplier_order_dates(self, count: int) -> list[date]:
        """Dates spaced at least 16 days apart, so no accidental split/duplicate clusters."""
        span_days = (END_DATE - START_DATE).days
        average_gap = span_days / max(count, 1)
        dates: list[date] = []
        current = START_DATE + timedelta(days=self.random.randint(0, 20))
        for _ in range(count):
            if current > END_DATE:
                break
            dates.append(current)
            gap = max(16, int(average_gap * self.random.uniform(0.7, 1.3)))
            current = current + timedelta(days=gap)
        return dates

    def build_clean_rows(self) -> None:
        for supplier in self.suppliers:
            supplier_materials = self._materials_for_supplier(supplier.supplier_id)
            if not supplier_materials:
                continue
            po_count = self.random.randint(*PO_PER_SUPPLIER)
            for order_date in self._supplier_order_dates(po_count):
                self._build_purchase_order(supplier, supplier_materials, order_date)

    def _build_purchase_order(
        self, supplier: Supplier, supplier_materials: list[Material], order_date: date
    ) -> None:
        po_number = self._next_po_number()
        plant = self.random.choice(supplier.plants)
        purchasing_group = self.random.choice(PURCHASING_GROUPS)
        buyer = self.random.choice(BUYERS)
        item_count = min(self.random.randint(*ITEMS_PER_PO), len(supplier_materials))
        chosen = self.random.sample(supplier_materials, item_count)

        lead_days = self.random.randint(10, 45)
        requested = order_date + timedelta(days=lead_days)
        # Delivery stays inside the configured 3 day grace period.
        actual = requested + timedelta(days=self.random.randint(-5, 3))

        rows: list[dict[str, Any]] = []
        for position, material in enumerate(chosen, start=1):
            quantity = self._quantity_for(material)
            unit_price = self._price_for(material, supplier.currency)
            rows.append(
                {
                    "po_number": po_number,
                    "po_item": f"{position * 10:05d}",
                    "supplier_id": supplier.supplier_id,
                    "supplier_name": supplier.name,
                    "material": material.material,
                    "material_description": material.description,
                    "material_group": material.material_group,
                    "company_code": supplier.company_code,
                    "purchasing_org": supplier.purchasing_org,
                    "purchasing_group": purchasing_group,
                    "plant": plant,
                    "quantity": quantity,
                    "unit_of_measure": material.unit_of_measure,
                    "unit_price": unit_price,
                    "currency": supplier.currency,
                    "total_value": round(quantity * unit_price, 2),
                    "order_date": order_date,
                    "requested_delivery_date": requested,
                    "actual_delivery_date": actual,
                    "contract_number": material.contract_number(supplier.supplier_id),
                    "payment_terms": supplier.payment_terms,
                    "approval_status": "Approved",
                    "created_by": buyer,
                    "changed_by": buyer,
                    "change_count": self.random.randint(0, 4),
                }
            )

        self._keep_free_text_lines_small(rows)
        self._avoid_threshold_proximity(rows)
        self._set_approval_status(rows)
        self.rows.extend(rows)

    def _price_for(self, material: Material, currency: str, jitter: tuple[float, float] = (0.95, 1.05)) -> float:
        """Nominal price in the document currency.

        The material has one *base currency* price. A supplier invoicing in USD
        quotes the same economic value as a EUR supplier, so the nominal number
        is converted with the configured rate. Without this, a currency mix
        alone would look like a 25%+ price variance to PO-R006.
        """
        rate = get_rule_config().conversion_rate(currency)
        return round(material.base_price / max(rate, 0.0001) * self.random.uniform(*jitter), 2)

    def _quantity_for(self, material: Material) -> float:
        """Quantity band tied to the price so line values stay plausible."""
        if material.base_price > 800:
            return float(self.random.randint(1, 12))
        if material.base_price > 100:
            return float(self.random.randint(5, 60))
        return float(self.random.randint(20, 400))

    def _keep_free_text_lines_small(self, rows: list[dict[str, Any]]) -> None:
        """Free-text (non-contract) lines stay below the PO-R008 review level."""
        config = get_rule_config()
        for row in rows:
            if row["contract_number"] is not None:
                continue
            base_value = row["total_value"] * config.conversion_rate(row["currency"])
            if base_value >= 20000:
                factor = 15000 / base_value
                row["quantity"] = round(max(1.0, row["quantity"] * factor), 2)
                row["total_value"] = round(row["quantity"] * row["unit_price"], 2)

    def _avoid_threshold_proximity(self, rows: list[dict[str, Any]]) -> None:
        """Nudge order totals out of the band just below an approval threshold."""
        thresholds = (10000.0, 50000.0, 250000.0)
        for _ in range(6):
            total = self._po_total_base(rows)
            near = [t for t in thresholds if 0 < (t - total) / t <= 0.07]
            if not near:
                return
            factor = 0.88
            for row in rows:
                row["quantity"] = round(max(1.0, row["quantity"] * factor), 2)
                row["total_value"] = round(row["quantity"] * row["unit_price"], 2)

    def _set_approval_status(self, rows: list[dict[str, Any]]) -> None:
        """Anything at or above the first release threshold is approved in clean data."""
        total = self._po_total_base(rows)
        status = "Approved" if total >= 9000 else self.random.choice(["Approved", "Approved", "Open"])
        for row in rows:
            row["approval_status"] = status

    # ------------------------------------------------------------------
    # Anomaly injection
    # ------------------------------------------------------------------
    def inject_anomalies(self) -> None:
        self._inject_duplicate_purchase_orders()
        self._inject_duplicate_line_items()
        self._inject_split_purchases()
        self._inject_threshold_proximity()
        self._inject_price_increase()
        self._inject_price_variance()
        self._inject_off_contract()
        self._inject_missing_contract_high_value()
        self._inject_unapproved_high_value()
        self._inject_late_deliveries()
        self._inject_requested_before_order()
        self._inject_delivery_before_order()
        self._inject_quantity_anomalies()
        self._inject_currency_anomalies()
        self._inject_missing_fields()
        self._inject_unusual_payment_terms()
        self._inject_excessive_changes()
        self._document_supplier_concentration()
        self._inject_maverick_spend()
        self._document_high_risk_suppliers()
        self._finalize_undocumented_orders()

    def _finalize_undocumented_orders(self) -> None:
        """Clean up side effects of injection on orders that are *not* documented.

        Raising a line value can push an unrelated order into the band just below
        an approval threshold (PO-R004) or above the release limit while it still
        carries an "Open" status (PO-R009). Those would be findings nobody asked
        for, so undocumented orders are nudged back into a clean state. Documented
        orders are never touched - their anomaly is the point.
        """
        documented = {entry.po_number for entry in self.manifest}
        unapproved_by_design = {
            entry.po_number for entry in self.manifest if entry.expected_rule_id == "PO-R009"
        }
        for po_number, rows in self._rows_by_po().items():
            if po_number not in unapproved_by_design and self._po_total_base(rows) >= 9000:
                for row in rows:
                    row["approval_status"] = "Approved"
            if po_number in documented:
                continue
            for _ in range(6):
                total = self._po_total_base(rows)
                if not [t for t in (10000.0, 50000.0, 250000.0) if 0 < (t - total) / t <= 0.07]:
                    break
                for row in rows:
                    row["quantity"] = round(max(1.0, row["quantity"] * 0.88), 2)
                    row["total_value"] = round(row["quantity"] * row["unit_price"], 2)
            if self._po_total_base(rows) >= 9000:
                for row in rows:
                    row["approval_status"] = "Approved"

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def _key(row: dict[str, Any]) -> tuple[str, str]:
        return (row["po_number"], row["po_item"])

    def _lock(self, rows: list[dict[str, Any]] | dict[str, Any]) -> None:
        """Mark rows as used so later injections leave them alone."""
        items = rows if isinstance(rows, list) else [rows]
        for row in items:
            self._locked.add(self._key(row))

    def _free_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Filter out rows that a previous injection already claimed."""
        return [row for row in rows if self._key(row) not in self._locked]

    def _make_order(
        self,
        supplier: Supplier,
        material: Material,
        target_value_base: float,
        order_date: date,
        *,
        line_count: int = 1,
        **overrides: Any,
    ) -> list[dict[str, Any]]:
        """Create a new purchase order worth roughly ``target_value_base``.

        The value is spread over ``line_count`` lines so that no single line
        needs an implausible quantity (which would trip PO-R013 by accident).
        """
        po_number = self._next_po_number()
        rate = get_rule_config().conversion_rate(supplier.currency)
        unit_price = self._price_for(material, supplier.currency, jitter=(1.0, 1.0))
        # Uneven line weights: identical lines would look like a duplicated item.
        weights = [self.random.uniform(0.75, 1.25) for _ in range(line_count)]
        weight_sum = sum(weights)
        rows: list[dict[str, Any]] = []

        for position in range(1, line_count + 1):
            per_line_base = target_value_base * weights[position - 1] / weight_sum
            quantity = round(per_line_base / max(unit_price * rate, 0.01), 2)
            row = {
                "po_number": po_number,
                "po_item": f"{position * 10:05d}",
                "supplier_id": supplier.supplier_id,
                "supplier_name": supplier.name,
                "material": material.material,
                "material_description": material.description,
                "material_group": material.material_group,
                "company_code": supplier.company_code,
                "purchasing_org": supplier.purchasing_org,
                "purchasing_group": self.random.choice(PURCHASING_GROUPS),
                "plant": supplier.plants[0],
                "quantity": quantity,
                "unit_of_measure": material.unit_of_measure,
                "unit_price": unit_price,
                "currency": supplier.currency,
                "total_value": round(quantity * unit_price, 2),
                "order_date": order_date,
                "requested_delivery_date": order_date + timedelta(days=20),
                "actual_delivery_date": order_date + timedelta(days=21),
                "contract_number": material.contract_number(supplier.supplier_id),
                "payment_terms": supplier.payment_terms,
                "approval_status": "Approved",
                "created_by": self.random.choice(BUYERS),
                "changed_by": self.random.choice(BUYERS),
                "change_count": self.random.randint(0, 3),
            }
            row.update(overrides)
            rows.append(row)

        self.rows.extend(rows)
        self._lock(rows)
        return rows

    def _expensive_material_for(self, supplier: Supplier, contracted: bool) -> Material | None:
        """Highest priced material of a supplier, used to keep quantities small."""
        candidates = [
            m for m in self._materials_for_supplier(supplier.supplier_id)
            if m.contracted is contracted
        ]
        return max(candidates, key=lambda m: m.base_price) if candidates else None

    def _rows_by_po(self) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in self.rows:
            grouped.setdefault(row["po_number"], []).append(row)
        return grouped

    def _po_total(self, rows: list[dict[str, Any]]) -> float:
        return sum(row["total_value"] for row in rows)

    @staticmethod
    def _po_total_base(rows: list[dict[str, Any]]) -> float:
        """Order total converted into the base currency.

        The rules compare against base-currency thresholds, so any check that
        keeps the clean population away from a threshold has to convert too.
        """
        config = get_rule_config()
        return sum(row["total_value"] * config.conversion_rate(row["currency"]) for row in rows)

    def _add(self, entry: ManifestEntry) -> None:
        self.manifest.append(entry)

    def _pick_pos(
        self, count: int, predicate, exclude: set[str] | None = None
    ) -> list[list[dict[str, Any]]]:
        """Pick ``count`` purchase orders whose row list satisfies ``predicate``."""
        grouped = self._rows_by_po()
        exclude = exclude or set()
        candidates = [
            rows for po, rows in sorted(grouped.items())
            if po not in exclude
            and not any(self._key(row) in self._locked for row in rows)
            and predicate(rows)
        ]
        self.random.shuffle(candidates)
        return candidates[:count]

    # -- PO-R001 ---------------------------------------------------------
    def _inject_duplicate_purchase_orders(self) -> None:
        targets = self._pick_pos(4, lambda rows: 5000 <= self._po_total(rows) <= 120000)
        for rows in targets:
            new_po = self._next_po_number()
            offset = self.random.randint(2, 9)
            for row in rows:
                clone = dict(row)
                clone["po_number"] = new_po
                clone["order_date"] = row["order_date"] + timedelta(days=offset)
                clone["requested_delivery_date"] = row["requested_delivery_date"] + timedelta(days=offset)
                clone["actual_delivery_date"] = row["actual_delivery_date"] + timedelta(days=offset)
                clone["change_count"] = 0
                self.rows.append(clone)
                self._lock(clone)
            self._add(
                ManifestEntry(
                    record_identifier=new_po,
                    po_number=new_po,
                    po_item=None,
                    expected_rule_id="PO-R001",
                    expected_risk="Duplicate purchase order",
                    expected_severity="high",
                    severity_may_escalate="yes",
                    reason=(
                        f"Exact copy of purchase order {rows[0]['po_number']} on the same supplier, "
                        f"raised {offset} day(s) later with an identical value."
                    ),
                )
            )

    # -- PO-R002 ---------------------------------------------------------
    def _inject_duplicate_line_items(self) -> None:
        targets = self._pick_pos(4, lambda rows: len(rows) >= 2)
        for rows in targets:
            source = rows[0]
            clone = dict(source)
            clone["po_item"] = f"{(len(rows) + 1) * 10:05d}"
            self.rows.append(clone)
            self._lock([clone, source])
            self._add(
                ManifestEntry(
                    record_identifier=f"{clone['po_number']}/{clone['po_item']}",
                    po_number=clone["po_number"],
                    po_item=clone["po_item"],
                    expected_rule_id="PO-R002",
                    expected_risk="Duplicate line item",
                    expected_severity="medium",
                    severity_may_escalate="yes",
                    reason=(
                        f"Item {clone['po_item']} repeats item {source['po_item']}: same material, "
                        "quantity and unit price inside the same purchase order."
                    ),
                )
            )

    # -- PO-R003 ---------------------------------------------------------
    def _inject_split_purchases(self) -> None:
        chosen_suppliers = [self.suppliers[index] for index in (3, 19, 34)]
        for supplier in chosen_suppliers:
            supplier_materials = self._materials_for_supplier(supplier.supplier_id)
            if not supplier_materials:
                continue
            material = supplier_materials[0]
            base_date = date(2025, 6, 2) + timedelta(days=self.random.randint(0, 60))
            po_numbers: list[str] = []
            targets = [8200.0, 9400.0, 8800.0, 9900.0]
            for offset, target_value in zip((0, 2, 4, 5), targets):
                po_number = self._next_po_number()
                po_numbers.append(po_number)
                unit_price = self._price_for(material, supplier.currency, jitter=(1.0, 1.0))
                rate = get_rule_config().conversion_rate(supplier.currency)
                quantity = round(target_value / max(unit_price * rate, 1.0), 2)
                order_date = base_date + timedelta(days=offset)
                self.rows.append(
                    {
                        "po_number": po_number,
                        "po_item": "00010",
                        "supplier_id": supplier.supplier_id,
                        "supplier_name": supplier.name,
                        "material": material.material,
                        "material_description": material.description,
                        "material_group": material.material_group,
                        "company_code": supplier.company_code,
                        "purchasing_org": supplier.purchasing_org,
                        "purchasing_group": "P02",
                        "plant": supplier.plants[0],
                        "quantity": quantity,
                        "unit_of_measure": material.unit_of_measure,
                        "unit_price": unit_price,
                        "currency": supplier.currency,
                        "total_value": round(quantity * unit_price, 2),
                        "order_date": order_date,
                        "requested_delivery_date": order_date + timedelta(days=21),
                        "actual_delivery_date": order_date + timedelta(days=22),
                        "contract_number": material.contract_number(supplier.supplier_id),
                        "payment_terms": supplier.payment_terms,
                        "approval_status": "Approved",
                        "created_by": "BUYER07",
                        "changed_by": "BUYER07",
                        "change_count": 1,
                    }
                )
                self._lock(self.rows[-1])
            self._add(
                ManifestEntry(
                    record_identifier=", ".join(po_numbers),
                    po_number=po_numbers[0],
                    po_item=None,
                    expected_rule_id="PO-R003",
                    expected_risk="Split purchase",
                    expected_severity="high",
                    severity_may_escalate="yes",
                    reason=(
                        "Four orders between 8,200 and 9,900 base currency raised on the same "
                        "supplier within "
                        "5 days; combined value crosses the 25,000 bundling threshold while every "
                        "single order stays below it."
                    ),
                )
            )

    # -- PO-R004 ---------------------------------------------------------
    def _inject_threshold_proximity(self) -> None:
        """Create orders that stop just under a release threshold.

        A fresh order is used rather than an existing one: rescaling a real line
        to reach 250,000 would need an extreme quantity and would then also trip
        the quantity outlier rule.
        """
        plans = [(10000.0, 1), (10000.0, 1), (50000.0, 2), (50000.0, 2), (250000.0, 6)]
        used_suppliers: set[str] = set()

        for index, (threshold, line_count) in enumerate(plans):
            supplier = next(
                (
                    candidate for candidate in self.suppliers[index * 5 :]
                    if candidate.supplier_id not in used_suppliers
                    and self._expensive_material_for(candidate, contracted=True)
                ),
                None,
            )
            if supplier is None:
                continue
            used_suppliers.add(supplier.supplier_id)
            material = self._expensive_material_for(supplier, contracted=True)
            assert material is not None

            target = threshold * self.random.uniform(0.978, 0.995)
            order_date = date(2025, 4, 7) + timedelta(days=index * 11)
            rows = self._make_order(supplier, material, target, order_date, line_count=line_count)
            total = sum(row["total_value"] for row in rows)
            self._add(
                ManifestEntry(
                    record_identifier=rows[0]["po_number"],
                    po_number=rows[0]["po_number"],
                    po_item=None,
                    expected_rule_id="PO-R004",
                    expected_risk="Order value just below an approval threshold",
                    expected_severity="medium",
                    severity_may_escalate="yes",
                    reason=(
                        f"Order built to {total:,.2f} document currency so that its base value "
                        f"lands within 3% below the {threshold:,.0f} release threshold."
                    ),
                )
            )

    # -- PO-R005 ---------------------------------------------------------
    def _inject_price_increase(self) -> None:
        pairs: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in self.rows:
            if row["material"] and row["supplier_id"]:
                pairs.setdefault((row["material"], row["supplier_id"]), []).append(row)
        candidates = [
            rows for rows in pairs.values()
            if len(rows) >= 3 and self._key(rows[-1]) not in self._locked
        ]
        self.random.shuffle(candidates)

        for rows in candidates[:4]:
            rows.sort(key=lambda item: item["order_date"])
            target = rows[-1]
            self._lock(target)
            increase = self.random.uniform(1.35, 1.75)
            target["unit_price"] = round(target["unit_price"] * increase, 2)
            target["total_value"] = round(target["quantity"] * target["unit_price"], 2)
            self._add(
                ManifestEntry(
                    record_identifier=f"{target['po_number']}/{target['po_item']}",
                    po_number=target["po_number"],
                    po_item=target["po_item"],
                    expected_rule_id="PO-R005",
                    expected_risk="Unusual unit price increase",
                    expected_severity="high",
                    severity_may_escalate="yes",
                    reason=(
                        f"Unit price raised by {(increase - 1) * 100:.0f}% versus the previous order "
                        f"of material {target['material']} from the same supplier "
                        "(alert level is 20%). May also trigger PO-R006."
                    ),
                )
            )

    # -- PO-R006 ---------------------------------------------------------
    def _inject_price_variance(self) -> None:
        by_material: dict[str, list[dict[str, Any]]] = {}
        for row in self.rows:
            if row["material"]:
                by_material.setdefault(row["material"], []).append(row)
        candidates = [
            rows for rows in by_material.values()
            if len(rows) >= 6 and self._key(rows[0]) not in self._locked
        ]
        self.random.shuffle(candidates)

        for rows in candidates[:5]:
            target = rows[0]
            self._lock(target)
            factor = self.random.uniform(1.55, 2.1)
            target["unit_price"] = round(target["unit_price"] * factor, 2)
            target["total_value"] = round(target["quantity"] * target["unit_price"], 2)
            self._add(
                ManifestEntry(
                    record_identifier=f"{target['po_number']}/{target['po_item']}",
                    po_number=target["po_number"],
                    po_item=target["po_item"],
                    expected_rule_id="PO-R006",
                    expected_risk="Price variance for the same material",
                    expected_severity="medium",
                    severity_may_escalate="yes",
                    reason=(
                        f"Unit price set to {(factor - 1) * 100:.0f}% above the median paid for "
                        f"material {target['material']} across the dataset (alert level is 25%)."
                    ),
                )
            )

    # -- PO-R007 ---------------------------------------------------------
    def _inject_off_contract(self) -> None:
        candidates = self._free_rows(
            [row for row in self.rows if row["contract_number"] and row["total_value"] >= 3000]
        )
        self.random.shuffle(candidates)
        for row in candidates[:5]:
            self._lock(row)
            row["contract_number"] = None
            self._add(
                ManifestEntry(
                    record_identifier=f"{row['po_number']}/{row['po_item']}",
                    po_number=row["po_number"],
                    po_item=row["po_item"],
                    expected_rule_id="PO-R007",
                    expected_risk="Off-contract purchase",
                    expected_severity="medium",
                    severity_may_escalate="yes",
                    reason=(
                        f"Contract reference removed although the same supplier supplies material "
                        f"{row['material']} under an outline agreement on other lines."
                    ),
                )
            )

    # -- PO-R008 ---------------------------------------------------------
    def _inject_missing_contract_high_value(self) -> None:
        """Create significant free-text orders with no outline agreement."""
        used_suppliers: set[str] = set()
        created = 0

        for supplier in self.suppliers:
            if created >= 5:
                break
            if supplier.supplier_id in used_suppliers:
                continue
            material = self._expensive_material_for(supplier, contracted=False)
            if material is None:
                continue
            used_suppliers.add(supplier.supplier_id)

            target = self.random.uniform(28000, 46000)
            order_date = date(2025, 3, 10) + timedelta(days=created * 13)
            rows = self._make_order(supplier, material, target, order_date, line_count=1)
            self._add(
                ManifestEntry(
                    record_identifier=f"{rows[0]['po_number']}/{rows[0]['po_item']}",
                    po_number=rows[0]["po_number"],
                    po_item=rows[0]["po_item"],
                    expected_rule_id="PO-R008",
                    expected_risk="Missing contract reference on a significant order",
                    expected_severity="low",
                    severity_may_escalate="yes",
                    reason=(
                        f"Free-text purchase of {rows[0]['total_value']:,.2f} for material "
                        f"{material.material}, which no supplier holds under contract, so the "
                        "outline agreement reference stays empty above the 25,000 review level."
                    ),
                )
            )
            created += 1

    # -- PO-R009 ---------------------------------------------------------
    def _inject_unapproved_high_value(self) -> None:
        targets = self._pick_pos(6, lambda rows: self._po_total_base(rows) >= 12000)
        statuses = ["Not Approved", "Pending", "Open", "In Review", "Blocked", "Not Approved"]
        for rows, status in zip(targets, statuses):
            self._lock(rows)
            for row in rows:
                row["approval_status"] = status
            self._add(
                ManifestEntry(
                    record_identifier=rows[0]["po_number"],
                    po_number=rows[0]["po_number"],
                    po_item=None,
                    expected_rule_id="PO-R009",
                    expected_risk="High value order without approval",
                    expected_severity="critical",
                    severity_may_escalate="no",
                    reason=(
                        f"Order worth {self._po_total_base(rows):,.2f} base currency carries the "
                        f"status '{status}', "
                        "which is not a released state."
                    ),
                )
            )

    # -- PO-R010 ---------------------------------------------------------
    def _inject_late_deliveries(self) -> None:
        candidates = self._free_rows([row for row in self.rows if row["actual_delivery_date"]])
        self.random.shuffle(candidates)
        delays = [12, 18, 25, 35, 44, 62, 75, 95]
        for row, delay in zip(candidates[:8], delays):
            self._lock(row)
            row["actual_delivery_date"] = row["requested_delivery_date"] + timedelta(days=delay)
            expected_severity = "critical" if delay >= 60 else "high" if delay >= 30 else "low"
            self._add(
                ManifestEntry(
                    record_identifier=f"{row['po_number']}/{row['po_item']}",
                    po_number=row["po_number"],
                    po_item=row["po_item"],
                    expected_rule_id="PO-R010",
                    expected_risk="Late delivery",
                    expected_severity=expected_severity,
                    severity_may_escalate="no",
                    reason=f"Goods receipt posted {delay} days after the requested delivery date.",
                )
            )

    # -- PO-R011 ---------------------------------------------------------
    def _inject_requested_before_order(self) -> None:
        candidates = self._free_rows([row for row in self.rows if row["order_date"]])
        self.random.shuffle(candidates)
        for row in candidates[:4]:
            self._lock(row)
            row["requested_delivery_date"] = row["order_date"] - timedelta(days=self.random.randint(3, 20))
            self._add(
                ManifestEntry(
                    record_identifier=f"{row['po_number']}/{row['po_item']}",
                    po_number=row["po_number"],
                    po_item=row["po_item"],
                    expected_rule_id="PO-R011",
                    expected_risk="Requested delivery date before order date",
                    expected_severity="medium",
                    severity_may_escalate="yes",
                    reason=(
                        "Requirement date backdated to before the purchase order date. The unchanged "
                        "goods receipt date is then also late, so PO-R010 fires on the same line."
                    ),
                )
            )

    # -- PO-R012 ---------------------------------------------------------
    def _inject_delivery_before_order(self) -> None:
        candidates = self._free_rows([
            row for row in self.rows
            if row["actual_delivery_date"] and row["requested_delivery_date"] >= row["order_date"]
        ])
        self.random.shuffle(candidates)
        for row in candidates[:3]:
            self._lock(row)
            row["actual_delivery_date"] = row["order_date"] - timedelta(days=self.random.randint(2, 12))
            self._add(
                ManifestEntry(
                    record_identifier=f"{row['po_number']}/{row['po_item']}",
                    po_number=row["po_number"],
                    po_item=row["po_item"],
                    expected_rule_id="PO-R012",
                    expected_risk="Actual delivery before order date",
                    expected_severity="high",
                    severity_may_escalate="yes",
                    reason=(
                        "Goods receipt dated before the purchase order date - the classic "
                        "after-the-fact purchase order pattern."
                    ),
                )
            )

    # -- PO-R013 ---------------------------------------------------------
    def _inject_quantity_anomalies(self) -> None:
        candidates = self._free_rows(
            [row for row in self.rows if row["quantity"] and row["quantity"] > 5]
        )
        self.random.shuffle(candidates)

        for row in candidates[:3]:
            self._lock(row)
            row["quantity"] = 0.0
            row["total_value"] = 0.0
            self._add(
                ManifestEntry(
                    record_identifier=f"{row['po_number']}/{row['po_item']}",
                    po_number=row["po_number"],
                    po_item=row["po_item"],
                    expected_rule_id="PO-R013",
                    expected_risk="Quantity anomaly (non-positive quantity)",
                    expected_severity="high",
                    severity_may_escalate="yes",
                    reason="Order quantity set to zero, which cannot be received.",
                )
            )

        by_material: dict[str, list[dict[str, Any]]] = {}
        for row in self.rows:
            if row["material"] and row["quantity"]:
                by_material.setdefault(row["material"], []).append(row)
        outlier_candidates = [
            rows for rows in by_material.values()
            if len(rows) >= 6
            and rows[-1]["contract_number"] is not None
            and self._key(rows[-1]) not in self._locked
        ]
        self.random.shuffle(outlier_candidates)

        for rows in outlier_candidates[:3]:
            target = rows[-1]
            self._lock(target)
            median = sorted(item["quantity"] for item in rows)[len(rows) // 2]
            target["quantity"] = round(median * self.random.uniform(30, 45), 2)
            target["total_value"] = round(target["quantity"] * target["unit_price"], 2)
            self._add(
                ManifestEntry(
                    record_identifier=f"{target['po_number']}/{target['po_item']}",
                    po_number=target["po_number"],
                    po_item=target["po_item"],
                    expected_rule_id="PO-R013",
                    expected_risk="Quantity anomaly (outlier versus material median)",
                    expected_severity="medium",
                    severity_may_escalate="yes",
                    reason=(
                        f"Quantity set to about 30-45x the median ordered quantity for material "
                        f"{target['material']} (alert level is 20x)."
                    ),
                )
            )

    # -- PO-R014 ---------------------------------------------------------
    def _inject_currency_anomalies(self) -> None:
        wrong_currency = {"EUR": "USD", "USD": "EUR", "GBP": "USD", "CHF": "EUR"}
        candidates = self._free_rows(
            [row for row in self.rows if row["currency"] and row["company_code"]]
        )
        self.random.shuffle(candidates)
        for row in candidates[:4]:
            self._lock(row)
            original = row["currency"]
            row["currency"] = wrong_currency[original]
            self._add(
                ManifestEntry(
                    record_identifier=f"{row['po_number']}/{row['po_item']}",
                    po_number=row["po_number"],
                    po_item=row["po_item"],
                    expected_rule_id="PO-R014",
                    expected_risk="Currency anomaly",
                    expected_severity="medium",
                    severity_may_escalate="yes",
                    reason=(
                        f"Document currency changed from {original} to {row['currency']} while "
                        f"company code {row['company_code']} is configured for {original}."
                    ),
                )
            )

    # -- PO-R015 ---------------------------------------------------------
    def _inject_missing_fields(self) -> None:
        candidates = self._free_rows([row for row in self.rows if row["material_group"]])
        self.random.shuffle(candidates)
        plans = [
            ("material_group", "Material group deleted."),
            ("plant", "Plant deleted."),
            ("payment_terms", "Payment terms deleted."),
            ("purchasing_group", "Purchasing group deleted."),
            ("material_group", "Material group deleted (second occurrence)."),
        ]
        for row, (field_name, reason) in zip(candidates[:5], plans):
            self._lock(row)
            row[field_name] = None
            self._add(
                ManifestEntry(
                    record_identifier=f"{row['po_number']}/{row['po_item']}",
                    po_number=row["po_number"],
                    po_item=row["po_item"],
                    expected_rule_id="PO-R015",
                    expected_risk="Missing required fields",
                    expected_severity="medium",
                    severity_may_escalate="yes",
                    reason=f"{reason} The field is on the PO-R015 watch list.",
                )
            )

    # -- PO-R016 ---------------------------------------------------------
    def _inject_unusual_payment_terms(self) -> None:
        candidates = self._free_rows([row for row in self.rows if row["total_value"] >= 6000])
        self.random.shuffle(candidates)
        terms = ["NT120", "CASH", "Z999", "NT007", "PREPAY"]
        for row, term in zip(candidates[:5], terms):
            self._lock(row)
            row["payment_terms"] = term
            self._add(
                ManifestEntry(
                    record_identifier=f"{row['po_number']}/{row['po_item']}",
                    po_number=row["po_number"],
                    po_item=row["po_item"],
                    expected_rule_id="PO-R016",
                    expected_risk="Unusual payment terms",
                    expected_severity="medium",
                    severity_may_escalate="yes",
                    reason=f"Payment terms set to '{term}', which is outside the approved list.",
                )
            )

    # -- PO-R017 ---------------------------------------------------------
    def _inject_excessive_changes(self) -> None:
        targets = self._pick_pos(4, lambda rows: True)
        change_counts = [7, 9, 13, 16]
        for rows, changes in zip(targets, change_counts):
            self._lock(rows)
            for row in rows:
                row["change_count"] = changes
                row["changed_by"] = "BUYER11"
            self._add(
                ManifestEntry(
                    record_identifier=rows[0]["po_number"],
                    po_number=rows[0]["po_number"],
                    po_item=None,
                    expected_rule_id="PO-R017",
                    expected_risk="Excessive manual changes",
                    expected_severity="high" if changes >= 12 else "medium",
                    severity_may_escalate="yes",
                    reason=f"Change count set to {changes} (alert level is more than 5 changes).",
                )
            )

    # -- PO-R018 ---------------------------------------------------------
    def _document_supplier_concentration(self) -> None:
        group_rows = [row for row in self.rows if row["material_group"] == CONCENTRATED_GROUP]
        if not group_rows:
            return
        supplier_id = group_rows[0]["supplier_id"]
        total = sum(row["total_value"] for row in group_rows)
        self._add(
            ManifestEntry(
                record_identifier=f"{CONCENTRATED_GROUP}/{supplier_id}",
                po_number=group_rows[0]["po_number"],
                po_item=None,
                expected_rule_id="PO-R018",
                expected_risk="Supplier concentration in a material group",
                expected_severity="high",
                severity_may_escalate="no",
                expected_scope="supplier",
                supplier_id=supplier_id,
                reason=(
                    f"Material group {CONCENTRATED_GROUP} (specialised tooling) is single-sourced "
                    f"from supplier {supplier_id} by design, giving a 100% share of roughly "
                    f"{total:,.0f} in document currency."
                ),
            )
        )

    # -- PO-R019 ---------------------------------------------------------
    def _inject_maverick_spend(self) -> None:
        # PO-R019 only fires when another supplier holds at least the configured
        # number of *contracted lines* for the material, so count actual rows.
        contracted_lines: dict[tuple[str, str], int] = {}
        for row in self.rows:
            if row["contract_number"] and row["material"] and row["supplier_id"]:
                key = (row["material"], row["supplier_id"])
                contracted_lines[key] = contracted_lines.get(key, 0) + 1
        eligible_materials = {
            material for (material, _supplier), count in contracted_lines.items() if count >= 2
        }

        contracted_materials = [
            m for m in self.materials if m.contracted and m.material in eligible_materials
        ]
        self.random.shuffle(contracted_materials)
        used_suppliers = set()
        injected = 0

        for material in contracted_materials:
            if injected >= 5:
                break
            outsiders = [
                supplier for supplier in self.suppliers
                if supplier.supplier_id not in material.supplier_ids
                and supplier.supplier_id not in used_suppliers
            ]
            if not outsiders:
                continue
            supplier = self.random.choice(outsiders)
            used_suppliers.add(supplier.supplier_id)

            po_number = self._next_po_number()
            order_date = date(2025, 9, 8) + timedelta(days=injected * 3)
            quantity = float(self.random.randint(10, 60))
            unit_price = self._price_for(material, supplier.currency, jitter=(1.05, 1.2))
            self.rows.append(
                {
                    "po_number": po_number,
                    "po_item": "00010",
                    "supplier_id": supplier.supplier_id,
                    "supplier_name": supplier.name,
                    "material": material.material,
                    "material_description": material.description,
                    "material_group": material.material_group,
                    "company_code": supplier.company_code,
                    "purchasing_org": supplier.purchasing_org,
                    "purchasing_group": "P05",
                    "plant": supplier.plants[0],
                    "quantity": quantity,
                    "unit_of_measure": material.unit_of_measure,
                    "unit_price": unit_price,
                    "currency": supplier.currency,
                    "total_value": round(quantity * unit_price, 2),
                    "order_date": order_date,
                    "requested_delivery_date": order_date + timedelta(days=18),
                    "actual_delivery_date": order_date + timedelta(days=19),
                    "contract_number": None,
                    "payment_terms": supplier.payment_terms,
                    "approval_status": "Approved",
                    "created_by": "BUYER04",
                    "changed_by": "BUYER04",
                    "change_count": 2,
                }
            )
            self._add(
                ManifestEntry(
                    record_identifier=f"{po_number}/00010",
                    po_number=po_number,
                    po_item="00010",
                    expected_rule_id="PO-R019",
                    expected_risk="Maverick spending",
                    expected_severity="high",
                    severity_may_escalate="yes",
                    reason=(
                        f"Material {material.material} bought from supplier {supplier.supplier_id} "
                        "without a contract while other suppliers hold an outline agreement for it."
                    ),
                )
            )
            injected += 1

    # -- PO-R020 ---------------------------------------------------------
    def _document_high_risk_suppliers(self) -> None:
        watch_list = ["0000100013", "0000100027", "0000100041"]
        for supplier_id in watch_list:
            supplier_rows = [row for row in self.rows if row["supplier_id"] == supplier_id]
            if not supplier_rows:
                continue
            po_numbers = sorted({row["po_number"] for row in supplier_rows})
            self._add(
                ManifestEntry(
                    record_identifier=f"supplier {supplier_id} ({len(po_numbers)} purchase orders)",
                    po_number=po_numbers[0],
                    po_item=None,
                    expected_rule_id="PO-R020",
                    expected_risk="Purchase from a high-risk supplier",
                    expected_severity="high",
                    severity_may_escalate="yes",
                    supplier_id=supplier_id,
                    reason=(
                        f"Supplier {supplier_id} is on the configured watch list, so every one of "
                        f"its {len(po_numbers)} purchase orders is expected to raise PO-R020."
                    ),
                )
            )

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------
    def to_dataframe(self) -> pd.DataFrame:
        """Return the generated rows sorted by purchase order and item."""
        frame = pd.DataFrame(self.rows)
        frame = frame.sort_values(["po_number", "po_item"]).reset_index(drop=True)
        return frame[list(CANONICAL_FIELDS)]

    def write(self, output_dir: Path) -> dict[str, Any]:
        """Write all sample files and the anomaly manifest."""
        output_dir.mkdir(parents=True, exist_ok=True)
        frame = self.to_dataframe()

        csv_frame = frame.rename(columns=SAP_TECHNICAL_HEADERS)
        csv_path = output_dir / "sample_purchase_orders.csv"
        csv_frame.to_csv(csv_path, index=False)

        xlsx_frame = frame.rename(columns={name: FIELD_BY_NAME[name].label for name in CANONICAL_FIELDS})
        xlsx_path = output_dir / "sample_purchase_orders.xlsx"
        xlsx_frame.to_excel(xlsx_path, index=False, sheet_name="Purchase Orders")

        json_path = output_dir / "sample_purchase_orders.json"
        json_records = json.loads(frame.to_json(orient="records", date_format="iso"))
        for record in json_records:
            for key, value in list(record.items()):
                if isinstance(value, str) and value.endswith("T00:00:00.000"):
                    record[key] = value[:10]
        json_path.write_text(
            json.dumps({"records": json_records}, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        manifest_rows = [entry.to_dict() for entry in self.manifest]
        manifest_frame = pd.DataFrame(manifest_rows)
        manifest_frame.to_csv(output_dir / "anomaly_manifest.csv", index=False)
        (output_dir / "anomaly_manifest.json").write_text(
            json.dumps(
                {
                    "generated_with_seed": SEED,
                    "data_origin": "demo_data",
                    "note": (
                        "Fictional dataset. Every entry below is an anomaly that was deliberately "
                        "injected so the corresponding rule has a known expected result."
                    ),
                    "anomalies": manifest_rows,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (output_dir / "ANOMALY_MANIFEST.md").write_text(
            _manifest_markdown(frame, manifest_rows), encoding="utf-8"
        )

        return {
            "rows": len(frame),
            "purchase_orders": int(frame["po_number"].nunique()),
            "suppliers": int(frame["supplier_id"].nunique()),
            "materials": int(frame["material"].nunique()),
            "anomalies": len(manifest_rows),
            "files": [
                str(csv_path), str(xlsx_path), str(json_path),
                str(output_dir / "anomaly_manifest.csv"),
                str(output_dir / "anomaly_manifest.json"),
                str(output_dir / "ANOMALY_MANIFEST.md"),
            ],
        }


def _manifest_markdown(frame: pd.DataFrame, manifest_rows: list[dict[str, Any]]) -> str:
    """Render the human readable manifest."""
    by_rule: dict[str, list[dict[str, Any]]] = {}
    for row in manifest_rows:
        by_rule.setdefault(row["expected_rule_id"], []).append(row)

    lines = [
        "# Sample data anomaly manifest",
        "",
        "**Origin: demo data.** This dataset is fictional. It was generated by "
        "`scripts/generate_sample_data.py` and does not come from any SAP system or real company.",
        "",
        f"- Line items: {len(frame):,}",
        f"- Purchase orders: {frame['po_number'].nunique():,}",
        f"- Suppliers: {frame['supplier_id'].nunique():,}",
        f"- Materials: {frame['material'].nunique():,}",
        f"- Documented anomalies: {len(manifest_rows)}",
        f"- Random seed: `{SEED}` (regenerating reproduces the identical dataset)",
        "",
        "The background population is generated so that it does *not* trigger rules: unit prices "
        "vary by at most +/-5%, orders on one supplier are at least 16 days apart, deliveries stay "
        "inside the 3 day grace period and free-text lines stay below the contract review level. "
        "Findings should therefore trace back to the anomalies below.",
        "",
    ]

    for rule_id in sorted(by_rule):
        entries = by_rule[rule_id]
        lines.append(f"## {rule_id} - {entries[0]['expected_risk']}")
        lines.append("")
        lines.append("| Record | PO | Item | Scope | Expected severity | May escalate | Reason |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for entry in entries:
            lines.append(
                f"| `{entry['record_identifier']}` | {entry['po_number']} | "
                f"{entry['po_item'] or '-'} | {entry['expected_scope']} | "
                f"{entry['expected_severity']} | "
                f"{entry['severity_may_escalate']} | {entry['reason']} |"
            )
        lines.append("")

    lines.extend([
        "## Notes on overlapping rules",
        "",
        "- A single line can legitimately trigger several rules. A price injected for PO-R005 "
        "usually also breaches the PO-R006 median band, and any order from a watch-listed supplier "
        "raises PO-R020 on top of whatever else applies.",
        "- `severity_may_escalate = yes` means the configured value bands "
        "(>= 100,000 base currency -> high, >= 250,000 -> critical) can raise the severity above "
        "the rule's base level. Severity is therefore asserted as *at least* the expected level.",
        "- PO-R018 and PO-R020 are portfolio level rules: they describe a supplier or a category "
        "rather than one document.",
        "- A few additional findings come from injected orders interacting with the clean "
        "population (for example a new order that happens to resemble an existing one). "
        "`expected_findings_baseline.json` records the exact per-rule totals the current engine "
        "produces, so the test suite can tell a deliberate change from an accidental one.",
        "",
        "## How the test suite uses this file",
        "",
        "`tests/integration/test_sample_data_anomalies.py` reads `anomaly_manifest.csv`, runs the "
        "engine over the sample file and asserts that every documented record is detected by the "
        "expected rule at a severity no lower than the expected one.",
        "",
    ])
    return "\n".join(lines)


def write_observed_baseline(output_dir: Path) -> dict[str, Any]:
    """Run the engine over the freshly generated file and record the result.

    The manifest states what *should* be found. This baseline records what the
    current engine *does* find, so the test suite can flag an unintended change
    in either the rules or the data. Extra findings beyond the manifest are
    legitimate rule overlaps (for example a price increase that also breaches
    the median band) and are counted here.
    """
    from app.modules.po_risk.column_mapping import suggest_mapping
    from app.modules.po_risk.engine import RiskEngine
    from app.modules.po_risk.normalizer import normalize_dataframe
    from app.services.files.readers import read_tabular

    content = (output_dir / "sample_purchase_orders.csv").read_bytes()
    read_result = read_tabular(content, ".csv")
    config = get_rule_config()
    dataset = normalize_dataframe(
        read_result.dataframe, suggest_mapping(read_result.source_columns).mapping, config
    )
    result = RiskEngine(config).run(dataset.frame)

    baseline = {
        "note": (
            "Observed output of the current engine on the generated sample file. "
            "Counts can exceed the anomaly manifest because rules legitimately overlap."
        ),
        "seed": SEED,
        "config_version": config.config_version,
        "engine_version": result.engine_version,
        "record_count": int(len(dataset.frame)),
        "findings_total": len(result.findings),
        "severity_counts": result.summary["severity_counts"],
        "findings_by_rule": {
            execution.rule_id: execution.findings_count for execution in result.executions
        },
    }
    (output_dir / "expected_findings_baseline.json").write_text(
        json.dumps(baseline, indent=2), encoding="utf-8"
    )
    return baseline


def main() -> int:
    """Generate the sample dataset."""
    generator = SampleDataGenerator()
    generator.build_suppliers()
    generator.build_materials()
    generator.build_clean_rows()
    generator.inject_anomalies()
    stats = generator.write(settings.sample_dir)
    stats["baseline"] = write_observed_baseline(settings.sample_dir)

    logger.info(
        "Generated %d line items across %d purchase orders, %d suppliers, %d materials",
        stats["rows"], stats["purchase_orders"], stats["suppliers"], stats["materials"],
    )
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
