"""Generate the fictional supplier risk data set for the Supplier Risk Copilot.

Run with::

    python scripts/generate_supplier_risk_sample_data.py

Outputs (into ``data/sample/``):

* ``sample_supplier_risk_profiles.csv``   - SAP technical / master-data column names
* ``sample_supplier_risk_profiles.xlsx``  - business labels
* ``sample_supplier_risk_profiles.json``  - canonical snake_case names
* ``sample_supplier_risk_events.csv``     - dated internal records, technical names
* ``sample_supplier_risk_events.xlsx``    - dated internal records, business labels
* ``sample_supplier_risk_events.json``    - dated internal records, canonical names
* ``supplier_risk_scenario_manifest.json`` / ``SUPPLIER_RISK_SCENARIO_MANIFEST.md``
* ``expected_supplier_risk_baseline.json`` - what the current engine produces

**The data is entirely fictional.** Supplier names, countries, contract numbers,
credit scores, audit outcomes and every internal record were invented for this
lab. Nothing comes from an SAP system, a credit bureau, an ESG rating service or
a real company, and no external service is contacted at any point.

Design principle: most suppliers are ordinary, well-behaved vendors whose
overall risk lands in the low or medium band. Nine *anchor* suppliers are placed
deliberately - one per testable behaviour of the risk model - so every claim in
the manifest can be asserted by the test suite.

The supplier id range (``0000300001``..``0000300055``) is deliberately the same
range module 3's recommendation catalogue uses, so the lab assesses the risk of
the same fictional suppliers it recommends.
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
from app.modules.supplier_risk.engine import run_risk_assessment  # noqa: E402
from app.modules.supplier_risk.field_definitions import (  # noqa: E402
    CANONICAL_FIELDS,
    EVENT_CANONICAL_FIELDS,
    EVENT_REGISTRY,
    LIST_FIELDS,
    REGISTRY,
)
from app.modules.supplier_risk.normalizer import (  # noqa: E402
    normalize_risk_event_dataframe,
    normalize_supplier_risk_dataframe,
)
from app.modules.supplier_risk.thresholds import get_supplier_risk_config  # noqa: E402
from app.services.files.readers import read_tabular  # noqa: E402
from app.services.tabular.mapping import suggest_mapping  # noqa: E402

logger = get_logger("generate_supplier_risk_sample_data")

SEED = 20260801
TOTAL_SUPPLIERS = 55

#: Reference date every day-count in the data set is measured against.
AS_OF_DATE = date(2026, 7, 1)

#: CSV uses master-data technical names, the way an SAP extract arrives.
TECHNICAL_HEADERS: dict[str, str] = {
    "supplier_id": "LIFNR",
    "supplier_name": "NAME1",
    "materials_supplied": "MATERIALS_SUPPLIED",
    "plants_served": "PLANTS_SERVED",
    "regions_served": "REGIONS_SERVED",
    "unit_price": "NETPR",
    "currency": "WAERS",
    "lead_time_days": "PLIFZ",
    "available_capacity": "AVAILABLE_CAPACITY",
    "on_time_delivery_rate": "OTD",
    "quality_score": "QUALITY_SCORE",
    "defect_rate": "DEFECT_RATE",
    "risk_score": "RISK_SCORE",
    "esg_score": "ESG_SCORE",
    "contract_status": "CONTRACT_STATUS",
    "contract_expiration": "CONTRACT_EXPIRATION",
    "payment_terms": "ZTERM",
    "historical_order_count": "ORDER_COUNT",
    "historical_spend": "HISTORICAL_SPEND",
    "country": "LAND1",
    "spend_category": "SPEND_CATEGORY",
    "open_purchase_order_count": "OPEN_PO_COUNT",
    "active_contract_count": "ACTIVE_CONTRACTS",
    "contract_number": "KONNR",
    "delivery_count": "DELIVERY_COUNT",
    "late_delivery_count": "LATE_DELIVERY_COUNT",
    "average_delay_days": "AVG_DELAY_DAYS",
    "quality_incident_count": "QUALITY_INCIDENTS",
    "invoice_count": "INVOICE_COUNT",
    "invoice_exception_count": "INVOICE_EXCEPTIONS",
    "disputed_invoice_count": "DISPUTED_INVOICES",
    "credit_score": "CREDIT_SCORE",
    "days_payable_outstanding": "DPO",
    "payment_default_count": "PAYMENT_DEFAULTS",
    "financial_distress_flag": "FINANCIAL_DISTRESS",
    "category_spend_share": "CATEGORY_SPEND_SHARE",
    "single_source_material_count": "SINGLE_SOURCE_MATERIALS",
    "compliance_finding_count": "COMPLIANCE_FINDINGS",
    "certification_status": "CERTIFICATION_STATUS",
    "audit_status": "AUDIT_STATUS",
    "last_audit_date": "LAST_AUDIT_DATE",
    "capacity_utilization": "CAPACITY_UTILIZATION",
    "lead_time_variability_days": "LEAD_TIME_VARIABILITY",
    "alternative_supplier_count": "ALTERNATIVE_SUPPLIERS",
}

#: CSV headers for the dated internal records.
EVENT_TECHNICAL_HEADERS: dict[str, str] = {
    "event_id": "EVENT_ID",
    "supplier_id": "LIFNR",
    "event_type": "EVENT_TYPE",
    "event_date": "BUDAT",
    "reference": "REFERENCE",
    "severity": "SEVERITY",
    "description": "DESCRIPTION",
    "amount": "WRBTR",
    "currency": "WAERS",
}

#: The six internal record types the copilot understands.
EVENT_TYPES: tuple[str, ...] = (
    "late_delivery",
    "quality_incident",
    "invoice_exception",
    "compliance_finding",
    "contract_event",
    "payment_default",
)

MATERIALS = [f"MAT-{1000 + i * 10}" for i in range(12)]
REGIONS = ["EU", "NA", "APAC", "LATAM"]
PLANTS = ["1010", "1020", "2010", "3010", "4010"]
PAYMENT_TERMS = ["NT30", "NT45", "NT60", "Z030", "Z045"]

#: Procurement categories. Every anchor shares its category with several
#: ordinary suppliers so ``find_alternatives`` has somewhere to look.
SPEND_CATEGORIES = [
    "Electronic Components",
    "Mechanical Parts",
    "Raw Materials",
    "Packaging",
    "Logistics Services",
    "MRO Supplies",
    "Specialty Chemicals",
    "IT Hardware",
]

#: Countries used for the ordinary population. All of them sit in the low half
#: of the configured country risk index, so no background supplier can out-score
#: an anchor on geographic risk by accident.
BACKGROUND_COUNTRIES = ["DE", "AT", "CH", "NL", "BE", "FR", "SE", "DK", "FI", "IE",
                        "IT", "ES", "PT", "PL", "CZ", "GB", "US", "CA", "JP"]

BACKGROUND_CURRENCIES = ["EUR", "EUR", "EUR", "USD", "GBP", "CHF"]

SUPPLIER_PREFIXES = [
    "Nordwind", "Bluepeak", "Vertex", "Ravenna", "Kestrel", "Alpenrose", "Silverline", "Bramble",
    "Cobalt", "Driftwood", "Ember", "Fairmont", "Granite", "Harbourview", "Ironwood", "Juniper",
    "Larkspur", "Meridian", "Northgate", "Orchard", "Pinnacle", "Quarry", "Redstone", "Summit",
    "Thornbury", "Umbra", "Valemont", "Westford", "Yarrow", "Zenith", "Ashford", "Belmont",
    "Cresthill", "Dunmore", "Eastvale", "Foxglove", "Glenmore", "Hollowbrook", "Inverness",
    "Kingsley", "Lakeshore", "Milbrook", "Norwood", "Oakfield", "Pemberton", "Ridgeway",
    "Stonebridge", "Tallowood", "Ullswater", "Vinemount", "Whitfield", "Yardley", "Zephyr",
    "Alderford", "Bexley", "Clearwater",
]
SUPPLIER_SUFFIXES = [
    "Industrie GmbH", "Supply Ltd", "Components SA", "Trading BV", "Manufacturing AG",
    "Technologies Oy", "Materials SpA", "Engineering Sp. z o.o.", "Logistics AS", "Systems Inc",
]

#: Background suppliers (by row index) whose contract falls inside the 90-day
#: reporting window but outside the 30-day critical window, so the
#: "contracts expiring soon" list has company without stealing SRK-06's anchor.
BACKGROUND_EXPIRING: dict[int, int] = {17: 55, 34: 78}


@dataclass
class Scenario:
    """One deliberately placed, documented anchor supplier."""

    scenario_id: str
    name: str
    supplier_id: str
    category: str
    description: str
    expects: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "name": self.name,
            "supplier_id": self.supplier_id,
            "category": self.category,
            "description": self.description,
            "expects": self.expects,
        }


class SupplierRiskSampleGenerator:
    """Builds the demo supplier risk profiles, their internal records and the manifest."""

    def __init__(self, seed: int = SEED, as_of: date = AS_OF_DATE) -> None:
        self.random = random.Random(seed)
        self.as_of = as_of
        self.config = get_supplier_risk_config()
        self.rows: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self.scenarios: list[Scenario] = []
        self._event_sequence = 0

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _supplier_id(self, index: int) -> str:
        return f"{300001 + index:010d}"

    def _name(self, index: int) -> str:
        prefix = SUPPLIER_PREFIXES[index % len(SUPPLIER_PREFIXES)]
        return f"{prefix} {self.random.choice(SUPPLIER_SUFFIXES)}"

    def _days_out(self, days: int) -> str:
        return (self.as_of + timedelta(days=days)).isoformat()

    def _days_ago(self, days: int) -> str:
        return (self.as_of - timedelta(days=days)).isoformat()

    def _blank_row(self, index: int) -> dict[str, Any]:
        """Every canonical field present and empty - the shape the CSV needs."""
        row: dict[str, Any] = dict.fromkeys(CANONICAL_FIELDS)
        row["supplier_id"] = self._supplier_id(index)
        for name in LIST_FIELDS:
            row[name] = []
        return row

    # ------------------------------------------------------------------
    # the ordinary population
    # ------------------------------------------------------------------
    def _background_row(self, index: int) -> dict[str, Any]:
        """An ordinary supplier.

        A single 0-1 "strain" draw shapes every metric, so a supplier is
        internally consistent - a vendor with a poor on-time rate also runs a
        higher defect rate - while every value stays inside a band that cannot
        reach an anchor's score.
        """
        rng = self.random
        strain = rng.random()
        row = self._blank_row(index)

        materials = sorted(rng.sample(MATERIALS, rng.randint(2, 4)))
        plants = sorted(set(["1010"] + rng.sample(PLANTS, rng.randint(1, 2))))
        regions = sorted(set(rng.sample(REGIONS, rng.randint(2, 3))))
        currency = rng.choice(BACKGROUND_CURRENCIES)

        on_time = round(99.0 - 8.0 * strain, 1)
        delivery_count = rng.randint(45, 220)
        late_share = (100.0 - on_time) / 100.0 * rng.uniform(0.9, 1.4)
        late_count = int(round(delivery_count * late_share))
        invoice_count = rng.randint(40, 260)
        exception_count = int(round(invoice_count * (0.005 + 0.06 * strain)))

        if strain < 0.60:
            contract_status = "Active"
        elif strain < 0.85:
            contract_status = "Expiring"
        else:
            contract_status = "Renewal due"

        expiry_days = BACKGROUND_EXPIRING.get(index, rng.randint(200, 1000))
        if index in BACKGROUND_EXPIRING:
            contract_status = "Expiring"

        certification = "Valid"
        if strain >= 0.90:
            certification = "Renewal due"
        elif strain >= 0.70:
            certification = "Expiring"

        audit = "Passed"
        if strain >= 0.90:
            audit = "Remediation"
        elif strain >= 0.65:
            audit = "Conditional"

        row.update(
            {
                "supplier_name": self._name(index),
                "materials_supplied": materials,
                "plants_served": plants,
                "regions_served": regions,
                "unit_price": round(rng.uniform(80.0, 420.0), 2),
                "currency": currency,
                "lead_time_days": int(round(9 + 26 * strain)),
                "available_capacity": float(rng.randint(400, 6000)),
                "on_time_delivery_rate": on_time,
                "quality_score": round(97.0 - 13.0 * strain, 1),
                "defect_rate": round(0.3 + 3.0 * strain + rng.uniform(0.0, 0.6), 2),
                # Module 3's stored master-data risk figure, not the computed risk.
                "risk_score": round(10.0 + 45.0 * strain, 1),
                "esg_score": round(90.0 - 28.0 * strain, 1),
                "contract_status": contract_status,
                "contract_expiration": self._days_out(expiry_days),
                "payment_terms": rng.choice(PAYMENT_TERMS),
                "historical_order_count": rng.randint(20, 320),
                "historical_spend": float(rng.randint(120_000, 3_400_000)),
                "country": rng.choice(BACKGROUND_COUNTRIES),
                "spend_category": SPEND_CATEGORIES[index % len(SPEND_CATEGORIES)],
                "open_purchase_order_count": rng.randint(0, 28),
                "active_contract_count": rng.randint(1, 4),
                "contract_number": f"46000{81000 + index:05d}",
                "delivery_count": delivery_count,
                "late_delivery_count": late_count,
                "average_delay_days": round(0.5 + 4.5 * strain + rng.uniform(0.0, 1.2), 1),
                "quality_incident_count": int(round(4 * strain + rng.uniform(0.0, 1.5))),
                "invoice_count": invoice_count,
                "invoice_exception_count": exception_count,
                "disputed_invoice_count": int(round(2.5 * strain)),
                "credit_score": round(92.0 - 26.0 * strain, 1),
                "days_payable_outstanding": round(30.0 + 34.0 * strain, 1),
                "payment_default_count": 1 if strain > 0.80 else 0,
                "financial_distress_flag": False,
                "category_spend_share": round(4.0 + 34.0 * strain, 1),
                "single_source_material_count": int(round(2.5 * strain)),
                "compliance_finding_count": int(round(2 * strain)),
                "certification_status": certification,
                "audit_status": audit,
                "last_audit_date": self._days_ago(rng.randint(40, 700)),
                "capacity_utilization": round(58.0 + 26.0 * strain, 1),
                "lead_time_variability_days": round(0.8 + 6.0 * strain, 1),
                "alternative_supplier_count": max(1, int(round(6 - 4 * strain))),
            }
        )
        return row

    # ------------------------------------------------------------------
    # the nine anchors
    # ------------------------------------------------------------------
    def _anchor_rows(self) -> list[dict[str, Any]]:
        """The nine deliberately-placed anchor suppliers, one per behaviour."""
        rows: list[dict[str, Any]] = []

        def anchor(index: int, **values: Any) -> dict[str, Any]:
            row = self._blank_row(index)
            row.update(values)
            rows.append(row)
            return row

        # -- SRK-01 highest overall risk: bad across the board, top of nothing.
        srk01 = anchor(
            0,
            supplier_name="Zephyr Continental Holdings AG",
            materials_supplied=["MAT-1000", "MAT-1010", "MAT-1020"],
            plants_served=["1010", "1020"],
            regions_served=["EU"],
            unit_price=240.0, currency="EUR", lead_time_days=52,
            available_capacity=2200.0, on_time_delivery_rate=74.0, quality_score=69.0,
            defect_rate=6.8, risk_score=88.0, esg_score=38.0,
            contract_status="Under negotiation", contract_expiration=self._days_out(198),
            payment_terms="NT60", historical_order_count=210, historical_spend=4_150_000.0,
            country="TR", spend_category="Electronic Components",
            open_purchase_order_count=31, active_contract_count=1, contract_number="4600008101",
            delivery_count=90, late_delivery_count=22, average_delay_days=12.0,
            quality_incident_count=8, invoice_count=120, invoice_exception_count=26,
            disputed_invoice_count=6, credit_score=40.0, days_payable_outstanding=78.0,
            payment_default_count=3, financial_distress_flag=True,
            category_spend_share=60.0, single_source_material_count=5,
            compliance_finding_count=4, certification_status="Expiring", audit_status="Overdue",
            last_audit_date=self._days_ago(477), capacity_utilization=94.0,
            lead_time_variability_days=12.0, alternative_supplier_count=1,
        )
        self.scenarios.append(Scenario(
            "SRK-01", "Highest overall risk supplier", srk01["supplier_id"], "overall",
            "Weak in almost every category at once: on-time rate 74%, quality score 69, credit "
            "score 40 with a financial distress flag, 60% of its category spend, an unresolved "
            "contract negotiation, a 21.7% invoice exception rate, four open compliance findings, "
            "ESG 38, a high-risk country and 94% capacity utilisation.",
            "Highest overall risk score in the data set, the only supplier in the 'critical' "
            "band, and the supplier reported as highest_risk_supplier_id. It also carries the "
            "highest geographic and operational risk. In each of the eight categories anchored "
            "below it is beaten by that category's specialist anchor, so it never wins a "
            "category ranking it is not meant to.",
        ))

        # -- SRK-02 delivery: worst on-time rate and the most late deliveries.
        srk02 = anchor(
            1,
            supplier_name="Ravenna Freight & Haulage Ltd",
            materials_supplied=["MAT-1030", "MAT-1040"],
            plants_served=["1010", "2010"], regions_served=["APAC", "EU"],
            unit_price=165.0, currency="EUR", lead_time_days=42,
            available_capacity=3100.0, on_time_delivery_rate=58.0, quality_score=88.0,
            defect_rate=2.4, risk_score=64.0, esg_score=70.0,
            contract_status="Active", contract_expiration=self._days_out(415),
            payment_terms="NT45", historical_order_count=180, historical_spend=1_950_000.0,
            country="VN", spend_category="Logistics Services",
            open_purchase_order_count=24, active_contract_count=2, contract_number="4600008102",
            delivery_count=140, late_delivery_count=68, average_delay_days=19.5,
            quality_incident_count=2, invoice_count=150, invoice_exception_count=9,
            disputed_invoice_count=1, credit_score=74.0, days_payable_outstanding=46.0,
            payment_default_count=0, financial_distress_flag=False,
            category_spend_share=22.0, single_source_material_count=1,
            compliance_finding_count=0, certification_status="Valid", audit_status="Passed",
            last_audit_date=self._days_ago(150), capacity_utilization=88.0,
            lead_time_variability_days=9.0, alternative_supplier_count=3,
        )
        self.scenarios.append(Scenario(
            "SRK-02", "Delivery risk anchor", srk02["supplier_id"], "delivery",
            "On-time delivery rate 58%, 68 of 140 deliveries late and an average delay of "
            "19.5 days - every delivery metric past its configured worst anchor.",
            "Highest delivery category score in the data set (100.0, 'critical' band) and the "
            "top of any delivery ranking. Its other categories stay ordinary.",
        ))

        # -- SRK-03 quality: worst defect rate and the most quality incidents.
        srk03 = anchor(
            2,
            supplier_name="Kestrel Precision Castings SpA",
            materials_supplied=["MAT-1050", "MAT-1060", "MAT-1070"],
            plants_served=["1010", "3010"], regions_served=["APAC"],
            unit_price=198.0, currency="EUR", lead_time_days=46,
            available_capacity=2600.0, on_time_delivery_rate=86.0, quality_score=61.0,
            defect_rate=9.4, risk_score=61.0, esg_score=52.0,
            contract_status="Active", contract_expiration=self._days_out(313),
            payment_terms="NT30", historical_order_count=145, historical_spend=1_420_000.0,
            country="CN", spend_category="Mechanical Parts",
            open_purchase_order_count=19, active_contract_count=1, contract_number="4600008103",
            delivery_count=110, late_delivery_count=19, average_delay_days=6.0,
            quality_incident_count=15, invoice_count=130, invoice_exception_count=20,
            disputed_invoice_count=3, credit_score=60.0, days_payable_outstanding=61.0,
            payment_default_count=1, financial_distress_flag=False,
            category_spend_share=40.0, single_source_material_count=3,
            compliance_finding_count=2, certification_status="Expiring",
            audit_status="Conditional",
            last_audit_date=self._days_ago(210), capacity_utilization=90.0,
            lead_time_variability_days=10.0, alternative_supplier_count=2,
        )
        self.scenarios.append(Scenario(
            "SRK-03", "Quality risk anchor", srk03["supplier_id"], "quality",
            "Quality score 61, defect rate 9.4% and 15 recorded quality incidents - every "
            "quality metric past its configured worst anchor.",
            "Highest quality category score in the data set (100.0, 'critical' band), which "
            "carries its overall risk into the 'high' band. No other category of this supplier "
            "tops a ranking.",
        ))

        # -- SRK-04 financial: low credit score, defaults, distress flag raised.
        srk04 = anchor(
            3,
            supplier_name="Bramble Iron & Alloys Ltda",
            materials_supplied=["MAT-1080", "MAT-1090"],
            plants_served=["1010"], regions_served=["LATAM"],
            unit_price=132.0, currency="USD", lead_time_days=44,
            available_capacity=4200.0, on_time_delivery_rate=85.0, quality_score=79.0,
            defect_rate=4.6, risk_score=72.0, esg_score=48.0,
            contract_status="Active", contract_expiration=self._days_out(260),
            payment_terms="NT60", historical_order_count=98, historical_spend=2_260_000.0,
            country="BR", spend_category="Raw Materials",
            open_purchase_order_count=12, active_contract_count=1, contract_number="4600008104",
            delivery_count=80, late_delivery_count=15, average_delay_days=6.5,
            quality_incident_count=5, invoice_count=90, invoice_exception_count=14,
            disputed_invoice_count=4, credit_score=26.0, days_payable_outstanding=96.0,
            payment_default_count=6, financial_distress_flag=True,
            category_spend_share=44.0, single_source_material_count=3,
            compliance_finding_count=2, certification_status="Expiring",
            audit_status="Conditional",
            last_audit_date=self._days_ago(320), capacity_utilization=89.0,
            lead_time_variability_days=9.5, alternative_supplier_count=2,
        )
        self.scenarios.append(Scenario(
            "SRK-04", "Financial risk anchor", srk04["supplier_id"], "financial",
            "Internally recorded credit score 26, six payment defaults and the financial "
            "distress flag set. No external credit feed is involved - these are stored "
            "internal figures.",
            "Highest financial category score in the data set (100.0, 'critical' band), a "
            "'critical'-priority finance action in its recommended actions, and an overall risk "
            "in the 'high' band.",
        ))

        # -- SRK-05 spend concentration: near-total dependence, no contract.
        srk05 = anchor(
            4,
            supplier_name="Cobalt Speciality Chemicals BV",
            materials_supplied=["MAT-1100", "MAT-1110"],
            plants_served=["1010", "1020"], regions_served=["EU", "NA"],
            unit_price=305.0, currency="EUR", lead_time_days=26,
            available_capacity=1500.0, on_time_delivery_rate=93.0, quality_score=90.0,
            defect_rate=1.6, risk_score=55.0, esg_score=72.0,
            # "No contract" is a real label. The bare word "None" would be read
            # back as a null by the file reader and the scenario would vanish.
            contract_status="No contract", contract_expiration=None,
            payment_terms="NT30", historical_order_count=260, historical_spend=3_800_000.0,
            country="DE", spend_category="Specialty Chemicals",
            open_purchase_order_count=22, active_contract_count=0, contract_number=None,
            delivery_count=70, late_delivery_count=6, average_delay_days=2.2,
            quality_incident_count=1, invoice_count=60, invoice_exception_count=4,
            disputed_invoice_count=1, credit_score=78.0, days_payable_outstanding=41.0,
            payment_default_count=0, financial_distress_flag=False,
            category_spend_share=92.0, single_source_material_count=11,
            compliance_finding_count=0, certification_status="Valid", audit_status="Passed",
            last_audit_date=self._days_ago(95), capacity_utilization=86.0,
            lead_time_variability_days=4.5, alternative_supplier_count=0,
        )
        self.scenarios.append(Scenario(
            "SRK-05", "Spend concentration anchor", srk05["supplier_id"], "spend_concentration",
            "92% of the Specialty Chemicals category spend, 11 single-sourced materials and no "
            "qualified alternative. It also buys with no outline agreement - contract status "
            "'No contract' (written as a real label, never the bare word 'None').",
            "Highest spend concentration category score in the data set (100.0) and a contract "
            "category score of 100.0 because there is no agreement at all. Ordinary Specialty "
            "Chemicals suppliers score far lower, so the alternatives lookup has candidates.",
        ))

        # -- SRK-06 contract: the only agreement inside the 30-day critical window.
        srk06 = anchor(
            5,
            supplier_name="Fairmont Digital Systems Oy",
            materials_supplied=["MAT-1000", "MAT-1110"],
            plants_served=["1010"], regions_served=["EU", "NA"],
            unit_price=410.0, currency="EUR", lead_time_days=22,
            available_capacity=900.0, on_time_delivery_rate=94.0, quality_score=91.0,
            defect_rate=1.4, risk_score=38.0, esg_score=74.0,
            contract_status="Expiring", contract_expiration=self._days_out(18),
            payment_terms="NT45", historical_order_count=76, historical_spend=1_180_000.0,
            country="PL", spend_category="IT Hardware",
            open_purchase_order_count=9, active_contract_count=1, contract_number="4600008106",
            delivery_count=60, late_delivery_count=4, average_delay_days=1.8,
            quality_incident_count=1, invoice_count=70, invoice_exception_count=3,
            disputed_invoice_count=0, credit_score=80.0, days_payable_outstanding=38.0,
            payment_default_count=0, financial_distress_flag=False,
            category_spend_share=18.0, single_source_material_count=1,
            compliance_finding_count=0, certification_status="Valid", audit_status="Passed",
            last_audit_date=self._days_ago(120), capacity_utilization=74.0,
            lead_time_variability_days=3.5, alternative_supplier_count=4,
        )
        self.scenarios.append(Scenario(
            "SRK-06", "Contract expiry anchor", srk06["supplier_id"], "contract",
            "An otherwise sound supplier whose outline agreement 4600008106 expires 18 days "
            "after the reference date of 2026-07-01.",
            "days_to_contract_expiry is 18, contract_expiring_soon is true and it is the only "
            "supplier inside the configured 30-day critical window. Its contract category "
            "scores in the 'high' band - the highest of any supplier that still holds a dated "
            "agreement.",
        ))

        # -- SRK-07 invoice: exception-heavy, many disputes.
        srk07 = anchor(
            6,
            supplier_name="Harbourview Packaging Sp. z o.o.",
            materials_supplied=["MAT-1020", "MAT-1030"],
            plants_served=["1010", "4010"], regions_served=["EU", "NA"],
            unit_price=88.0, currency="EUR", lead_time_days=30,
            available_capacity=5200.0, on_time_delivery_rate=92.0, quality_score=88.0,
            defect_rate=2.0, risk_score=58.0, esg_score=68.0,
            contract_status="Active", contract_expiration=self._days_out(226),
            payment_terms="Z030", historical_order_count=190, historical_spend=1_640_000.0,
            country="IT", spend_category="Packaging",
            open_purchase_order_count=17, active_contract_count=2, contract_number="4600008107",
            delivery_count=85, late_delivery_count=8, average_delay_days=2.6,
            quality_incident_count=2, invoice_count=96, invoice_exception_count=34,
            disputed_invoice_count=11, credit_score=72.0, days_payable_outstanding=55.0,
            payment_default_count=1, financial_distress_flag=False,
            category_spend_share=28.0, single_source_material_count=2,
            compliance_finding_count=1, certification_status="Valid", audit_status="Conditional",
            last_audit_date=self._days_ago(260), capacity_utilization=80.0,
            lead_time_variability_days=5.0, alternative_supplier_count=3,
        )
        self.scenarios.append(Scenario(
            "SRK-07", "Invoice risk anchor", srk07["supplier_id"], "invoice",
            "34 of 96 invoices raised an exception (35.4%) and 11 invoices are formally "
            "disputed - the same exception concept module 4 (Invoice Validator) produces.",
            "Highest invoice category score in the data set (100.0, 'critical' band) and an "
            "invoice-accuracy action in its recommended actions.",
        ))

        # -- SRK-08 compliance and ESG: findings, expired cert, failed audit.
        srk08 = anchor(
            7,
            supplier_name="Ironwood Industrial Supplies Oy",
            materials_supplied=["MAT-1040", "MAT-1050"],
            plants_served=["1010", "2010"], regions_served=["APAC"],
            unit_price=119.0, currency="EUR", lead_time_days=50,
            available_capacity=3400.0, on_time_delivery_rate=84.0, quality_score=80.0,
            defect_rate=4.2, risk_score=69.0, esg_score=18.0,
            contract_status="Active", contract_expiration=self._days_out(339),
            payment_terms="NT45", historical_order_count=132, historical_spend=1_310_000.0,
            country="IN", spend_category="MRO Supplies",
            open_purchase_order_count=14, active_contract_count=1, contract_number="4600008108",
            delivery_count=95, late_delivery_count=19, average_delay_days=7.5,
            quality_incident_count=5, invoice_count=110, invoice_exception_count=18,
            disputed_invoice_count=4, credit_score=58.0, days_payable_outstanding=64.0,
            payment_default_count=2, financial_distress_flag=False,
            category_spend_share=42.0, single_source_material_count=3,
            compliance_finding_count=8, certification_status="Expired", audit_status="Failed",
            last_audit_date=self._days_ago(282), capacity_utilization=91.0,
            lead_time_variability_days=11.0, alternative_supplier_count=2,
        )
        self.scenarios.append(Scenario(
            "SRK-08", "Compliance and ESG anchor", srk08["supplier_id"], "compliance",
            "Eight open compliance findings, an expired certification, a failed audit and an "
            "internally recorded ESG score of 18. No external ESG rating service is contacted.",
            "Highest compliance category score in the data set ('critical' band) and the "
            "highest ESG category score (100.0), which together carry its overall risk into the "
            "'high' band. Neither its delivery nor its quality category tops a ranking.",
        ))

        # -- SRK-09 missing data: too little to state an overall risk.
        srk09 = self._blank_row(8)
        srk09.update(
            {
                "supplier_name": "Larkspur Emerging Components Ltd",
                "country": "PT",
                "spend_category": "Electronic Components",
                "esg_score": 61.0,
            }
        )
        rows.append(srk09)
        self.scenarios.append(Scenario(
            "SRK-09", "Missing data anchor", srk09["supplier_id"], "missing_data",
            "A newly onboarded supplier with almost nothing recorded: a name, a country, a "
            "spend category and an ESG score. Every other cell is genuinely empty - no "
            "placeholder text, so nothing is mistaken for a real value.",
            "Only the geographic and ESG categories can be scored, which is below the "
            "configured minimum of three, so overall_score is withheld (None), overall_band is "
            "None and limited_data is true at 12% data completeness. It is the only supplier "
            "in the data set that is not scored.",
        ))

        return rows

    # ------------------------------------------------------------------
    # internal records
    # ------------------------------------------------------------------
    def _next_event_id(self) -> str:
        self._event_sequence += 1
        return f"SRE-{self._event_sequence:05d}"

    def _event_date(self, recent: bool) -> str:
        window = self.config.trend.window_days
        if recent:
            offset = self.random.randint(0, window - 1)
        else:
            offset = self.random.randint(window, window * 2 - 1)
        return (self.as_of - timedelta(days=offset)).isoformat()

    def _add_event(
        self,
        supplier_id: str,
        event_type: str,
        recent: bool,
        severity: str,
    ) -> dict[str, Any]:
        """Append one dated internal record, shaped by its type."""
        rng = self.random
        reference: str | None
        amount: float | None
        currency: str | None
        if event_type == "late_delivery":
            reference = f"45000{rng.randint(10000, 99999)}"
            description = f"Goods receipt {rng.randint(2, 34)} days after the confirmed date."
            amount, currency = None, None
        elif event_type == "quality_incident":
            reference = f"QN-1000{rng.randint(1000, 9999)}"
            description = "Non-conformance report raised; batch quarantined at goods receipt."
            amount = float(rng.randint(500, 25_000))
            currency = "EUR"
        elif event_type == "invoice_exception":
            reference = f"51056{rng.randint(10000, 99999)}"
            description = "Invoice blocked: price and quantity did not match the purchase order."
            amount = float(rng.randint(200, 45_000))
            currency = "EUR"
        elif event_type == "compliance_finding":
            reference = f"CF-2026-{rng.randint(100, 999)}"
            description = "Supplier audit finding recorded and not yet closed."
            amount, currency = None, None
        elif event_type == "contract_event":
            reference = f"46000{rng.randint(80000, 89999)}"
            description = "Outline agreement change recorded: renewal not yet signed."
            amount = float(rng.randint(50_000, 900_000))
            currency = "EUR"
        else:  # payment_default
            reference = f"AP-2026-{rng.randint(100, 999)}"
            description = "Payment default recorded by accounts payable."
            amount = float(rng.randint(5_000, 120_000))
            currency = "EUR"

        event = {
            "event_id": self._next_event_id(),
            "supplier_id": supplier_id,
            "event_type": event_type,
            "event_date": self._event_date(recent),
            "reference": reference,
            "severity": severity,
            "description": description,
            "amount": amount,
            "currency": currency,
        }
        self.events.append(event)
        return event

    def _build_events(self) -> None:
        """Dated internal records: heavy on the anchors, thin on everyone else."""
        rng = self.random

        # Anchor record plans: (supplier index, type, recent count, previous count, severity)
        plans: list[tuple[int, str, int, int, str]] = [
            (0, "late_delivery", 4, 2, "high"),
            (0, "quality_incident", 3, 1, "high"),
            (0, "invoice_exception", 3, 1, "medium"),
            (0, "compliance_finding", 2, 0, "critical"),
            (0, "payment_default", 2, 0, "critical"),
            (1, "late_delivery", 11, 5, "high"),
            (1, "contract_event", 1, 0, "low"),
            (2, "quality_incident", 9, 4, "high"),
            (2, "late_delivery", 2, 1, "medium"),
            (3, "payment_default", 4, 1, "critical"),
            (3, "invoice_exception", 2, 1, "medium"),
            (3, "compliance_finding", 1, 0, "high"),
            (4, "contract_event", 3, 1, "high"),
            (4, "late_delivery", 2, 1, "low"),
            (5, "contract_event", 4, 1, "medium"),
            (6, "invoice_exception", 10, 4, "high"),
            (6, "late_delivery", 1, 1, "low"),
            (7, "compliance_finding", 6, 3, "critical"),
            (7, "quality_incident", 2, 1, "medium"),
        ]
        for index, event_type, recent, previous, severity in plans:
            supplier_id = self._supplier_id(index)
            for _ in range(recent):
                self._add_event(supplier_id, event_type, True, severity)
            for _ in range(previous):
                self._add_event(supplier_id, event_type, False, severity)

        # A thin, ordinary tail across the rest of the population. SRK-09 stays
        # empty: the missing-data anchor has no internal records either.
        for index in range(9, TOTAL_SUPPLIERS):
            for _ in range(rng.randint(0, 3)):
                self._add_event(
                    self._supplier_id(index),
                    rng.choice(EVENT_TYPES),
                    rng.random() < 0.55,
                    rng.choice(["low", "low", "medium", "medium", "high"]),
                )

    # ------------------------------------------------------------------
    def build(self) -> None:
        """Assemble the anchors, the ordinary population and the internal records."""
        anchors = self._anchor_rows()
        self.rows.extend(anchors)
        for index in range(len(anchors), TOTAL_SUPPLIERS):
            self.rows.append(self._background_row(index))
        self._build_events()

    # ------------------------------------------------------------------
    # output
    # ------------------------------------------------------------------
    def profiles_dataframe(self) -> pd.DataFrame:
        """Profiles as an object-dtype frame, so empty cells stay genuinely empty."""
        records = []
        for row in sorted(self.rows, key=lambda item: item["supplier_id"]):
            record = dict(row)
            for name in LIST_FIELDS:
                values = record.get(name) or []
                record[name] = ";".join(values) if values else None
            records.append(record)
        return _object_frame(records, CANONICAL_FIELDS)

    def events_dataframe(self) -> pd.DataFrame:
        """Internal records as an object-dtype frame, sorted by id."""
        records = sorted(self.events, key=lambda item: item["event_id"])
        return _object_frame(records, EVENT_CANONICAL_FIELDS)

    def write(self, output_dir: Path) -> dict[str, Any]:
        """Write both data sets in CSV, XLSX and JSON, plus the scenario manifest."""
        output_dir.mkdir(parents=True, exist_ok=True)

        profiles = self.profiles_dataframe()
        events = self.events_dataframe()

        written = [
            *_write_triplet(
                profiles, output_dir, "sample_supplier_risk_profiles",
                TECHNICAL_HEADERS, REGISTRY, CANONICAL_FIELDS, "Supplier Risk",
            ),
            *_write_triplet(
                events, output_dir, "sample_supplier_risk_events",
                EVENT_TECHNICAL_HEADERS, EVENT_REGISTRY, EVENT_CANONICAL_FIELDS, "Risk Events",
            ),
        ]

        manifest = {
            "generated_with_seed": SEED,
            "data_origin": "demo_data",
            "as_of_date": self.as_of.isoformat(),
            "supplier_count": int(len(profiles)),
            "event_count": int(len(events)),
            "note": (
                "Fictional supplier risk records. Most suppliers are ordinary vendors whose "
                "overall risk lands in the low or medium band; the anchor suppliers below are "
                "placed deliberately so every documented risk behaviour can be asserted against "
                "the deterministic scoring model. No live credit, ESG, news or country-risk "
                "service is contacted anywhere in this module."
            ),
            "scenarios": [scenario.to_dict() for scenario in self.scenarios],
        }
        (output_dir / "supplier_risk_scenario_manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (output_dir / "SUPPLIER_RISK_SCENARIO_MANIFEST.md").write_text(
            _manifest_markdown(profiles, events, manifest), encoding="utf-8"
        )

        return {
            "suppliers": int(len(profiles)),
            "events": int(len(events)),
            "spend_categories": int(profiles["spend_category"].nunique()),
            "countries": int(profiles["country"].nunique()),
            "scenarios": len(self.scenarios),
            "files": [str(path) for path in written],
        }


# ---------------------------------------------------------------------------
# writing helpers
# ---------------------------------------------------------------------------
def _object_frame(records: list[dict[str, Any]], columns: tuple[str, ...]) -> pd.DataFrame:
    """Build a frame whose columns keep Python types and ``None`` holes.

    pandas would otherwise widen an integer column containing a hole to float,
    writing ``90.0`` where the extract should read ``90`` - and it would write
    the placeholder ``NaN`` where the missing-data anchor needs a genuinely
    empty cell.
    """
    return pd.DataFrame(
        {name: pd.Series([record.get(name) for record in records], dtype=object)
         for name in columns}
    )


def _json_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Canonical snake_case records with ``None`` for every empty cell."""
    records: list[dict[str, Any]] = []
    for row in frame.to_dict(orient="records"):
        records.append({key: (None if pd.isna(value) else value) for key, value in row.items()})
    return records


def _write_triplet(
    frame: pd.DataFrame,
    output_dir: Path,
    stem: str,
    technical_headers: dict[str, str],
    registry: Any,
    columns: tuple[str, ...],
    sheet_name: str,
) -> list[Path]:
    """Write one data set as CSV (technical), XLSX (labels) and JSON (canonical)."""
    csv_path = output_dir / f"{stem}.csv"
    frame.rename(columns=technical_headers).to_csv(csv_path, index=False)

    xlsx_path = output_dir / f"{stem}.xlsx"
    frame.rename(columns={name: registry.label(name) for name in columns}).to_excel(
        xlsx_path, index=False, sheet_name=sheet_name
    )

    json_path = output_dir / f"{stem}.json"
    json_path.write_text(
        json.dumps({"records": _json_records(frame)}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return [csv_path, xlsx_path, json_path]


# ---------------------------------------------------------------------------
# baseline
# ---------------------------------------------------------------------------
def load_generated_assessment(output_dir: Path, as_of: date = AS_OF_DATE) -> Any:
    """Read both written CSVs back through the production path and score them.

    Nothing here shortcuts through the generator's in-memory rows: the files are
    parsed by the real reader, mapped by the real column mapper and normalised by
    the real normaliser, so the result is exactly what the API produces from the
    same upload.
    """
    config = get_supplier_risk_config()

    profile_bytes = (output_dir / "sample_supplier_risk_profiles.csv").read_bytes()
    profile_result = read_tabular(profile_bytes, ".csv")
    profile_mapping = suggest_mapping(profile_result.source_columns, REGISTRY)
    profile_dataset = normalize_supplier_risk_dataframe(
        profile_result.dataframe, profile_mapping.mapping, config
    )

    event_bytes = (output_dir / "sample_supplier_risk_events.csv").read_bytes()
    event_result = read_tabular(event_bytes, ".csv")
    event_mapping = suggest_mapping(event_result.source_columns, EVENT_REGISTRY)
    event_dataset = normalize_risk_event_dataframe(
        event_result.dataframe, event_mapping.mapping, config
    )

    return run_risk_assessment(
        profile_dataset.profiles,
        event_dataset.events,
        config.default_weights,
        config,
        as_of,
    )


def write_observed_baseline(output_dir: Path, as_of: date = AS_OF_DATE) -> dict[str, Any]:
    """Run the engine over the written files and record what it produced."""
    config = get_supplier_risk_config()
    result = load_generated_assessment(output_dir, as_of)

    ranked = sorted(
        (item for item in result.profiles if item.overall_score is not None),
        key=lambda item: (-(item.overall_score or 0.0), item.supplier_id),
    )
    top_five = [
        {
            "rank": rank,
            "supplier_id": profile.supplier_id,
            "overall_score": profile.overall_score,
            "overall_band": profile.overall_band,
        }
        for rank, profile in enumerate(ranked[:5], start=1)
    ]

    baseline = {
        "note": (
            "Observed output of the current supplier risk engine on the generated data set with "
            "the default category weights, read back from the written CSV files through the real "
            "reader, mapper and normaliser. Used by the test suite to detect unintended changes "
            "in the engine or the generator."
        ),
        "seed": SEED,
        "as_of_date": as_of.isoformat(),
        "config_version": config.config_version,
        "engine_version": result.engine_version,
        "supplier_count": result.supplier_count,
        "scored_count": result.scored_count,
        "event_count": result.event_count,
        "band_counts": dict(result.band_counts),
        "average_overall_score": result.average_overall_score,
        "highest_risk_supplier_id": result.highest_risk_supplier_id,
        "highest_risk_score": result.highest_risk_score,
        "contracts_expiring_count": result.contracts_expiring_count,
        "limited_data_count": result.limited_data_count,
        "category_averages": dict(result.category_averages),
        "top_five": top_five,
    }
    (output_dir / "expected_supplier_risk_baseline.json").write_text(
        json.dumps(baseline, indent=2, default=str), encoding="utf-8"
    )
    return baseline


# ---------------------------------------------------------------------------
# manifest
# ---------------------------------------------------------------------------
def _manifest_markdown(
    profiles: pd.DataFrame,
    events: pd.DataFrame,
    manifest: dict[str, Any],
) -> str:
    event_types = sorted({str(value) for value in events["event_type"].tolist()})
    lines = [
        "# Supplier risk sample data - scenario manifest",
        "",
        "**Origin: demo data.** These records are fictional. They were generated by "
        "`scripts/generate_supplier_risk_sample_data.py` and do not come from any SAP system, "
        "credit bureau, ESG rating service or real company. No external service is contacted by "
        "the generator or by the Supplier Risk Copilot.",
        "",
        f"- Suppliers: {len(profiles):,}",
        f"- Dated internal records: {len(events):,}",
        f"- Record types: {', '.join(event_types)}",
        f"- Spend categories: {profiles['spend_category'].nunique()}",
        f"- Countries: {profiles['country'].nunique()}",
        f"- Reference date (`as_of`): `{manifest['as_of_date']}`",
        f"- Random seed: `{manifest['generated_with_seed']}` (regenerating reproduces the "
        "identical data set)",
        "",
        "Most suppliers are ordinary vendors: a consistent spread of on-time rates, defect "
        "rates, credit scores, spend shares, certifications and audit outcomes that keeps their "
        "overall risk in the low or medium band. The nine anchor suppliers below are placed "
        "deliberately, one per testable behaviour of the risk model.",
        "",
        "## Files",
        "",
        "| File | Contents |",
        "| --- | --- |",
        "| `sample_supplier_risk_profiles.csv` | One row per supplier, SAP technical headers |",
        "| `sample_supplier_risk_profiles.xlsx` | The same rows with business labels |",
        "| `sample_supplier_risk_profiles.json` | The same rows with canonical field names |",
        "| `sample_supplier_risk_events.csv` | Dated internal records, SAP technical headers |",
        "| `sample_supplier_risk_events.xlsx` | The same records with business labels |",
        "| `sample_supplier_risk_events.json` | The same records with canonical field names |",
        "| `expected_supplier_risk_baseline.json` | What the current engine produces from them |",
        "",
        "## Anchor suppliers",
        "",
    ]
    for scenario in manifest["scenarios"]:
        lines.extend([
            f"### {scenario['scenario_id']} - {scenario['name']}",
            "",
            f"- Supplier: `{scenario['supplier_id']}`",
            f"- Risk category: `{scenario['category']}`",
            f"- {scenario['description']}",
            f"- **Expected effect:** {scenario['expects']}",
            "",
        ])
    lines.extend([
        "## Reading the columns",
        "",
        "`RISK_SCORE` is module 3's *stored* supplier-master risk figure, inherited with the "
        "rest of the supplier master contract. It is not an input to the Supplier Risk Copilot "
        "and it is not the computed risk: the copilot's scores come from the ten weighted "
        "categories in `app/modules/supplier_risk/config/supplier_risk_rules.json`.",
        "",
        "Empty cells are genuinely empty. The generator never writes the words `None`, `null`, "
        "`NA` or `-` as a value, because the shared file reader treats those as null "
        "placeholders and a scenario written that way would silently disappear on the round "
        "trip through CSV. Where a supplier has no outline agreement the contract status is the "
        "real label `No contract`.",
        "",
        "## How the test suite uses this file",
        "",
        "The module 5 integration tests load these files through the real reader, mapper and "
        "normaliser, run the risk assessment for `as_of` "
        f"`{manifest['as_of_date']}` and assert that each anchor behaves as documented, that the "
        "portfolio figures reproduce `expected_supplier_risk_baseline.json`, and that repeated "
        "runs over the same files are identical.",
        "",
        "## A note on the figures",
        "",
        "Every risk score is produced by the deterministic weighted-scoring model in "
        "`app/modules/supplier_risk`, not by an AI model. Credit scores, ESG scores, audit "
        "outcomes and country risk indexes are invented internal figures, not ratings from any "
        "provider. Estimated exposure is an indicative planning figure, not a guaranteed one, "
        "and nothing here has been validated in a live SAP environment.",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    """Generate the data set, then record the baseline the engine produces from it."""
    generator = SupplierRiskSampleGenerator()
    generator.build()
    stats = generator.write(settings.sample_dir)
    baseline = write_observed_baseline(settings.sample_dir)

    logger.info(
        "Generated %d supplier risk profiles, %d internal records, %d scenarios",
        stats["suppliers"], stats["events"], stats["scenarios"],
    )
    print(json.dumps(stats, indent=2))
    print(
        f"assessment: {baseline['scored_count']}/{baseline['supplier_count']} scored | "
        f"bands {baseline['band_counts']} | highest {baseline['highest_risk_supplier_id']} "
        f"({baseline['highest_risk_score']}) | expiring {baseline['contracts_expiring_count']} | "
        f"limited data {baseline['limited_data_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
