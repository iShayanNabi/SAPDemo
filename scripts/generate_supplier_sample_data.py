"""Generate the fictional supplier catalogue for the Recommendation Engine.

Run with::

    python scripts/generate_supplier_sample_data.py

Outputs (into ``data/sample/``):

* ``sample_suppliers.csv``   - SAP technical / master-data column names
* ``sample_suppliers.xlsx``  - business labels
* ``sample_suppliers.json``  - canonical snake_case names
* ``supplier_scenario_manifest.json`` / ``.md``
* ``expected_supplier_baseline.json`` - what the current engine produces

**The data is entirely fictional.** Supplier names, materials and numbers were
invented for this lab. Nothing comes from an SAP system or a real company.

Design principle: most suppliers are ordinary, well-rounded candidates. A small
set of *anchor* suppliers is placed deliberately - the cheapest bidder, a
high-risk supplier, one that does not supply the material, one with a weak ESG
score, one with no contract and one that cannot cover the quantity - so every
documented eligibility and ranking behaviour traces back to a line in the
manifest and can be asserted by the test suite against a canonical requirement.
"""

from __future__ import annotations

import json
import random
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.logging import get_logger  # noqa: E402
from app.modules.supplier_reco.engine import run_recommendation  # noqa: E402
from app.modules.supplier_reco.field_definitions import CANONICAL_FIELDS, REGISTRY  # noqa: E402
from app.modules.supplier_reco.normalizer import NormalizedSupplier  # noqa: E402
from app.modules.supplier_reco.requirement import Requirement  # noqa: E402
from app.modules.supplier_reco.thresholds import get_supplier_reco_config  # noqa: E402

logger = get_logger("generate_supplier_sample_data")

SEED = 20260301
TOTAL_SUPPLIERS = 55

#: CSV uses master-data technical names.
TECHNICAL_HEADERS = {
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
}

#: The material every anchor scenario is written around.
CANONICAL_MATERIAL = "MAT-1000"

MATERIALS = [f"MAT-{1000 + i * 10}" for i in range(12)]
REGIONS = ["EU", "NA", "APAC", "LATAM"]
PLANTS = ["1010", "1020", "2010", "3010", "4010"]
CURRENCIES = ["EUR", "USD", "GBP"]
PAYMENT_TERMS = ["NT30", "NT45", "NT60", "Z030", "Z045"]

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


@dataclass
class Scenario:
    """One deliberately placed, documented anchor supplier."""

    scenario_id: str
    name: str
    supplier_id: str
    description: str
    expects: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "name": self.name,
            "supplier_id": self.supplier_id,
            "description": self.description,
            "expects": self.expects,
        }


class SupplierSampleGenerator:
    """Builds the demo supplier catalogue and its scenario manifest."""

    def __init__(self, seed: int = SEED) -> None:
        self.random = random.Random(seed)
        self.config = get_supplier_reco_config()
        self.rows: list[dict[str, Any]] = []
        self.scenarios: list[Scenario] = []

    # ------------------------------------------------------------------
    def _name(self, index: int) -> str:
        prefix = SUPPLIER_PREFIXES[index % len(SUPPLIER_PREFIXES)]
        return f"{prefix} {self.random.choice(SUPPLIER_SUFFIXES)}"

    def _base_row(self, index: int, **overrides: Any) -> dict[str, Any]:
        """A well-rounded, ordinary supplier; overrides tune the anchors."""
        supplier_id = f"{300001 + index:010d}"
        # A varied but sensible spread across every attribute.
        materials = overrides.pop("materials_supplied", None)
        if materials is None:
            pool = [CANONICAL_MATERIAL] if index % 2 == 0 else []
            pool += self.random.sample(MATERIALS, self.random.randint(1, 4))
            materials = sorted(set(pool))
        plants = overrides.pop("plants_served", None)
        if plants is None:
            plants = sorted(set(["1010"] + self.random.sample(PLANTS, self.random.randint(1, 3))))
        regions = overrides.pop("regions_served", None)
        if regions is None:
            regions = sorted(set(["EU"] + self.random.sample(REGIONS, self.random.randint(1, 2))))

        currency = overrides.pop("currency", self.random.choice(CURRENCIES))
        base_price = self.random.uniform(90.0, 380.0)
        unit_price = round(base_price / max(self.config.conversion_rate(currency), 0.0001), 2)

        row = {
            "supplier_id": supplier_id,
            "supplier_name": self._name(index),
            "materials_supplied": materials,
            "plants_served": plants,
            "regions_served": regions,
            "unit_price": unit_price,
            "currency": currency,
            "lead_time_days": self.random.randint(7, 55),
            "available_capacity": float(self.random.randint(150, 5000)),
            "on_time_delivery_rate": round(self.random.uniform(70.0, 99.5), 1),
            "quality_score": round(self.random.uniform(62.0, 98.0), 1),
            "defect_rate": round(self.random.uniform(0.2, 7.5), 2),
            "risk_score": round(self.random.uniform(8.0, 58.0), 1),
            "esg_score": round(self.random.uniform(48.0, 95.0), 1),
            # "No contract" (not the bare word "None", which a CSV reader treats as null).
            "contract_status": self.random.choice(["Active", "Active", "Expiring", "No contract"]),
            "contract_expiration": self._expiry(),
            "payment_terms": self.random.choice(PAYMENT_TERMS),
            "historical_order_count": self.random.randint(0, 130),
            "historical_spend": float(self.random.randint(0, 1_500_000)),
        }
        row.update(overrides)
        return row

    def _expiry(self) -> str | None:
        choice = self.random.random()
        if choice < 0.2:
            return None
        year = self.random.choice([2026, 2027, 2028])
        month = self.random.randint(1, 12)
        return date(year, month, 15).isoformat()

    # ------------------------------------------------------------------
    def build(self) -> None:
        anchors = self._anchor_rows()
        self.rows.extend(anchors)

        for index in range(len(anchors), TOTAL_SUPPLIERS):
            self.rows.append(self._base_row(index))

        # Guarantee a healthy pool of eligible candidates for the canonical
        # requirement (supply MAT-1000, serve plant 1010, cover the quantity).
        eligible_like = [
            r for r in self.rows
            if CANONICAL_MATERIAL in r["materials_supplied"] and "1010" in r["plants_served"]
        ]
        if len(eligible_like) < 20:
            extra_needed = 20 - len(eligible_like)
            candidates = [
                r for r in self.rows
                if r["supplier_id"] not in {s.supplier_id for s in self.scenarios}
                and CANONICAL_MATERIAL not in r["materials_supplied"]
            ]
            for row in candidates[:extra_needed]:
                row["materials_supplied"] = sorted(set(row["materials_supplied"] + [CANONICAL_MATERIAL]))
                if "1010" not in row["plants_served"]:
                    row["plants_served"] = sorted(set(row["plants_served"] + ["1010"]))

    def _anchor_rows(self) -> list[dict[str, Any]]:
        """The seven deliberately-placed anchor suppliers."""
        rows: list[dict[str, Any]] = []

        # SR-01 lowest cost: cheapest EUR bidder, eligible at medium tolerance.
        lowest = self._base_row(
            0, supplier_name="Bluepeak Value Supply Ltd",
            materials_supplied=[CANONICAL_MATERIAL, "MAT-1010"], plants_served=["1010", "1020"],
            regions_served=["EU"], currency="EUR", unit_price=55.0, lead_time_days=28,
            available_capacity=900.0, on_time_delivery_rate=86.0, quality_score=78.0,
            defect_rate=3.2, risk_score=42.0, esg_score=64.0, contract_status="Active",
            contract_expiration="2028-01-15", historical_order_count=35, historical_spend=280000.0,
        )
        rows.append(lowest)
        self.scenarios.append(Scenario(
            "SR-01", "Lowest cost bidder", lowest["supplier_id"],
            "The cheapest eligible supplier for the canonical requirement (unit price 55 EUR).",
            "With all weight on cost this supplier ranks #1; under the default weights it is "
            "eligible but does not necessarily win.",
        ))

        # SR-02 high risk: eligible only when the risk tolerance is high.
        high_risk = self._base_row(
            1, supplier_name="Ravenna Frontier Trading BV",
            materials_supplied=[CANONICAL_MATERIAL], plants_served=["1010"], regions_served=["EU"],
            currency="EUR", unit_price=210.0, lead_time_days=18, available_capacity=1200.0,
            on_time_delivery_rate=88.0, quality_score=83.0, defect_rate=2.5, risk_score=85.0,
            esg_score=72.0, contract_status="Active", contract_expiration="2027-09-15",
            historical_order_count=20, historical_spend=190000.0,
        )
        rows.append(high_risk)
        self.scenarios.append(Scenario(
            "SR-02", "High-risk supplier", high_risk["supplier_id"],
            "Risk score 85. Passes every other constraint for the canonical requirement.",
            "Ineligible at 'low' and 'medium' risk tolerance; eligible at 'high' tolerance.",
        ))

        # SR-03 wrong material: does not supply the canonical material.
        wrong_material = self._base_row(
            2, supplier_name="Kestrel Specialities SA",
            materials_supplied=["MAT-1100", "MAT-1110"], plants_served=["1010"], regions_served=["EU"],
            currency="EUR", unit_price=140.0, lead_time_days=15, available_capacity=2000.0,
            on_time_delivery_rate=95.0, quality_score=94.0, defect_rate=0.8, risk_score=15.0,
            esg_score=90.0, contract_status="Active", contract_expiration="2028-05-15",
            historical_order_count=70, historical_spend=900000.0,
        )
        rows.append(wrong_material)
        self.scenarios.append(Scenario(
            "SR-03", "Does not supply the material", wrong_material["supplier_id"],
            f"An otherwise excellent supplier that does not list {CANONICAL_MATERIAL}.",
            "Ineligible for the canonical requirement because of the material-match filter.",
        ))

        # SR-04 weak ESG: eligible normally, ineligible under a sustainability floor.
        low_esg = self._base_row(
            3, supplier_name="Cobalt Basic Materials SpA",
            materials_supplied=[CANONICAL_MATERIAL], plants_served=["1010"], regions_served=["EU"],
            currency="EUR", unit_price=118.0, lead_time_days=22, available_capacity=1500.0,
            on_time_delivery_rate=90.0, quality_score=85.0, defect_rate=2.0, risk_score=35.0,
            esg_score=35.0, contract_status="Active", contract_expiration="2027-11-15",
            historical_order_count=40, historical_spend=410000.0,
        )
        rows.append(low_esg)
        self.scenarios.append(Scenario(
            "SR-04", "Weak ESG score", low_esg["supplier_id"],
            "ESG score 35, below a typical sustainability floor.",
            "Eligible for the canonical requirement; ineligible once a sustainability requirement "
            "of 70 is set.",
        ))

        # SR-05 no contract: eligible normally, ineligible when a contract is required.
        no_contract = self._base_row(
            4, supplier_name="Driftwood Spot Supply AS",
            materials_supplied=[CANONICAL_MATERIAL], plants_served=["1010"], regions_served=["EU"],
            currency="EUR", unit_price=132.0, lead_time_days=20, available_capacity=1000.0,
            on_time_delivery_rate=87.0, quality_score=80.0, defect_rate=3.0, risk_score=48.0,
            esg_score=68.0, contract_status="No contract", contract_expiration=None,
            historical_order_count=12, historical_spend=95000.0,
        )
        rows.append(no_contract)
        self.scenarios.append(Scenario(
            "SR-05", "No active contract", no_contract["supplier_id"],
            "Contract status 'None'.",
            "Eligible for the canonical requirement; ineligible once a contract requirement is set.",
        ))

        # SR-06 low capacity: cannot cover the canonical quantity.
        low_capacity = self._base_row(
            5, supplier_name="Ember Boutique Components AG",
            materials_supplied=[CANONICAL_MATERIAL], plants_served=["1010"], regions_served=["EU"],
            currency="EUR", unit_price=99.0, lead_time_days=12, available_capacity=40.0,
            on_time_delivery_rate=97.0, quality_score=96.0, defect_rate=0.5, risk_score=18.0,
            esg_score=88.0, contract_status="Active", contract_expiration="2028-02-15",
            historical_order_count=8, historical_spend=60000.0,
        )
        rows.append(low_capacity)
        self.scenarios.append(Scenario(
            "SR-06", "Insufficient capacity", low_capacity["supplier_id"],
            "Available capacity 40, below the canonical requested quantity of 100.",
            "Ineligible for the canonical requirement because capacity cannot cover the quantity.",
        ))

        # SR-07 expiring contract: contract lapses before the required delivery date.
        expiring = self._base_row(
            6, supplier_name="Fairmont Legacy Trading BV",
            materials_supplied=[CANONICAL_MATERIAL], plants_served=["1010"], regions_served=["EU"],
            currency="EUR", unit_price=125.0, lead_time_days=16, available_capacity=1100.0,
            on_time_delivery_rate=92.0, quality_score=88.0, defect_rate=1.5, risk_score=25.0,
            esg_score=79.0, contract_status="Active", contract_expiration="2026-09-01",
            historical_order_count=55, historical_spend=520000.0,
        )
        rows.append(expiring)
        self.scenarios.append(Scenario(
            "SR-07", "Contract expiring before delivery", expiring["supplier_id"],
            "Holds an active contract, but it expires 2026-09-01, before the canonical required "
            "delivery date of 2026-10-01.",
            "Eligible for the canonical requirement, but its contract score is penalised to the "
            "'expiring' level and its risks list the lapse.",
        ))

        return rows

    # ------------------------------------------------------------------
    def to_dataframe(self) -> pd.DataFrame:
        records = []
        for row in self.rows:
            record = dict(row)
            for list_field in ("materials_supplied", "plants_served", "regions_served"):
                record[list_field] = ";".join(record[list_field])
            records.append(record)
        frame = pd.DataFrame(records).sort_values("supplier_id").reset_index(drop=True)
        return frame[list(CANONICAL_FIELDS)]

    def write(self, output_dir: Path) -> dict[str, Any]:
        output_dir.mkdir(parents=True, exist_ok=True)
        frame = self.to_dataframe()

        csv_path = output_dir / "sample_suppliers.csv"
        frame.rename(columns=TECHNICAL_HEADERS).to_csv(csv_path, index=False)

        xlsx_path = output_dir / "sample_suppliers.xlsx"
        frame.rename(columns={name: REGISTRY.label(name) for name in CANONICAL_FIELDS}).to_excel(
            xlsx_path, index=False, sheet_name="Suppliers"
        )

        json_path = output_dir / "sample_suppliers.json"
        records = json.loads(frame.to_json(orient="records"))
        json_path.write_text(
            json.dumps({"records": records}, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        manifest = {
            "generated_with_seed": SEED,
            "data_origin": "demo_data",
            "supplier_count": int(len(frame)),
            "canonical_requirement": CANONICAL_REQUIREMENT,
            "note": (
                "Fictional supplier catalogue. Most suppliers are ordinary candidates; the anchor "
                "suppliers below are placed deliberately so every documented eligibility and "
                "ranking behaviour can be asserted against the canonical requirement."
            ),
            "scenarios": [scenario.to_dict() for scenario in self.scenarios],
        }
        (output_dir / "supplier_scenario_manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (output_dir / "SUPPLIER_SCENARIO_MANIFEST.md").write_text(
            _manifest_markdown(frame, manifest), encoding="utf-8"
        )

        return {
            "suppliers": int(len(frame)),
            "materials": len({m for row in self.rows for m in row["materials_supplied"]}),
            "regions": len({r for row in self.rows for r in row["regions_served"]}),
            "currencies": int(frame["currency"].nunique()),
            "scenarios": len(self.scenarios),
            "files": [str(csv_path), str(xlsx_path), str(json_path)],
        }

    def normalized_suppliers(self) -> list[NormalizedSupplier]:
        """Build engine-ready records straight from the generated rows."""
        suppliers = []
        for index, row in enumerate(self.rows, start=2):
            currency = row["currency"]
            rate = self.config.conversion_rate(currency)
            expiration = row["contract_expiration"]
            suppliers.append(
                NormalizedSupplier(
                    row_number=index,
                    supplier_id=row["supplier_id"],
                    supplier_name=row["supplier_name"],
                    materials_supplied=list(row["materials_supplied"]),
                    plants_served=list(row["plants_served"]),
                    regions_served=list(row["regions_served"]),
                    unit_price=row["unit_price"],
                    currency=currency,
                    unit_price_base=round(row["unit_price"] * rate, 4),
                    lead_time_days=row["lead_time_days"],
                    available_capacity=row["available_capacity"],
                    on_time_delivery_rate=row["on_time_delivery_rate"],
                    quality_score=row["quality_score"],
                    defect_rate=row["defect_rate"],
                    risk_score=row["risk_score"],
                    esg_score=row["esg_score"],
                    contract_status=row["contract_status"],
                    contract_expiration=date.fromisoformat(expiration) if expiration else None,
                    payment_terms=row["payment_terms"],
                    historical_order_count=row["historical_order_count"],
                    historical_spend=row["historical_spend"],
                    historical_spend_base=round(row["historical_spend"] * rate, 2),
                )
            )
        return suppliers


CANONICAL_REQUIREMENT: dict[str, Any] = {
    "material": CANONICAL_MATERIAL,
    "material_description": "Precision component, grade A",
    "material_group": "MG10",
    "quantity": 100,
    "unit_of_measure": "PC",
    "plant": "1010",
    "company_code": "1000",
    "required_delivery_date": "2026-10-01",
    "order_date": "2026-08-01",
    "target_price": 120,
    "currency": "EUR",
    "preferred_region": "EU",
    "risk_tolerance": "medium",
    "sustainability_requirement": None,
    "contract_requirement": False,
    "minimum_quality_score": None,
    "minimum_available_capacity": None,
}


def _requirement_from_dict(payload: dict[str, Any]) -> Requirement:
    return Requirement(
        material=payload.get("material"),
        material_description=payload.get("material_description"),
        material_group=payload.get("material_group"),
        quantity=payload.get("quantity"),
        unit_of_measure=payload.get("unit_of_measure"),
        plant=payload.get("plant"),
        company_code=payload.get("company_code"),
        required_delivery_date=date.fromisoformat(payload["required_delivery_date"])
        if payload.get("required_delivery_date")
        else None,
        order_date=date.fromisoformat(payload["order_date"]) if payload.get("order_date") else None,
        target_price=payload.get("target_price"),
        currency=payload.get("currency"),
        preferred_region=payload.get("preferred_region"),
        risk_tolerance=payload.get("risk_tolerance", "medium"),
        sustainability_requirement=payload.get("sustainability_requirement"),
        contract_requirement=payload.get("contract_requirement", False),
        minimum_quality_score=payload.get("minimum_quality_score"),
        minimum_available_capacity=payload.get("minimum_available_capacity"),
    )


def write_observed_baseline(generator: SupplierSampleGenerator, output_dir: Path) -> dict[str, Any]:
    """Run the engine over the generated catalogue and record the result.

    The catalogue is read back from the written CSV through the real reader and
    normaliser, so the baseline is exactly what the API produces - not an
    in-memory shortcut that could drift from the file the API actually parses.
    """
    from app.modules.supplier_reco.normalizer import normalize_supplier_dataframe
    from app.services.files.readers import read_tabular
    from app.services.tabular.mapping import suggest_mapping

    config = generator.config
    content = (output_dir / "sample_suppliers.csv").read_bytes()
    read_result = read_tabular(content, ".csv")
    mapping = suggest_mapping(read_result.source_columns, REGISTRY)
    dataset = normalize_supplier_dataframe(read_result.dataframe, mapping.mapping, config)

    requirement = _requirement_from_dict(CANONICAL_REQUIREMENT)
    result = run_recommendation(dataset.suppliers, requirement, config.default_weights, config)

    top_five = [
        {
            "rank": entry.rank,
            "supplier_id": entry.supplier_id,
            "overall_score": entry.overall_score,
        }
        for entry in result.ranked
        if entry.is_eligible
    ][:5]

    baseline = {
        "note": (
            "Observed output of the current engine on the generated catalogue for the canonical "
            "requirement with default weights. Used by the test suite to detect unintended "
            "changes in the engine or the generator."
        ),
        "seed": SEED,
        "config_version": config.config_version,
        "scoring_engine_version": result.scoring_engine_version,
        "supplier_count": result.total_supplier_count,
        "eligible_count": result.eligible_count,
        "ineligible_count": result.ineligible_count,
        "top_supplier_id": result.top_supplier_id,
        "top_supplier_score": result.top_supplier_score,
        "top_five": top_five,
    }
    (output_dir / "expected_supplier_baseline.json").write_text(
        json.dumps(baseline, indent=2, default=str), encoding="utf-8"
    )
    return baseline


def _manifest_markdown(frame: pd.DataFrame, manifest: dict[str, Any]) -> str:
    lines = [
        "# Supplier sample data - scenario manifest",
        "",
        "**Origin: demo data.** This catalogue is fictional. It was generated by "
        "`scripts/generate_supplier_sample_data.py` and does not come from any SAP system or real "
        "company.",
        "",
        f"- Suppliers: {len(frame):,}",
        f"- Distinct materials referenced: {manifest['supplier_count'] and len({m for m in ';'.join(frame['materials_supplied']).split(';') if m})}",
        f"- Currencies: {frame['currency'].nunique()}",
        f"- Random seed: `{manifest['generated_with_seed']}` (regenerating reproduces the identical "
        "catalogue)",
        "",
        "Most suppliers are ordinary, well-rounded candidates with varied prices, lead times, "
        "quality, capacity, risk, ESG scores, contract status and regions. The anchor suppliers "
        "below are placed deliberately so each eligibility and ranking behaviour is testable.",
        "",
        "## Canonical requirement",
        "",
        "The test suite scores the catalogue against this requirement:",
        "",
        "```json",
        json.dumps(manifest["canonical_requirement"], indent=2),
        "```",
        "",
        "## Anchor suppliers",
        "",
    ]
    for scenario in manifest["scenarios"]:
        lines.extend([
            f"### {scenario['scenario_id']} - {scenario['name']}",
            "",
            f"- Supplier: `{scenario['supplier_id']}`",
            f"- {scenario['description']}",
            f"- **Expected effect:** {scenario['expects']}",
            "",
        ])
    lines.extend([
        "## How the test suite uses this file",
        "",
        "`tests/integration/test_supplier_sample_data.py` uploads this catalogue, runs the "
        "canonical requirement and asserts that each anchor behaves as documented, that the "
        "ranking reproduces `expected_supplier_baseline.json`, and that repeated runs are "
        "identical.",
        "",
        "## A note on the figures",
        "",
        "Scores and ranking are produced by the deterministic weighted-scoring model in "
        "`app/modules/supplier_reco`. Estimated costs and delivery dates are indicative planning "
        "figures, not quotations, and nothing here has been validated in a live SAP environment.",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    generator = SupplierSampleGenerator()
    generator.build()
    stats = generator.write(settings.sample_dir)
    baseline = write_observed_baseline(generator, settings.sample_dir)

    logger.info(
        "Generated %d suppliers across %d materials, %d scenarios",
        stats["suppliers"], stats["materials"], stats["scenarios"],
    )
    print(json.dumps(stats, indent=2))
    print(
        f"canonical: {baseline['eligible_count']}/{baseline['supplier_count']} eligible | "
        f"top {baseline['top_supplier_id']} ({baseline['top_supplier_score']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
