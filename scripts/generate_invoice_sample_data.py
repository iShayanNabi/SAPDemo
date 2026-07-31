"""Generate the fictional invoice / purchase-order / goods-receipt datasets.

Run with::

    python scripts/generate_invoice_sample_data.py

Outputs (into ``data/sample/``), each in three formats:

* ``sample_invoices.{csv,xlsx,json}``
* ``sample_invoice_purchase_orders.{csv,xlsx,json}``
* ``sample_goods_receipts.{csv,xlsx,json}``
* ``invoice_scenario_manifest.json`` / ``.md``
* ``expected_invoice_baseline.json`` - what the current engine produces

**The data is entirely fictional.** Supplier names, materials and numbers were
invented for this lab. Nothing comes from an SAP system or a real company.

Design principle: most invoices are ordinary and match their purchase order and
goods receipt cleanly (they raise no exception). A small set of *anchor*
invoices is placed deliberately - one per validation rule - so every documented
exception traces back to a line in the manifest and can be asserted by the test
suite against a fixed reference date.
"""

from __future__ import annotations

import json
import random
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.logging import get_logger  # noqa: E402
from app.modules.invoice_validator.field_definitions import (  # noqa: E402
    GOODS_RECEIPT_CANONICAL_FIELDS,
    GOODS_RECEIPT_REGISTRY,
    INVOICE_CANONICAL_FIELDS,
    INVOICE_REGISTRY,
    PO_REGISTRY,
)
from app.modules.invoice_validator.thresholds import get_invoice_validator_config  # noqa: E402

logger = get_logger("generate_invoice_sample_data")

SEED = 20260731
CLEAN_COUNT = 400
TAX_RATE = 0.19
AS_OF_DATE = "2026-06-30"

#: PO columns we populate (a subset of the reused purchase-order registry + status).
PO_COLS: tuple[str, ...] = (
    "po_number", "po_item", "supplier_id", "supplier_name", "material",
    "material_description", "quantity", "unit_price", "currency", "payment_terms",
    "order_date", "po_status",
)

INVOICE_HEADERS = {
    "invoice_number": "BELNR", "supplier_id": "LIFNR", "supplier_name": "NAME1",
    "po_number": "EBELN", "po_item": "EBELP", "invoice_date": "BLDAT", "posting_date": "BUDAT",
    "quantity": "MENGE", "unit_price": "NETPR", "subtotal": "WRBTR", "tax": "MWSTS",
    "freight": "FREIGHT", "currency": "WAERS", "total_amount": "RMWWR", "payment_terms": "ZTERM",
    "gr_reference": "LFBNR",
}
PO_HEADERS = {
    "po_number": "EBELN", "po_item": "EBELP", "supplier_id": "LIFNR", "supplier_name": "NAME1",
    "material": "MATNR", "material_description": "TXZ01", "quantity": "MENGE", "unit_price": "NETPR",
    "currency": "WAERS", "payment_terms": "ZTERM", "order_date": "BEDAT", "po_status": "PO_STATUS",
}
GR_HEADERS = {
    "gr_number": "MBLNR", "po_number": "EBELN", "po_item": "EBELP", "receipt_date": "BUDAT",
    "received_quantity": "MENGE", "accepted_quantity": "ACCEPTED_QTY", "rejected_quantity": "REJECTED_QTY",
}

MATERIALS = [
    ("MAT-100010", "Stainless bearing type A"), ("MAT-100020", "Hydraulic seal kit"),
    ("MAT-100030", "Control valve 2in"), ("MAT-100040", "Copper cable reel"),
    ("MAT-100050", "Industrial gearbox"), ("MAT-100060", "Steel plate 10mm"),
    ("MAT-100070", "Filter cartridge"), ("MAT-100080", "Sensor module"),
    ("MAT-100090", "Coupling flange"), ("MAT-100100", "Pump impeller"),
]
CURRENCIES = ["EUR", "EUR", "EUR", "USD", "GBP"]
PAYMENT_TERMS = ["NT30", "NT45", "NT60"]

SUPPLIER_PREFIXES = [
    "Nordwind", "Bluepeak", "Vertex", "Ravenna", "Kestrel", "Alpenrose", "Silverline", "Bramble",
    "Cobalt", "Driftwood", "Ember", "Fairmont", "Granite", "Harbourview", "Ironwood", "Juniper",
    "Larkspur", "Meridian", "Northgate", "Orchard", "Pinnacle", "Quarry", "Redstone", "Summit",
    "Thornbury", "Umbra", "Valemont", "Westford", "Yarrow", "Zenith",
]
SUPPLIER_SUFFIXES = [
    "Industrie GmbH", "Supply Ltd", "Components SA", "Trading BV", "Manufacturing AG",
    "Technologies Oy", "Materials SpA", "Logistics AS", "Systems Inc",
]


@dataclass
class Scenario:
    """One deliberately placed, documented anchor."""

    scenario_id: str
    rule_id: str
    name: str
    invoice_numbers: list[str]
    description: str
    expects: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "rule_id": self.rule_id,
            "name": self.name,
            "invoice_numbers": self.invoice_numbers,
            "description": self.description,
            "expects": self.expects,
        }


class InvoiceSampleGenerator:
    """Builds the demo invoice / PO / GR datasets and the scenario manifest."""

    def __init__(self, seed: int = SEED) -> None:
        self.random = random.Random(seed)
        self.config = get_invoice_validator_config()
        self.invoices: list[dict[str, Any]] = []
        self.po_lines: list[dict[str, Any]] = []
        self.goods_receipts: list[dict[str, Any]] = []
        self.scenarios: list[Scenario] = []
        self.suppliers = self._build_suppliers()
        self._po_seq = 0
        self._gr_seq = 0

    def _build_suppliers(self) -> list[tuple[str, str]]:
        suppliers = []
        for index, prefix in enumerate(SUPPLIER_PREFIXES):
            supplier_id = f"{700001 + index:010d}"
            name = f"{prefix} {self.random.choice(SUPPLIER_SUFFIXES)}"
            suppliers.append((supplier_id, name))
        return suppliers

    def _next_po(self, anchor: bool = False) -> str:
        self._po_seq += 1
        base = 4590000000 if anchor else 4500000000
        return str(base + self._po_seq)

    def _next_gr(self, anchor: bool = False) -> str:
        self._gr_seq += 1
        base = 5090000000 if anchor else 5000000000
        return str(base + self._gr_seq)

    # ------------------------------------------------------------------
    # Building blocks
    # ------------------------------------------------------------------
    def _emit_match(
        self,
        *,
        invoice_number: str,
        supplier: tuple[str, str],
        quantity: float,
        unit_price: float,
        currency: str,
        payment_terms: str,
        order_date: date,
        receipt_date: date | None,
        invoice_date: date,
        material: tuple[str, str],
        po_status: str = "Open",
        received: float | None = None,
        accepted: float | None = None,
        rejected: float = 0.0,
        invoice_overrides: dict[str, Any] | None = None,
        po_number: str | None = None,
        anchor: bool = False,
        emit_po: bool = True,
        emit_gr: bool = True,
    ) -> dict[str, Any]:
        """Emit a matched PO line, goods receipt and invoice; return the invoice."""
        supplier_id, supplier_name = supplier
        po_number = po_number or self._next_po(anchor)
        po_item = "00010"
        subtotal = round(quantity * unit_price, 2)
        tax = round(subtotal * TAX_RATE, 2)
        freight = round(min(subtotal * 0.02, 120.0), 2)
        total = round(subtotal + tax + freight, 2)
        gr_number = self._next_gr(anchor) if emit_gr else None

        if emit_po:
            self.po_lines.append({
                "po_number": po_number, "po_item": po_item, "supplier_id": supplier_id,
                "supplier_name": supplier_name, "material": material[0],
                "material_description": material[1], "quantity": quantity, "unit_price": unit_price,
                "currency": currency, "payment_terms": payment_terms,
                "order_date": order_date.isoformat(), "po_status": po_status,
            })
        if emit_gr and receipt_date is not None:
            received = quantity if received is None else received
            accepted = received - rejected if accepted is None else accepted
            self.goods_receipts.append({
                "gr_number": gr_number, "po_number": po_number, "po_item": po_item,
                "receipt_date": receipt_date.isoformat(), "received_quantity": received,
                "accepted_quantity": accepted, "rejected_quantity": rejected,
            })

        invoice = {
            "invoice_number": invoice_number, "supplier_id": supplier_id,
            "supplier_name": supplier_name, "po_number": po_number, "po_item": po_item,
            "invoice_date": invoice_date.isoformat(),
            "posting_date": (invoice_date + timedelta(days=1)).isoformat(),
            "quantity": quantity, "unit_price": unit_price, "subtotal": subtotal, "tax": tax,
            "freight": freight, "currency": currency, "total_amount": total,
            "payment_terms": payment_terms, "gr_reference": gr_number,
        }
        if invoice_overrides:
            invoice.update(invoice_overrides)
        self.invoices.append(invoice)
        return invoice

    # ------------------------------------------------------------------
    # Clean population
    # ------------------------------------------------------------------
    def build_clean(self) -> None:
        for index in range(CLEAN_COUNT):
            supplier = self.suppliers[index % len(self.suppliers)]
            material = MATERIALS[index % len(MATERIALS)]
            currency = self.random.choice(CURRENCIES)
            quantity = float(self.random.randint(1, 60))
            # Distinct unit prices (cents vary with the index) keep every total unique,
            # so clean invoices never collide into a false duplicate.
            unit_price = round(self.random.uniform(40.0, 600.0) + (index % 97) * 0.01, 2)
            order_date = date(2026, 1, 1) + timedelta(days=self.random.randint(0, 130))
            receipt_date = order_date + timedelta(days=self.random.randint(3, 15))
            invoice_date = receipt_date + timedelta(days=self.random.randint(1, 18))
            self._emit_match(
                invoice_number=f"INV-2026-{index + 1:05d}",
                supplier=supplier, quantity=quantity, unit_price=unit_price, currency=currency,
                payment_terms=self.random.choice(PAYMENT_TERMS), order_date=order_date,
                receipt_date=receipt_date, invoice_date=invoice_date, material=material,
            )

    # ------------------------------------------------------------------
    # Anchors - one per rule
    # ------------------------------------------------------------------
    def build_anchors(self) -> None:
        supplier = self.suppliers[0]
        supplier_b = self.suppliers[1]
        material = MATERIALS[0]
        o = date(2026, 3, 1)          # a common order date
        r = date(2026, 3, 10)         # a common receipt date
        d = date(2026, 3, 20)         # a common invoice date

        # IV-R001 duplicate invoices: two invoices, same supplier/amount/date, distinct clean POs.
        self._emit_match(invoice_number="INV-ANOM-01A", supplier=supplier, quantity=10, unit_price=100.0,
                         currency="EUR", payment_terms="NT30", order_date=o, receipt_date=r,
                         invoice_date=d, material=material, anchor=True)
        self._emit_match(invoice_number="INV-ANOM-01B", supplier=supplier, quantity=10, unit_price=100.0,
                         currency="EUR", payment_terms="NT30", order_date=o, receipt_date=r,
                         invoice_date=d, material=material, anchor=True)
        self._scenario("IV-R001", "Duplicate invoices", ["INV-ANOM-01B"],
                       "Two invoices from the same supplier for 1,210.00 EUR on the same date, against "
                       "different purchase orders.",
                       "The second invoice is flagged as a duplicate (double-payment risk).")

        # IV-R002 duplicate invoice number: same number, same supplier, different POs, amounts, dates.
        self._emit_match(invoice_number="INV-ANOM-02", supplier=supplier, quantity=5, unit_price=80.0,
                         currency="EUR", payment_terms="NT30", order_date=o, receipt_date=r,
                         invoice_date=date(2026, 3, 15), material=material, anchor=True)
        self._emit_match(invoice_number="INV-ANOM-02", supplier=supplier, quantity=7, unit_price=120.0,
                         currency="EUR", payment_terms="NT30", order_date=o, receipt_date=r,
                         invoice_date=date(2026, 4, 2), material=material, anchor=True)
        self._scenario("IV-R002", "Duplicate invoice number for a supplier", ["INV-ANOM-02"],
                       "Invoice number INV-ANOM-02 is used on two different invoices from the same supplier.",
                       "The second use of the invoice number is flagged.")

        # IV-R003 missing PO: references a PO that is not in the PO file, no GR.
        self._emit_match(invoice_number="INV-ANOM-03", supplier=supplier, quantity=4, unit_price=90.0,
                         currency="EUR", payment_terms="NT30", order_date=o, receipt_date=None,
                         invoice_date=d, material=material, po_number="4599999999",
                         emit_po=False, emit_gr=False, anchor=True)
        self._scenario("IV-R003", "Missing purchase order", ["INV-ANOM-03"],
                       "Invoice references purchase order 4599999999, which is absent from the PO file.",
                       "Flagged as a missing purchase order.")

        # IV-R004 missing GR: PO exists, no goods receipt.
        self._emit_match(invoice_number="INV-ANOM-04", supplier=supplier, quantity=6, unit_price=110.0,
                         currency="EUR", payment_terms="NT30", order_date=o, receipt_date=None,
                         invoice_date=d, material=material, emit_gr=False, anchor=True)
        self._scenario("IV-R004", "Missing goods receipt", ["INV-ANOM-04"],
                       "Invoice matches a purchase order but no goods receipt exists for the line.",
                       "Flagged as a missing goods receipt.")

        # IV-R005 price mismatch: invoiced 130 vs PO 100.
        self._emit_match(invoice_number="INV-ANOM-05", supplier=supplier, quantity=10, unit_price=100.0,
                         currency="EUR", payment_terms="NT30", order_date=o, receipt_date=r,
                         invoice_date=d, material=material, anchor=True,
                         invoice_overrides=self._reprice(10, 130.0))
        self._scenario("IV-R005", "Price mismatch", ["INV-ANOM-05"],
                       "Invoiced unit price 130 against a purchase-order price of 100.",
                       "Flagged as a price mismatch beyond the price tolerance.")

        # IV-R006 quantity mismatch: invoiced 8 vs received 10 (under-billed).
        self._emit_match(invoice_number="INV-ANOM-06", supplier=supplier, quantity=10, unit_price=100.0,
                         currency="EUR", payment_terms="NT30", order_date=o, receipt_date=r,
                         invoice_date=d, material=material, anchor=True,
                         invoice_overrides=self._reprice(8, 100.0))
        self._scenario("IV-R006", "Quantity mismatch", ["INV-ANOM-06"],
                       "Invoiced quantity 8 against a received quantity of 10.",
                       "Flagged as a quantity mismatch versus the receipt.")

        # IV-R007 tax mismatch: tax 250 where 19% of 1000 is 190.
        self._emit_match(invoice_number="INV-ANOM-07", supplier=supplier, quantity=10, unit_price=100.0,
                         currency="EUR", payment_terms="NT30", order_date=o, receipt_date=r,
                         invoice_date=d, material=material, anchor=True,
                         invoice_overrides={"tax": 250.0, "total_amount": round(1000 + 250 + 20.0, 2)})
        self._scenario("IV-R007", "Tax mismatch", ["INV-ANOM-07"],
                       "Tax charged is 250 where 19% of the 1,000 net amount is 190.",
                       "Flagged as a tax mismatch.")

        # IV-R008 currency mismatch: invoice USD, PO EUR.
        self._emit_match(invoice_number="INV-ANOM-08", supplier=supplier, quantity=10, unit_price=100.0,
                         currency="EUR", payment_terms="NT30", order_date=o, receipt_date=r,
                         invoice_date=d, material=material, anchor=True,
                         invoice_overrides={"currency": "USD"})
        self._scenario("IV-R008", "Currency mismatch", ["INV-ANOM-08"],
                       "Invoice is in USD while the purchase order is in EUR.",
                       "Flagged as a currency mismatch.")

        # IV-R009 supplier mismatch: invoice supplier differs from PO supplier.
        self._emit_match(invoice_number="INV-ANOM-09", supplier=supplier, quantity=10, unit_price=100.0,
                         currency="EUR", payment_terms="NT30", order_date=o, receipt_date=r,
                         invoice_date=d, material=material, anchor=True,
                         invoice_overrides={"supplier_id": supplier_b[0], "supplier_name": supplier_b[1]})
        self._scenario("IV-R009", "Supplier mismatch", ["INV-ANOM-09"],
                       "The invoicing supplier differs from the supplier on the purchase order.",
                       "Flagged as a supplier mismatch.")

        # IV-R010 freight mismatch: freight 900 well above the policy ceiling.
        self._emit_match(invoice_number="INV-ANOM-10", supplier=supplier, quantity=10, unit_price=100.0,
                         currency="EUR", payment_terms="NT30", order_date=o, receipt_date=r,
                         invoice_date=d, material=material, anchor=True,
                         invoice_overrides={"freight": 900.0, "total_amount": round(1000 + 190 + 900.0, 2)})
        self._scenario("IV-R010", "Freight mismatch", ["INV-ANOM-10"],
                       "Freight of 900 on a 1,000 net invoice, above the freight policy ceiling.",
                       "Flagged as a freight mismatch.")

        # IV-R011 payment-term mismatch: invoice NT60 vs PO NT30 (own dates to avoid an
        # incidental duplicate collision with the other 1,210 EUR anchors).
        self._emit_match(invoice_number="INV-ANOM-11", supplier=supplier, quantity=10, unit_price=100.0,
                         currency="EUR", payment_terms="NT30", order_date=date(2026, 1, 15),
                         receipt_date=date(2026, 1, 22), invoice_date=date(2026, 2, 5),
                         material=material, anchor=True,
                         invoice_overrides={"payment_terms": "NT60"})
        self._scenario("IV-R011", "Payment-term mismatch", ["INV-ANOM-11"],
                       "Invoice states NT60 while the purchase order agreed NT30.",
                       "Flagged as a payment-term mismatch.")

        # IV-R012 three-way match: 3 of 10 rejected (accepted 7), invoiced 10.
        self._emit_match(invoice_number="INV-ANOM-12", supplier=supplier, quantity=10, unit_price=100.0,
                         currency="EUR", payment_terms="NT30", order_date=date(2026, 1, 16),
                         receipt_date=date(2026, 1, 23), invoice_date=date(2026, 2, 6),
                         material=material, anchor=True, received=10.0, accepted=7.0, rejected=3.0)
        self._scenario("IV-R012", "Three-way-match exception", ["INV-ANOM-12"],
                       "Invoiced 10 units but only 7 were accepted at goods receipt (3 rejected).",
                       "Flagged as a three-way-match exception (billed above accepted quantity).")

        # IV-R013 overbilling: two invoices of 10 against an ordered quantity of 10.
        over_po = self._next_po(anchor=True)
        self._emit_match(invoice_number="INV-ANOM-13A", supplier=supplier, quantity=10, unit_price=100.0,
                         currency="EUR", payment_terms="NT30", order_date=o, receipt_date=r,
                         invoice_date=date(2026, 3, 12), material=material, po_number=over_po, anchor=True)
        self._emit_match(invoice_number="INV-ANOM-13B", supplier=supplier, quantity=10, unit_price=100.0,
                         currency="EUR", payment_terms="NT30", order_date=o, receipt_date=None,
                         invoice_date=date(2026, 3, 26), material=material, po_number=over_po,
                         emit_po=False, emit_gr=False, anchor=True)
        self._scenario("IV-R013", "Overbilling", ["INV-ANOM-13B"],
                       "Two invoices of 10 units are booked against a purchase-order line ordered for 10.",
                       "The second invoice pushes cumulative invoicing above the ordered quantity and is flagged.")

        # IV-R014 invoice before PO: invoice dated before the order; receipt earlier still (isolates R014).
        self._emit_match(invoice_number="INV-ANOM-14", supplier=supplier, quantity=10, unit_price=100.0,
                         currency="EUR", payment_terms="NT30", order_date=date(2026, 4, 1),
                         receipt_date=date(2026, 3, 10), invoice_date=date(2026, 3, 18),
                         material=material, anchor=True)
        self._scenario("IV-R014", "Invoice before purchase order", ["INV-ANOM-14"],
                       "Invoice dated 2026-03-20, before its purchase order was raised on 2026-04-01.",
                       "Flagged as an invoice dated before the purchase order.")

        # IV-R015 invoice before receipt: invoice after PO but before the goods receipt.
        self._emit_match(invoice_number="INV-ANOM-15", supplier=supplier, quantity=10, unit_price=100.0,
                         currency="EUR", payment_terms="NT30", order_date=date(2026, 3, 1),
                         receipt_date=date(2026, 3, 25), invoice_date=date(2026, 3, 10),
                         material=material, anchor=True)
        self._scenario("IV-R015", "Invoice before goods receipt", ["INV-ANOM-15"],
                       "Invoice dated 2026-03-10, before the goods were received on 2026-03-25.",
                       "Flagged as an invoice dated before the goods receipt.")

        # IV-R016 future invoice date: dated after the validation reference date.
        self._emit_match(invoice_number="INV-ANOM-16", supplier=supplier, quantity=10, unit_price=100.0,
                         currency="EUR", payment_terms="NT30", order_date=date(2026, 5, 1),
                         receipt_date=date(2026, 5, 10), invoice_date=date(2026, 9, 15),
                         material=material, anchor=True)
        self._scenario("IV-R016", "Future invoice date", ["INV-ANOM-16"],
                       f"Invoice dated 2026-09-15, after the validation reference date {AS_OF_DATE}.",
                       "Flagged as a future invoice date.")

        # IV-R017 closed PO invoicing: invoice against a PO line flagged closed.
        self._emit_match(invoice_number="INV-ANOM-17", supplier=supplier, quantity=10, unit_price=100.0,
                         currency="EUR", payment_terms="NT30", order_date=date(2026, 1, 17),
                         receipt_date=date(2026, 1, 24), invoice_date=date(2026, 2, 7),
                         material=material, po_status="Closed", anchor=True)
        self._scenario("IV-R017", "Closed purchase-order invoicing", ["INV-ANOM-17"],
                       "Invoice booked against a purchase-order line flagged 'Closed'.",
                       "Flagged as invoicing against a closed purchase order.")

    @staticmethod
    def _reprice(quantity: float, unit_price: float) -> dict[str, Any]:
        """Override an invoice's quantity/price and keep its amounts internally consistent."""
        subtotal = round(quantity * unit_price, 2)
        tax = round(subtotal * TAX_RATE, 2)
        freight = round(min(subtotal * 0.02, 120.0), 2)
        return {
            "quantity": quantity, "unit_price": unit_price, "subtotal": subtotal, "tax": tax,
            "freight": freight, "total_amount": round(subtotal + tax + freight, 2),
        }

    def _scenario(
        self, rule_id: str, name: str, invoice_numbers: list[str], description: str, expects: str
    ) -> None:
        self.scenarios.append(
            Scenario(f"IV-S{len(self.scenarios) + 1:02d}", rule_id, name, invoice_numbers, description, expects)
        )

    # ------------------------------------------------------------------
    def build(self) -> None:
        self.build_clean()
        self.build_anchors()

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------
    def write(self, output_dir: Path) -> dict[str, Any]:
        output_dir.mkdir(parents=True, exist_ok=True)
        self._write_dataset(
            output_dir, "sample_invoices", self.invoices, list(INVOICE_CANONICAL_FIELDS),
            INVOICE_HEADERS, {n: INVOICE_REGISTRY.label(n) for n in INVOICE_CANONICAL_FIELDS}, "Invoices",
        )
        self._write_dataset(
            output_dir, "sample_invoice_purchase_orders", self.po_lines, list(PO_COLS),
            PO_HEADERS, {n: PO_REGISTRY.label(n) for n in PO_COLS}, "Purchase Orders",
        )
        self._write_dataset(
            output_dir, "sample_goods_receipts", self.goods_receipts, list(GOODS_RECEIPT_CANONICAL_FIELDS),
            GR_HEADERS, {n: GOODS_RECEIPT_REGISTRY.label(n) for n in GOODS_RECEIPT_CANONICAL_FIELDS},
            "Goods Receipts",
        )

        manifest = {
            "generated_with_seed": SEED,
            "data_origin": "demo_data",
            "as_of_date": AS_OF_DATE,
            "invoice_count": len(self.invoices),
            "purchase_order_line_count": len(self.po_lines),
            "goods_receipt_count": len(self.goods_receipts),
            "note": (
                "Fictional invoice, purchase order and goods receipt datasets. Most invoices match "
                "their PO and goods receipt cleanly and raise no exception; the anchor invoices below "
                "are placed deliberately, one per rule, so every documented exception is testable "
                f"against the fixed reference date {AS_OF_DATE}."
            ),
            "scenarios": [scenario.to_dict() for scenario in self.scenarios],
        }
        (output_dir / "invoice_scenario_manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (output_dir / "INVOICE_SCENARIO_MANIFEST.md").write_text(
            _manifest_markdown(manifest), encoding="utf-8"
        )
        return {
            "invoices": len(self.invoices),
            "purchase_order_lines": len(self.po_lines),
            "goods_receipts": len(self.goods_receipts),
            "scenarios": len(self.scenarios),
        }

    def _write_dataset(
        self, output_dir: Path, stem: str, rows: list[dict[str, Any]], columns: list[str],
        technical: dict[str, str], labels: dict[str, str], sheet_name: str,
    ) -> None:
        frame = pd.DataFrame([{c: row.get(c) for c in columns} for row in rows])[columns]
        frame.rename(columns=technical).to_csv(output_dir / f"{stem}.csv", index=False)
        frame.rename(columns=labels).to_excel(
            output_dir / f"{stem}.xlsx", index=False, sheet_name=sheet_name
        )
        records = json.loads(frame.to_json(orient="records"))
        (output_dir / f"{stem}.json").write_text(
            json.dumps({"records": records}, indent=2, ensure_ascii=False), encoding="utf-8"
        )


# ---------------------------------------------------------------------------
# Baseline
# ---------------------------------------------------------------------------
def write_observed_baseline(output_dir: Path) -> dict[str, Any]:
    """Run the engine over the written files and record the result.

    The datasets are read back from the written CSVs through the real reader and
    normalisers, so the baseline is exactly what the API produces - not an
    in-memory shortcut that could drift from the files the API actually parses.
    """
    from app.modules.invoice_validator.engine import InvoiceValidationEngine
    from app.modules.invoice_validator.normalizer import (
        normalize_goods_receipt_dataframe,
        normalize_invoice_dataframe,
        normalize_po_dataframe,
    )
    from app.services.files.readers import read_tabular
    from app.services.tabular.mapping import suggest_mapping

    config = get_invoice_validator_config()

    def _load(stem: str, registry, normalize):
        content = (output_dir / f"{stem}.csv").read_bytes()
        read_result = read_tabular(content, ".csv")
        mapping = suggest_mapping(read_result.source_columns, registry).mapping
        return normalize(read_result.dataframe, mapping, config).records

    invoices = _load("sample_invoices", INVOICE_REGISTRY, normalize_invoice_dataframe)
    po_lines = _load("sample_invoice_purchase_orders", PO_REGISTRY, normalize_po_dataframe)
    receipts = _load("sample_goods_receipts", GOODS_RECEIPT_REGISTRY, normalize_goods_receipt_dataframe)

    result = InvoiceValidationEngine(config).run(
        invoices, po_lines, receipts, as_of_date=date.fromisoformat(AS_OF_DATE)
    )

    rules_hit = sorted({e.rule_id for e in result.exceptions})
    flagged_invoices = sorted({e.invoice_number for e in result.exceptions if e.invoice_number})
    baseline = {
        "note": (
            "Observed output of the current engine on the generated datasets with default tolerances "
            f"and the reference date {AS_OF_DATE}. Used by the test suite to detect unintended changes."
        ),
        "seed": SEED,
        "as_of_date": AS_OF_DATE,
        "config_version": result.config_version,
        "engine_version": result.engine_version,
        "invoice_count": result.summary["invoice_count"],
        "purchase_order_line_count": result.summary["purchase_order_line_count"],
        "goods_receipt_count": result.summary["goods_receipt_count"],
        "exceptions_count": result.summary["exceptions_count"],
        "severity_counts": result.summary["severity_counts"],
        "rule_counts": {entry["rule_id"]: entry["count"] for entry in result.summary["rule_counts"]},
        "rules_hit": rules_hit,
        "flagged_invoice_numbers": flagged_invoices,
    }
    (output_dir / "expected_invoice_baseline.json").write_text(
        json.dumps(baseline, indent=2, default=str), encoding="utf-8"
    )
    return baseline


def _manifest_markdown(manifest: dict[str, Any]) -> str:
    lines = [
        "# Invoice validator sample data - scenario manifest",
        "",
        "**Origin: demo data.** These datasets are fictional. They were generated by "
        "`scripts/generate_invoice_sample_data.py` and do not come from any SAP system or real "
        "company.",
        "",
        f"- Invoices: {manifest['invoice_count']:,}",
        f"- Purchase order lines: {manifest['purchase_order_line_count']:,}",
        f"- Goods receipts: {manifest['goods_receipt_count']:,}",
        f"- Reference date (for the future-invoice-date check): `{manifest['as_of_date']}`",
        f"- Random seed: `{manifest['generated_with_seed']}` (regenerating reproduces the identical data)",
        "",
        "Most invoices match their purchase order and goods receipt cleanly and raise no exception. "
        "The anchor invoices below are placed deliberately, one per rule, so each exception is testable.",
        "",
        "## Anchor invoices",
        "",
    ]
    for scenario in manifest["scenarios"]:
        lines.extend([
            f"### {scenario['scenario_id']} - {scenario['rule_id']} {scenario['name']}",
            "",
            f"- Invoice(s): {', '.join(f'`{n}`' for n in scenario['invoice_numbers'])}",
            f"- {scenario['description']}",
            f"- **Expected effect:** {scenario['expects']}",
            "",
        ])
    lines.extend([
        "## How the test suite uses this file",
        "",
        "`tests/integration/test_invoice_sample_data.py` uploads the three datasets, validates them "
        f"with the reference date `{manifest['as_of_date']}`, and asserts that each anchor rule is "
        "detected, that the run reproduces `expected_invoice_baseline.json`, and that repeated runs "
        "are identical.",
        "",
        "## A note on the figures",
        "",
        "Exceptions are produced by the deterministic engine in `app/modules/invoice_validator`. "
        "Difference amounts are indicative and describe the uploaded files only; nothing here has "
        "been validated in a live SAP environment.",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    generator = InvoiceSampleGenerator()
    generator.build()
    stats = generator.write(settings.sample_dir)
    baseline = write_observed_baseline(settings.sample_dir)

    logger.info(
        "Generated %d invoices, %d PO lines, %d goods receipts, %d scenarios",
        stats["invoices"], stats["purchase_order_lines"], stats["goods_receipts"], stats["scenarios"],
    )
    print(json.dumps(stats, indent=2))
    print(
        f"baseline: {baseline['exceptions_count']} exceptions over "
        f"{baseline['invoice_count']} invoices | rules hit: {', '.join(baseline['rules_hit'])}"
    )
    print(f"flagged invoices: {baseline['flagged_invoice_numbers']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
