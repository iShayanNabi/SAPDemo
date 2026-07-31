"""Generate the fictional spend dataset for the Spend Analytics Dashboard.

Run with::

    python scripts/generate_spend_sample_data.py

Outputs (into ``data/sample/``):

* ``sample_spend_transactions.csv``   - SAP technical / spend-cube column names
* ``sample_spend_transactions.xlsx``  - business labels
* ``sample_spend_transactions.json``  - canonical snake_case names
* ``spend_scenario_manifest.json`` / ``.md``
* ``expected_spend_baseline.json``    - what the current engine produces

**The data is entirely fictional.** Supplier names, materials and numbers were
invented for this lab. Nothing comes from an SAP system or a real company.

Design principle: the background population is deliberately *healthy* -
contracted, preferred, priced within a few percent of its baseline and spread
over enough suppliers per category that no rule fires. Each documented scenario
then injects one specific condition, so every metric movement and every savings
opportunity traces back to a line in the manifest.
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
from app.modules.spend.field_definitions import CANONICAL_FIELDS, REGISTRY  # noqa: E402
from app.modules.spend.thresholds import get_spend_config  # noqa: E402

logger = get_logger("generate_spend_sample_data")

SEED = 20260201
START_MONTH = date(2024, 1, 1)
MONTHS = 24
CORE_SUPPLIER_COUNT = 42
TAIL_SUPPLIER_COUNT = 22
MATERIAL_COUNT = 120

#: CSV uses the technical names a spend extract usually carries.
TECHNICAL_HEADERS = {
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
    "transaction_date": "POSTING_DATE",
    "category": "SPEND_CATEGORY",
    "subcategory": "SUB_CATEGORY",
    "contract_status": "CONTRACT_STATUS",
    "preferred_supplier_status": "PREFERRED_SUPPLIER",
    "baseline_price": "BASELINE_PRICE",
    "current_price": "ACTUAL_PRICE",
    "payment_status": "PAYMENT_STATUS",
}

COMPANY_CODES = [
    {"company_code": "1000", "currency": "EUR", "purchasing_org": "1000", "plants": ["1010", "1020"]},
    {"company_code": "2000", "currency": "USD", "purchasing_org": "2000", "plants": ["2010", "2020"]},
    {"company_code": "3000", "currency": "GBP", "purchasing_org": "3000", "plants": ["3010"]},
    {"company_code": "4000", "currency": "CHF", "purchasing_org": "4000", "plants": ["4010"]},
    {"company_code": "5000", "currency": "SEK", "purchasing_org": "5000", "plants": ["5010"]},
]

#: (category, subcategories, material groups, price band)
CATEGORIES = [
    ("IT and Telecom", ["Hardware", "Software Licences", "Network"], ["MG40", "MG41"], (95.0, 2400.0)),
    ("Facilities", ["Cleaning", "Energy", "Maintenance"], ["MG35", "MG45"], (25.0, 480.0)),
    ("Logistics", ["Freight", "Warehousing", "Couriers"], ["MG50"], (75.0, 900.0)),
    ("Raw Materials", ["Metals", "Polymers", "Chemicals"], ["MG20", "MG30"], (1.4, 65.0)),
    ("Components", ["Electrical", "Mechanical", "Fasteners"], ["MG10", "MG15"], (8.0, 950.0)),
    ("Packaging", ["Cartons", "Films", "Labels"], ["MG25"], (0.4, 12.0)),
    ("Professional Services", ["Consulting", "Audit", "Training"], ["MG60"], (140.0, 1800.0)),
    ("Laboratory", ["Instruments", "Consumables"], ["MG55"], (140.0, 3200.0)),
]

#: Deliberately single-sourced so supplier concentration has a documented target.
CONCENTRATED_CATEGORY = "Specialised Tooling"
CONCENTRATED_GROUP = "MG90"

#: Deliberately fragmented so supplier consolidation has a documented target.
FRAGMENTED_GROUP = "MG15"

SUPPLIER_PREFIXES = [
    "Nordwind", "Bluepeak", "Vertex", "Ravenna", "Kestrel", "Alpenrose", "Silverline", "Bramble",
    "Cobalt", "Driftwood", "Ember", "Fairmont", "Granite", "Harbourview", "Ironwood", "Juniper",
    "Larkspur", "Meridian", "Northgate", "Orchard", "Pinnacle", "Quarry", "Redstone", "Summit",
    "Thornbury", "Umbra", "Valemont", "Westford", "Yarrow", "Zenith", "Ashford", "Belmont",
    "Cresthill", "Dunmore", "Eastvale", "Foxglove", "Glenmore", "Hollowbrook", "Inverness",
    "Kingsley", "Lakeshore", "Milbrook", "Norwood", "Oakfield", "Pemberton", "Ridgeway",
    "Stonebridge", "Tallowood", "Ullswater", "Vinemount", "Whitfield", "Yardley", "Zephyr",
    "Alderford", "Bexley", "Clearwater", "Draycott", "Elmsworth", "Fernhill", "Greystone",
    "Havenwood", "Ilford", "Jasperfield", "Kelmscott", "Lowfield", "Maplewood",
]
SUPPLIER_SUFFIXES = [
    "Industrie GmbH", "Supply Ltd", "Components SA", "Trading BV", "Manufacturing AG",
    "Technologies Oy", "Materials SpA", "Engineering Sp. z o.o.", "Logistics AS", "Systems Inc",
]

MATERIAL_NOUNS = [
    "bearing", "gasket", "relay", "connector", "valve", "bracket", "sensor", "filter", "coupling",
    "actuator", "housing", "spindle", "cartridge", "membrane", "adapter", "clamp", "pulley",
    "seal ring", "terminal block", "control unit", "licence pack", "service block", "pallet",
]
MATERIAL_ADJECTIVES = [
    "stainless", "high-temperature", "industrial", "precision", "heavy-duty", "compact",
    "insulated", "reinforced", "modular", "low-friction", "certified", "recycled",
]

PAYMENT_TERMS = ["NT30", "NT45", "NT60", "Z030", "Z045"]
PAYMENT_STATUSES = ["Paid", "Paid", "Paid", "Open", "Overdue"]
BUYERS = [f"BUYER{index:02d}" for index in range(1, 15)]


@dataclass
class Supplier:
    """A fictional supplier."""

    supplier_id: str
    name: str
    company_code: str
    currency: str
    purchasing_org: str
    plants: list[str]
    is_preferred: bool
    is_tail: bool = False


@dataclass
class Material:
    """A fictional material with its category and contracted suppliers."""

    material: str
    description: str
    material_group: str
    category: str
    subcategory: str
    unit_of_measure: str
    base_price_eur: float
    supplier_ids: list[str] = field(default_factory=list)

    def contract_number(self, supplier_id: str) -> str:
        """Deterministic contract id for a material/supplier pair."""
        return f"46{supplier_id[-4:]}{int(self.material.split('-')[1]) % 900 + 100:03d}"


@dataclass
class Scenario:
    """One deliberately injected, documented condition."""

    scenario_id: str
    name: str
    description: str
    expects: str
    affected_transactions: int = 0
    affected_spend_base: float = 0.0
    suppliers: list[str] = field(default_factory=list)
    materials: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "name": self.name,
            "description": self.description,
            "expects": self.expects,
            "affected_transactions": self.affected_transactions,
            "affected_spend_base": round(self.affected_spend_base, 2),
            "suppliers": self.suppliers,
            "materials": self.materials,
            "categories": self.categories,
        }


class SpendSampleGenerator:
    """Builds the demo spend dataset and its scenario manifest."""

    def __init__(self, seed: int = SEED) -> None:
        self.random = random.Random(seed)
        self.config = get_spend_config()
        self.suppliers: list[Supplier] = []
        self.materials: list[Material] = []
        self.rows: list[dict[str, Any]] = []
        self.scenarios: list[Scenario] = []
        self._po_sequence = 5500000

    # ------------------------------------------------------------------
    # Master data
    # ------------------------------------------------------------------
    def build_suppliers(self) -> None:
        total = CORE_SUPPLIER_COUNT + TAIL_SUPPLIER_COUNT
        for index in range(total):
            company = COMPANY_CODES[index % len(COMPANY_CODES)]
            is_tail = index >= CORE_SUPPLIER_COUNT
            self.suppliers.append(
                Supplier(
                    supplier_id=f"{200001 + index:010d}",
                    name=(
                        f"{SUPPLIER_PREFIXES[index % len(SUPPLIER_PREFIXES)]} "
                        f"{self.random.choice(SUPPLIER_SUFFIXES)}"
                    ),
                    company_code=company["company_code"],
                    currency=company["currency"],
                    purchasing_org=company["purchasing_org"],
                    plants=list(company["plants"]),
                    # Tail suppliers are never preferred; that is what makes them tail.
                    is_preferred=(not is_tail) and index % 5 != 0,
                    is_tail=is_tail,
                )
            )

    @property
    def core_suppliers(self) -> list[Supplier]:
        return [s for s in self.suppliers if not s.is_tail]

    @property
    def tail_suppliers(self) -> list[Supplier]:
        return [s for s in self.suppliers if s.is_tail]

    def build_materials(self) -> None:
        core_ids = [s.supplier_id for s in self.core_suppliers]

        for index in range(MATERIAL_COUNT):
            category, subcategories, groups, price_band = CATEGORIES[index % len(CATEGORIES)]
            # Rotate on the *cycle* number, not the index: index % len(groups) would
            # always pick the same entry because the category itself is chosen with
            # index % len(CATEGORIES).
            group = groups[(index // len(CATEGORIES)) % len(groups)]
            # A fragmented group gets many suppliers; everything else gets 2-3.
            supplier_count = 7 if group == FRAGMENTED_GROUP else self.random.choice([2, 3])
            self.materials.append(
                Material(
                    material=f"SPM-{100000 + index * 3}",
                    description=(
                        f"{self.random.choice(MATERIAL_ADJECTIVES).capitalize()} "
                        f"{self.random.choice(MATERIAL_NOUNS)} type {index % 45 + 1}"
                    ),
                    material_group=group,
                    category=category,
                    subcategory=self.random.choice(subcategories),
                    unit_of_measure=self.random.choice(["PC", "EA", "KG", "L", "BOX"]),
                    base_price_eur=round(self.random.uniform(*price_band), 2),
                    supplier_ids=self.random.sample(core_ids, min(supplier_count, len(core_ids))),
                )
            )

        # The single-sourced category used by the concentration scenario.
        concentrated_supplier = core_ids[3]
        for offset in range(4):
            self.materials.append(
                Material(
                    material=f"SPM-{900000 + offset * 3}",
                    description=f"Precision tooling assembly type {offset + 1}",
                    material_group=CONCENTRATED_GROUP,
                    category=CONCENTRATED_CATEGORY,
                    subcategory="Custom Tooling",
                    unit_of_measure="PC",
                    base_price_eur=round(self.random.uniform(900.0, 3800.0), 2),
                    supplier_ids=[concentrated_supplier],
                )
            )

    # ------------------------------------------------------------------
    # Background population
    # ------------------------------------------------------------------
    def _next_po(self) -> str:
        self._po_sequence += 1
        return str(self._po_sequence)

    def _months(self) -> list[date]:
        months = []
        year, month = START_MONTH.year, START_MONTH.month
        for _ in range(MONTHS):
            months.append(date(year, month, 1))
            month += 1
            if month > 12:
                month, year = 1, year + 1
        return months

    def _price_in_currency(self, material: Material, currency: str, jitter: tuple[float, float]) -> float:
        """Convert the EUR base price into the document currency.

        Without this a currency mix alone would look like price variance.
        """
        rate = self.config.conversion_rate(currency)
        return round(material.base_price_eur / max(rate, 0.0001) * self.random.uniform(*jitter), 2)

    def _quantity_for(self, material: Material) -> float:
        if material.base_price_eur > 800:
            return float(self.random.randint(1, 10))
        if material.base_price_eur > 100:
            return float(self.random.randint(5, 50))
        return float(self.random.randint(20, 400))

    def _materials_for(self, supplier_id: str) -> list[Material]:
        return [m for m in self.materials if supplier_id in m.supplier_ids]

    def _make_row(
        self,
        supplier: Supplier,
        material: Material,
        transaction_date: date,
        *,
        po_number: str,
        item: int,
        quantity: float | None = None,
        unit_price: float | None = None,
        contracted: bool = True,
        preferred: bool | None = None,
        baseline_price: float | None = None,
    ) -> dict[str, Any]:
        """Build one transaction row."""
        price = unit_price if unit_price is not None else self._price_in_currency(
            material, supplier.currency, (0.99, 1.01)
        )
        units = quantity if quantity is not None else self._quantity_for(material)
        order_date = transaction_date - timedelta(days=self.random.randint(2, 20))
        requested = order_date + timedelta(days=self.random.randint(10, 40))
        is_preferred = supplier.is_preferred if preferred is None else preferred

        return {
            "po_number": po_number,
            "po_item": f"{item * 10:05d}",
            "supplier_id": supplier.supplier_id,
            "supplier_name": supplier.name,
            "material": material.material,
            "material_description": material.description,
            "material_group": material.material_group,
            "company_code": supplier.company_code,
            "purchasing_org": supplier.purchasing_org,
            "purchasing_group": self.random.choice(["P01", "P02", "P03", "P04", "P05"]),
            "plant": self.random.choice(supplier.plants),
            "quantity": units,
            "unit_of_measure": material.unit_of_measure,
            "unit_price": price,
            "currency": supplier.currency,
            "total_value": round(units * price, 2),
            "order_date": order_date,
            "requested_delivery_date": requested,
            "actual_delivery_date": requested + timedelta(days=self.random.randint(-3, 4)),
            "contract_number": material.contract_number(supplier.supplier_id) if contracted else None,
            "payment_terms": self.random.choice(PAYMENT_TERMS),
            "approval_status": "Approved",
            "created_by": self.random.choice(BUYERS),
            "changed_by": self.random.choice(BUYERS),
            "change_count": self.random.randint(0, 3),
            "transaction_date": transaction_date,
            "category": material.category,
            "subcategory": material.subcategory,
            "contract_status": "Contracted" if contracted else "Not contracted",
            "preferred_supplier_status": "Preferred" if is_preferred else "Non-preferred",
            # Healthy background: the baseline is what was actually paid.
            "baseline_price": baseline_price if baseline_price is not None else price,
            "current_price": price,
            "payment_status": self.random.choice(PAYMENT_STATUSES),
        }

    def build_background(self) -> None:
        """Healthy, contracted, correctly priced spend across 24 months."""
        for month_start in self._months():
            for supplier in self.core_suppliers:
                supplier_materials = self._materials_for(supplier.supplier_id)
                if not supplier_materials:
                    continue
                # Not every supplier trades every month.
                if self.random.random() < 0.25:
                    continue
                for _ in range(self.random.randint(1, 3)):
                    po_number = self._next_po()
                    transaction_date = month_start + timedelta(
                        days=self.random.randint(0, 27)
                    )
                    line_count = min(self.random.randint(1, 3), len(supplier_materials))
                    for item, material in enumerate(
                        self.random.sample(supplier_materials, line_count), start=1
                    ):
                        self.rows.append(
                            self._make_row(
                                supplier, material, transaction_date,
                                po_number=po_number, item=item,
                            )
                        )

    # ------------------------------------------------------------------
    # Scenarios
    # ------------------------------------------------------------------
    def inject_scenarios(self) -> None:
        self._scenario_maverick()
        self._scenario_contract_leakage()
        self._scenario_supplier_concentration()
        self._scenario_price_variance()
        self._scenario_tail_spend()
        self._scenario_preferred_migration()
        self._scenario_supplier_fragmentation()
        self._scenario_price_dispersion()

    def _scenario_maverick(self) -> None:
        """Non-preferred suppliers bought without any contract."""
        suppliers = [s for s in self.core_suppliers if not s.is_preferred][:5]
        scenario = Scenario(
            scenario_id="SC-01",
            name="Maverick spend",
            description=(
                "Five non-preferred suppliers are bought from without any contract reference, "
                "which is the configured definition of maverick spend."
            ),
            expects=(
                "maverick_spend > 0 and these suppliers appear in the maverick spend breakdown; "
                "savings rule SAV-02 (contract compliance) should also fire for them."
            ),
        )
        for supplier in suppliers:
            supplier_materials = self._materials_for(supplier.supplier_id)
            if not supplier_materials:
                continue
            scenario.suppliers.append(supplier.supplier_id)
            for month_start in self._months()[::2]:
                po_number = self._next_po()
                material = self.random.choice(supplier_materials)
                row = self._make_row(
                    supplier, material,
                    month_start + timedelta(days=self.random.randint(0, 27)),
                    po_number=po_number, item=1,
                    quantity=float(self.random.randint(10, 90)),
                    contracted=False, preferred=False,
                )
                self.rows.append(row)
                scenario.affected_transactions += 1
                scenario.affected_spend_base += self._base(row)
        self.scenarios.append(scenario)

    def _scenario_contract_leakage(self) -> None:
        """Suppliers that hold a contract but are also bought off it."""
        suppliers = [s for s in self.core_suppliers if s.is_preferred][:4]
        scenario = Scenario(
            scenario_id="SC-02",
            name="Contract leakage",
            description=(
                "Four suppliers that hold contracts are also bought from without a contract "
                "reference on roughly a third of their orders."
            ),
            expects=(
                "these suppliers appear in the contract_leakage breakdown with leaked_spend_base "
                "greater than zero; SAV-02 should propose bringing that spend under contract."
            ),
        )
        for supplier in suppliers:
            supplier_materials = self._materials_for(supplier.supplier_id)
            if not supplier_materials:
                continue
            scenario.suppliers.append(supplier.supplier_id)
            for month_start in self._months()[::3]:
                po_number = self._next_po()
                material = self.random.choice(supplier_materials)
                row = self._make_row(
                    supplier, material,
                    month_start + timedelta(days=self.random.randint(0, 27)),
                    po_number=po_number, item=1,
                    quantity=float(self.random.randint(20, 120)),
                    contracted=False,
                )
                self.rows.append(row)
                scenario.affected_transactions += 1
                scenario.affected_spend_base += self._base(row)
        self.scenarios.append(scenario)

    def _scenario_supplier_concentration(self) -> None:
        """A category served by exactly one supplier."""
        tooling = [m for m in self.materials if m.material_group == CONCENTRATED_GROUP]
        if not tooling:
            return
        supplier_id = tooling[0].supplier_ids[0]
        supplier = next(s for s in self.suppliers if s.supplier_id == supplier_id)
        scenario = Scenario(
            scenario_id="SC-03",
            name="Supplier concentration",
            description=(
                f"Material group {CONCENTRATED_GROUP} ({CONCENTRATED_CATEGORY}) is sourced "
                "entirely from one supplier by design."
            ),
            expects=(
                f"supplier_concentration breakdown shows {CONCENTRATED_GROUP} at a 100% top "
                "supplier share, above the configured warning threshold."
            ),
            suppliers=[supplier_id],
            categories=[CONCENTRATED_CATEGORY],
        )
        for month_start in self._months():
            po_number = self._next_po()
            material = self.random.choice(tooling)
            row = self._make_row(
                supplier, material,
                month_start + timedelta(days=self.random.randint(0, 27)),
                po_number=po_number, item=1,
                quantity=float(self.random.randint(2, 12)),
            )
            self.rows.append(row)
            scenario.affected_transactions += 1
            scenario.affected_spend_base += self._base(row)
        self.scenarios.append(scenario)

    def _scenario_price_variance(self) -> None:
        """Lines bought well above their documented baseline price."""
        candidates = [
            m for m in self.materials
            if m.material_group not in (CONCENTRATED_GROUP,) and m.base_price_eur > 50
        ]
        self.random.shuffle(candidates)
        chosen = candidates[:6]
        scenario = Scenario(
            scenario_id="SC-04",
            name="Purchase price variance",
            description=(
                "Six materials have orders priced 20-45% above the baseline price recorded on "
                "the same line."
            ),
            expects=(
                "price_variance_base is clearly positive, these materials appear in the "
                "purchase_price_variance breakdown, and SAV-06 proposes closing the gap."
            ),
            materials=[m.material for m in chosen],
        )
        for material in chosen:
            supplier = next(
                s for s in self.suppliers if s.supplier_id == material.supplier_ids[0]
            )
            for offset in range(0, MONTHS, 4):
                month_start = self._months()[offset]
                baseline = self._price_in_currency(material, supplier.currency, (1.0, 1.0))
                inflated = round(baseline * self.random.uniform(1.20, 1.45), 2)
                po_number = self._next_po()
                row = self._make_row(
                    supplier, material,
                    month_start + timedelta(days=self.random.randint(0, 27)),
                    po_number=po_number, item=1,
                    quantity=float(self.random.randint(20, 80)),
                    unit_price=inflated,
                    baseline_price=baseline,
                )
                self.rows.append(row)
                scenario.affected_transactions += 1
                scenario.affected_spend_base += self._base(row)
        self.scenarios.append(scenario)

    def _scenario_tail_spend(self) -> None:
        """Many very small suppliers, each with a handful of transactions."""
        scenario = Scenario(
            scenario_id="SC-05",
            name="Tail spend",
            description=(
                f"{TAIL_SUPPLIER_COUNT} suppliers each carry only a few small, non-contracted "
                "orders, placing them outside the Pareto threshold."
            ),
            expects=(
                "tail_supplier_count is at least 20, tail_spend is greater than zero, these "
                "suppliers appear in tail_spend_suppliers, and SAV-04 proposes rationalising them."
            ),
        )
        for supplier in self.tail_suppliers:
            scenario.suppliers.append(supplier.supplier_id)
            for _ in range(self.random.randint(1, 4)):
                material = self.random.choice(self.materials)
                month_start = self.random.choice(self._months())
                po_number = self._next_po()
                row = self._make_row(
                    supplier, material,
                    month_start + timedelta(days=self.random.randint(0, 27)),
                    po_number=po_number, item=1,
                    quantity=float(self.random.randint(1, 8)),
                    contracted=False, preferred=False,
                )
                self.rows.append(row)
                scenario.affected_transactions += 1
                scenario.affected_spend_base += self._base(row)
        self.scenarios.append(scenario)

    def _scenario_preferred_migration(self) -> None:
        """A preferred supplier sells the same material cheaper than others."""
        candidates = [
            m for m in self.materials
            if len(m.supplier_ids) >= 2 and 80 < m.base_price_eur < 1500
        ]
        self.random.shuffle(candidates)
        chosen = candidates[:4]
        scenario = Scenario(
            scenario_id="SC-06",
            name="Preferred supplier price gap",
            description=(
                "Four materials are supplied by a preferred supplier at the baseline price and "
                "by non-preferred suppliers 18-35% higher."
            ),
            expects=(
                "SAV-05 (move to preferred suppliers) proposes migrating these materials, with "
                "a documented price gap above the configured minimum."
            ),
            materials=[m.material for m in chosen],
        )
        for material in chosen:
            preferred_supplier = next(
                (s for s in self.core_suppliers
                 if s.supplier_id in material.supplier_ids and s.is_preferred),
                None,
            )
            other_supplier = next(
                (s for s in self.core_suppliers
                 if s.supplier_id in material.supplier_ids and s is not preferred_supplier),
                None,
            )
            if preferred_supplier is None or other_supplier is None:
                continue

            cheap_price = self._price_in_currency(material, preferred_supplier.currency, (1.0, 1.0))
            for offset in range(0, MONTHS, 6):
                month_start = self._months()[offset]
                self.rows.append(
                    self._make_row(
                        preferred_supplier, material,
                        month_start + timedelta(days=self.random.randint(0, 27)),
                        po_number=self._next_po(), item=1,
                        quantity=float(self.random.randint(15, 60)),
                        unit_price=cheap_price, baseline_price=cheap_price, preferred=True,
                    )
                )
                scenario.affected_transactions += 1

            expensive_base = self._price_in_currency(material, other_supplier.currency, (1.0, 1.0))
            for offset in range(0, MONTHS, 3):
                month_start = self._months()[offset]
                expensive = round(expensive_base * self.random.uniform(1.18, 1.35), 2)
                row = self._make_row(
                    other_supplier, material,
                    month_start + timedelta(days=self.random.randint(0, 27)),
                    po_number=self._next_po(), item=1,
                    quantity=float(self.random.randint(25, 90)),
                    unit_price=expensive, baseline_price=expensive, preferred=False,
                )
                self.rows.append(row)
                scenario.affected_transactions += 1
                scenario.affected_spend_base += self._base(row)
        self.scenarios.append(scenario)

    def _scenario_supplier_fragmentation(self) -> None:
        """A material group split across many suppliers."""
        group_materials = [m for m in self.materials if m.material_group == FRAGMENTED_GROUP]
        if not group_materials:
            return
        supplier_ids = sorted({s for m in group_materials for s in m.supplier_ids})
        scenario = Scenario(
            scenario_id="SC-07",
            name="Supplier fragmentation",
            description=(
                f"Material group {FRAGMENTED_GROUP} is deliberately spread across "
                f"{len(supplier_ids)} suppliers."
            ),
            expects="SAV-03 (supplier consolidation) proposes consolidating this material group.",
            suppliers=supplier_ids,
        )
        for material in group_materials[:6]:
            for supplier_id in material.supplier_ids:
                supplier = next(s for s in self.suppliers if s.supplier_id == supplier_id)
                for offset in range(0, MONTHS, 5):
                    month_start = self._months()[offset]
                    row = self._make_row(
                        supplier, material,
                        month_start + timedelta(days=self.random.randint(0, 27)),
                        po_number=self._next_po(), item=1,
                        quantity=float(self.random.randint(20, 100)),
                    )
                    self.rows.append(row)
                    scenario.affected_transactions += 1
                    scenario.affected_spend_base += self._base(row)
        self.scenarios.append(scenario)

    def _scenario_price_dispersion(self) -> None:
        """The same material bought at widely different prices over time."""
        candidates = [
            m for m in self.materials
            if m.material_group not in (CONCENTRATED_GROUP, FRAGMENTED_GROUP)
            and m.base_price_eur > 100
        ]
        self.random.shuffle(candidates)
        chosen = candidates[:5]
        scenario = Scenario(
            scenario_id="SC-08",
            name="Price dispersion",
            description=(
                "Five materials are bought at prices ranging from 15% below to 40% above their "
                "usual level, with the baseline kept in line with each payment so the dispersion "
                "shows up as inconsistent pricing rather than variance against a baseline."
            ),
            expects="SAV-01 (price harmonisation) proposes moving all lines to the target percentile.",
            materials=[m.material for m in chosen],
        )
        for material in chosen:
            supplier = next(s for s in self.suppliers if s.supplier_id == material.supplier_ids[0])
            for offset in range(MONTHS):
                if offset % 2:
                    continue
                month_start = self._months()[offset]
                factor = self.random.choice([0.85, 0.92, 1.0, 1.18, 1.30, 1.40])
                price = round(
                    self._price_in_currency(material, supplier.currency, (1.0, 1.0)) * factor, 2
                )
                row = self._make_row(
                    supplier, material,
                    month_start + timedelta(days=self.random.randint(0, 27)),
                    po_number=self._next_po(), item=1,
                    quantity=float(self.random.randint(20, 70)),
                    unit_price=price, baseline_price=price,
                )
                self.rows.append(row)
                scenario.affected_transactions += 1
                scenario.affected_spend_base += self._base(row)
        self.scenarios.append(scenario)

    def _base(self, row: dict[str, Any]) -> float:
        """Base-currency value of a row."""
        return float(row["total_value"]) * self.config.conversion_rate(row["currency"])

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------
    def to_dataframe(self) -> pd.DataFrame:
        frame = pd.DataFrame(self.rows)
        frame = frame.sort_values(["transaction_date", "po_number", "po_item"]).reset_index(
            drop=True
        )
        return frame[list(CANONICAL_FIELDS)]

    def write(self, output_dir: Path) -> dict[str, Any]:
        """Write the three sample files and the scenario manifest."""
        output_dir.mkdir(parents=True, exist_ok=True)
        frame = self.to_dataframe()

        csv_path = output_dir / "sample_spend_transactions.csv"
        frame.rename(columns=TECHNICAL_HEADERS).to_csv(csv_path, index=False)

        xlsx_path = output_dir / "sample_spend_transactions.xlsx"
        frame.rename(columns={name: REGISTRY.label(name) for name in CANONICAL_FIELDS}).to_excel(
            xlsx_path, index=False, sheet_name="Spend Transactions"
        )

        json_path = output_dir / "sample_spend_transactions.json"
        records = json.loads(frame.to_json(orient="records", date_format="iso"))
        for record in records:
            for key, value in list(record.items()):
                if isinstance(value, str) and value.endswith("T00:00:00.000"):
                    record[key] = value[:10]
        json_path.write_text(
            json.dumps({"records": records}, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        manifest = {
            "generated_with_seed": SEED,
            "data_origin": "demo_data",
            "months_covered": MONTHS,
            "period_start": str(frame["transaction_date"].min()),
            "period_end": str(frame["transaction_date"].max()),
            "note": (
                "Fictional dataset. The background population is healthy by construction; each "
                "scenario below injects one specific condition so every metric movement is "
                "traceable."
            ),
            "scenarios": [scenario.to_dict() for scenario in self.scenarios],
        }
        (output_dir / "spend_scenario_manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (output_dir / "SPEND_SCENARIO_MANIFEST.md").write_text(
            _manifest_markdown(frame, manifest), encoding="utf-8"
        )

        return {
            "rows": len(frame),
            "purchase_orders": int(frame["po_number"].nunique()),
            "suppliers": int(frame["supplier_id"].nunique()),
            "materials": int(frame["material"].nunique()),
            "categories": int(frame["category"].nunique()),
            "months": MONTHS,
            "scenarios": len(self.scenarios),
            "files": [
                str(csv_path), str(xlsx_path), str(json_path),
                str(output_dir / "spend_scenario_manifest.json"),
                str(output_dir / "SPEND_SCENARIO_MANIFEST.md"),
            ],
        }


def _manifest_markdown(frame: pd.DataFrame, manifest: dict[str, Any]) -> str:
    """Render the human readable scenario manifest."""
    lines = [
        "# Spend sample data - scenario manifest",
        "",
        "**Origin: demo data.** This dataset is fictional. It was generated by "
        "`scripts/generate_spend_sample_data.py` and does not come from any SAP system or real "
        "company.",
        "",
        f"- Transactions: {len(frame):,}",
        f"- Purchase orders: {frame['po_number'].nunique():,}",
        f"- Suppliers: {frame['supplier_id'].nunique():,}",
        f"- Materials: {frame['material'].nunique():,}",
        f"- Categories: {frame['category'].nunique():,}",
        f"- Period: {manifest['period_start']} to {manifest['period_end']} "
        f"({manifest['months_covered']} months)",
        f"- Random seed: `{manifest['generated_with_seed']}` (regenerating reproduces the "
        "identical dataset)",
        "",
        "The background population is contracted, placed with preferred suppliers and priced "
        "within about 1% of its baseline, so it does not by itself produce maverick spend, "
        "leakage, variance or savings opportunities. Everything the dashboard reports should "
        "trace back to one of the scenarios below.",
        "",
        "## Scenarios",
        "",
    ]
    for scenario in manifest["scenarios"]:
        lines.extend([
            f"### {scenario['scenario_id']} - {scenario['name']}",
            "",
            scenario["description"],
            "",
            f"**Expected effect:** {scenario['expects']}",
            "",
            f"- Transactions injected: {scenario['affected_transactions']:,}",
            f"- Spend affected (base currency): {scenario['affected_spend_base']:,.2f}",
        ])
        if scenario["suppliers"]:
            shown = ", ".join(f"`{s}`" for s in scenario["suppliers"][:8])
            more = "" if len(scenario["suppliers"]) <= 8 else f" (+{len(scenario['suppliers']) - 8} more)"
            lines.append(f"- Suppliers: {shown}{more}")
        if scenario["materials"]:
            lines.append("- Materials: " + ", ".join(f"`{m}`" for m in scenario["materials"]))
        if scenario["categories"]:
            lines.append("- Categories: " + ", ".join(scenario["categories"]))
        lines.append("")

    lines.extend([
        "## How the test suite uses this file",
        "",
        "`tests/integration/test_spend_sample_data.py` runs the full pipeline over the sample "
        "file and asserts that each scenario produces the effect documented above - that "
        "maverick spend is detected, that the concentrated group is flagged, that each savings "
        "rule fires, and so on.",
        "",
        "`expected_spend_baseline.json` records the exact figures the current engine produces, "
        "so an accidental change in either the metrics or the generator is caught immediately.",
        "",
        "## A note on savings figures",
        "",
        "Savings opportunities in this dataset are **modelled estimates** produced from the "
        "documented assumptions in `app/modules/spend/config/spend_rules.json`. They are not "
        "guaranteed savings, they have not been negotiated with any supplier, and nothing here "
        "has been validated in a live SAP environment.",
        "",
    ])
    return "\n".join(lines)


def write_observed_baseline(output_dir: Path) -> dict[str, Any]:
    """Run the pipeline over the generated file and record the result."""
    from app.modules.spend.analytics import build_analytics
    from app.modules.spend.metrics import calculate_metrics, calculate_supplier_spend
    from app.modules.spend.normalizer import normalize_spend_dataframe
    from app.modules.spend.savings import calculate_savings
    from app.services.files.readers import read_tabular
    from app.services.tabular.mapping import suggest_mapping

    config = get_spend_config()
    content = (output_dir / "sample_spend_transactions.csv").read_bytes()
    read_result = read_tabular(content, ".csv")
    mapping = suggest_mapping(read_result.source_columns, REGISTRY)
    dataset = normalize_spend_dataframe(read_result.dataframe, mapping.mapping, config)

    supplier_rows = calculate_supplier_spend(dataset.frame, config)
    savings = calculate_savings(dataset.frame, config, supplier_rows)
    metrics = calculate_metrics(
        dataset.frame, config, supplier_rows, estimated_savings=savings.total_estimated_saving
    )
    analytics = build_analytics(dataset.frame, config, supplier_rows)

    baseline = {
        "note": (
            "Observed output of the current engine on the generated sample file. Used by the "
            "test suite to detect unintended changes in the metrics or the generator."
        ),
        "seed": SEED,
        "config_version": config.config_version,
        "record_count": int(len(dataset.frame)),
        "metrics": metrics.to_dict(),
        "opportunities_by_rule": savings.by_rule(),
        "opportunity_count": len(savings.opportunities),
        "analytics_row_counts": {key: len(rows) for key, rows in analytics.items()},
    }
    (output_dir / "expected_spend_baseline.json").write_text(
        json.dumps(baseline, indent=2, default=str), encoding="utf-8"
    )
    return baseline


def main() -> int:
    """Generate the spend sample dataset."""
    generator = SpendSampleGenerator()
    generator.build_suppliers()
    generator.build_materials()
    generator.build_background()
    generator.inject_scenarios()
    stats = generator.write(settings.sample_dir)
    stats["baseline"] = write_observed_baseline(settings.sample_dir)

    logger.info(
        "Generated %d spend transactions across %d months, %d suppliers, %d scenarios",
        stats["rows"], stats["months"], stats["suppliers"], stats["scenarios"],
    )
    print(json.dumps({k: v for k, v in stats.items() if k != "baseline"}, indent=2))
    metrics = stats["baseline"]["metrics"]
    print(
        f"total spend {metrics['total_spend']:,.0f} {metrics['base_currency']} | "
        f"maverick {metrics['maverick_spend_pct']:.1f}% | "
        f"tail {metrics['tail_spend_pct']:.1f}% ({metrics['tail_supplier_count']} suppliers) | "
        f"savings {metrics['estimated_savings_opportunity']:,.0f}"
    )
    print("opportunities by rule:", stats["baseline"]["opportunities_by_rule"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
