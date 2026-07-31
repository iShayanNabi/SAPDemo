"""Generate the fictional demo process definitions for the Test Case Generator.

Run with::

    python scripts/generate_test_case_sample_data.py

Outputs into ``data/sample/``:

* ``sample_test_case_processes.json``   - four fictional SAP process definitions
* ``test_case_scenario_manifest.json``  - the documented expectations
* ``TEST_CASE_SCENARIO_MANIFEST.md``    - the same, readable
* ``expected_test_case_baseline.json``  - what the current engine produces

**Every process here is fiction.** The company, the plants, the material and
vendor numbers, the roles and the interface names were invented for this lab.
Nothing comes from a real SAP system, and neither the generator nor the module
contacts one.

Modules 1-7 ship *datasets* with anomalies planted in them. This module has no
dataset: its input is a form. What is planted here instead is a set of process
definitions chosen so that every deterministic decision the generator makes is
observable and can be asserted:

* ``p2p_standard_po``   - a financially sensitive, heavily integrated process:
                          the priority escalation rules fire on all three
                          signals (keywords, integrations, roles)
* ``pm_notification``   - a quiet, single-role process with no integration and
                          no financial keyword: the negative control, where
                          nothing escalates
* ``migration_vendor``  - a data migration cutover, requested with more test
                          types than test cases, so the *uncovered types* path
                          is exercised and reported - and the type it lists
                          first survives the shortfall
* ``fiori_approval``    - an approval app with many roles: the role-count
                          escalation fires for the access test types only

The baseline is recorded from the engine running in **mock mode with AI turned
off**, so it records the deterministic half of the module: identifiers, type
allocation, priorities, step counts and coverage. Those are exactly the things
that must not move when a provider, a key or a model changes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import settings  # noqa: E402
from app.core.logging import get_logger  # noqa: E402
from app.modules.test_case_generator.engine import (  # noqa: E402
    ENGINE_VERSION,
    generate_suite,
)
from app.modules.test_case_generator.thresholds import get_test_case_config  # noqa: E402
from app.schemas.test_case_generator import ProcessContextSchema, TestType  # noqa: E402

logger = get_logger("generate_test_case_sample_data")

PROCESSES: list[dict[str, Any]] = [
    {
        "name": "p2p_standard_po",
        "title": "Procure to Pay - standard purchase order",
        "summary": (
            "The financially sensitive, heavily integrated process. Its description mentions "
            "invoices, goods receipts and payments, it names four integrations and four roles, "
            "so every configured priority escalation signal fires."
        ),
        "suggested_test_types": ["sit", "uat", "negative", "integration", "regression"],
        "suggested_test_case_count": 10,
        "context": {
            "sap_product": "SAP S/4HANA 2023 (on premise)",
            "sap_module": "MM - Materials Management",
            "business_process": "Procure to Pay - standard purchase order",
            "process_description": (
                "A requisitioner raises a purchase requisition for a stock material at plant "
                "1010. The requisition is released according to the release strategy, a buyer "
                "converts it into a standard purchase order, and the order is sent to the "
                "supplier. The warehouse posts a goods receipt against the order, accounts "
                "payable posts the supplier invoice with a three-way match, and the payment run "
                "settles the open item. Purchase orders above 10,000 EUR require a second "
                "release before they can be sent."
            ),
            "preconditions": [
                "Vendor 100234 (Nordwind Industrie GmbH, fictional) exists and is not blocked.",
                "Material 100001 exists in plant 1010 with a valid purchasing info record.",
                "The release strategy for purchasing group 010 is active in the test client.",
                "The tester holds the roles listed below in the test client only.",
            ],
            "business_rules": [
                "A purchase order above 10,000 EUR requires a second release before output.",
                "The invoice price may deviate from the purchase order price by at most 2%.",
                "The invoiced quantity may not exceed the received quantity.",
                "A goods receipt is mandatory before invoice posting for stock materials.",
            ],
            "systems_involved": [
                "SAP S/4HANA 2023",
                "SAP Ariba Buying (fictional test tenant)",
                "House bank payment gateway (fictional)",
            ],
            "integrations": [
                "Requisition replication from SAP Ariba Buying",
                "Purchase order output to the supplier portal",
                "Payment file to the house bank gateway",
                "Invoice image archive link",
            ],
            "user_roles": [
                "Requisitioner",
                "Purchasing buyer",
                "Warehouse clerk",
                "Accounts payable clerk",
            ],
            "test_data_requirements": [
                "Vendor 100234 with payment terms Z030 and currency EUR.",
                "Material 100001, base unit PC, standard price 42.50 EUR.",
                "One requisition below 10,000 EUR and one above it.",
                "A supplier invoice PDF for the archive link check.",
            ],
        },
    },
    {
        "name": "pm_notification",
        "title": "Plant maintenance - raise a maintenance notification",
        "summary": (
            "The negative control. One role, no integration, no financial vocabulary, so no "
            "escalation rule fires and every test case keeps its test type's base priority."
        ),
        "suggested_test_types": ["sit", "uat", "negative"],
        "suggested_test_case_count": 6,
        "context": {
            "sap_product": "SAP S/4HANA 2023 (on premise)",
            "sap_module": "PM - Plant Maintenance",
            "business_process": "Raise a maintenance notification for equipment",
            "process_description": (
                "A technician notices a fault on a piece of equipment and raises a maintenance "
                "notification describing the problem. The notification records the equipment "
                "number, the functional location and the fault text. A maintenance planner "
                "reviews the notification and either accepts it into planning or returns it "
                "with a reason."
            ),
            "preconditions": [
                "Equipment 10000042 (fictional) exists and is assigned to functional location "
                "PLANT-1010-LINE-A.",
                "Notification type M1 is active in the test client.",
            ],
            "business_rules": [
                "A notification must name an equipment number or a functional location.",
                "A notification returned by the planner must carry a reason text.",
            ],
            "systems_involved": ["SAP S/4HANA 2023"],
            "integrations": [],
            "user_roles": ["Maintenance technician"],
            "test_data_requirements": [
                "Equipment 10000042 with a valid functional location.",
                "One fault description of at least 20 characters.",
            ],
        },
    },
    {
        "name": "migration_vendor",
        "title": "Vendor master migration - cutover load",
        "summary": (
            "A cutover load, deliberately requested with more test types than test cases so "
            "the uncovered-type path is exercised: the types listed last go without a case, "
            "the type listed first survives, and the shortfall is reported rather than "
            "silently absorbed."
        ),
        "suggested_test_types": [
            "data_migration",
            "sit",
            "negative",
            "authorization",
            "security",
            "regression",
        ],
        "suggested_test_case_count": 4,
        "context": {
            "sap_product": "SAP S/4HANA 2023 (on premise)",
            "sap_module": "MDG - Master Data Governance",
            "business_process": "Vendor master migration - cutover load",
            "process_description": (
                "The signed-off vendor extract from the legacy system is loaded into the new "
                "client using the agreed migration object. Bank details and tax numbers are "
                "mapped field by field. Records that fail validation are written to an error "
                "file, corrected by the data team and reloaded. The load is reconciled against "
                "the source record count and control totals before the cutover is signed off."
            ),
            "preconditions": [
                "The legacy vendor extract is signed off and its control totals are recorded.",
                "The migration object and its field mapping template are released.",
                "The target client is closed to all other postings during the load window.",
            ],
            "business_rules": [
                "Loaded records plus rejected records must equal the source record count.",
                "A vendor without a tax number may not be loaded as payment-relevant.",
                "Bank details must reconcile to the source down to the IBAN check digits.",
            ],
            "systems_involved": [
                "SAP S/4HANA 2023",
                "Legacy vendor system (fictional)",
            ],
            "integrations": ["Legacy extract file transfer"],
            "user_roles": ["Data migration lead", "Master data steward"],
            "test_data_requirements": [
                "The signed-off legacy extract with its recorded control totals.",
                "A documented sample of 25 vendors for the field-mapping check.",
                "Three records known to fail validation, for the error-file check.",
            ],
        },
    },
    {
        "name": "fiori_approval",
        "title": "Fiori purchase requisition approval",
        "summary": (
            "An approval app with six roles and no financial posting. Only the access-related "
            "test types escalate, which is what the role-count rule is for."
        ),
        "suggested_test_types": ["uat", "authorization", "security", "negative"],
        "suggested_test_case_count": 8,
        "context": {
            "sap_product": "SAP S/4HANA 2023 with SAP Fiori launchpad",
            "sap_module": "MM - Materials Management (Fiori)",
            "business_process": "Approve a purchase requisition in the Fiori inbox",
            "process_description": (
                "A requisition awaiting release appears in the approver's Fiori inbox. The "
                "approver reviews the item, the quantity and the requested delivery date, then "
                "releases or rejects the requisition. A rejected requisition returns to the "
                "requisitioner with a mandatory reason. Substitution rules let a deputy act "
                "while the approver is absent."
            ),
            "preconditions": [
                "The Fiori launchpad is reachable and the inbox tile is assigned to the role.",
                "At least one requisition is waiting for release for the tested approver.",
                "The substitution rule for the deputy is maintained in the test client.",
            ],
            "business_rules": [
                "A rejection requires a reason text of at least 10 characters.",
                "An approver may not release their own requisition.",
                "A deputy may only act while a substitution is active.",
            ],
            "systems_involved": [
                "SAP S/4HANA 2023",
                "SAP Fiori launchpad",
            ],
            "integrations": ["Notification e-mail to the requisitioner"],
            "user_roles": [
                "Requisitioner",
                "Cost centre approver",
                "Department head",
                "Deputy approver",
                "Purchasing buyer",
                "Launchpad administrator",
            ],
            "test_data_requirements": [
                "One requisition awaiting release for the tested approver.",
                "One requisition raised by the approver themselves.",
                "An active substitution rule for the deputy.",
            ],
        },
    },
]


def build_processes_payload() -> dict[str, Any]:
    """The demo process definitions, ready to post to ``/test-cases/generate``."""
    return {
        "description": (
            "Fictional SAP process definitions for the Test Case Generator. Every company, "
            "plant, material, vendor, role and interface below was invented for this lab. "
            "Nothing was taken from a real SAP system."
        ),
        "manifest": "test_case_scenario_manifest.json",
        "generated_by": "scripts/generate_test_case_sample_data.py",
        "processes": PROCESSES,
    }


def observed_baseline() -> dict[str, Any]:
    """Record what the engine produces for each demo process.

    Deliberately run with ``use_ai=False``: the baseline records the
    deterministic half of the module - identifiers, allocation, priorities, step
    counts and coverage - which must not move when a provider, an API key or a
    model changes. The drafted prose is not a baseline-able thing and is not
    recorded here.
    """
    config = get_test_case_config()
    entries: dict[str, Any] = {}

    for process in PROCESSES:
        context = ProcessContextSchema.model_validate(process["context"])
        test_types = [TestType(name) for name in process["suggested_test_types"]]
        count = int(process["suggested_test_case_count"])
        result = generate_suite(context, test_types, count, config, use_ai=False)

        entries[process["name"]] = {
            "requested_test_types": [item.value for item in test_types],
            "requested_count": count,
            "allocation": {
                test_type.value: number
                for test_type, number in result.plan.allocation.items()
            },
            "uncovered_test_types": [item.value for item in result.plan.uncovered_types],
            "keyword_hits": sorted(result.plan.signals.keyword_hits),
            "integration_count": result.plan.signals.integration_count,
            "role_count": result.plan.signals.role_count,
            "test_case_count": len(result.cases),
            "note_count": len(result.notes),
            "test_cases": [
                {
                    "test_case_id": case.slot.slot_id,
                    "test_type": case.slot.test_type.value,
                    "priority": case.slot.priority.value,
                    "focus": case.slot.focus,
                    "owner": case.slot.owner,
                    "step_count": len(case.steps),
                    "source": case.source.value,
                }
                for case in result.cases
            ],
        }

    return {
        "description": (
            "What the deterministic half of the engine produces for each demo process, with "
            "AI drafting switched off. Recorded by "
            "scripts/generate_test_case_sample_data.py."
        ),
        "config_version": config.config_version,
        "engine_version": ENGINE_VERSION,
        "processes": entries,
    }


def build_manifest(baseline: dict[str, Any]) -> dict[str, Any]:
    """The documented expectations the integration tests assert against."""
    scenarios = [
        {
            "id": "TCG-S001",
            "process": "p2p_standard_po",
            "condition": "All three priority escalation signals fire",
            "expectation": (
                "The process description contains configured escalation keywords, four "
                "integrations are named (>= the threshold of 3) and four roles are named "
                "(>= the threshold of 4)."
            ),
            "assert": "keyword_hits is not empty, integration_count >= 3, role_count >= 4",
        },
        {
            "id": "TCG-S002",
            "process": "p2p_standard_po",
            "condition": "System integration tests are escalated above their base priority",
            "expectation": (
                "SIT has a base priority of high and the keyword rule applies to it, so every "
                "SIT case in this suite is critical."
            ),
            "assert": "every sit test case has priority 'critical'",
        },
        {
            "id": "TCG-S003",
            "process": "pm_notification",
            "condition": "Nothing escalates for a quiet process",
            "expectation": (
                "No escalation keyword appears, no integration is named and one role is named, "
                "so every case keeps its test type's configured base priority."
            ),
            "assert": (
                "keyword_hits is empty and every test case priority equals the configured "
                "base priority of its type"
            ),
        },
        {
            "id": "TCG-S004",
            "process": "migration_vendor",
            "condition": "More test types requested than test cases",
            "expectation": (
                "Six types are requested and four cases are asked for, so the two types listed "
                "last receive no case, are reported as uncovered and produce a note. The "
                "headline type of the process - data migration, listed first - is kept."
            ),
            "assert": (
                "uncovered_test_types == ['security', 'regression'], note_count >= 1, and a "
                "data_migration case exists"
            ),
        },
        {
            "id": "TCG-S005",
            "process": "fiori_approval",
            "condition": "Only the access test types escalate on role count",
            "expectation": (
                "Six roles are named, so authorization and security escalate one level; the "
                "process description contains no financial keyword, so UAT does not."
            ),
            "assert": (
                "authorization and security cases are above their base priority while uat "
                "cases are at theirs"
            ),
        },
        {
            "id": "TCG-S006",
            "process": "all",
            "condition": "Every planned case is complete without any AI",
            "expectation": (
                "With drafting switched off, every case is built from the configured templates "
                "and still has at least the configured minimum number of steps."
            ),
            "assert": "every test case has source 'template' and step_count >= min_steps",
        },
        {
            "id": "TCG-S007",
            "process": "all",
            "condition": "Identifiers are unique and typed",
            "expectation": (
                "Each identifier follows the configured template and carries its test type's "
                "id_code, numbered from 1 within the type."
            ),
            "assert": "test_case_id values are unique per suite and match the type's id_code",
        },
    ]
    return {
        "description": (
            "Documented expectations for the Test Case Generator demo processes. Every "
            "condition below is asserted by tests/integration/test_test_case_sample_data.py."
        ),
        "config_version": baseline["config_version"],
        "engine_version": baseline["engine_version"],
        "processes": [
            {
                "name": item["name"],
                "title": item["title"],
                "summary": item["summary"],
                "suggested_test_types": item["suggested_test_types"],
                "suggested_test_case_count": item["suggested_test_case_count"],
            }
            for item in PROCESSES
        ],
        "scenarios": scenarios,
    }


def build_markdown(manifest: dict[str, Any], baseline: dict[str, Any]) -> str:
    """Render the manifest as readable Markdown."""
    lines = [
        "# Test Case Generator - demo process manifest",
        "",
        "Every process below is **fiction**. The company, plants, material and vendor numbers, "
        "roles and interface names were invented for this lab. Nothing here comes from a real "
        "SAP system, and no output has been validated in one.",
        "",
        f"Configuration version: `{manifest['config_version']}` - "
        f"engine version: `{manifest['engine_version']}`",
        "",
        "Regenerate with:",
        "",
        "```bash",
        "python scripts/generate_test_case_sample_data.py",
        "```",
        "",
        "---",
        "",
        "## Demo processes",
        "",
        "| Name | Title | Types | Cases | Why it is here |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in manifest["processes"]:
        lines.append(
            f"| `{item['name']}` | {item['title']} | "
            f"{', '.join(item['suggested_test_types'])} | "
            f"{item['suggested_test_case_count']} | {item['summary']} |"
        )

    lines += [
        "",
        "---",
        "",
        "## Documented scenarios",
        "",
        "| ID | Process | Condition | Expectation |",
        "| --- | --- | --- | --- |",
    ]
    for scenario in manifest["scenarios"]:
        lines.append(
            f"| {scenario['id']} | `{scenario['process']}` | {scenario['condition']} | "
            f"{scenario['expectation']} |"
        )

    lines += [
        "",
        "---",
        "",
        "## Recorded baseline (AI drafting off)",
        "",
        "The baseline records the **deterministic** half of the module only: identifiers, type "
        "allocation, priorities, focus areas, owners and step counts. Those must not move when "
        "a provider, an API key or a model changes. Drafted prose is not recorded, because it "
        "is the one part that is allowed to differ.",
        "",
        "| Process | Cases | Allocation | Priorities |",
        "| --- | --- | --- | --- |",
    ]
    for name, entry in baseline["processes"].items():
        priorities: dict[str, int] = {}
        for case in entry["test_cases"]:
            priorities[case["priority"]] = priorities.get(case["priority"], 0) + 1
        allocation = ", ".join(
            f"{key} {value}" for key, value in sorted(entry["allocation"].items())
        )
        priority_text = ", ".join(
            f"{key} {value}" for key, value in sorted(priorities.items())
        )
        lines.append(
            f"| `{name}` | {entry['test_case_count']} | {allocation} | {priority_text} |"
        )

    lines += [
        "",
        "> These are draft test cases produced from a typed process description. They have not "
        "been executed or validated in a live SAP system.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    """Write the demo processes, the manifest and the baseline."""
    directory = settings.sample_dir
    directory.mkdir(parents=True, exist_ok=True)

    (directory / "sample_test_case_processes.json").write_text(
        json.dumps(build_processes_payload(), indent=2, ensure_ascii=False), encoding="utf-8"
    )

    baseline = observed_baseline()
    (directory / "expected_test_case_baseline.json").write_text(
        json.dumps(baseline, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    manifest = build_manifest(baseline)
    (directory / "test_case_scenario_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (directory / "TEST_CASE_SCENARIO_MANIFEST.md").write_text(
        build_markdown(manifest, baseline), encoding="utf-8"
    )

    logger.info(
        "Generated %d demo process definitions (%d scenarios)",
        len(PROCESSES),
        len(manifest["scenarios"]),
    )
    print(
        json.dumps(
            {
                "processes": len(PROCESSES),
                "scenarios": len(manifest["scenarios"]),
                "files_written": 4,
                "config_version": baseline["config_version"],
            },
            indent=2,
        )
    )
    for name, entry in baseline["processes"].items():
        priorities = ", ".join(
            sorted({case["priority"] for case in entry["test_cases"]})
        )
        uncovered = ", ".join(entry["uncovered_test_types"]) or "-"
        print(
            f"{name:18} {entry['test_case_count']:>2} cases | priorities: {priorities:<22} "
            f"| uncovered: {uncovered}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
