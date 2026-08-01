"""Generate the bundled SAP Interview Coach question bank, manifest and baseline.

Run with::

    python scripts/generate_interview_sample_data.py

Everything this script writes is **entirely fictional**. The questions are the
kind an SAP procurement or architecture interview really asks, but no question,
company, scenario or reference answer here comes from a real interview, a real
customer or any SAP certification scheme.

Three files are produced in ``data/sample/``:

``sample_interview_questions.json``
    The question bank: over a hundred questions across nine tracks, each with
    its expected concepts, its keyword lists, its known-wrong statements, its
    follow-ups and a reference answer.
``interview_scenario_manifest.json`` / ``INTERVIEW_SCENARIO_MANIFEST.md``
    The documented anchors - specific questions with a strong, a partial, a
    wrong and a non-answer, and what the rubric is expected to do with each.
``expected_interview_baseline.json``
    What the real engine actually produces for those anchors today.

The generator is deterministic and does two things that a plain data dump would
not:

* **It marks every reference answer against its own rubric before writing.**
  A model answer that does not match its own keyword list is a bank bug, not a
  scoring bug, and it would show up as a candidate mysteriously losing marks for
  saying exactly the right thing. The build fails loudly instead. This is the
  "run the thing" lesson applied to the data.
* **It builds the baseline by reading the written file back through the real
  loader**, never from the in-memory literals - module 3's lesson. A value that
  survives in memory and changes on the round trip is exactly the kind of
  disagreement a recorded baseline exists to catch.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import PROJECT_ROOT  # noqa: E402
from app.modules.interview_coach.question_bank import load_question_bank  # noqa: E402
from app.modules.interview_coach.scoring import score_answer  # noqa: E402
from app.modules.interview_coach.thresholds import get_interview_config  # noqa: E402
from app.schemas.interview_coach import InterviewMode  # noqa: E402

SAMPLE_DIR = PROJECT_ROOT / "data" / "sample"
BANK_FILE = SAMPLE_DIR / "sample_interview_questions.json"
MANIFEST_JSON = SAMPLE_DIR / "interview_scenario_manifest.json"
MANIFEST_MD = SAMPLE_DIR / "INTERVIEW_SCENARIO_MANIFEST.md"
BASELINE_FILE = SAMPLE_DIR / "expected_interview_baseline.json"

#: Bump whenever a keyword list, a weight or a penalty changes. Every stored
#: score records the rubric fingerprint it was marked against, so retuning the
#: bank flags old scores as stale rather than silently mixing marking schemes.
BANK_VERSION = "1.0.0"

MANIFEST_NOTE = (
    "Every question, scenario, company and reference answer in this bank is fictional. "
    "Nothing here is an SAP certification question, and no answer has been reviewed by SAP."
)


# ---------------------------------------------------------------------------
# Authoring helpers
# ---------------------------------------------------------------------------


def c(
    concept_id: str,
    label: str,
    dimension: str,
    keywords: Sequence[str],
    *,
    weight: float = 1.0,
    required: bool = False,
    hint: str = "",
    negations: Sequence[str] = (),
) -> dict[str, Any]:
    """Author one expected concept."""
    return {
        "concept_id": concept_id,
        "label": label,
        "dimension": dimension,
        "weight": weight,
        "required": required,
        "keywords": list(keywords),
        "negation_patterns": list(negations),
        "study_hint": hint,
    }


def w(
    statement_id: str,
    label: str,
    patterns: Sequence[str],
    correction: str,
    *,
    penalty: float = 10.0,
) -> dict[str, Any]:
    """Author one known-wrong statement."""
    return {
        "statement_id": statement_id,
        "label": label,
        "patterns": list(patterns),
        "correction": correction,
        "penalty_points": penalty,
    }


def f(text: str, targets: str | None = None) -> dict[str, Any]:
    """Author one follow-up question, optionally aimed at a concept."""
    return {"text": text, "targets_concept_id": targets}


def q(
    question_id: str,
    track: str,
    topic: str,
    difficulty: str,
    modes: Sequence[str],
    question: str,
    concepts: Sequence[dict[str, Any]],
    reference: str,
    follow_ups: Sequence[dict[str, Any]] = (),
    *,
    wrong: Sequence[dict[str, Any]] = (),
    study_topics: Sequence[str] = (),
    tags: Sequence[str] = (),
    rubric_summary: str = "",
) -> dict[str, Any]:
    """Author one complete interview question."""
    return {
        "question_id": question_id,
        "track": track,
        "topic": topic,
        "difficulty": difficulty,
        "modes": list(modes),
        "question": question,
        "expected_concepts": list(concepts),
        "incorrect_statements": list(wrong),
        "follow_up_questions": list(follow_ups),
        "reference_answer": " ".join(reference.split()),
        "rubric": {
            "summary": rubric_summary
            or "Cover each expected concept, stay accurate, and explain why it matters.",
            "weights": {},
            "pass_score": None,
        },
        "study_topics": list(study_topics),
        "tags": list(tags),
    }


# Mode shorthands, so a question's mode list stays readable.
ALL_PRACTICE = ["practice", "timed"]
TECH = ["practice", "timed", "technical"]
TECH_RAPID = ["practice", "timed", "technical", "rapid_fire"]
ARCH = ["practice", "timed", "technical", "architecture"]
BEHAVE = ["practice", "timed", "behavioral"]
JUDGEMENT = ["practice", "timed", "behavioral"]
PRACTICE_RAPID = ["practice", "timed", "rapid_fire"]
RAPID = ["practice", "rapid_fire"]


def build_questions() -> list[dict[str, Any]]:
    """Return the complete authored question bank, in a stable order."""
    questions: list[dict[str, Any]] = []
    for builder in (
        sap_mm_questions,
        sap_ariba_questions,
        sap_s4hana_questions,
        sap_business_network_questions,
        sap_integration_questions,
        sap_architecture_questions,
        procurement_questions,
        supply_chain_questions,
        sap_consulting_questions,
    ):
        questions.extend(builder())
    return questions


# ---------------------------------------------------------------------------
# Track 1 - SAP MM
# ---------------------------------------------------------------------------


def sap_mm_questions() -> list[dict[str, Any]]:
    """Materials management: documents, master data, valuation and the flow."""
    return [
        q(
            "IQ-MM-001", "sap_mm", "Purchasing documents", "foundational", TECH_RAPID,
            "What is the difference between a purchase requisition and a purchase order, "
            "and who owns each one?",
            [
                c("pr_internal", "A purchase requisition is an internal request for a need",
                  "technical", ["purchase requisition", "internal request"],
                  weight=1.5, required=True,
                  hint="Say explicitly that the requisition never reaches the supplier."),
                c("po_external", "A purchase order is the external document sent to the supplier",
                  "technical", ["purchase order", "sent to the supplier"],
                  weight=1.5, required=True),
                c("conversion", "A requisition becomes an order once a source of supply is assigned",
                  "technical", ["source of supply", "converted"]),
                c("ownership", "The requisitioner raises the demand, the buyer owns the order",
                  "business", ["requisitioner", "buyer"], weight=1.2,
                  hint="Name the two roles and what each is accountable for."),
            ],
            "A purchase requisition is an internal request that records a need and stays "
            "inside the company. A buyer reviews it, assigns a source of supply and it is "
            "then converted into a purchase order, which is the external document sent to "
            "the supplier and which commits the company commercially. The requisitioner "
            "raises the demand; the buyer owns the order and the terms on it.",
            [
                f("Who is allowed to change the price after the order has been sent?", "po_external"),
                f("What happens to the requisition once the order exists?", "conversion"),
            ],
            wrong=[
                w("pr_to_supplier",
                  "The requisition is described as going to the supplier.",
                  ["requisition is sent to the supplier", "requisition goes to the supplier"],
                  "The requisition is internal. Only the purchase order reaches the supplier."),
            ],
            study_topics=["Purchasing document types", "Procure to pay document flow"],
        ),
        q(
            "IQ-MM-002", "sap_mm", "Release strategies", "intermediate", TECH,
            "How does a release strategy work in SAP MM, and what drives which strategy "
            "a document picks up?",
            [
                c("characteristics", "Release strategies are driven by characteristics and a class",
                  "technical", ["characteristics", "classification"], weight=1.5, required=True),
                c("release_codes", "Release codes represent the approvers and their sequence",
                  "technical", ["release code", "sequence"], weight=1.3),
                c("value_driver", "Document value is the usual driver, alongside plant or group",
                  "technical", ["document value", "purchasing group"]),
                c("control", "The point is spend control and segregation of duties",
                  "business", ["spend control", "segregation of duties"], weight=1.2),
            ],
            "A release strategy is assigned by matching a document against characteristics "
            "held in a classification: typically document value, purchasing group, plant or "
            "material group. Each strategy holds release codes that represent the approvers, "
            "and the sequence decides whether they approve in parallel or one after another. "
            "The business purpose is spend control and segregation of duties, so that the "
            "person who raises a commitment is not the person who approves it.",
            [
                f("What happens to an approved order when its value is increased?", "value_driver"),
                f("How would you approve in parallel rather than in sequence?", "release_codes"),
            ],
            wrong=[
                w("release_is_workflow",
                  "Release strategy is described as being the same thing as workflow.",
                  ["release strategy is just workflow", "release strategy is the same as workflow"],
                  "A release strategy decides who must approve; workflow is one way of "
                  "delivering that approval to them. They are configured separately."),
            ],
            study_topics=["Release strategies", "Classification"],
        ),
        q(
            "IQ-MM-003", "sap_mm", "Three-way match", "intermediate", TECH,
            "Explain the three-way match in SAP and what the GR/IR account is doing "
            "in the middle of it.",
            [
                c("three_documents", "The match compares the order, the goods receipt and the invoice",
                  "technical", ["purchase order", "goods receipt", "invoice"],
                  weight=1.6, required=True),
                c("gr_ir", "GR/IR is a clearing account that holds the value between receipt and invoice",
                  "technical", ["GR/IR", "clearing account"], weight=1.5, required=True,
                  hint="Say what sits in the account and what clears it."),
                c("tolerances", "Tolerances decide whether a difference blocks the invoice",
                  "technical", ["tolerance", "blocked"], weight=1.2),
                c("why_it_matters", "It stops payment for goods that were never received",
                  "business", ["never received", "paying"], weight=1.3),
            ],
            "The three-way match compares the purchase order, the goods receipt and the "
            "supplier invoice on quantity and price. When the goods receipt is posted the "
            "value goes to the GR/IR clearing account rather than straight to the supplier, "
            "and the invoice clears that account when it arrives. If quantity or price fall "
            "outside the configured tolerance the invoice is blocked for payment until "
            "somebody resolves it. The point is that the company avoids paying for goods it "
            "never received, and an old GR/IR balance is a reliable sign that one of the "
            "three documents is missing.",
            [
                f("What does a large aged GR/IR balance usually tell you?", "gr_ir"),
                f("When would a two-way match be the right choice instead?", "three_documents"),
            ],
            wrong=[
                w("grir_is_pl",
                  "GR/IR is described as a profit and loss account.",
                  ["GR/IR is a profit and loss account", "GR/IR is a P&L account"],
                  "GR/IR is a balance sheet clearing account, not a profit and loss account."),
            ],
            study_topics=["Three-way match", "GR/IR clearing", "Invoice verification"],
        ),
        q(
            "IQ-MM-004", "sap_mm", "Material master", "foundational", TECH_RAPID,
            "Why is the material master organised into views, and what problem does that "
            "solve on a real project?",
            [
                c("views_by_function", "Views hold the data one function owns",
                  "technical", ["views", "purchasing", "accounting"], weight=1.5, required=True),
                c("org_levels", "Data is held at different organisational levels",
                  "technical", ["plant", "client level"], weight=1.3),
                c("ownership", "Different departments maintain different views",
                  "business", ["maintained by", "departments"], weight=1.2,
                  hint="Name who maintains which view."),
                c("consequence", "Missing a view blocks a transaction later in the process",
                  "business", ["blocked", "cannot be"], weight=1.2),
            ],
            "The material master is split into views because each function owns different "
            "data about the same material: the purchasing view, the accounting view, the "
            "sales view and the storage views are all maintained by the departments that "
            "understand them. The data also sits at different organisational levels, so "
            "description is held at client level while others are held per plant. On a "
            "project this matters because a material with no purchasing view for a plant "
            "cannot be ordered there, and the transaction is blocked at exactly the moment "
            "somebody needs it.",
            [
                f("Which view would you check first if a material cannot be ordered in one plant?",
                  "org_levels"),
                f("Who should own material master governance after go-live?", "ownership"),
            ],
            study_topics=["Material master", "Master data governance"],
        ),
        q(
            "IQ-MM-005", "sap_mm", "Outline agreements", "intermediate", TECH_RAPID,
            "When would you use a contract rather than a scheduling agreement, and what "
            "changes operationally?",
            [
                c("contract_release", "A contract is called off with release orders",
                  "technical", ["contract", "release order"], weight=1.5, required=True),
                c("schedule_lines", "A scheduling agreement carries delivery schedule lines",
                  "technical", ["scheduling agreement", "schedule lines"],
                  weight=1.5, required=True),
                c("target_value", "A contract holds a target quantity or value, not a delivery plan",
                  "technical", ["target quantity", "target value"]),
                c("when_to_use", "Steady, predictable demand suits a schedule; sporadic demand suits a contract",
                  "business", ["predictable", "sporadic"], weight=1.3),
            ],
            "A contract records agreed commercial terms against a target quantity or target "
            "value, and each requirement is called off against it with a release order. A "
            "scheduling agreement instead carries schedule lines with dates and quantities, "
            "so the supplier is told the delivery plan directly and no separate order is "
            "needed. Predictable, repeating demand for a production material suits a "
            "scheduling agreement; sporadic demand across many materials suits a contract, "
            "because nobody has to maintain a delivery plan that will not hold.",
            [
                f("How does the supplier learn what to deliver under each of the two?",
                  "schedule_lines"),
                f("What happens when the target value of a contract is exhausted?", "target_value"),
            ],
            study_topics=["Outline agreements", "Contracts and scheduling agreements"],
        ),
        q(
            "IQ-MM-006", "sap_mm", "Inventory movements", "advanced", TECH,
            "What does a movement type actually control, and why do projects get it wrong?",
            [
                c("what_it_controls", "The movement type controls the accounts, the fields and the stock update",
                  "technical", ["account determination", "stock"], weight=1.6, required=True),
                c("reversals", "Movement types come in pairs, one to post and one to reverse",
                  "technical", ["reversal", "pairs"], weight=1.2),
                c("special_stock", "Special stock indicators change what the same movement means",
                  "technical", ["special stock", "consignment"], weight=1.3),
                c("reporting", "Choosing the wrong one distorts inventory reporting and valuation",
                  "business", ["reporting", "valuation"], weight=1.3),
            ],
            "A movement type controls what happens when stock moves: which stock type is "
            "updated, which fields the posting asks for and which accounts the account "
            "determination picks. They exist in pairs so every posting has a reversal, and a "
            "special stock indicator changes the meaning of the same movement, which is how "
            "consignment and subcontracting stock stay separate from own stock. Projects get "
            "it wrong by copying a movement type without following the account determination "
            "behind it, and the damage shows up later as inventory reporting and valuation "
            "that nobody can reconcile.",
            [
                f("How would you investigate a posting that hit an unexpected account?",
                  "what_it_controls"),
                f("Why does consignment stock need its own indicator?", "special_stock"),
            ],
            study_topics=["Movement types", "Account determination"],
        ),
        q(
            "IQ-MM-007", "sap_mm", "Valuation", "advanced", TECH,
            "What is split valuation for, and what does it cost you to run it?",
            [
                c("separate_values", "Split valuation values one material at different prices",
                  "technical", ["split valuation", "valuation types"], weight=1.6, required=True),
                c("valuation_category", "A valuation category defines the allowed valuation types",
                  "technical", ["valuation category"], weight=1.3),
                c("use_cases", "Typical drivers are origin, quality grade or new versus refurbished",
                  "technical", ["refurbished", "origin"], weight=1.2),
                c("cost", "It complicates procurement, stock reporting and daily transactions",
                  "business", ["complicates", "every transaction"], weight=1.4,
                  hint="An interviewer wants the downside, not just the definition."),
            ],
            "Split valuation lets one material number carry more than one value at the same "
            "time, using valuation types grouped under a valuation category. It is the right "
            "answer when the same material is genuinely worth different amounts depending on "
            "origin, quality grade or whether it is new or refurbished. The cost is that it "
            "complicates every transaction that touches the material, because each posting "
            "has to name a valuation type, and stock reporting has to be read one valuation "
            "type at a time.",
            [
                f("What would you propose instead if the driver is only reporting?", "cost"),
                f("Can split valuation be switched on for a material that already has stock?",
                  "valuation_category"),
            ],
            study_topics=["Split valuation", "Material valuation"],
        ),
        q(
            "IQ-MM-008", "sap_mm", "Source determination", "intermediate", TECH,
            "How does SAP decide which supplier a requisition should go to?",
            [
                c("source_list", "The source list records the allowed sources for a material and plant",
                  "technical", ["source list"], weight=1.5, required=True),
                c("quota", "A quota arrangement splits volume across several sources",
                  "technical", ["quota arrangement"], weight=1.3),
                c("info_record", "The purchasing info record supplies the price and terms",
                  "technical", ["info record"], weight=1.3),
                c("why", "Automating this is what keeps buyers off routine orders",
                  "business", ["automates", "routine"], weight=1.2),
            ],
            "Source determination looks at the source list for that material and plant, which "
            "records which suppliers are allowed and whether one of them is fixed. When more "
            "than one is allowed a quota arrangement can split the volume between them, and "
            "the purchasing info record supplies the price and the terms once a source is "
            "chosen. Getting this right is what automates routine ordering, so buyers spend "
            "their time on negotiation rather than on assigning sources by hand.",
            [
                f("What would you check first when a requisition finds no source?", "source_list"),
                f("How does a quota arrangement decide who gets the next order?", "quota"),
            ],
            study_topics=["Source determination", "Purchasing info records"],
        ),
        q(
            "IQ-MM-009", "sap_mm", "Invoice verification", "advanced", TECH,
            "An invoice is blocked for payment. Walk me through how you would work out why "
            "and what you would do about it.",
            [
                c("block_reasons", "Blocks come from price, quantity, date or amount differences",
                  "technical", ["price", "quantity", "date"], weight=1.5, required=True),
                c("tolerance_keys", "Tolerance keys define the limits per company code",
                  "technical", ["tolerance key"], weight=1.4),
                c("release_step", "Blocked invoices are released in a separate step once resolved",
                  "technical", ["released"], weight=1.2),
                c("commercial", "The underlying cause is usually a commercial disagreement, not a system fault",
                  "business", ["commercial", "supplier"], weight=1.3,
                  hint="Say who you would talk to, not only which transaction you would open."),
            ],
            "First I would look at which check produced the block, because price, quantity, "
            "date and amount differences are recorded separately, and the tolerance key for "
            "that company code tells me how large a difference is allowed before it blocks. "
            "Then I would compare the invoice against the order and the goods receipt to see "
            "which of the three is out of line. Most blocks are a commercial disagreement "
            "rather than a system fault, so the fix is normally a conversation with the "
            "supplier or the buyer, after which the invoice is released for payment in a "
            "separate step that leaves an audit trail.",
            [
                f("Who should be allowed to release a blocked invoice?", "release_step"),
                f("How would you reduce the number of blocks over the next quarter?", "commercial"),
            ],
            study_topics=["Invoice verification", "Tolerance keys"],
        ),
        q(
            "IQ-MM-010", "sap_mm", "Subcontracting", "advanced", TECH,
            "Describe the subcontracting process in SAP MM and what makes it different from "
            "a normal purchase.",
            [
                c("components", "Components are provided to the subcontractor and stay owned by you",
                  "technical", ["components", "provided"], weight=1.5, required=True),
                c("special_stock_o", "The provided stock sits as special stock at the vendor",
                  "technical", ["special stock", "at the vendor"], weight=1.4),
                c("consumption", "The goods receipt of the finished item consumes the components",
                  "technical", ["goods receipt", "consumes"], weight=1.4),
                c("value_add", "You pay for the service rather than for the whole item",
                  "business", ["service", "full value"], weight=1.3),
            ],
            "In subcontracting you send components to the supplier and buy back a finished "
            "item. The components are provided to the subcontractor but remain your property, "
            "so they sit as special stock recorded at the vendor rather than leaving your "
            "balance sheet. When the goods receipt of the finished item is posted it consumes "
            "those components and receives the finished material, and the invoice covers the "
            "service the subcontractor added rather than the full value of the item.",
            [
                f("What happens if the subcontractor scraps some of the components?", "consumption"),
                f("How would you reconcile provided stock at year end?", "special_stock_o"),
            ],
            study_topics=["Subcontracting", "Special stock"],
        ),
        q(
            "IQ-MM-011", "sap_mm", "Account determination", "expert", TECH,
            "How does SAP work out which general ledger account an inventory posting hits?",
            [
                c("automatic_postings", "Automatic account determination maps postings to accounts",
                  "technical", ["automatic", "account determination"], weight=1.6, required=True),
                c("valuation_class", "The valuation class on the material links it to an account group",
                  "technical", ["valuation class"], weight=1.5, required=True),
                c("transaction_keys", "Transaction keys separate the different kinds of posting",
                  "technical", ["transaction key"], weight=1.3),
                c("finance_owns", "Finance owns the mapping and has to sign it off",
                  "business", ["finance", "sign"], weight=1.2),
            ],
            "Inventory postings use automatic account determination. The valuation class held "
            "on the material master links the material to a group of accounts, the movement "
            "and the posting type resolve to a transaction key, and the combination of the "
            "two picks the general ledger account for that valuation area. It is configured "
            "once and used everywhere, so finance owns the mapping and has to sign it off - a "
            "wrong entry is not a purchasing problem, it is a set of postings in the wrong "
            "account that somebody has to unwind.",
            [
                f("Which transaction key would an inventory difference use?", "transaction_keys"),
                f("How would you test account determination before go-live?", "finance_owns"),
            ],
            study_topics=["Account determination", "Valuation classes"],
        ),
        q(
            "IQ-MM-012", "sap_mm", "Consignment", "advanced", TECH,
            "How does consignment stock work, and when does the value move onto your books?",
            [
                c("supplier_owned", "The stock is on your site but owned by the supplier",
                  "technical", ["owned by the supplier", "on site"], weight=1.6, required=True),
                c("withdrawal", "Liability arises on withdrawal, not on delivery",
                  "technical", ["withdrawal", "liability"], weight=1.5, required=True),
                c("settlement", "Consignment settlement creates the payable periodically",
                  "technical", ["settlement"], weight=1.3),
                c("working_capital", "It moves working capital and inventory risk to the supplier",
                  "business", ["working capital"], weight=1.3),
            ],
            "Consignment stock sits in your warehouse but stays owned by the supplier until "
            "somebody takes it. Liability arises on withdrawal rather than on delivery, so the "
            "stock is visible and usable without being on your balance sheet, and consignment "
            "settlement runs periodically to turn the withdrawals into a payable. The reason "
            "procurement likes it is that working capital and obsolescence risk sit with the "
            "supplier, and the reason suppliers resist it is exactly the same.",
            [
                f("What does the supplier get in return for holding the risk?", "working_capital"),
                f("How is consignment stock counted at a physical inventory?", "supplier_owned"),
            ],
            study_topics=["Consignment", "Inventory ownership"],
        ),
    ]


# ---------------------------------------------------------------------------
# Track 2 - SAP Ariba
# ---------------------------------------------------------------------------


def sap_ariba_questions() -> list[dict[str, Any]]:
    """Sourcing, buying, contracts, suppliers and the road back to the ERP."""
    return [
        q(
            "IQ-AR-001", "sap_ariba", "Ariba solution landscape", "foundational", TECH_RAPID,
            "What is the difference between Ariba Sourcing and Ariba Buying, and where does "
            "each one sit in the procurement process?",
            [
                c("sourcing_upstream", "Sourcing is upstream: events, awards and supplier selection",
                  "technical", ["sourcing", "upstream", "event"], weight=1.5, required=True),
                c("buying_downstream", "Buying is downstream: requisitions, approvals and orders",
                  "technical", ["buying", "downstream", "requisition"],
                  weight=1.5, required=True),
                c("contract_bridge", "A contract is what carries the award into buying",
                  "technical", ["contract"], weight=1.3),
                c("who_uses", "Category managers use sourcing; ordinary employees use buying",
                  "business", ["category manager", "employees"], weight=1.3),
            ],
            "Ariba Sourcing is the upstream part of the process: running an event, comparing "
            "responses and awarding business to a supplier. Ariba Buying is downstream: an "
            "employee raises a requisition, it is approved and it becomes an order. The "
            "bridge between them is a contract, which carries the awarded prices and terms "
            "into everyday buying. Category managers live in sourcing a few times a year; "
            "ordinary employees live in buying every week, which is why the two need very "
            "different user experiences.",
            [
                f("What is lost if an award never becomes a contract?", "contract_bridge"),
                f("Which of the two would you deploy first, and why?", "who_uses"),
            ],
            study_topics=["Ariba solution landscape", "Source to pay process"],
        ),
        q(
            "IQ-AR-002", "sap_ariba", "Guided buying", "intermediate", TECH,
            "What problem is guided buying trying to solve, and how does it solve it?",
            [
                c("untrained_users", "It targets occasional buyers who will not learn a procurement tool",
                  "technical", ["occasional", "untrained"], weight=1.4, required=True),
                c("policy_in_flow", "Policy and the right channel are presented in the flow of buying",
                  "technical", ["policy", "channel"], weight=1.5, required=True),
                c("landing_page", "Tiles and forms route a request to the correct process",
                  "technical", ["tiles", "forms"], weight=1.2),
                c("compliance", "The measurable outcome is less maverick spend",
                  "business", ["maverick spend", "compliance"], weight=1.4),
            ],
            "Guided buying exists because most people who buy something at work are "
            "occasional, untrained users who will never learn a procurement application. It "
            "presents policy and the right buying channel inside the flow of the request "
            "itself, so somebody asking for a laptop is steered to the catalogue and somebody "
            "asking for consultancy is steered to a sourcing form. Tiles and forms do the "
            "routing rather than the user choosing a document type. The outcome procurement "
            "actually cares about is compliance: less maverick spend, because the compliant "
            "route is now the easy one.",
            [
                f("How would you measure whether guided buying worked?", "compliance"),
                f("What do you do about a category with no catalogue and no form?", "landing_page"),
            ],
            study_topics=["Guided buying", "Buying channels"],
        ),
        q(
            "IQ-AR-003", "sap_ariba", "Catalogues", "intermediate", TECH,
            "Compare a hosted catalogue with a punchout catalogue. When would you insist "
            "on one over the other?",
            [
                c("hosted", "A hosted catalogue is a file the supplier uploads and you validate",
                  "technical", ["hosted catalogue", "uploaded"], weight=1.5, required=True),
                c("punchout", "A punchout sends the user to the supplier site and returns a cart",
                  "technical", ["punchout", "returns"], weight=1.5, required=True),
                c("maintenance", "Hosted content ages; punchout content is always current",
                  "technical", ["current", "ages"], weight=1.2),
                c("price_control", "Hosted gives you contracted price control, punchout gives range",
                  "business", ["contracted price", "range"], weight=1.4),
            ],
            "A hosted catalogue is content the supplier uploads as a file, which you validate "
            "and load, so the prices are the contracted price and nothing else. A punchout "
            "sends the user out to the supplier's own site and returns a cart into the "
            "requisition, so the content is always current and the range is much wider. I "
            "would insist on hosted where price control matters and the range is stable, such "
            "as office supplies on a negotiated list, and accept punchout where the catalogue "
            "ages quickly and the supplier's own site is the only realistic source of truth.",
            [
                f("How do you stop a punchout cart being edited after it returns?", "price_control"),
                f("What is your process when a hosted catalogue file fails validation?", "hosted"),
            ],
            study_topics=["Catalogue strategy", "Punchout"],
        ),
        q(
            "IQ-AR-004", "sap_ariba", "Supplier management", "intermediate", TECH,
            "Walk me through supplier lifecycle management in Ariba and what each stage is for.",
            [
                c("registration", "Registration collects the data needed to trade at all",
                  "technical", ["registration"], weight=1.4, required=True),
                c("qualification", "Qualification checks the supplier against category requirements",
                  "technical", ["qualification"], weight=1.4, required=True),
                c("segmentation", "Segmentation decides how much attention a supplier gets",
                  "technical", ["segmentation"], weight=1.2),
                c("risk_and_perf", "Ongoing risk and performance monitoring is the point of the record",
                  "business", ["performance", "risk"], weight=1.4),
            ],
            "Supplier lifecycle management starts with registration, which collects the data "
            "needed to trade at all, and moves to qualification, which checks the supplier "
            "against the requirements of a specific category. Segmentation then decides how "
            "much attention each supplier gets, so a strategic partner is managed differently "
            "from a one-off vendor. The reason to hold all of it in one record is ongoing "
            "monitoring: risk exposure and supplier performance only mean anything when they "
            "are tracked over time against the same master record.",
            [
                f("What would you do with a supplier who is qualified but performing badly?",
                  "risk_and_perf"),
                f("How do you keep registration short enough that suppliers finish it?",
                  "registration"),
            ],
            study_topics=["Supplier lifecycle", "Supplier performance"],
        ),
        q(
            "IQ-AR-005", "sap_ariba", "Contract compliance", "advanced", TECH,
            "How would you make sure that the prices negotiated in a contract are the prices "
            "that actually get paid?",
            [
                c("contract_to_order", "The contract has to be referenced by the order",
                  "technical", ["referenced", "order"], weight=1.5, required=True),
                c("price_source", "Prices must flow from one source rather than being retyped",
                  "technical", ["one source", "retyped"], weight=1.4, required=True),
                c("invoice_check", "Invoice matching against the contract price is the last gate",
                  "technical", ["invoice", "matching"], weight=1.3),
                c("leakage", "The measure is realised savings versus negotiated savings",
                  "business", ["realised savings", "negotiated"], weight=1.5,
                  hint="Name the gap between the two, which is what a CPO is asked about."),
            ],
            "The contract has to be referenced by the order rather than sitting in a "
            "repository, so prices flow from one source instead of being retyped by whoever "
            "raises the requisition. Catalogue content and pricing conditions should be "
            "generated from the contract, and invoice matching against the contract price is "
            "the last gate before money leaves. The measure that matters is the gap between "
            "negotiated savings and realised savings, because that gap is contract leakage "
            "and it is the number a chief procurement officer is asked to explain.",
            [
                f("Where would you look first to quantify leakage?", "leakage"),
                f("What do you do about spend with a contracted supplier but off contract?",
                  "contract_to_order"),
            ],
            study_topics=["Contract compliance", "Savings realisation"],
        ),
        q(
            "IQ-AR-006", "sap_ariba", "Ariba and ERP integration", "advanced", ARCH,
            "How does Ariba Buying integrate with an SAP ERP, and what do you have to decide "
            "before you build it?",
            [
                c("master_data_out", "Master data is replicated from the ERP to Ariba",
                  "technical", ["master data", "replicated"], weight=1.5, required=True),
                c("documents_back", "Requisitions or orders come back into the ERP",
                  "technical", ["requisition", "back into"], weight=1.5, required=True),
                c("system_of_record", "You must decide which system is the record for each document",
                  "architecture", ["system of record"], weight=1.6, required=True,
                  hint="This is the decision the whole integration hangs on."),
                c("failure_mode", "Both sides need agreed error handling and reconciliation",
                  "architecture", ["error handling", "reconciliation"], weight=1.3),
                c("business_impact", "Getting it wrong shows up as orders nobody can find",
                  "business", ["orders", "nobody"], weight=1.2),
            ],
            "Master data - suppliers, materials, cost centres and organisational units - is "
            "replicated from the ERP out to Ariba, and the transactional documents come back "
            "into the ERP, either as a requisition or as a completed order depending on the "
            "deployment. The decision to take first is which system of record owns each "
            "document, because that decides where approvals live, where changes are made and "
            "which side wins a disagreement. You also have to agree error handling and a "
            "reconciliation report on both sides, because the failure mode is orders that "
            "exist on one side and not the other, and nobody can find them until a supplier "
            "calls about an invoice.",
            [
                f("Which system should own the approval, and why?", "system_of_record"),
                f("How would you detect documents that exist on only one side?", "failure_mode"),
            ],
            study_topics=["Ariba integration", "System of record"],
        ),
        q(
            "IQ-AR-007", "sap_ariba", "Sourcing events", "intermediate", TECH,
            "What kinds of sourcing event are there and how do you decide which one to run?",
            [
                c("rfi_rfp_auction", "Information gathering, proposals and auctions are different tools",
                  "technical", ["RFI", "RFP", "auction"], weight=1.5, required=True),
                c("award_criteria", "Award criteria have to be set before the event opens",
                  "technical", ["award criteria", "before"], weight=1.4, required=True),
                c("lots", "Lots and bidding rules shape how suppliers can respond",
                  "technical", ["lots"], weight=1.1),
                c("market_fit", "An auction needs a commoditised specification and real competition",
                  "business", ["commoditised", "competition"], weight=1.5,
                  hint="Say when an auction is the wrong tool, not only what it is."),
            ],
            "An RFI gathers information when you do not yet know the market, an RFP compares "
            "proposals when the requirement has qualitative dimensions, and an auction drives "
            "price when the specification is settled. The award criteria and their weighting "
            "have to be agreed before the event opens, because changing them afterwards "
            "destroys the defensibility of the award, and lots let you split the scope so "
            "suppliers bid on what they are actually good at. An auction only works with a "
            "commoditised specification and genuine competition; running one without both "
            "wastes everybody's time and damages the supplier relationship.",
            [
                f("How do you handle a supplier who bids outside the rules?", "lots"),
                f("What do you do when only one supplier responds?", "market_fit"),
            ],
            study_topics=["Sourcing events", "Award criteria"],
        ),
        q(
            "IQ-AR-008", "sap_ariba", "Approval flows", "intermediate", TECH,
            "How do approval flows work in Ariba Buying, and how do you keep them from "
            "becoming a bottleneck?",
            [
                c("rules_driven", "Approvers are added by rules evaluated against the request",
                  "technical", ["rules", "approvers"], weight=1.5, required=True),
                c("parallel", "Approvals can run in parallel rather than in a chain",
                  "technical", ["parallel"], weight=1.3),
                c("delegation", "Delegation and escalation keep a flow moving when somebody is away",
                  "technical", ["delegation", "escalation"], weight=1.3),
                c("cycle_time", "Every approver added is measurable cycle time",
                  "business", ["cycle time"], weight=1.4,
                  hint="Quantify the cost of an approval step, do not just list features."),
            ],
            "Approvers are added by rules evaluated against the request: value, cost centre, "
            "commodity and whether the item is on contract. Wherever the approvals are "
            "independent they should run in parallel rather than as a chain, and delegation "
            "and escalation have to be configured so one person on holiday does not stop "
            "everything. The discipline is remembering that every approver added is "
            "measurable cycle time, so each one has to be justified by a risk it actually "
            "removes rather than by somebody wanting visibility.",
            [
                f("How would you justify removing an approval level?", "cycle_time"),
                f("What happens to an approved requisition when its value changes?", "rules_driven"),
            ],
            study_topics=["Approval design", "Cycle time"],
        ),
        q(
            "IQ-AR-009", "sap_ariba", "Invoice automation", "advanced", TECH,
            "What does it take to get most supplier invoices to post without anybody touching "
            "them?",
            [
                c("structured_input", "Invoices have to arrive structured, not as an image",
                  "technical", ["structured", "image"], weight=1.5, required=True),
                c("po_reference", "A valid order reference on every line is the precondition",
                  "technical", ["order reference", "line"], weight=1.5, required=True),
                c("rules", "Invoice rules reject bad invoices at the door rather than downstream",
                  "technical", ["invoice rules", "reject"], weight=1.3),
                c("exception_rate", "The metric is touchless rate and the cost per invoice",
                  "business", ["touchless", "cost per invoice"], weight=1.4),
            ],
            "Invoices have to arrive structured rather than as an image or a PDF attachment, "
            "and every line needs a valid order reference, because without one there is "
            "nothing to match against. Invoice rules should reject a bad invoice at the door "
            "and tell the supplier why, rather than letting it into the process to become an "
            "exception somebody works on for a week. The numbers to manage are the touchless "
            "rate and the cost per invoice, and both of them are usually limited by supplier "
            "behaviour and by order quality rather than by the tool.",
            [
                f("What would you do about suppliers who will not send structured invoices?",
                  "structured_input"),
                f("Which single change usually lifts the touchless rate most?", "po_reference"),
            ],
            study_topics=["Invoice automation", "Touchless processing"],
        ),
        q(
            "IQ-AR-010", "sap_ariba", "Multi-ERP deployments", "expert", ARCH,
            "A group runs three ERPs and wants one procurement front end. How would you "
            "approach it?",
            [
                c("one_front_end", "One buying experience can front several back ends",
                  "technical", ["one buying", "back ends"], weight=1.4, required=True),
                c("data_alignment", "Master data has to be aligned or mapped before anything works",
                  "technical", ["aligned", "mapped"], weight=1.6, required=True,
                  hint="This is where these programmes actually fail."),
                c("routing", "Documents must be routed to the correct back end deterministically",
                  "architecture", ["routed", "correct back end"], weight=1.5, required=True),
                c("phasing", "Phasing by ERP limits the blast radius of each cutover",
                  "architecture", ["phase", "cutover"], weight=1.3),
                c("value_case", "The value is harmonised process and visible group spend",
                  "business", ["harmonised", "group spend"], weight=1.3),
            ],
            "One buying experience can sit in front of several back ends, but the work is not "
            "in the front end. Master data has to be aligned or at least mapped first - "
            "suppliers, categories, units of measure and the organisational structure - "
            "because without that a single requisition form cannot be filled in consistently. "
            "Every document then has to be routed to the correct back end deterministically, "
            "from a rule somebody can explain, and I would phase the rollout one ERP at a "
            "time so each cutover has a small blast radius. The value case is a harmonised "
            "process and group spend that is finally visible in one place.",
            [
                f("What is your fallback when master data cannot be harmonised?", "data_alignment"),
                f("How do you decide which ERP goes first?", "phasing"),
            ],
            study_topics=["Multi-ERP procurement", "Master data harmonisation"],
        ),
        q(
            "IQ-AR-011", "sap_ariba", "Master data replication", "advanced", TECH,
            "Which master data has to reach Ariba from the ERP, and what goes wrong when it "
            "drifts?",
            [
                c("what_replicates", "Suppliers, materials, accounting objects and the org structure",
                  "technical", ["suppliers", "cost centre", "organisational"],
                  weight=1.5, required=True),
                c("direction", "Replication is one way, with the ERP as the source",
                  "technical", ["one way", "source"], weight=1.4, required=True),
                c("timing", "Frequency and sequence decide what a user can select today",
                  "technical", ["frequency", "sequence"], weight=1.2),
                c("drift_symptom", "Drift shows up as requisitions that will not post",
                  "business", ["will not post", "rejected"], weight=1.4),
            ],
            "Suppliers, materials, cost centre and other accounting objects, and the "
            "organisational structure all have to reach Ariba, and replication is one way "
            "with the ERP as the source, because two systems both editing a supplier is a "
            "reconciliation problem nobody wins. Frequency and sequence matter more than "
            "people expect: a new cost centre that has not replicated yet is a cost centre "
            "the user cannot select today. When data drifts the symptom is requisitions that "
            "look fine to the user and are rejected on the way into the ERP, which is the "
            "worst possible place to find out.",
            [
                f("How would you detect drift before a user does?", "drift_symptom"),
                f("Which object would you replicate most frequently, and why?", "timing"),
            ],
            study_topics=["Master data replication", "Integration monitoring"],
        ),
        q(
            "IQ-AR-012", "sap_ariba", "Ariba fundamentals", "foundational", RAPID,
            "In a sentence or two: what is a realm in Ariba, and why does it matter?",
            [
                c("realm_definition", "A realm is a separate configured instance of the solution",
                  "technical", ["realm", "instance"], weight=1.6, required=True),
                c("isolation", "Configuration, data and users are isolated per realm",
                  "technical", ["isolated"], weight=1.4, required=True),
                c("consequence", "Splitting into realms splits reporting and supplier relationships",
                  "business", ["reporting"], weight=1.3),
            ],
            "A realm is a separate configured instance of an Ariba solution, with its own "
            "configuration, data and users isolated from any other realm. It matters because "
            "the decision to run one realm or several decides whether reporting and supplier "
            "relationships are shared across the group or split up, and that is very hard to "
            "reverse later.",
            [
                f("When would a second realm be the right answer?", "consequence"),
            ],
            study_topics=["Ariba realms"],
        ),
    ]


# ---------------------------------------------------------------------------
# Track 3 - SAP S/4HANA
# ---------------------------------------------------------------------------


def sap_s4hana_questions() -> list[dict[str, Any]]:
    """What changed, what it means for procurement, and how you get there."""
    return [
        q(
            "IQ-S4-001", "sap_s4hana", "ECC to S/4HANA changes", "intermediate", TECH,
            "What changed for materials management when SAP moved from ECC to S/4HANA?",
            [
                c("matdoc", "Inventory tables were consolidated into one document table",
                  "technical", ["consolidated", "one table"], weight=1.5, required=True),
                c("business_partner", "Vendors and customers became business partners",
                  "technical", ["business partner"], weight=1.5, required=True),
                c("field_lengths", "Field length changes such as the longer material number",
                  "technical", ["material number", "field length"], weight=1.2),
                c("why_changed", "The point was fewer aggregates and real-time reporting",
                  "business", ["aggregates", "real time"], weight=1.3),
            ],
            "The inventory tables were consolidated so that one table holds the material "
            "documents instead of the old split between header, item and the aggregate "
            "tables, and vendors and customers were unified into the business partner model. "
            "There are field length changes as well, notably the longer material number, "
            "which matters to every interface that carries one. The reason for all of it is "
            "the same: fewer aggregates to keep in step, and real time reporting off the "
            "document table rather than off a nightly summary.",
            [
                f("What does the removal of aggregate tables mean for custom reports?",
                  "why_changed"),
                f("What breaks first when the material number gets longer?", "field_lengths"),
            ],
            wrong=[
                w("s4_is_ui",
                  "S/4HANA is described as only a user interface change.",
                  ["S/4HANA is just a new user interface", "S/4HANA is only a UI change"],
                  "Fiori is the user experience layer. S/4HANA also changed the data model, "
                  "which is why conversion projects need a simplification item check."),
            ],
            study_topics=["S/4HANA simplification", "Business partner"],
        ),
        q(
            "IQ-S4-002", "sap_s4hana", "Business partner", "intermediate", TECH,
            "Explain the business partner model and what a conversion project has to do "
            "about it.",
            [
                c("one_object", "One business partner carries several roles",
                  "technical", ["business partner", "role"], weight=1.6, required=True),
                c("cvi", "Synchronisation keeps the partner and the vendor master aligned",
                  "technical", ["synchronisation", "vendor master"], weight=1.4, required=True),
                c("conversion_work", "Existing vendors must be converted and de-duplicated first",
                  "technical", ["convert", "duplicate"], weight=1.4),
                c("why_better", "One record for an organisation that is both supplier and customer",
                  "business", ["both a supplier and a customer"], weight=1.3),
            ],
            "In the business partner model one object carries several roles, so the same "
            "organisation can hold a supplier role and a customer role at once rather than "
            "existing as two unrelated master records. Synchronisation keeps the business "
            "partner and the underlying vendor master aligned, and a conversion project has "
            "to convert existing vendors into business partners and resolve duplicate records "
            "before it can proceed. The benefit is a single record for an organisation that "
            "is both a supplier and a customer, which is exactly the case that used to cause "
            "reconciliation arguments.",
            [
                f("What do you do with vendors that duplicate an existing customer?", "cvi"),
                f("Why is de-duplication done before the technical conversion?", "conversion_work"),
            ],
            study_topics=["Business partner", "Customer vendor integration"],
        ),
        q(
            "IQ-S4-003", "sap_s4hana", "Data model", "advanced", TECH,
            "Why did SAP remove the inventory aggregate tables, and what does that change "
            "for someone writing a report?",
            [
                c("single_source", "One document table is now the single source for stock",
                  "technical", ["single source", "document table"], weight=1.6, required=True),
                c("no_locks", "Removing aggregates removed a serious update lock contention",
                  "technical", ["lock", "contention"], weight=1.4),
                c("compat_views", "Compatibility views keep old reads working, not old writes",
                  "technical", ["compatibility view"], weight=1.4, required=True),
                c("report_impact", "Reports must be rewritten to aggregate on the fly",
                  "business", ["rewritten", "on the fly"], weight=1.3),
            ],
            "Stock quantities used to be maintained in aggregate tables alongside the "
            "documents, which meant every posting updated several rows and high volume "
            "postings fought each other for the same lock. Now one document table is the "
            "single source and totals are calculated when they are asked for, so the lock "
            "contention disappears. Compatibility views keep old read access working, but "
            "they do not make old direct writes valid, so custom reports have to be rewritten "
            "to aggregate on the fly and any code that wrote to an aggregate table has to go.",
            [
                f("How would you find custom code that writes to a removed table?", "compat_views"),
                f("What is the performance risk of aggregating on the fly?", "report_impact"),
            ],
            study_topics=["S/4HANA data model", "Custom code adaptation"],
        ),
        q(
            "IQ-S4-004", "sap_s4hana", "Fiori", "foundational", TECH_RAPID,
            "What kinds of Fiori app are there, and why does the distinction matter to a "
            "project?",
            [
                c("app_types", "Transactional, analytical and fact sheet apps do different jobs",
                  "technical", ["transactional", "analytical", "fact sheet"],
                  weight=1.6, required=True),
                c("launchpad", "The launchpad and catalogues control what a user sees",
                  "technical", ["launchpad", "catalogue"], weight=1.3),
                c("role_based", "Apps are assigned through roles rather than menu paths",
                  "technical", ["role"], weight=1.2),
                c("adoption", "Fewer, better targeted apps is what drives adoption",
                  "business", ["adoption"], weight=1.3),
            ],
            "There are transactional apps for doing work, analytical apps for looking at "
            "numbers and fact sheet apps for exploring one object and its relationships. The "
            "launchpad and the catalogues behind it control what a user actually sees, and "
            "apps reach a user through a role rather than through a menu path, so security "
            "design and user experience design become the same conversation. The distinction "
            "matters because adoption comes from giving somebody the six apps their job needs, "
            "not from switching on everything available.",
            [
                f("How would you decide which apps a buyer role gets?", "role_based"),
                f("What would you measure to know whether adoption is working?", "adoption"),
            ],
            study_topics=["Fiori app types", "Launchpad and catalogues"],
        ),
        q(
            "IQ-S4-005", "sap_s4hana", "Embedded analytics", "advanced", TECH,
            "What are CDS views and what makes embedded analytics different from a separate "
            "data warehouse?",
            [
                c("cds_definition", "CDS views define the model on top of the tables",
                  "technical", ["CDS view", "model"], weight=1.5, required=True),
                c("virtual", "Analytics run on the live transactional data with no copy",
                  "technical", ["live", "no copy"], weight=1.5, required=True),
                c("annotations", "Annotations turn a view into something a tool can consume",
                  "technical", ["annotation"], weight=1.2),
                c("when_warehouse", "A warehouse is still needed for history and non-SAP sources",
                  "business", ["history", "non-SAP"], weight=1.4,
                  hint="An interviewer wants the limit of embedded analytics, not a sales pitch."),
            ],
            "CDS views define a reusable model on top of the underlying tables, and "
            "annotations describe how that model should be consumed, which is what lets one "
            "definition serve an application, an analytical app and an interface. Embedded "
            "analytics then runs on the live transactional data with no copy and no load, so "
            "an operational figure is current rather than as at last night. It does not "
            "replace a warehouse: long history, heavy restatement and data from non-SAP "
            "sources still belong somewhere else, and pretending otherwise is how a project "
            "ends up doing both badly.",
            [
                f("When would you push back on an embedded analytics requirement?",
                  "when_warehouse"),
                f("Why reuse one CDS view rather than writing a report-specific one?",
                  "cds_definition"),
            ],
            study_topics=["CDS views", "Embedded analytics"],
        ),
        q(
            "IQ-S4-006", "sap_s4hana", "Transition approach", "advanced", ARCH,
            "A customer on ECC asks whether to convert or to reimplement. How do you help "
            "them decide?",
            [
                c("conversion", "A conversion keeps the history and the existing configuration",
                  "technical", ["conversion", "history"], weight=1.5, required=True),
                c("greenfield", "A new implementation redesigns the process and leaves the past",
                  "technical", ["new implementation", "redesign"], weight=1.5, required=True),
                c("decision_inputs", "Custom code volume, data quality and appetite for change decide it",
                  "architecture", ["custom code", "data quality"], weight=1.6, required=True),
                c("selective", "A selective transition is the middle road and it is not cheap",
                  "architecture", ["selective"], weight=1.2),
                c("business_case", "The question is really about disruption versus benefit",
                  "business", ["disruption", "benefit"], weight=1.4),
            ],
            "A conversion keeps the existing configuration and the transactional history and "
            "changes the technical foundation underneath, so it is the lower disruption route "
            "when the current process is fundamentally sound. A new implementation redesigns "
            "the process and leaves the past behind, which is the right answer when the "
            "existing design is the problem. What decides it in practice is the volume of "
            "custom code, the data quality, and how much appetite the business genuinely has "
            "for process change; a selective transition sits in the middle and is usually the "
            "most expensive of the three. Underneath, the decision is disruption against "
            "benefit, and it is a business decision that the technical facts inform.",
            [
                f("What evidence would you gather before recommending either?", "decision_inputs"),
                f("How would you test whether the appetite for change is real?", "business_case"),
            ],
            study_topics=["Transition approaches", "Custom code analysis"],
        ),
        q(
            "IQ-S4-007", "sap_s4hana", "Flexible workflow", "advanced", TECH,
            "How does flexible workflow change the way approvals are set up compared with "
            "classic release strategies?",
            [
                c("scenarios", "Workflow scenarios are activated and configured with steps",
                  "technical", ["scenario", "step"], weight=1.5, required=True),
                c("conditions", "Preconditions decide which steps apply to a document",
                  "technical", ["precondition"], weight=1.4, required=True),
                c("no_classification", "It replaces classification-based release with maintained rules",
                  "technical", ["classification"], weight=1.3),
                c("who_maintains", "Business users can maintain it without a transport",
                  "business", ["business user", "transport"], weight=1.4),
            ],
            "Flexible workflow is set up by activating a scenario and defining its steps, with "
            "preconditions deciding which steps apply to a given document. It replaces the "
            "old classification based release strategy with rules that are maintained as "
            "data, so a business user can change who approves a category of spend without a "
            "transport and without a developer. That is the real difference: approvals stop "
            "being a configuration change and become something the process owner maintains.",
            [
                f("What governance would you put around business users editing approvals?",
                  "who_maintains"),
                f("How would you migrate an existing release strategy to it?",
                  "no_classification"),
            ],
            study_topics=["Flexible workflow", "Approval configuration"],
        ),
        q(
            "IQ-S4-008", "sap_s4hana", "Central procurement", "expert", ARCH,
            "What is a central procurement hub, and what is hard about running one?",
            [
                c("hub_concept", "One system provides procurement across several connected back ends",
                  "technical", ["hub", "back end"], weight=1.5, required=True),
                c("scenarios", "Central requisitioning, central contracts and central purchasing differ",
                  "technical", ["central requisitioning", "central contract"],
                  weight=1.4, required=True),
                c("connectivity", "Every back end has to be connected and kept in step",
                  "architecture", ["connected", "in step"], weight=1.5, required=True),
                c("harmonisation", "Category and supplier data have to mean the same thing everywhere",
                  "architecture", ["mean the same"], weight=1.4),
                c("value", "The benefit is group leverage and visible spend without one ERP",
                  "business", ["leverage", "without"], weight=1.3),
            ],
            "A central procurement hub is one system that provides procurement capability "
            "across several connected back end systems, so the group buys in one place while "
            "the transactions still land where they belong. Central requisitioning, central "
            "contracts and central purchasing are different scenarios with different amounts "
            "of the process moved to the hub, and picking the wrong one leaves people working "
            "in two systems. The hard part is that every back end has to be connected and kept "
            "in step, and category and supplier data have to mean the same thing everywhere, "
            "or the group reporting is fiction. The benefit is group leverage and visible "
            "spend without forcing everybody onto one ERP first.",
            [
                f("Which scenario would you start with, and why?", "scenarios"),
                f("How do you handle a back end that cannot be connected yet?", "connectivity"),
            ],
            study_topics=["Central procurement", "Hub architecture"],
        ),
        q(
            "IQ-S4-009", "sap_s4hana", "Conversion preparation", "advanced", TECH,
            "What is a simplification item check telling you, and what do you do with the "
            "output?",
            [
                c("what_it_does", "It checks the system against the items that changed",
                  "technical", ["simplification item", "check"], weight=1.6, required=True),
                c("blocking", "Some findings block the conversion until they are resolved",
                  "technical", ["block"], weight=1.4, required=True),
                c("iterate", "It is run repeatedly, not once",
                  "technical", ["repeatedly"], weight=1.2),
                c("planning", "The output is a work list that sizes the project",
                  "business", ["work list", "size"], weight=1.4),
            ],
            "The simplification item check compares the system against every simplification "
            "item, which are the specific things SAP changed, and reports where the system as "
            "configured and used is affected. Some findings block the conversion until they "
            "are resolved and others are advisory, and it is run repeatedly through the "
            "project rather than once at the start, because each fix changes the picture. The "
            "output is the work list that sizes the project, so running it early is what turns "
            "a conversion estimate from a guess into a plan.",
            [
                f("What would you do with an advisory finding you cannot fix in time?", "blocking"),
                f("When in the project would you run it for the first time?", "planning"),
            ],
            study_topics=["Simplification item check", "Conversion readiness"],
        ),
        q(
            "IQ-S4-010", "sap_s4hana", "Extensibility", "advanced", ARCH,
            "Somebody asks for a field that does not exist in standard. Walk me through the "
            "options and how you choose.",
            [
                c("key_user", "Key user extensibility adds fields without development",
                  "technical", ["key user"], weight=1.5, required=True),
                c("side_by_side", "Side-by-side extensions live outside the core",
                  "architecture", ["side by side", "outside the core"],
                  weight=1.5, required=True),
                c("upgrade_safe", "Released extension points survive an upgrade; modifications do not",
                  "architecture", ["upgrade", "released"], weight=1.6, required=True),
                c("ask_why", "First establish what the field is for, not where to put it",
                  "business", ["what it is for", "requirement"], weight=1.4,
                  hint="The best answers push back on the requirement before choosing a tool."),
            ],
            "The first move is to establish what it is for, because the requirement is often "
            "already met by a standard field somebody has not found, and a new field that "
            "nobody fills is worse than no field. If it is genuinely needed, key user "
            "extensibility adds a field through configuration with no development at all. "
            "Anything with real logic behind it belongs in a side by side extension outside "
            "the core, calling released interfaces. The line that decides all of it is upgrade "
            "safety: released extension points survive an upgrade and a modification of "
            "standard objects does not.",
            [
                f("How do you handle a request that needs logic on save?", "side_by_side"),
                f("What do you tell somebody whose only reason is 'we did it in ECC'?",
                  "ask_why"),
            ],
            study_topics=["Extensibility options", "Clean core"],
        ),
        q(
            "IQ-S4-011", "sap_s4hana", "Universal Journal", "intermediate", TECH,
            "What is the Universal Journal and why do procurement people end up caring "
            "about it?",
            [
                c("one_line_item_table", "One table holds the financial line items",
                  "technical", ["one table", "line item"], weight=1.6, required=True),
                c("merged_ledgers", "Financial accounting and controlling share the same record",
                  "technical", ["controlling", "same record"], weight=1.5, required=True),
                c("no_reconciliation", "Reconciliation between the two disappears",
                  "technical", ["reconciliation"], weight=1.3),
                c("procurement_link", "Purchasing postings become visible in one place immediately",
                  "business", ["purchasing", "immediately"], weight=1.3),
            ],
            "The Universal Journal is one table holding the financial line items, so financial "
            "accounting and controlling write the same record instead of two that have to "
            "agree afterwards. That means the periodic reconciliation between the two "
            "disappears, and a posting carries its cost object and its profitability "
            "attributes on the same line. Procurement people care because purchasing postings "
            "become visible in one place immediately, so a question about committed spend "
            "against a cost centre has one answer rather than three.",
            [
                f("What does this change about month end?", "no_reconciliation"),
                f("How would you report committed versus actual spend?", "procurement_link"),
            ],
            study_topics=["Universal Journal", "Finance integration"],
        ),
        q(
            "IQ-S4-012", "sap_s4hana", "Deployment options", "intermediate", ARCH,
            "Compare the public cloud and private cloud editions of S/4HANA for a "
            "procurement-heavy customer.",
            [
                c("public_standard", "Public cloud means standard scope and a fixed upgrade cycle",
                  "technical", ["standard scope", "upgrade cycle"], weight=1.5, required=True),
                c("private_flexible", "Private cloud keeps more configuration and custom code freedom",
                  "technical", ["private cloud", "custom code"], weight=1.5, required=True),
                c("extensibility_limits", "The extensibility model differs and constrains the design",
                  "architecture", ["extensibility"], weight=1.4, required=True),
                c("fit_to_standard", "Public cloud demands a genuine fit-to-standard commitment",
                  "business", ["fit to standard"], weight=1.4),
            ],
            "The public cloud edition provides a standard scope on a fixed upgrade cycle, so "
            "the customer gets continuous innovation and gives up the ability to bend the "
            "system. The private cloud edition keeps far more configuration freedom and "
            "existing custom code, at the price of owning the upgrade. The extensibility "
            "model differs between them and constrains the design from day one, so it is not "
            "a decision you can defer. For a procurement heavy customer the real question is "
            "whether the organisation will genuinely commit to fit to standard, because "
            "public cloud punishes a customer who says yes and means no.",
            [
                f("How would you test the fit-to-standard commitment before signing?",
                  "fit_to_standard"),
                f("What would push you towards private cloud specifically?", "private_flexible"),
            ],
            study_topics=["Deployment options", "Fit to standard"],
        ),
    ]


# ---------------------------------------------------------------------------
# Track 4 - SAP Business Network
# ---------------------------------------------------------------------------


def sap_business_network_questions() -> list[dict[str, Any]]:
    """Trading partners, document exchange and the commercial model behind it."""
    return [
        q(
            "IQ-BN-001", "sap_business_network", "Network fundamentals", "foundational",
            TECH_RAPID,
            "What is SAP Business Network, and what does a buyer actually get from it?",
            [
                c("many_to_many", "It is a shared network connecting many buyers and many suppliers",
                  "technical", ["network", "many"], weight=1.6, required=True),
                c("documents", "Orders, confirmations, shipping notices and invoices cross it",
                  "technical", ["order", "invoice"], weight=1.5, required=True),
                c("one_connection", "A supplier connects once and trades with everybody on it",
                  "technical", ["connects once"], weight=1.3),
                c("buyer_value", "The buyer gets automation and visibility without a point-to-point build",
                  "business", ["automation", "visibility"], weight=1.4),
            ],
            "SAP Business Network is a shared network that connects many buyers with many "
            "suppliers, rather than a link between two companies. Orders, order "
            "confirmations, shipping notices and invoices cross it in a common format, and a "
            "supplier connects once and can then trade with everybody else on it. What the "
            "buyer gets is automation and visibility of the transaction with the supplier "
            "without building and running a point to point connection per trading partner.",
            [
                f("What does the supplier get in return?", "one_connection"),
                f("Which document usually delivers the first measurable benefit?", "documents"),
            ],
            study_topics=["Business Network fundamentals", "Trading partner enablement"],
        ),
        q(
            "IQ-BN-002", "sap_business_network", "Supplier enablement", "intermediate", TECH,
            "How would you plan the onboarding of two thousand suppliers onto a network?",
            [
                c("segmentation", "Segment suppliers by spend and transaction volume first",
                  "technical", ["segment", "volume"], weight=1.6, required=True),
                c("methods", "Different connection methods suit different supplier sizes",
                  "technical", ["connection method", "portal"], weight=1.4, required=True),
                c("waves", "Onboarding runs in waves with a defined go-live per wave",
                  "technical", ["wave"], weight=1.3),
                c("comms", "Supplier communications and a business reason decide adoption",
                  "business", ["communication", "adoption"], weight=1.5,
                  hint="Enablement is a change programme with a technical component, not the reverse."),
            ],
            "I would segment the suppliers by spend and transaction volume first, because the "
            "top few per cent of suppliers carry most of the documents and deserve most of the "
            "effort. Different connection methods suit different sizes: a full integration for "
            "the largest, and the supplier portal for the long tail who will never build one. "
            "Onboarding then runs in waves with a defined go live per wave, so problems stay "
            "contained. The part that decides success is communication: suppliers need a "
            "business reason to move and a named contact, and adoption stalls without both.",
            [
                f("What do you do about a strategic supplier who simply refuses?", "comms"),
                f("How large would you make the first wave?", "waves"),
            ],
            study_topics=["Supplier enablement", "Onboarding waves"],
        ),
        q(
            "IQ-BN-003", "sap_business_network", "Document exchange", "intermediate", TECH_RAPID,
            "Which documents flow in each direction across the network in a normal order "
            "to invoice cycle?",
            [
                c("buyer_to_supplier", "The order and its changes go out to the supplier",
                  "technical", ["order", "change"], weight=1.5, required=True),
                c("supplier_to_buyer", "Confirmation, shipping notice and invoice come back",
                  "technical", ["confirmation", "shipping notice", "invoice"],
                  weight=1.6, required=True),
                c("status", "Status updates flow continuously in both directions",
                  "technical", ["status"], weight=1.2),
                c("why_confirm", "The confirmation is what turns a promised date into a managed one",
                  "business", ["promised date", "managed"], weight=1.3),
            ],
            "The purchase order and any subsequent change go out from the buyer to the "
            "supplier. Coming back are the order confirmation, the advance shipping notice "
            "and the invoice, with status updates flowing continuously in both directions so "
            "each side can see where a document has got to. The order confirmation is the "
            "underrated one, because it is what turns a requested date into a promised date "
            "that can be managed, and without it the buyer only finds out about a delay when "
            "the delivery does not arrive.",
            [
                f("What would you do with a confirmation that changes the date?", "why_confirm"),
                f("Which document should a supplier send first when they join?",
                  "supplier_to_buyer"),
            ],
            study_topics=["Document exchange", "Order confirmations"],
        ),
        q(
            "IQ-BN-004", "sap_business_network", "Commercial model", "intermediate", JUDGEMENT,
            "Suppliers sometimes push back on network fees. How would you handle that "
            "conversation?",
            [
                c("who_pays", "Understand which side the fee falls on and at what volume",
                  "technical", ["fee", "volume"], weight=1.4, required=True),
                c("thresholds", "Small suppliers often fall below the charging threshold",
                  "technical", ["threshold"], weight=1.3, required=True),
                c("alternatives", "Alternative connection options exist for the long tail",
                  "technical", ["alternative"], weight=1.2),
                c("supplier_value", "Make the supplier's own benefit concrete: fewer queries, faster payment",
                  "business", ["faster payment", "queries"], weight=1.5),
                c("honesty", "Do not pretend the cost is zero",
                  "business", ["cost"], weight=1.3,
                  hint="An interviewer is testing whether you will mislead a supplier."),
            ],
            "First I would establish the facts for that specific supplier: which side the fee "
            "falls on and at what document volume, because many smaller suppliers sit below "
            "the charging threshold entirely and are worrying about a cost they will not "
            "incur. For those above it, there are alternative connection options for the long "
            "tail, and the conversation should make their own benefit concrete - fewer "
            "queries, fewer disputed invoices and faster payment. What I would not do is "
            "pretend the cost is zero, because a supplier who finds out later trusts nothing "
            "else the programme tells them.",
            [
                f("What would you do if the fee genuinely outweighs the supplier's benefit?",
                  "honesty"),
                f("How would you segment suppliers for this conversation?", "who_pays"),
            ],
            study_topics=["Network commercial model", "Supplier relations"],
        ),
        q(
            "IQ-BN-005", "sap_business_network", "cXML", "advanced", TECH,
            "What is cXML and where does a new integrator usually go wrong with it?",
            [
                c("what_it_is", "An XML standard for procurement documents between partners",
                  "technical", ["XML", "document"], weight=1.5, required=True),
                c("request_response", "Documents are sent as requests with an acknowledged response",
                  "technical", ["request", "response"], weight=1.4, required=True),
                c("punchout_use", "Punchout sessions are set up with cXML as well",
                  "technical", ["punchout"], weight=1.3),
                c("common_error", "Credentials and identity domains are the usual first failure",
                  "technical", ["credential", "identity"], weight=1.4),
                c("testing", "Test with the real partner early rather than against a specification",
                  "business", ["test", "early"], weight=1.2),
            ],
            "cXML is an XML standard for exchanging procurement documents between trading "
            "partners: orders, invoices, confirmations and the setup of a punchout session. "
            "Documents are sent as a request and the receiver returns a response that says "
            "whether it was accepted, so failures are visible rather than silent. Where new "
            "integrators go wrong is credentials and identity domains: both sides have to "
            "agree exactly how each party is identified, and a mismatch there looks like a "
            "network problem and is not one. The fix is to test with the real partner early "
            "instead of building carefully against the specification and meeting reality on "
            "the day of go-live.",
            [
                f("How would you debug a document the partner says never arrived?",
                  "request_response"),
                f("What would you put in a partner test plan?", "testing"),
            ],
            study_topics=["cXML", "Trading partner testing"],
        ),
        q(
            "IQ-BN-006", "sap_business_network", "Invoice rules", "advanced", TECH,
            "What are invoice rules on the network for, and what is the risk of setting "
            "them too tightly?",
            [
                c("validate_early", "Rules validate an invoice before it reaches the buyer",
                  "technical", ["validate", "before"], weight=1.6, required=True),
                c("examples", "Typical rules cover order reference, tax, quantity and duplicates",
                  "technical", ["order reference", "duplicate"], weight=1.4, required=True),
                c("supplier_feedback", "The supplier is told immediately and can correct it",
                  "technical", ["immediately", "correct"], weight=1.3),
                c("too_tight", "Over-tight rules push suppliers back to email and paper",
                  "business", ["email", "back to"], weight=1.5,
                  hint="Name the failure mode, not just the benefit."),
            ],
            "Invoice rules validate an invoice on the network before it ever reaches the "
            "buyer's system, covering things like a valid order reference, tax treatment, "
            "quantity against the order and duplicate detection. The value is that the "
            "supplier is told immediately and can correct it themselves, instead of the "
            "invoice becoming an exception that somebody investigates a fortnight later. Set "
            "too tightly they become a wall, and a supplier who gives up goes "
            "back to email and paper, so the buyer loses both the automation and the "
            "visibility they were paying for.",
            [
                f("How would you decide which rules to relax first?", "too_tight"),
                f("What would you monitor after switching a new rule on?", "supplier_feedback"),
            ],
            study_topics=["Invoice rules", "Supplier experience"],
        ),
        q(
            "IQ-BN-007", "sap_business_network", "Enablement waves", "advanced", JUDGEMENT,
            "The first enablement wave has slipped and adoption is below target. What do "
            "you do?",
            [
                c("diagnose", "Find out whether it is a technical, commercial or awareness problem",
                  "technical", ["technical", "commercial", "awareness"],
                  weight=1.6, required=True),
                c("segment_again", "Re-check the segmentation: the wave may have the wrong suppliers",
                  "technical", ["segmentation"], weight=1.3),
                c("unblock", "Fix the top blocker rather than pushing everybody harder",
                  "technical", ["blocker"], weight=1.4, required=True),
                c("replan", "Replan the later waves honestly rather than absorbing the slip",
                  "business", ["replan", "honestly"], weight=1.5),
            ],
            "Before changing the plan I would find out which problem it is, because a "
            "technical blocker, a commercial objection and simple lack of awareness look "
            "identical in an adoption number and have completely different fixes. I would "
            "re-check the segmentation as well, since a wave built around the wrong suppliers "
            "will underperform however well it is run. Then I would fix the single biggest "
            "blocker rather than pushing everybody harder, and replan the later waves "
            "honestly instead of quietly absorbing the slip and arriving at the same problem "
            "three months later with less credibility.",
            [
                f("What would you tell the steering committee?", "replan"),
                f("How would you find the top blocker quickly?", "unblock"),
            ],
            study_topics=["Enablement programmes", "Adoption management"],
        ),
        q(
            "IQ-BN-008", "sap_business_network", "Network versus EDI", "advanced", ARCH,
            "A customer already runs EDI with their top suppliers. Why would they add a "
            "business network?",
            [
                c("edi_strength", "EDI works well for high volume with a stable partner",
                  "technical", ["EDI", "high volume"], weight=1.4, required=True),
                c("tail_problem", "EDI does not reach the long tail economically",
                  "technical", ["long tail"], weight=1.6, required=True),
                c("coexistence", "The two coexist rather than one replacing the other",
                  "architecture", ["coexist"], weight=1.5, required=True),
                c("single_process", "One process with two transport mechanisms underneath",
                  "architecture", ["one process", "transport"], weight=1.4),
                c("cost_per_partner", "The decision is cost per partner against benefit per partner",
                  "business", ["cost per", "benefit"], weight=1.3),
            ],
            "EDI works well where volume is high and the partner is stable, and there is "
            "rarely a good reason to rip it out. The gap is the long tail, which EDI reaches "
            "only at a cost per partner nobody can justify, because every new partner is a "
            "project. A business network is how "
            "the remaining few hundred suppliers get connected, so in practice the two "
            "coexist: one process inside the buyer's system, with two transport mechanisms "
            "underneath it. The decision for any individual partner is the cost per partner "
            "against the benefit per partner, not a religious argument about which technology "
            "is better.",
            [
                f("How would you keep one process across two transports?", "single_process"),
                f("Where is the crossover point between the two?", "cost_per_partner"),
            ],
            study_topics=["EDI and networks", "Integration strategy"],
        ),
        q(
            "IQ-BN-009", "sap_business_network", "Order collaboration", "intermediate", TECH,
            "What is an advance shipping notice for, and what does it enable at the "
            "receiving dock?",
            [
                c("what_it_is", "The supplier tells you what has shipped before it arrives",
                  "technical", ["shipped", "before it arrives"], weight=1.6, required=True),
                c("receipt_speed", "Goods receipt can be posted against it instead of keyed",
                  "technical", ["goods receipt", "against"], weight=1.5, required=True),
                c("discrepancy", "Differences are visible before the lorry is on site",
                  "technical", ["difference", "visible"], weight=1.2),
                c("planning_value", "Inbound visibility improves planning and dock scheduling",
                  "business", ["planning", "scheduling"], weight=1.4),
            ],
            "An advance shipping notice is the supplier telling you what has actually shipped "
            "before it arrives, with quantities and often packaging and tracking detail. At "
            "the dock the goods receipt can be posted against it rather than keyed from a "
            "delivery note, which is faster and much less error prone, and any difference "
            "between what was ordered and what was shipped is visible before the lorry is on "
            "site. Upstream it gives inbound visibility, which is what makes planning and "
            "dock scheduling possible rather than reactive.",
            [
                f("What do you do when the notice and the delivery disagree?", "discrepancy"),
                f("Which suppliers would you ask for it first?", "planning_value"),
            ],
            study_topics=["Order collaboration", "Advance shipping notices"],
        ),
        q(
            "IQ-BN-010", "sap_business_network", "Payment collaboration", "advanced",
            ALL_PRACTICE,
            "How does early payment discounting work, and who actually benefits?",
            [
                c("mechanism", "The supplier is paid early in exchange for a discount",
                  "technical", ["paid early", "discount"], weight=1.6, required=True),
                c("dynamic", "A dynamic discount scales with how early the payment is",
                  "technical", ["dynamic", "scales"], weight=1.4, required=True),
                c("funding", "Somebody has to fund it: the buyer's cash or a third party",
                  "technical", ["fund"], weight=1.4),
                c("both_sides", "The buyer gets a return on cash, the supplier gets certainty",
                  "business", ["return on cash", "certainty"], weight=1.5),
                c("caution", "It is not a substitute for fixing slow approvals",
                  "business", ["slow approval"], weight=1.2),
            ],
            "The supplier is paid early in exchange for a discount on the invoice, and in a "
            "dynamic programme the discount scales with how early the payment lands rather "
            "than being a single fixed term. Somebody has to fund it, either from the buyer's "
            "own cash or through a third party, and which of those it is changes the "
            "economics completely. Both sides can win: the buyer earns a return on cash it is "
            "holding anyway and the supplier gets certainty and cheaper working capital. "
            "Fixing slow approval comes first, though, because discounting an "
            "invoice that took three weeks to approve is paying to hide a process problem.",
            [
                f("Which suppliers would you offer it to first?", "both_sides"),
                f("What would make you advise against a programme?", "caution"),
            ],
            study_topics=["Payment collaboration", "Working capital"],
        ),
        q(
            "IQ-BN-011", "sap_business_network", "Troubleshooting", "expert", TECH,
            "A supplier says they sent an invoice three days ago and the buyer has no record "
            "of it. How do you investigate?",
            [
                c("trace", "Trace the document by number through each hop in turn",
                  "technical", ["trace", "hop"], weight=1.6, required=True),
                c("rejection", "Check whether a rule rejected it and where the rejection went",
                  "technical", ["rejected", "rule"], weight=1.5, required=True),
                c("identity", "Check the routing identity: it may have gone to another account",
                  "technical", ["routing", "identity"], weight=1.4),
                c("evidence", "Ask the supplier for the document number and the timestamp",
                  "technical", ["document number", "timestamp"], weight=1.2),
                c("communication", "Keep the supplier informed while you look",
                  "business", ["informed"], weight=1.3),
            ],
            "I would ask the supplier for the document number and the timestamp first, "
            "because without those I am guessing, and then trace that document by number "
            "through each hop in turn rather than assuming which side lost it. The two "
            "commonest causes are that a rule rejected it and the rejection went to an "
            "address nobody reads, or that the routing identity is wrong and it arrived "
            "correctly in somebody else's account. Throughout, I would keep the supplier "
            "informed, because from where they sit an unpaid invoice and a silent buyer are "
            "the same problem.",
            [
                f("How would you stop this recurring for that supplier?", "rejection"),
                f("What if the trace shows it never left the supplier?", "evidence"),
            ],
            study_topics=["Network troubleshooting", "Document tracing"],
        ),
    ]


# ---------------------------------------------------------------------------
# Track 5 - SAP Integration
# ---------------------------------------------------------------------------


def sap_integration_questions() -> list[dict[str, Any]]:
    """IDocs, APIs, events, middleware and what happens when they fail."""
    return [
        q(
            "IQ-IN-001", "sap_integration", "IDoc basics", "foundational", TECH_RAPID,
            "What is an IDoc, and what are the parts of one?",
            [
                c("structure", "An IDoc has a control record, data records and status records",
                  "technical", ["control record", "data record", "status record"],
                  weight=1.6, required=True),
                c("message_type", "The message type and basic type describe what it carries",
                  "technical", ["message type", "basic type"], weight=1.4, required=True),
                c("asynchronous", "IDoc processing is asynchronous",
                  "technical", ["asynchronous"], weight=1.3),
                c("audit", "The status records are what make an IDoc auditable after the fact",
                  "business", ["auditable", "after the fact"], weight=1.2),
            ],
            "An IDoc is a structured container for a business document moving between systems. "
            "It has a control record holding the sender, receiver and message type, data "
            "records holding the segments with the content, and status records recording "
            "everything that has happened to it. The message type says what business document "
            "it is and the basic type describes its structure. Processing is asynchronous, so "
            "the sender is free once the IDoc is handed over, and the status records are what "
            "make the whole thing auditable after the fact.",
            [
                f("What is the difference between a basic type and an extension?",
                  "message_type"),
                f("Why does asynchronous processing complicate error handling?", "asynchronous"),
            ],
            study_topics=["IDoc structure", "IDoc processing"],
        ),
        q(
            "IQ-IN-002", "sap_integration", "Interface troubleshooting", "advanced", TECH,
            "An overnight interface has failed and two hundred documents are stuck. Talk me "
            "through your first hour.",
            [
                c("assess_impact", "Establish the business impact before touching anything",
                  "technical", ["business impact", "before"], weight=1.5, required=True),
                c("find_status", "Read the error status and group the failures by cause",
                  "technical", ["error status", "group"], weight=1.6, required=True),
                c("root_cause", "Separate data errors from a system or connectivity failure",
                  "technical", ["data error", "connectivity"], weight=1.5, required=True),
                c("reprocess", "Reprocess in a controlled batch once the cause is fixed",
                  "technical", ["reprocess", "batch"], weight=1.3),
                c("communicate", "Tell the affected business area what to expect and when",
                  "business", ["tell", "expect"], weight=1.4,
                  hint="An interviewer is listening for who you inform, not only what you type."),
            ],
            "In the first hour I would establish the business impact before touching anything: "
            "which documents, whose process and whether anything is time critical today. Then "
            "I would read the error status on the failed messages and group the failures by "
            "cause, because two hundred failures are usually three problems. That grouping "
            "separates a data error, which needs the sending system corrected, from a "
            "connectivity or system failure, which needs the interface restarted. Once the "
            "cause is fixed I would reprocess in a controlled batch rather than all at once, "
            "and throughout I would tell the affected business area what to expect and when, "
            "because they are making decisions with or without me.",
            [
                f("How do you avoid double posting when you reprocess?", "reprocess"),
                f("What would you put in the post-incident actions?", "root_cause"),
            ],
            wrong=[
                w("just_reprocess",
                  "Reprocessing everything immediately is offered as the first step.",
                  ["just reprocess everything", "reprocess them all immediately"],
                  "Reprocessing before the cause is understood usually recreates the same "
                  "failures and can post duplicates."),
            ],
            study_topics=["Interface monitoring", "Incident handling"],
        ),
        q(
            "IQ-IN-003", "sap_integration", "API styles", "intermediate", TECH_RAPID,
            "When would you choose OData over a SOAP service or a plain REST API?",
            [
                c("odata", "OData is a REST convention with query and metadata built in",
                  "technical", ["OData", "metadata"], weight=1.5, required=True),
                c("soap", "SOAP brings a strict contract and heavier tooling",
                  "technical", ["SOAP", "contract"], weight=1.4, required=True),
                c("fit", "The choice follows the consumer, not fashion",
                  "architecture", ["consumer"], weight=1.5, required=True),
                c("payload_size", "Query capability matters when the consumer needs a subset",
                  "architecture", ["subset"], weight=1.2),
                c("cost", "Every style you support is one more thing to secure and monitor",
                  "business", ["secure", "monitor"], weight=1.3),
            ],
            "OData is a REST convention with query capability and metadata built in, which is "
            "why it fits a user interface that needs to fetch a subset of a large collection "
            "and discover the shape of it. SOAP brings a strict contract and heavier tooling, "
            "which still earns its place in machine to machine integration where both sides "
            "want the contract enforced. A plain REST API is the pragmatic middle. The choice "
            "should follow the consumer and what it can actually implement, not fashion, and "
            "it is worth remembering that every style you support is one more thing to secure "
            "and monitor.",
            [
                f("Which would you choose for a mobile app, and why?", "fit"),
                f("What do you lose by exposing OData to an external partner?",
                  "payload_size"),
            ],
            study_topics=["API styles", "Integration design"],
        ),
        q(
            "IQ-IN-004", "sap_integration", "Integration platform", "advanced", ARCH,
            "What does an integration platform give you that a direct connection between two "
            "systems does not?",
            [
                c("decoupling", "It decouples the two systems from each other",
                  "technical", ["decouple"], weight=1.5, required=True),
                c("mapping", "Mapping and transformation live in one place",
                  "technical", ["mapping", "transformation"], weight=1.4, required=True),
                c("operations", "Monitoring, retry and alerting are provided once",
                  "architecture", ["monitoring", "retry"], weight=1.5, required=True),
                c("governance", "Interfaces become an inventory somebody can govern",
                  "architecture", ["inventory"], weight=1.3),
                c("cost_case", "It only pays back above a certain number of interfaces",
                  "business", ["pays back", "number of interfaces"], weight=1.4,
                  hint="Say when it is NOT worth it - two interfaces do not need a platform."),
            ],
            "A platform decouples the two systems, so a change on one side does not force a "
            "change on the other, and it puts mapping and transformation in one place rather "
            "than in whichever system happened to build the link. Monitoring, retry and "
            "alerting are provided once instead of per interface, and the interfaces become an "
            "inventory somebody can actually govern. The honest caveat is that it only pays "
            "back above a certain number of interfaces: a company with two links between two "
            "systems is buying a platform to run a cron job.",
            [
                f("Where would you draw the line for a small landscape?", "cost_case"),
                f("What belongs in the platform and what belongs in the application?",
                  "mapping"),
            ],
            study_topics=["Integration platforms", "Middleware patterns"],
        ),
        q(
            "IQ-IN-005", "sap_integration", "Reliability", "expert", ARCH,
            "How do you design an interface so that a retry cannot create a duplicate "
            "document?",
            [
                c("idempotency", "The receiver has to be idempotent on a stable key",
                  "technical", ["idempotent", "stable key"], weight=1.6, required=True),
                c("correlation", "A correlation identifier travels with every message",
                  "technical", ["correlation"], weight=1.5, required=True),
                c("at_least_once", "Assume at-least-once delivery, because exactly-once is expensive",
                  "architecture", ["at least once", "exactly once"], weight=1.5, required=True),
                c("dedup_window", "Duplicate detection needs a defined window and a store",
                  "architecture", ["window"], weight=1.3),
                c("consequence", "A duplicate order is a real payment somebody has to unwind",
                  "business", ["duplicate order", "unwind"], weight=1.4),
            ],
            "I design for at least once delivery, because exactly once across two systems is "
            "expensive and usually a fiction, and then make the receiver idempotent. That "
            "means every message carries a correlation identifier built from a stable key, and "
            "the receiver records what it has already processed so a repeat is recognised and "
            "acknowledged rather than posted again. Duplicate detection needs a defined window "
            "and somewhere to keep the keys, and both of those have to be sized deliberately. "
            "The reason it is worth the effort is that a duplicate order is a real payment and "
            "somebody in accounts payable has to unwind it.",
            [
                f("What would you use as the stable key for a purchase order?", "idempotency"),
                f("How long would you keep the duplicate detection window?", "dedup_window"),
            ],
            study_topics=["Idempotency", "Message reliability"],
        ),
        q(
            "IQ-IN-006", "sap_integration", "Event-driven integration", "advanced", ARCH,
            "When is an event the right integration style, and what does it cost you?",
            [
                c("publish", "The producer publishes without knowing the consumers",
                  "technical", ["publish", "consumer"], weight=1.5, required=True),
                c("loose_coupling", "New consumers can be added without touching the producer",
                  "architecture", ["without touching"], weight=1.5, required=True),
                c("eventual", "You accept eventual consistency and out-of-order delivery",
                  "architecture", ["eventual consistency", "out of order"],
                  weight=1.5, required=True),
                c("debugging", "Tracing a business process across events is genuinely harder",
                  "technical", ["tracing", "harder"], weight=1.3),
                c("fit", "It suits notification, not a request that needs an answer",
                  "business", ["notification", "answer"], weight=1.4),
            ],
            "An event is right when the producer should publish that something happened "
            "without knowing which consumers care, so a new consumer can be added later "
            "without touching the producer at all. The price is that you accept eventual "
            "consistency and possibly out of order delivery, and that tracing one business "
            "process across a chain of events is genuinely harder than following a synchronous "
            "call. So it suits notification and fan-out, and it is the wrong choice when the "
            "caller needs an answer before it can continue.",
            [
                f("How would you trace one order across an event chain?", "debugging"),
                f("What would you do about a consumer that falls behind?", "eventual"),
            ],
            study_topics=["Event-driven architecture", "Eventual consistency"],
        ),
        q(
            "IQ-IN-007", "sap_integration", "Interface monitoring", "advanced", TECH,
            "What would you put in place so that a failed interface is noticed before a user "
            "notices it?",
            [
                c("alerting", "Alerts on failure and on volume falling to zero",
                  "technical", ["alert", "zero"], weight=1.6, required=True),
                c("dashboard", "A dashboard showing each interface and its last successful run",
                  "technical", ["last successful"], weight=1.4, required=True),
                c("ownership", "Every interface needs a named owner and a response time",
                  "technical", ["named owner"], weight=1.4, required=True),
                c("silence_is_worst", "The dangerous failure is the one that produces no error",
                  "technical", ["no error"], weight=1.3),
                c("business_view", "The business needs a view in their own terms, not message counts",
                  "business", ["their own terms", "message count"], weight=1.3),
            ],
            "Alerts on failure are the easy half. The half that gets missed is an alert when "
            "volume falls to zero, because the dangerous failure is the one that produces no "
            "error at all: nothing arrives and nothing complains. Alongside that I would want "
            "a dashboard showing each interface and its last successful run, and every "
            "interface needs a named owner and an agreed response time or the alert goes to "
            "everybody and therefore to nobody. Finally the business needs a view in their own "
            "terms - orders not sent today - rather than a message count they cannot interpret.",
            [
                f("How would you set the threshold for a volume alert?", "alerting"),
                f("Who should own an interface between two departments?", "ownership"),
            ],
            study_topics=["Interface monitoring", "Operational readiness"],
        ),
        q(
            "IQ-IN-008", "sap_integration", "Integration topology", "advanced", ARCH,
            "A landscape has grown twenty point-to-point interfaces. What would you "
            "recommend and how would you sequence it?",
            [
                c("problem", "Point-to-point coupling grows faster than the system count",
                  "technical", ["point to point", "coupling"], weight=1.5, required=True),
                c("hub", "A hub or platform reduces the number of connections to maintain",
                  "architecture", ["hub", "connections"], weight=1.5, required=True),
                c("no_big_bang", "Migrate interface by interface, never in one move",
                  "architecture", ["interface by interface"], weight=1.6, required=True),
                c("prioritise", "Start with the interfaces that break most or change most",
                  "technical", ["break most", "change most"], weight=1.3),
                c("cost_benefit", "The case is maintenance cost and change speed, not elegance",
                  "business", ["maintenance cost", "change speed"], weight=1.4),
            ],
            "Point to point works until it does not: the coupling grows faster than the system "
            "count, and every change ripples through links nobody has documented. I would "
            "recommend a hub so the number of connections to maintain drops, but I would "
            "migrate interface by interface rather than in one move, because a big bang "
            "replaces twenty working interfaces with one untested platform. I would start with "
            "the interfaces that break most or change most, since those pay back first, and I "
            "would make the case on maintenance cost and change speed rather than on "
            "architectural elegance, which no finance director has ever funded.",
            [
                f("What would you leave on point-to-point permanently?", "prioritise"),
                f("How would you prove the maintenance saving?", "cost_benefit"),
            ],
            study_topics=["Integration topology", "Migration sequencing"],
        ),
        q(
            "IQ-IN-009", "sap_integration", "API management", "advanced", ARCH,
            "What does an API gateway do for you when you expose an SAP service to a partner?",
            [
                c("security", "It terminates authentication and hides the backend",
                  "technical", ["authentication", "hides"], weight=1.6, required=True),
                c("throttling", "Rate limiting protects the backend from a badly behaved caller",
                  "technical", ["rate limiting", "rate limit"], weight=1.5, required=True),
                c("versioning", "It gives you a place to version and deprecate an interface",
                  "architecture", ["version", "deprecate"], weight=1.4, required=True),
                c("observability", "Usage per consumer becomes visible and chargeable",
                  "architecture", ["usage per consumer"], weight=1.2),
                c("risk", "Exposing an ERP directly to the internet is the thing you are avoiding",
                  "business", ["ERP directly", "open a port"], weight=1.4),
            ],
            "A gateway terminates authentication at the edge and hides the backend, so the "
            "partner never talks to the ERP directly - which is the thing you are actually "
            "trying to prevent when somebody asks to open a port. It applies rate limiting so "
            "one badly behaved caller cannot exhaust the backend, and it gives you somewhere "
            "to version an interface and deprecate an old one on a published timetable. It "
            "also makes usage per consumer visible, which matters as soon as somebody asks who "
            "is generating the load or who should pay for it.",
            [
                f("How would you deprecate a version a partner still uses?", "versioning"),
                f("What rate limit would you start with?", "throttling"),
            ],
            study_topics=["API management", "External exposure"],
        ),
        q(
            "IQ-IN-010", "sap_integration", "File interfaces", "intermediate", TECH,
            "A partner insists on exchanging files on a schedule. What are the risks and how "
            "do you contain them?",
            [
                c("no_ack", "A file drop gives you no acknowledgement by default",
                  "technical", ["acknowledgement"], weight=1.5, required=True),
                c("partial_file", "A file read while still being written is a classic failure",
                  "technical", ["still being written"], weight=1.5, required=True),
                c("duplicates", "Reprocessing the same file twice must be prevented",
                  "technical", ["same file twice"], weight=1.4),
                c("controls", "Control totals and a manifest make a bad file detectable",
                  "technical", ["control total"], weight=1.3),
                c("latency", "Batch latency has to be acceptable to the business process",
                  "business", ["latency"], weight=1.3),
            ],
            "The first risk is that a file drop leaves you without an acknowledgement unless you "
            "build one, so neither side "
            "knows whether anything was received until somebody asks. The second is a file "
            "read while it is still being written, which produces a half a file that looks "
            "valid; a temporary name and an atomic rename, or a separate marker file, fixes "
            "it. Then you have to prevent the same file twice from being reprocessed, and "
            "carry control totals or a manifest so a truncated file is detectable rather than "
            "silently short. Finally the batch latency has to be acceptable to the business "
            "process, because a nightly file is a decision made once a day.",
            [
                f("How would you acknowledge a file back to the partner?", "no_ack"),
                f("What would you do if the row count and the control total disagree?",
                  "controls"),
            ],
            study_topics=["File interfaces", "Batch integration"],
        ),
        q(
            "IQ-IN-011", "sap_integration", "Authentication", "advanced", ARCH,
            "How should two systems authenticate to each other, and what do you do about "
            "the credentials?",
            [
                c("technical_user", "A dedicated technical identity, never a person's account",
                  "technical", ["technical", "person"], weight=1.6, required=True),
                c("modern_auth", "Certificates or token-based authentication beat a shared password",
                  "technical", ["certificate", "token"], weight=1.5, required=True),
                c("rotation", "Credentials need an owner, an expiry and a rehearsed rotation",
                  "architecture", ["rotation", "expiry"], weight=1.5, required=True),
                c("least_privilege", "The identity gets only the authorisations the interface needs",
                  "architecture", ["least privilege"], weight=1.4),
                c("outage", "An expired certificate nobody owns is a self-inflicted outage",
                  "business", ["expired", "outage"], weight=1.3),
            ],
            "The calling system should use a dedicated technical identity rather than a "
            "person's account, because a person leaves and the interface stops. Certificates "
            "or token based authentication are preferable to a shared password, and whichever "
            "is used needs an owner, a recorded expiry and a rotation somebody has rehearsed. "
            "The identity itself gets least privilege - only the authorisations the interface "
            "actually needs - so a compromised credential does not become a compromised "
            "system. The failure mode to design out is an expired certificate that nobody "
            "owns, which is a completely self-inflicted outage and a surprisingly common one.",
            [
                f("How would you rehearse a certificate rotation?", "rotation"),
                f("What authorisations would you give an inbound order interface?",
                  "least_privilege"),
            ],
            study_topics=["Interface security", "Credential management"],
        ),
        q(
            "IQ-IN-012", "sap_integration", "Error recovery", "expert", ARCH,
            "Design the error handling for an inbound order interface. What happens to a "
            "message that cannot be processed?",
            [
                c("classify", "Separate retryable failures from permanent ones",
                  "technical", ["retryable", "permanent"], weight=1.6, required=True),
                c("backoff", "Retry with a backoff and a maximum attempt count",
                  "technical", ["backoff", "maximum"], weight=1.5, required=True),
                c("dead_letter", "Permanent failures go to a queue somebody actually works",
                  "architecture", ["dead letter", "works"], weight=1.5, required=True),
                c("visibility", "The sender must learn that their message failed",
                  "architecture", ["sender", "failed"], weight=1.4),
                c("ownership", "A rejected order is somebody's revenue, so it needs an owner",
                  "business", ["revenue", "owner"], weight=1.4),
            ],
            "First I would classify the failure, because a retryable failure such as a locked "
            "record and a permanent one such as an unknown material need opposite treatment. "
            "Retryable failures retry with a backoff and a maximum attempt count so a "
            "temporary outage heals itself without flooding the receiver. Permanent failures "
            "go to a dead letter queue that somebody actually works, with the original payload "
            "kept so it can be corrected and resubmitted. The sender has to learn that their "
            "message failed rather than assuming silence means success. And the queue needs a "
            "named owner, because a rejected order is somebody's revenue sitting in a "
            "technical holding area.",
            [
                f("How many retries, and how would you choose the number?", "backoff"),
                f("Who should own the dead letter queue in a procurement interface?",
                  "ownership"),
            ],
            study_topics=["Error handling", "Dead letter queues"],
        ),
    ]


# ---------------------------------------------------------------------------
# Track 6 - SAP Architecture
# ---------------------------------------------------------------------------


def sap_architecture_questions() -> list[dict[str, Any]]:
    """Landscape, extensibility, resilience and the trade-offs behind them."""
    return [
        q(
            "IQ-AC-001", "sap_architecture", "System landscape", "intermediate", ARCH,
            "Why does an SAP landscape have separate development, quality and production "
            "systems, and what flows between them?",
            [
                c("separation", "Change is made in development and never in production",
                  "technical", ["development", "production"], weight=1.6, required=True),
                c("transport", "Transports carry configuration and code along a defined route",
                  "technical", ["transport", "route"], weight=1.5, required=True),
                c("test_data", "Quality needs representative data to test against",
                  "architecture", ["representative"], weight=1.3),
                c("no_backflow", "Nothing flows back from production except data copies",
                  "architecture", ["copies"], weight=1.3),
                c("risk", "The separation exists to make an untested change impossible",
                  "business", ["untested"], weight=1.4),
            ],
            "Change is made in development and moves forward through quality to production, "
            "and it is never made directly in production. Transports carry the configuration "
            "and the code along that defined route in a recorded order, so what was tested is "
            "what arrives. The quality system needs representative data or the test proves "
            "nothing, and nothing flows backwards except data copies taken for that purpose. "
            "The whole arrangement exists so that an untested change reaching production is "
            "hard rather than merely discouraged.",
            [
                f("What do you do when an emergency fix is needed in production?",
                  "no_backflow"),
                f("How would you keep quality data representative without copying "
                  "personal data?", "test_data"),
            ],
            study_topics=["System landscape", "Transport management"],
        ),
        q(
            "IQ-AC-002", "sap_architecture", "Clean core", "advanced", ARCH,
            "What does clean core mean in practice, and what do you say to a customer who "
            "wants a modification?",
            [
                c("no_modification", "The standard objects stay unmodified",
                  "technical", ["unmodified", "standard"], weight=1.6, required=True),
                c("released_apis", "Extensions use released interfaces and extension points",
                  "technical", ["released", "extension point"], weight=1.6, required=True),
                c("upgrade_cost", "The benefit is upgrades that stay affordable",
                  "architecture", ["upgrade"], weight=1.5, required=True),
                c("side_by_side", "Heavier logic moves to a side-by-side extension",
                  "architecture", ["side by side"], weight=1.3),
                c("conversation", "Ask what business outcome the modification is for",
                  "business", ["business outcome"], weight=1.4,
                  hint="A flat refusal is not an answer; find the requirement underneath."),
            ],
            "Clean core means the standard objects stay unmodified and everything you add "
            "reaches the system through released interfaces and published extension points, "
            "with heavier logic moving to a side by side extension outside the core. The "
            "benefit is that an upgrade stays a technical exercise instead of a project, which "
            "is what keeps a customer current. Faced with a request for a modification I would "
            "ask what business outcome it is for, because in my experience most of them are "
            "either already possible through an extension point or are a habit carried over "
            "from an older system, and the few that are genuinely necessary deserve a "
            "documented, deliberate exception rather than a quiet one.",
            [
                f("What would make you accept a modification?", "conversation"),
                f("How would you find existing modifications in a legacy system?",
                  "no_modification"),
            ],
            wrong=[
                w("clean_core_no_custom",
                  "Clean core is described as meaning no custom code at all.",
                  ["clean core means no custom code", "you cannot write any custom code"],
                  "Clean core does not forbid custom code. It requires custom code to use "
                  "released interfaces and extension points rather than modifying standard."),
            ],
            study_topics=["Clean core", "Extensibility"],
        ),
        q(
            "IQ-AC-003", "sap_architecture", "Side-by-side extensions", "advanced", ARCH,
            "When would you build an extension outside the ERP rather than inside it?",
            [
                c("different_lifecycle", "When the extension changes at a different pace",
                  "technical", ["different pace"], weight=1.4, required=True),
                c("different_users", "When it serves users who should not be in the ERP",
                  "technical", ["users"], weight=1.4, required=True),
                c("scaling", "When load or technology needs differ from the core",
                  "architecture", ["load", "technology"], weight=1.5, required=True),
                c("integration_cost", "It adds an integration, an identity model and an operations burden",
                  "architecture", ["operations", "identity"], weight=1.5, required=True),
                c("decision", "The default stays inside; outside must be justified",
                  "business", ["default"], weight=1.3),
            ],
            "I would go outside when the extension changes at a different pace from the core, "
            "when it serves users who should never be given ERP access at all, or when the "
            "load pattern or the technology needed differs from what the core is good at - a "
            "public-facing supplier portal is all three at once. What it costs is real: an "
            "integration to build, an identity model to run and an operations burden that did "
            "not exist before. So the default stays inside the ERP and going outside is a "
            "decision somebody has to justify, not a preference.",
            [
                f("What is the identity story for external users?", "different_users"),
                f("Who operates the extension after go-live?", "integration_cost"),
            ],
            study_topics=["Side-by-side extensibility", "BTP patterns"],
        ),
        q(
            "IQ-AC-004", "sap_architecture", "Data residency", "expert", ARCH,
            "A group operating in several countries has data residency requirements. How "
            "does that shape the architecture?",
            [
                c("where_data_lives", "Establish which data is restricted and where it may live",
                  "technical", ["restricted", "where"], weight=1.6, required=True),
                c("legal_first", "The legal requirement has to be written down before design",
                  "technical", ["legal", "written down"], weight=1.5, required=True),
                c("regional_instances", "Regional instances or regional storage may be forced",
                  "architecture", ["regional"], weight=1.5, required=True),
                c("consequence", "Splitting by region splits reporting and increases cost",
                  "architecture", ["splits reporting"], weight=1.4),
                c("business_tradeoff", "The business has to accept the price of the constraint",
                  "business", ["price"], weight=1.3),
            ],
            "The first step is to get the legal requirement written down precisely, because "
            "residency, sovereignty and privacy are different constraints and people use the "
            "words interchangeably. Then establish which data is actually restricted and where "
            "it may live, since it is usually a subset rather than everything. That may force "
            "regional instances or at least regional storage, and the consequence is that "
            "splitting by region splits reporting, raises cost and complicates every "
            "cross-border process. The business has to see and accept that price, because it "
            "is a constraint they are buying rather than a technical preference.",
            [
                f("How would you keep group reporting under regional instances?",
                  "consequence"),
                f("What would you do if the legal position is genuinely unclear?",
                  "legal_first"),
            ],
            study_topics=["Data residency", "Regional architecture"],
        ),
        q(
            "IQ-AC-005", "sap_architecture", "Resilience", "expert", ARCH,
            "How would you approach high availability and disaster recovery for a "
            "procurement-critical SAP system?",
            [
                c("rto_rpo", "Start from the recovery time and recovery point objectives",
                  "technical", ["recovery time", "recovery point"], weight=1.6, required=True),
                c("ha_vs_dr", "High availability and disaster recovery solve different problems",
                  "technical", ["high availability", "disaster recovery"],
                  weight=1.5, required=True),
                c("test_it", "An untested recovery plan is not a recovery plan",
                  "architecture", ["untested", "tested"], weight=1.6, required=True),
                c("dependencies", "The interfaces and the middleware have to recover too",
                  "architecture", ["interfaces", "middleware"], weight=1.4),
                c("cost_curve", "Each nine costs money the business has to agree to",
                  "business", ["costs money", "agree"], weight=1.4),
            ],
            "I would start from the recovery time and recovery point objectives the business "
            "will actually sign, because everything else follows from those two numbers. High "
            "availability and disaster recovery then solve different problems - one is a "
            "component failing, the other is a site being lost - and they need different "
            "designs. Whatever is built has to be tested on a schedule, because an untested "
            "recovery plan is a document rather than a capability. The dependencies matter as "
            "much as the database: if the interfaces and the middleware do not recover, an "
            "available ERP still cannot receive an order. And each additional nine costs money "
            "the business has to see and agree.",
            [
                f("How often would you test a failover, and how?", "test_it"),
                f("What RPO would you argue for in procurement, and why?", "rto_rpo"),
            ],
            study_topics=["High availability", "Disaster recovery"],
        ),
        q(
            "IQ-AC-006", "sap_architecture", "Global template", "expert", ARCH,
            "Single global instance or regional instances? How do you make that "
            "recommendation?",
            [
                c("single_benefits", "One instance gives one process and one set of data",
                  "technical", ["one process", "one set of data"], weight=1.5, required=True),
                c("regional_drivers", "Regulation, latency, autonomy and timing push the other way",
                  "technical", ["regulation", "autonomy"], weight=1.5, required=True),
                c("template_governance", "A global template needs governance or it fragments",
                  "architecture", ["governance", "fragment"], weight=1.6, required=True),
                c("change_capacity", "One instance means one change calendar for everybody",
                  "architecture", ["change calendar"], weight=1.4),
                c("honest_answer", "It is an organisational decision more than a technical one",
                  "business", ["organisational"], weight=1.5,
                  hint="An interviewer wants to hear that you know this is not really a technical call."),
            ],
            "A single instance gives one process and one set of data, which is what makes "
            "group reporting and shared services possible at all. Regulation, latency, local "
            "autonomy and differing project timing all push the other way, and any of them can "
            "be decisive. If a single instance is chosen, the global template needs real "
            "governance or it fragments into regional variants that share a database and "
            "nothing else, and everybody ends up on one change calendar, which is a genuine "
            "constraint on how fast any one region can move. The honest answer is that this is "
            "an organisational decision about how centralised the group wants to be, and the "
            "technical facts inform it rather than settle it.",
            [
                f("How would you govern a global template in practice?",
                  "template_governance"),
                f("What would make you recommend regional instances outright?",
                  "regional_drivers"),
            ],
            study_topics=["Global template", "Instance strategy"],
        ),
        q(
            "IQ-AC-007", "sap_architecture", "Sizing and performance", "advanced", ARCH,
            "How would you size a new SAP system, and what usually goes wrong with sizing?",
            [
                c("inputs", "Sizing starts from transaction volumes and user counts",
                  "technical", ["transaction volume", "user count"], weight=1.6, required=True),
                c("peaks", "Peaks matter more than averages",
                  "technical", ["peak", "average"], weight=1.5, required=True),
                c("growth", "Growth and retention drive the data footprint over time",
                  "architecture", ["growth", "retention"], weight=1.4, required=True),
                c("revisit", "Sizing is revisited after go-live against real measurement",
                  "architecture", ["measurement"], weight=1.3),
                c("what_goes_wrong", "The usual failure is estimating from an optimistic plan",
                  "business", ["optimistic"], weight=1.4),
            ],
            "Sizing starts from transaction volumes and user counts by process, and the peak "
            "matters far more than the average - a month-end that is four times a normal day "
            "is the number that decides the hardware. Growth and data retention drive the "
            "footprint over time, so a retention policy is a sizing input rather than an "
            "afterthought. After go-live the sizing is revisited against real measurement, "
            "because the first estimate is always partly wrong. What usually goes wrong is "
            "sizing from an optimistic business plan instead of from measured history, which "
            "produces a system that is comfortable in month one and struggling in month nine.",
            [
                f("Where would you get volumes for a process that does not exist yet?",
                  "inputs"),
                f("What would you measure in the first month after go-live?", "revisit"),
            ],
            study_topics=["Sizing", "Performance management"],
        ),
        q(
            "IQ-AC-008", "sap_architecture", "Master data governance", "advanced", ARCH,
            "Where should master data governance sit in a landscape with several systems?",
            [
                c("single_owner", "One system has to own each master data object",
                  "technical", ["own", "object"], weight=1.6, required=True),
                c("distribution", "The owning system distributes to the consumers",
                  "technical", ["distribute", "consumer"], weight=1.5, required=True),
                c("central_vs_local", "Central governance and local maintenance can be split by attribute",
                  "architecture", ["attribute"], weight=1.4, required=True),
                c("process_not_tool", "Governance is a process with owners, not a product you install",
                  "architecture", ["process", "owners"], weight=1.5, required=True),
                c("cost_of_bad", "Bad master data shows up as failed transactions and bad reporting",
                  "business", ["failed transactions"], weight=1.3),
            ],
            "Each master data object needs exactly one owning system, and that system "
            "distributes to the consumers rather than each system maintaining its own copy. "
            "Central governance and local maintenance can be split by attribute, so the group "
            "controls the fields that affect reporting and compliance while a plant maintains "
            "the ones only it knows. The point I would press hardest is that governance is a "
            "process with named owners and agreed rules; it is not a product you install, and "
            "a tool bought without the process produces the same bad data faster. The cost of "
            "getting it wrong is visible as failed transactions and reporting nobody trusts.",
            [
                f("Which supplier attributes would you govern centrally?",
                  "central_vs_local"),
                f("How would you measure master data quality?", "cost_of_bad"),
            ],
            study_topics=["Master data governance", "Data ownership"],
        ),
        q(
            "IQ-AC-009", "sap_architecture", "Integration principles", "advanced", ARCH,
            "What principles would you write down for integration in a new landscape?",
            [
                c("one_owner_per_interface", "Every interface has an owner and documentation",
                  "technical", ["owner", "documentation"], weight=1.4, required=True),
                c("standard_first", "Use standard interfaces before building anything",
                  "technical", ["standard interface"], weight=1.5, required=True),
                c("loose_coupling", "Decouple through the platform rather than point to point",
                  "architecture", ["decouple"], weight=1.5, required=True),
                c("observability", "Every interface must be monitorable and replayable",
                  "architecture", ["monitorable", "replayable"], weight=1.5, required=True),
                c("enforcement", "Principles without a review gate are decoration",
                  "business", ["review gate"], weight=1.4,
                  hint="Say how the principles are enforced, not only what they are."),
            ],
            "I would write down four: use a standard interface before building anything "
            "custom; decouple through the platform rather than adding another point to point "
            "link; make every interface monitorable and replayable from the day it is built; "
            "and give every interface a named owner and documentation that exists before it "
            "goes live. Then I would add the part most principle documents leave out, which is "
            "how they are enforced - a design review gate with the authority to say no, "
            "because principles without a review gate are decoration that everybody quotes and "
            "nobody follows.",
            [
                f("What would you do when a project wants an exception?", "enforcement"),
                f("How do you keep the documentation current after go-live?",
                  "one_owner_per_interface"),
            ],
            study_topics=["Integration principles", "Architecture governance"],
        ),
        q(
            "IQ-AC-010", "sap_architecture", "Security architecture", "advanced", ARCH,
            "How do you approach authorisation design and segregation of duties in a "
            "procurement landscape?",
            [
                c("role_design", "Roles are built from job functions, not from transactions",
                  "technical", ["job function"], weight=1.6, required=True),
                c("sod_conflicts", "Conflicting duties must be identified and either split or mitigated",
                  "technical", ["conflicting", "mitigated"], weight=1.6, required=True),
                c("least_privilege", "Least privilege applies to people and to technical users alike",
                  "architecture", ["least privilege"], weight=1.4),
                c("review_cycle", "Access needs a recertification cycle, not a one-off design",
                  "architecture", ["recertification"], weight=1.4, required=True),
                c("audit_reality", "The classic finding is one person raising and approving an order",
                  "business", ["raising and approving"], weight=1.4),
            ],
            "Roles should be built from job functions rather than assembled from transactions, "
            "because a role that mirrors a job survives reorganisation and a role that mirrors "
            "a screen list does not. Conflicting duties are then identified explicitly and "
            "either split between people or mitigated with a compensating control that "
            "somebody actually performs. Least privilege applies to technical users as much as "
            "to people. And access needs a recertification cycle, because entitlement "
            "accumulates as people move around. The classic audit finding in procurement is "
            "one person raising and approving an order, and it is almost always the result of "
            "a temporary arrangement nobody removed.",
            [
                f("What is an acceptable mitigating control?", "sod_conflicts"),
                f("How often would you recertify procurement access?", "review_cycle"),
            ],
            study_topics=["Authorisation design", "Segregation of duties"],
        ),
        q(
            "IQ-AC-011", "sap_architecture", "Build versus configure", "advanced", ARCH,
            "A requirement can be met by configuration with a workaround, or by a custom "
            "build. How do you decide?",
            [
                c("total_cost", "Compare lifetime cost, not build cost",
                  "technical", ["lifetime cost"], weight=1.6, required=True),
                c("upgrade_impact", "Custom code carries an upgrade and maintenance obligation",
                  "technical", ["upgrade", "maintenance"], weight=1.5, required=True),
                c("who_operates", "Somebody has to own and support the build afterwards",
                  "architecture", ["support"], weight=1.4, required=True),
                c("reversibility", "Prefer the option that is easier to undo",
                  "architecture", ["undo", "reversibility"], weight=1.4),
                c("business_value", "The requirement's value has to justify either option",
                  "business", ["value", "justify"], weight=1.4),
            ],
            "I would compare lifetime cost rather than build cost, because custom code carries "
            "an upgrade and maintenance obligation for as long as it exists, and the workaround "
            "carries a recurring manual cost that is easy to ignore in a business case. I "
            "would ask who operates and supports the build afterwards, since a build with no "
            "owner becomes an outage nobody can fix. Where the two are close I prefer the "
            "option that is easier to undo, because reversibility is worth real money when the "
            "requirement turns out to have been misunderstood. And underneath all of it the "
            "value of the requirement has to justify either option at all.",
            [
                f("How would you cost a manual workaround honestly?", "total_cost"),
                f("What would make you refuse both options?", "business_value"),
            ],
            study_topics=["Build versus configure", "Total cost of ownership"],
        ),
    ]


# ---------------------------------------------------------------------------
# Track 7 - Procurement
# ---------------------------------------------------------------------------


def procurement_questions() -> list[dict[str, Any]]:
    """Category strategy, savings, suppliers and the numbers behind them."""
    return [
        q(
            "IQ-PR-001", "procurement", "Category strategy", "intermediate", ALL_PRACTICE,
            "How would you build a category strategy for a spend area you have just "
            "inherited?",
            [
                c("spend_analysis", "Start from the spend data: who, what and how much",
                  "technical", ["spend data", "how much"], weight=1.5, required=True),
                c("market_view", "Understand the supply market and how competitive it is",
                  "technical", ["supply market", "competitive"], weight=1.5, required=True),
                c("stakeholders", "Talk to the people who actually use what is bought",
                  "technical", ["stakeholder", "use"], weight=1.3),
                c("levers", "Choose levers: consolidation, specification, terms or demand",
                  "business", ["consolidation", "specification", "demand"],
                  weight=1.5, required=True),
                c("measurable", "Set out the measurable outcome before starting",
                  "business", ["measurable outcome"], weight=1.3),
            ],
            "I would start from the spend data to see who is buying what and how much, since "
            "most inherited categories turn out to be more fragmented than anybody expects. "
            "Then I would build a view of the supply market and how competitive it actually "
            "is, and talk to the stakeholders who use what is bought, because they know where "
            "the specification is gold plated. From there the levers are consolidation of "
            "suppliers, changing the specification, negotiating terms, or reducing demand, and "
            "usually two of them matter far more than the rest. Finally I would set out the "
            "measurable outcome before starting, so the strategy can be judged rather than "
            "admired.",
            [
                f("Which lever gives the fastest result, and which the largest?", "levers"),
                f("What would you do if the spend data is not trustworthy?", "spend_analysis"),
            ],
            study_topics=["Category management", "Spend analysis"],
        ),
        q(
            "IQ-PR-002", "procurement", "Tail spend", "intermediate", PRACTICE_RAPID,
            "What is tail spend and why is it so hard to do anything about?",
            [
                c("definition", "A large number of suppliers carrying a small share of spend",
                  "technical", ["large number", "small share"], weight=1.6, required=True),
                c("cost_to_manage", "The cost to manage each supplier exceeds the saving available",
                  "technical", ["cost to manage"], weight=1.5, required=True),
                c("approaches", "Aggregation, catalogues and a marketplace are the usual answers",
                  "technical", ["aggregation", "catalogue"], weight=1.4),
                c("risk_angle", "Unmanaged suppliers carry compliance and risk exposure",
                  "business", ["compliance"], weight=1.4),
                c("realistic", "The goal is control and simplicity rather than a big saving",
                  "business", ["control", "simplicity"], weight=1.3),
            ],
            "Tail spend is the large number of suppliers who between them carry a small share "
            "of total spend. It is hard because the cost to manage each of those suppliers "
            "exceeds the saving available from any one of them, so classic sourcing does not "
            "pay for itself. The usual answers are aggregation onto fewer suppliers, "
            "catalogues or a marketplace for the long tail, and simply making the compliant "
            "route easy. The stronger argument is often compliance and risk rather than price, "
            "because unmanaged suppliers are where the unchecked ones hide, and the realistic "
            "goal is control and simplicity rather than a headline saving.",
            [
                f("How would you build the business case for tackling it?", "risk_angle"),
                f("Where would you start with two thousand tail suppliers?", "approaches"),
            ],
            study_topics=["Tail spend", "Supplier rationalisation"],
        ),
        q(
            "IQ-PR-003", "procurement", "Savings measurement", "foundational", ALL_PRACTICE,
            "What is the difference between hard and soft savings, and why does finance "
            "care?",
            [
                c("hard", "Hard savings reduce actual spend against a comparable baseline",
                  "technical", ["baseline", "reduce"], weight=1.6, required=True),
                c("soft", "Soft savings are cost avoidance or a benefit that is not budget",
                  "technical", ["cost avoidance"], weight=1.5, required=True),
                c("baseline_dispute", "Most arguments are about the baseline, not the arithmetic",
                  "technical", ["arguments", "arithmetic"], weight=1.4),
                c("budget_link", "Finance only recognises a saving that shows up in a budget",
                  "business", ["budget"], weight=1.5, required=True),
                c("credibility", "Overclaiming destroys procurement's credibility permanently",
                  "business", ["credibility"], weight=1.4),
            ],
            "A hard saving reduces actual spend against a comparable baseline and can be taken "
            "out of a budget. A soft saving is cost avoidance or a benefit that never reaches "
            "the budget, such as a price increase negotiated down or an improvement in payment "
            "terms. Almost every argument about savings is about the baseline rather than the "
            "arithmetic, which is why the baseline should be agreed with finance in advance. "
            "Finance cares because only the first kind changes the numbers they are "
            "accountable for, and overclaiming is the fastest way to lose procurement's "
            "credibility for good.",
            [
                f("How would you agree a baseline for a new product nobody has bought?",
                  "baseline_dispute"),
                f("Would you still report soft savings, and how?", "budget_link"),
            ],
            wrong=[
                w("all_savings_hard",
                  "Cost avoidance is presented as a hard saving.",
                  ["cost avoidance is a hard saving", "avoided cost increases are hard savings"],
                  "Cost avoidance does not reduce a budget, so finance treats it as a soft "
                  "saving however real it is."),
            ],
            study_topics=["Savings measurement", "Baseline definition"],
        ),
        q(
            "IQ-PR-004", "procurement", "Negotiation", "intermediate", JUDGEMENT,
            "How do you prepare for a negotiation with a supplier who knows they are hard "
            "to replace?",
            [
                c("understand_position", "Establish your real alternatives before you start",
                  "technical", ["alternative"], weight=1.6, required=True),
                c("cost_structure", "Understand their cost structure and what drives their price",
                  "technical", ["cost structure", "drives"], weight=1.5, required=True),
                c("beyond_price", "Trade on terms, volume, lead time and risk, not only price",
                  "technical", ["terms", "lead time"], weight=1.4, required=True),
                c("relationship", "You will still need them afterwards",
                  "business", ["afterwards"], weight=1.4),
                c("walk_away", "Know your walk-away and whether it is credible",
                  "business", ["walk-away", "walk away", "credible"], weight=1.5),
            ],
            "The preparation that matters is establishing my real alternatives, because "
            "leverage comes from having one rather than from behaving as though I do. I would "
            "understand their cost structure and what actually drives their price, so the "
            "conversation is about something specific rather than a percentage. With a "
            "supplier who is genuinely hard to replace I would look to trade on terms, volume "
            "commitment, lead time and risk sharing rather than only on price. I would know my "
            "walk-away and whether it is credible, and I would remember that I will still need "
            "them afterwards, so winning badly is losing.",
            [
                f("What do you do when your walk-away is not credible?", "walk_away"),
                f("How would you build an alternative over twelve months?",
                  "understand_position"),
            ],
            study_topics=["Negotiation preparation", "Supplier leverage"],
        ),
        q(
            "IQ-PR-005", "procurement", "Total cost of ownership", "advanced", ALL_PRACTICE,
            "Explain total cost of ownership to somebody who only looks at unit price.",
            [
                c("beyond_unit", "TCO includes everything the purchase costs over its life",
                  "technical", ["over its life"], weight=1.6, required=True),
                c("components", "Acquisition, operation, maintenance, downtime and disposal",
                  "technical", ["maintenance", "disposal"], weight=1.5, required=True),
                c("who_pays", "The costs often land in a different budget from the purchase",
                  "technical", ["different budget"], weight=1.4, required=True),
                c("evidence", "It needs credible numbers or it sounds like an excuse",
                  "business", ["credible numbers"], weight=1.5,
                  hint="A TCO argument without data loses to a unit price with data."),
                c("decision_change", "The point is to change a decision, not to produce a model",
                  "business", ["change a decision"], weight=1.3),
            ],
            "Total cost of ownership is everything a purchase costs over its life rather than "
            "what appears on the invoice: acquisition, operation, spares and maintenance, "
            "downtime, training and disposal. It matters most when those costs land in a "
            "different budget from the purchase, which is exactly when a unit price decision "
            "looks rational to the person making it and expensive to the company. To be taken "
            "seriously it needs credible numbers rather than assertions, and the aim is to "
            "change a decision rather than to produce a model that impresses people, so I "
            "would build the smallest version that answers the question.",
            [
                f("Where would you get the operating cost data?", "evidence"),
                f("How do you handle the budget holder who is judged on unit price?",
                  "who_pays"),
            ],
            study_topics=["Total cost of ownership", "Business cases"],
        ),
        q(
            "IQ-PR-006", "procurement", "Supplier risk", "advanced", ALL_PRACTICE,
            "How would you build a supplier risk programme that people actually use?",
            [
                c("segment", "Assess in proportion to exposure, not every supplier equally",
                  "technical", ["proportion", "exposure"], weight=1.6, required=True),
                c("categories", "Cover financial, operational, compliance and geographic risk",
                  "technical", ["financial", "operational", "compliance"],
                  weight=1.5, required=True),
                c("refresh", "A risk assessment has to be refreshed or it is history",
                  "technical", ["refreshed"], weight=1.4, required=True),
                c("action", "Every rating must have an owner and an action, or nothing changes",
                  "business", ["owner", "action"], weight=1.6, required=True),
                c("realistic", "A questionnaire nobody reads is worse than nothing",
                  "business", ["questionnaire"], weight=1.3),
            ],
            "I would assess suppliers in proportion to the exposure they represent rather than "
            "sending everybody the same questionnaire, because effort spread evenly is effort "
            "wasted. The assessment should cover financial, operational, compliance and "
            "geographic risk, since a supplier can be solvent and still be a single point of "
            "failure. It has to be refreshed on a cycle or it becomes history dressed as "
            "insight. Above all every rating needs an owner and an action, because the failure "
            "mode is a heat map that everybody looks at and nobody acts on, and a "
            "questionnaire nobody reads is worse than nothing because it creates the illusion "
            "of control.",
            [
                f("What action would you attach to a high financial risk rating?", "action"),
                f("How often would you refresh, and what triggers an off-cycle review?",
                  "refresh"),
            ],
            study_topics=["Supplier risk management", "Risk segmentation"],
        ),
        q(
            "IQ-PR-007", "procurement", "Compliance", "intermediate", JUDGEMENT,
            "What is maverick spend, and how would you reduce it without upsetting "
            "everybody?",
            [
                c("definition", "Buying outside the agreed process or the agreed supplier",
                  "technical", ["outside the agreed"], weight=1.6, required=True),
                c("measure_it", "Measure it before trying to fix it",
                  "technical", ["measure"], weight=1.4, required=True),
                c("root_cause", "It usually means the compliant route is slower or unknown",
                  "technical", ["slower", "unknown"], weight=1.5, required=True),
                c("make_easy", "Make the compliant route the easiest route",
                  "business", ["easiest"], weight=1.5, required=True),
                c("enforcement_last", "Blocking behaviour without fixing the cause moves it elsewhere",
                  "business", ["moves it elsewhere"], weight=1.3),
            ],
            "Maverick spend is buying outside the agreed process or away from the agreed "
            "supplier. I would measure it first, by category and by area, because the number "
            "usually turns out to be concentrated rather than universal. Almost always the "
            "root cause is that the compliant route is slower, harder or simply unknown to the "
            "person buying, so the fix is to make the compliant route the easiest route: "
            "catalogues, guided forms and a sensible approval threshold. Enforcement comes "
            "last, because blocking the behaviour without fixing the cause just moves it "
            "elsewhere and makes procurement the department that says no.",
            [
                f("Which measurement would you trust for maverick spend?", "measure_it"),
                f("When is enforcement the right answer?", "enforcement_last"),
            ],
            study_topics=["Process compliance", "Buying channels"],
        ),
        q(
            "IQ-PR-008", "procurement", "Sourcing event design", "advanced", ALL_PRACTICE,
            "How would you design a sourcing event so the result is defensible six months "
            "later?",
            [
                c("criteria_first", "Award criteria and weightings agreed before the event opens",
                  "technical", ["award criteria", "weighting"], weight=1.6, required=True),
                c("comparable", "Ask for a structured response so bids are comparable",
                  "technical", ["structured", "comparable"], weight=1.5, required=True),
                c("audit_trail", "Keep a record of the evaluation and the decision",
                  "technical", ["record", "evaluation"], weight=1.4, required=True),
                c("fair_process", "Every bidder gets the same information at the same time",
                  "business", ["same information"], weight=1.5, required=True),
                c("stakeholder_buyin", "Involve the people who will live with the decision",
                  "business", ["live with"], weight=1.3),
            ],
            "The award criteria and their weightings have to be agreed before the event opens, "
            "because a criterion introduced afterwards is indistinguishable from a "
            "justification. The response has to be structured so bids are genuinely "
            "comparable, which usually means a fixed pricing sheet rather than free-form "
            "proposals. Every bidder gets the same information at the same time, questions and "
            "answers included. I would keep a record of the evaluation and the decision as it "
            "was made rather than reconstructed afterwards, and involve the people who will "
            "live with the decision, because a defensible award that the business rejects is "
            "not much of a win.",
            [
                f("What do you do when a bidder asks a question that changes the scope?",
                  "fair_process"),
                f("How would you weight price against quality?", "criteria_first"),
            ],
            study_topics=["Sourcing events", "Evaluation and award"],
        ),
        q(
            "IQ-PR-009", "procurement", "Contract lifecycle", "intermediate", ALL_PRACTICE,
            "What happens to a contract after signature, and why do so many organisations "
            "get that wrong?",
            [
                c("obligations", "Both sides have obligations that somebody has to track",
                  "technical", ["obligation", "track"], weight=1.6, required=True),
                c("renewal", "Renewal and notice dates need to be managed in advance",
                  "technical", ["renewal", "notice"], weight=1.5, required=True),
                c("performance", "Performance against the agreed terms has to be reviewed",
                  "technical", ["performance", "reviewed"], weight=1.3),
                c("repository", "A contract nobody can find is a contract nobody uses",
                  "business", ["nobody can find"], weight=1.5, required=True),
                c("value_leak", "Unmanaged contracts are where negotiated value quietly leaks",
                  "business", ["leak"], weight=1.4),
            ],
            "After signature both sides have obligations that somebody has to track, renewal "
            "and notice dates that need managing well in advance, and performance against the "
            "agreed terms that has to be reviewed rather than assumed. Organisations get it "
            "wrong because the effort and the attention are all front-loaded onto getting the "
            "contract signed, and afterwards it goes into a drawer: a contract nobody can find "
            "is a contract nobody uses, and unmanaged contracts are exactly where negotiated "
            "value quietly leaks away through auto-renewals and off-contract buying.",
            [
                f("What would you put in place for notice dates?", "renewal"),
                f("Who should own post-signature obligations?", "obligations"),
            ],
            study_topics=["Contract lifecycle management", "Obligation tracking"],
        ),
        q(
            "IQ-PR-010", "procurement", "Procurement KPIs", "foundational", RAPID,
            "Name the measures you would put on a procurement dashboard and say what each "
            "one is for.",
            [
                c("savings", "Savings, split into realised and negotiated",
                  "technical", ["savings"], weight=1.5, required=True),
                c("cycle_time", "Cycle time from requisition to order",
                  "technical", ["cycle time"], weight=1.4, required=True),
                c("compliance_rate", "Compliance: spend under contract and through the right channel",
                  "technical", ["under contract"], weight=1.4, required=True),
                c("supplier_perf", "Supplier performance such as on-time delivery",
                  "technical", ["on time delivery"], weight=1.3),
                c("balance", "The set has to balance cost against service, or it drives bad behaviour",
                  "business", ["balance", "behaviour"], weight=1.5,
                  hint="A single-measure dashboard always gets gamed."),
            ],
            "I would show savings split into realised and negotiated, cycle time from "
            "requisition to order, compliance as the share of spend under contract and through "
            "the right channel, and supplier performance such as on time delivery and quality. "
            "The important part is the balance: a dashboard that shows only cost drives "
            "behaviour that damages service, and one that shows only service never gets "
            "funded, so the set has to hold both in view at once.",
            [
                f("Which single measure would you add if you could only have one more?",
                  "balance"),
            ],
            study_topics=["Procurement KPIs", "Performance measurement"],
        ),
        q(
            "IQ-PR-011", "procurement", "Sustainable sourcing", "advanced", ALL_PRACTICE,
            "How do you build sustainability into a sourcing decision without it becoming "
            "a box-ticking exercise?",
            [
                c("in_criteria", "Put it in the award criteria with a real weighting",
                  "technical", ["award criteria", "weighting"], weight=1.6, required=True),
                c("measurable", "Ask for evidence that can be verified, not statements",
                  "technical", ["evidence", "verified"], weight=1.5, required=True),
                c("scope", "Be clear which emissions or standards are actually in scope",
                  "technical", ["in scope"], weight=1.3),
                c("tradeoff", "Be honest when it costs more and let the business decide",
                  "business", ["costs more", "decide"], weight=1.5, required=True),
                c("follow_through", "Track the commitment after award or it means nothing",
                  "business", ["after award"], weight=1.4),
            ],
            "It has to be in the award criteria with a real weighting, because a requirement "
            "worth nothing in the scoring is a requirement suppliers learn to answer without "
            "changing anything. The questions should ask for evidence that can be verified "
            "rather than statements of intent, and the scope has to be clear about which "
            "emissions or which standards are actually in scope. Where the sustainable option "
            "costs more I would say so plainly and let the business decide with the number in "
            "front of them. And the commitment has to be tracked after award, because that is "
            "the step that separates a policy from a box-ticking exercise.",
            [
                f("What evidence would you accept from a small supplier?", "measurable"),
                f("How would you track a commitment after award?", "follow_through"),
            ],
            study_topics=["Sustainable sourcing", "Supplier evaluation"],
        ),
    ]


# ---------------------------------------------------------------------------
# Track 8 - Supply chain
# ---------------------------------------------------------------------------


def supply_chain_questions() -> list[dict[str, Any]]:
    """Demand, inventory, lead times and the working capital they consume."""
    return [
        q(
            "IQ-SC-001", "supply_chain", "Safety stock", "intermediate", ALL_PRACTICE,
            "What is safety stock actually protecting against, and how would you set it?",
            [
                c("variability", "It covers variability in demand and in lead time",
                  "technical", ["variability", "lead time"], weight=1.6, required=True),
                c("service_level", "The service level chosen decides how much cover is held",
                  "technical", ["service level"], weight=1.5, required=True),
                c("inputs", "You need demand history and lead time history to set it",
                  "technical", ["demand history"], weight=1.4, required=True),
                c("cost", "Every unit of safety stock is working capital and risk",
                  "business", ["working capital"], weight=1.5, required=True),
                c("not_a_buffer_for_bad_data", "It should not be covering for bad master data",
                  "business", ["bad master data"], weight=1.3),
            ],
            "Safety stock covers variability: demand that is higher than forecast and lead "
            "time that is longer than planned. How much you hold follows from the service "
            "level chosen, and setting it properly needs demand history and lead time history "
            "rather than a rule of thumb, because the variability is the whole input. The "
            "cost side matters just as much: every unit is working capital and obsolescence "
            "risk. The thing to watch for is safety stock quietly covering for bad master data "
            "or an unreliable supplier, which is expensive and hides the real problem.",
            [
                f("What service level would you set for a critical spare?", "service_level"),
                f("How would you tell whether safety stock is covering a data problem?",
                  "not_a_buffer_for_bad_data"),
            ],
            wrong=[
                w("safety_is_average",
                  "Safety stock is described as covering average demand.",
                  ["safety stock covers average demand", "safety stock is average demand"],
                  "Average demand is covered by the cycle stock. Safety stock exists for the "
                  "variation around the average."),
            ],
            study_topics=["Safety stock", "Service levels"],
        ),
        q(
            "IQ-SC-002", "supply_chain", "Reorder point", "intermediate", PRACTICE_RAPID,
            "How is a reorder point calculated, and what makes a static one dangerous?",
            [
                c("formula", "Demand over the lead time plus safety stock",
                  "technical", ["over the lead time", "safety stock"], weight=1.6, required=True),
                c("trigger", "It triggers a replenishment when stock falls to that level",
                  "technical", ["replenishment"], weight=1.4, required=True),
                c("seasonality", "A static point uses the wrong demand for a seasonal material",
                  "technical", ["seasonal"], weight=1.6, required=True),
                c("review", "It has to be recalculated as demand and lead times move",
                  "technical", ["recalculated"], weight=1.3),
                c("consequence", "Getting it wrong means a stockout or dead stock",
                  "business", ["stockout"], weight=1.4),
            ],
            "The reorder point is the demand expected over the lead time plus safety stock, "
            "and it triggers a replenishment when stock on hand and on order falls to that "
            "level. A static reorder point is dangerous for a seasonal material because it "
            "uses an average demand that applies at no particular time of year: set from "
            "quiet-season demand it will trigger too late going into a peak. It has to be "
            "recalculated as demand and lead times move, and the cost of getting it wrong is a "
            "stockout in one direction and dead stock in the other.",
            [
                f("How would you handle a material whose lead time doubled?", "review"),
                f("What would you use instead of a static point for a seasonal item?",
                  "seasonality"),
            ],
            study_topics=["Reorder point", "Replenishment policy"],
        ),
        q(
            "IQ-SC-003", "supply_chain", "Lead time management", "advanced", ALL_PRACTICE,
            "A supplier's lead time is officially fourteen days but deliveries vary between "
            "ten and thirty. What do you do?",
            [
                c("measure", "Measure the actual distribution rather than the quoted figure",
                  "technical", ["actual", "distribution"], weight=1.6, required=True),
                c("variability_cost", "Variability costs more than a longer stable lead time",
                  "technical", ["longer", "stable"], weight=1.6, required=True),
                c("replan", "Plan against the measured figure while you fix the cause",
                  "technical", ["measured figure"], weight=1.4, required=True),
                c("supplier_conversation", "Take the data to the supplier and find the cause",
                  "business", ["take the data"], weight=1.5, required=True),
                c("dual_source", "Consider a second source if it cannot be fixed",
                  "business", ["second source"], weight=1.2),
            ],
            "First I would measure the actual distribution rather than arguing about the "
            "quoted figure, because fourteen days is a claim and the deliveries are evidence. "
            "The important point is that variability costs more than a longer but stable lead "
            "time: a reliable twenty-five days is easier to plan than an unpredictable ten to "
            "thirty. In the short term I would plan against the measured figure so the "
            "business is not surprised, and in parallel take the data to the supplier and find "
            "the cause, which is often their own upstream supply rather than anything they "
            "control at dispatch. If it cannot be fixed, a second source becomes a genuine "
            "option.",
            [
                f("How would you present the variability to the supplier?",
                  "supplier_conversation"),
                f("What safety stock does this variability imply?", "variability_cost"),
            ],
            study_topics=["Lead time variability", "Supplier performance"],
        ),
        q(
            "IQ-SC-004", "supply_chain", "Forecast accuracy", "advanced", ALL_PRACTICE,
            "How would you measure forecast accuracy, and what is wrong with using one "
            "number?",
            [
                c("measures", "Different error measures answer different questions",
                  "technical", ["error measure"], weight=1.5, required=True),
                c("bias_vs_error", "Bias and error size are separate problems",
                  "technical", ["bias"], weight=1.6, required=True),
                c("aggregation", "Accuracy improves with aggregation, which can flatter a forecast",
                  "technical", ["aggregation", "flatter"], weight=1.5, required=True),
                c("actionable", "Measure at the level decisions are actually made",
                  "business", ["decisions"], weight=1.4, required=True),
                c("improvement", "The measure exists to improve the forecast, not to score people",
                  "business", ["improve"], weight=1.3),
            ],
            "I would use more than one error measure, because a percentage error, an absolute "
            "error and a weighted error each answer a different question and each hides "
            "something. Bias and error size are separate problems: a forecast that is "
            "consistently ten per cent low is fixable in a way that a noisy forecast is not, "
            "and one number hides which of the two you have. Accuracy also improves with "
            "aggregation, so a group-level figure can flatter a forecast that is useless at "
            "the level where decisions are made. That is where it should be measured, and the "
            "purpose is to improve the forecast rather than to score the planners.",
            [
                f("How would you detect and correct bias?", "bias_vs_error"),
                f("At what level would you measure for a purchasing decision?", "actionable"),
            ],
            study_topics=["Forecast accuracy", "Forecast bias"],
        ),
        q(
            "IQ-SC-005", "supply_chain", "Bullwhip effect", "intermediate", ALL_PRACTICE,
            "What is the bullwhip effect and what causes it?",
            [
                c("amplification", "Order variability amplifies moving up the chain",
                  "technical", ["amplifying", "up the chain"], weight=1.6, required=True),
                c("causes", "Batching, promotions, shortage gaming and long lead times cause it",
                  "technical", ["batching", "shortage"], weight=1.5, required=True),
                c("information", "Each tier reacting to orders rather than to real demand",
                  "technical", ["real demand"], weight=1.5, required=True),
                c("fixes", "Sharing demand data and shortening lead times reduces it",
                  "business", ["sharing", "shortening"], weight=1.4, required=True),
                c("cost", "It shows up as alternating shortage and excess inventory",
                  "business", ["excess inventory"], weight=1.3),
            ],
            "The bullwhip effect is order variability amplifying as it moves up the chain, so "
            "a small change in consumer demand becomes a large swing in factory orders. The "
            "causes are order batching, promotions that distort the signal, gaming during a "
            "shortage and long lead times, and underneath all of them each tier reacting to "
            "the orders it receives rather than to real demand. Sharing demand data along the "
            "chain and shortening lead times both reduce it. Left alone it shows up as "
            "alternating shortage and excess inventory, and everybody blames the tier next to "
            "them.",
            [
                f("How would you share demand data with a supplier in practice?", "fixes"),
                f("Which cause is usually the biggest in a procurement setting?", "causes"),
            ],
            study_topics=["Bullwhip effect", "Demand signal sharing"],
        ),
        q(
            "IQ-SC-006", "supply_chain", "Inventory classification", "foundational", RAPID,
            "What do ABC and XYZ classifications tell you, and why use both?",
            [
                c("abc", "ABC ranks materials by value or consumption",
                  "technical", ["ABC", "value"], weight=1.5, required=True),
                c("xyz", "XYZ ranks them by how predictable demand is",
                  "technical", ["XYZ", "predictable"], weight=1.5, required=True),
                c("combination", "The combination decides the policy for each group",
                  "technical", ["combination", "policy"], weight=1.4, required=True),
                c("effort", "It directs planning effort where it pays back",
                  "business", ["effort"], weight=1.3),
            ],
            "ABC ranks materials by value or consumption, so it tells you where the money is. "
            "XYZ ranks them by how predictable demand is, so it tells you where forecasting "
            "will work. The combination is what decides the policy for each group: a high "
            "value, predictable material deserves tight planning, while a low value, erratic "
            "one is better handled with a simple rule and a bit of stock. Using both is what "
            "directs planning effort to where it pays back.",
            [
                f("What policy would you set for a high value, erratic material?",
                  "combination"),
            ],
            study_topics=["ABC XYZ analysis", "Inventory policy"],
        ),
        q(
            "IQ-SC-007", "supply_chain", "MRP", "intermediate", TECH,
            "Explain what an MRP run does and what it needs to be right.",
            [
                c("what_it_does", "It nets requirements against stock and creates proposals",
                  "technical", ["nets", "proposal"], weight=1.6, required=True),
                c("inputs", "It needs demand, stock, bills of material and lead times",
                  "technical", ["bills of material", "lead time"], weight=1.5, required=True),
                c("master_data", "Its output is only as good as the planning master data",
                  "technical", ["planning master data"], weight=1.5, required=True),
                c("garbage", "Wrong lot sizes or lead times produce confident nonsense",
                  "business", ["wrong lot size"], weight=1.4, required=True),
                c("planner_role", "Planners exist to exercise judgement over the proposals",
                  "business", ["judgement"], weight=1.3),
            ],
            "An MRP run nets requirements against available stock and existing supply, and "
            "creates proposals for what to make or buy and when. It needs demand, current "
            "stock, bills of material, lead times and lot sizing rules to do it. The output is "
            "only ever as good as the planning master data behind it, and a wrong lot size or "
            "an optimistic lead time produces confident nonsense that looks exactly like a "
            "correct answer. That is why planners exist: to exercise judgement over the "
            "proposals rather than to convert all of them.",
            [
                f("What would you check first if MRP proposes far too much?", "master_data"),
                f("How would you review lot sizing across a plant?", "garbage"),
            ],
            study_topics=["MRP", "Planning master data"],
        ),
        q(
            "IQ-SC-008", "supply_chain", "Service and working capital", "advanced",
            ALL_PRACTICE,
            "The board wants higher service levels and lower inventory. How do you respond?",
            [
                c("tension", "Name the trade-off rather than promising both",
                  "technical", ["trade-off", "trade off"], weight=1.6, required=True),
                c("shift_curve", "You can move the curve by reducing variability and lead time",
                  "technical", ["variability", "lead time"], weight=1.6, required=True),
                c("segmentation", "Differentiate service levels by product rather than one target",
                  "technical", ["differentiate"], weight=1.5, required=True),
                c("data", "Quantify what each service level actually costs",
                  "business", ["quantify"], weight=1.4, required=True),
                c("honesty", "Agreeing to both without a plan guarantees failing at one",
                  "business", ["failing"], weight=1.3),
            ],
            "I would name the trade-off rather than promise both, and then show what can "
            "actually be done about it. For a fixed process you buy service with inventory, "
            "but you can move the whole curve by reducing lead time and demand variability, "
            "which delivers better service on less stock. I would also differentiate service "
            "levels by product rather than applying one target everywhere, since the top few "
            "per cent of lines drive most of the perceived service. All of it needs numbers: "
            "quantify what each service level costs so the board is choosing rather than "
            "wishing. Agreeing to both without a plan just guarantees failing at one of them.",
            [
                f("Which lever would you pull first, and why?", "shift_curve"),
                f("How would you segment service levels?", "segmentation"),
            ],
            study_topics=["Service level design", "Working capital"],
        ),
        q(
            "IQ-SC-009", "supply_chain", "Disruption response", "advanced", JUDGEMENT,
            "A key supplier has just told you they cannot deliver for six weeks. What do "
            "you do in the first day?",
            [
                c("assess_exposure", "Establish what is affected and how long cover lasts",
                  "technical", ["how long", "cover"], weight=1.6, required=True),
                c("options", "Work the options: alternative source, substitution, allocation",
                  "technical", ["alternative source", "substitution"], weight=1.5, required=True),
                c("verify", "Verify the supplier's story and the restart date",
                  "technical", ["restart date"], weight=1.3),
                c("communicate", "Tell the affected business areas early with what you know",
                  "business", ["early"], weight=1.5, required=True),
                c("prioritise", "Decide who gets the remaining stock, and on what basis",
                  "business", ["remaining stock"], weight=1.4, required=True),
            ],
            "On the first day I would establish exactly what is affected and how long the "
            "existing cover lasts, because that number sets how much time I have to work with. "
            "Then I would work the options in parallel: an alternative source, a substitution, "
            "or allocation of what is left, and verify the supplier's story and their restart "
            "date rather than taking it at face value. I would tell the affected business "
            "areas early with what I know and what I do not, since they have decisions to make "
            "too. And I would get agreement on who gets the remaining stock and on what basis, "
            "because that decision gets made either way and it is better made deliberately.",
            [
                f("On what basis would you allocate remaining stock?", "prioritise"),
                f("What would you put in place to see this earlier next time?",
                  "assess_exposure"),
            ],
            study_topics=["Supply disruption", "Business continuity"],
        ),
        q(
            "IQ-SC-010", "supply_chain", "Inventory performance", "foundational", RAPID,
            "What does inventory turnover tell you, and what does it hide?",
            [
                c("definition", "Cost of goods sold divided by average inventory",
                  "technical", ["average inventory"], weight=1.5, required=True),
                c("interpretation", "Higher turnover means stock is converting faster",
                  "technical", ["faster"], weight=1.4, required=True),
                c("hides", "An aggregate hides slow movers behind fast ones",
                  "technical", ["slow mover"], weight=1.5, required=True),
                c("balance", "Pushed too far it buys turnover with stockouts",
                  "business", ["stockout"], weight=1.4, required=True),
            ],
            "Inventory turnover is cost of goods sold divided by average inventory, so it says "
            "how many times the stock converts in a period and higher generally means capital "
            "is working faster. What the aggregate hides is the mix: a healthy overall figure "
            "can conceal slow movers sitting behind a few fast lines. And pushed too far it "
            "buys turnover with stockouts, so it should always be read next to a service "
            "measure rather than on its own.",
            [
                f("What would you look at alongside turnover?", "balance"),
            ],
            study_topics=["Inventory turnover", "Inventory analysis"],
        ),
        q(
            "IQ-SC-011", "supply_chain", "Sales and operations planning", "advanced",
            ALL_PRACTICE,
            "What makes an S&OP process work, and why do most of them become a reporting "
            "meeting?",
            [
                c("one_plan", "It produces one agreed plan across functions",
                  "technical", ["one agreed plan"], weight=1.6, required=True),
                c("horizon", "It looks forward over a planning horizon, not at last month",
                  "technical", ["forward", "horizon"], weight=1.5, required=True),
                c("decisions", "Gaps have to be closed with decisions, not noted",
                  "technical", ["gap", "decision"], weight=1.6, required=True),
                c("authority", "The people in the room need authority to commit",
                  "business", ["authority"], weight=1.5, required=True),
                c("failure_mode", "Without decisions it degrades into reporting the past",
                  "business", ["reporting the past"], weight=1.3),
            ],
            "S&OP works when it produces one agreed plan across sales, operations and finance, "
            "looking forward over a planning horizon rather than reviewing last month. The "
            "part that makes it real is that gaps between demand and supply have to be closed "
            "with a decision in the meeting, which means the people in the room need the "
            "authority to commit. Most of them fail on exactly that point: without decisions "
            "and without authority the meeting degrades into reporting the past, and everybody "
            "sensible stops attending.",
            [
                f("What would you change about a meeting that has become reporting?",
                  "failure_mode"),
                f("Who has to be in the room, and why?", "authority"),
            ],
            study_topics=["S&OP", "Planning governance"],
        ),
    ]


# ---------------------------------------------------------------------------
# Track 9 - SAP consulting scenarios
# ---------------------------------------------------------------------------


def sap_consulting_questions() -> list[dict[str, Any]]:
    """Behavioural and judgement questions, marked on structure and outcome.

    These carry technical concepts too, because the bank contract requires every
    question to be scorable on technical accuracy. Here "technical" means the
    concrete, checkable content of a consulting answer - a named action, a
    documented decision, an agreed owner - rather than an SAP object. A
    behavioural answer with no specifics is exactly the answer an interviewer
    remembers badly.
    """
    return [
        q(
            "IQ-CO-001", "sap_consulting", "Requirements workshops", "intermediate", BEHAVE,
            "How do you run a requirements workshop with a business team that has never "
            "been through an SAP project?",
            [
                c("prepare", "Prepare with material they can react to rather than a blank page",
                  "technical", ["react to", "blank page"], weight=1.5, required=True),
                c("as_is_to_be", "Separate what happens today from what should happen",
                  "technical", ["today", "should happen"], weight=1.5, required=True),
                c("decisions_logged", "Decisions and open points are written down and owned",
                  "technical", ["written down", "owned"], weight=1.5, required=True),
                c("right_people", "The people who do the work have to be in the room",
                  "business", ["in the room"], weight=1.4, required=True),
                c("language", "Talk in their process language, not in system terms",
                  "business", ["their process language"], weight=1.4),
            ],
            "I would prepare with something they can react to - a draft process or a standard "
            "flow - rather than opening with a blank page, because a team new to this cannot "
            "specify a system they have never seen. In the session I keep what happens today "
            "separate from what should happen afterwards, so today's workarounds do not get "
            "built into the design by accident. Every decision and open point is written down "
            "and owned by a named person before the session ends. The people who actually do "
            "the work have to be in the room, not only their managers, and I would talk in "
            "their process language rather than in system terms, which is what keeps them "
            "engaged enough to correct me.",
            [
                f("What do you do when the right people will not attend?", "right_people"),
                f("How do you stop today's workarounds becoming requirements?",
                  "as_is_to_be"),
            ],
            study_topics=["Requirements gathering", "Workshop facilitation"],
        ),
        q(
            "IQ-CO-002", "sap_consulting", "Scope management", "advanced", BEHAVE,
            "A stakeholder asks for something clearly outside scope, two weeks before "
            "user acceptance testing. What do you do?",
            [
                c("understand_need", "Find out what the underlying need is first",
                  "technical", ["underlying need"], weight=1.5, required=True),
                c("impact", "Assess the impact on cost, timeline and risk honestly",
                  "technical", ["impact", "timeline"], weight=1.6, required=True),
                c("process", "Put it through the change process rather than deciding alone",
                  "technical", ["change process"], weight=1.6, required=True),
                c("workaround", "Offer an interim option so the need is not simply refused",
                  "business", ["interim"], weight=1.4, required=True),
                c("relationship", "Refuse the request without refusing the person",
                  "business", ["not the person"], weight=1.4),
            ],
            "I would find out what the underlying need is first, because the request as "
            "phrased is often one solution to a problem that has cheaper solutions. Then I "
            "would assess the impact on cost, timeline and risk honestly and put it through "
            "the change process, since a consultant who quietly absorbs scope is making a "
            "budget decision that is not theirs to make. Where the need is real but the timing "
            "is wrong I would offer an interim option, a manual step now and the proper "
            "solution in a later phase. The way I would put it matters as much as the answer: "
            "I am refusing the request, not the person, because I need them at user "
            "acceptance testing.",
            [
                f("What if the sponsor overrules the change process?", "process"),
                f("How would you document the interim workaround?", "workaround"),
            ],
            wrong=[
                w("just_absorb",
                  "Quietly absorbing the change is offered as the answer.",
                  ["just squeeze it in", "absorb it into the current scope"],
                  "Absorbing scope silently hides a cost and a risk decision that belongs to "
                  "the project board."),
            ],
            study_topics=["Scope management", "Change control"],
        ),
        q(
            "IQ-CO-003", "sap_consulting", "Disagreement", "intermediate", BEHAVE,
            "Tell me about a time you disagreed with a client's decision. What did you do?",
            [
                c("structure", "Set out the situation, what you did and what happened",
                  "technical", ["situation", "what happened"], weight=1.5, required=True),
                c("evidence", "Make the case with evidence rather than opinion",
                  "technical", ["evidence"], weight=1.5, required=True),
                c("escalate_properly", "Escalate once, in the right forum, then record the decision",
                  "technical", ["escalated once", "recorded"], weight=1.5, required=True),
                c("commit", "Once the decision is made, commit to it",
                  "business", ["committed", "commit to it"], weight=1.5, required=True),
                c("outcome", "Say honestly how it turned out, including if you were wrong",
                  "business", ["turned out"], weight=1.4),
            ],
            "I would describe the situation briefly, what I did and what happened afterwards. "
            "The substance is that I made the case with evidence rather than with opinion, "
            "escalated once in the right forum rather than repeatedly in corridors, and made "
            "sure the decision and its rationale were recorded so nobody had to reconstruct it "
            "later. Once the decision was made I committed to it and made it work, because a "
            "consultant who keeps relitigating a settled decision becomes the problem. And I "
            "would say honestly how it turned out, including the times I was wrong, which is "
            "usually the more useful half of the story.",
            [
                f("What would you do if the decision created a real compliance risk?",
                  "escalate_properly"),
                f("How do you commit to a decision you still think is wrong?", "commit"),
            ],
            study_topics=["Stakeholder management", "Structured answers"],
        ),
        q(
            "IQ-CO-004", "sap_consulting", "Go-live pressure", "advanced", BEHAVE,
            "It is go-live weekend and a critical interface is failing. Walk me through how "
            "you handle it.",
            [
                c("facts_first", "Establish the facts and the impact before proposing anything",
                  "technical", ["facts", "impact"], weight=1.6, required=True),
                c("options", "Present options with consequences, including the fallback",
                  "technical", ["options", "fallback"], weight=1.6, required=True),
                c("decision_owner", "The go or no-go decision belongs to the named owner",
                  "technical", ["go or no-go", "named owner"], weight=1.5, required=True),
                c("comms", "Keep one clear communication line rather than five side channels",
                  "business", ["one clear communication"], weight=1.4, required=True),
                c("stay_calm", "Behaviour under pressure is what people remember",
                  "business", ["under pressure"], weight=1.3),
            ],
            "I would establish the facts and the business impact before proposing anything, "
            "because in the first twenty minutes of a go-live problem half of what is being "
            "said is wrong. Then I would present options with their consequences, explicitly "
            "including the fallback and the point of no return for using it. The go or no-go "
            "decision belongs to the named owner and I would make sure they have what they "
            "need to make it rather than making it for them. Throughout I would keep one clear "
            "communication line instead of five side channels, and be aware that behaviour "
            "under pressure is the thing everybody in that room will remember about me.",
            [
                f("When is the point of no return for the fallback?", "options"),
                f("Who should be on the communication line?", "comms"),
            ],
            study_topics=["Cutover management", "Incident leadership"],
        ),
        q(
            "IQ-CO-005", "sap_consulting", "Explaining constraints", "intermediate", BEHAVE,
            "How would you explain to a business sponsor that what they have asked for "
            "would take six months and is not worth it?",
            [
                c("their_terms", "Explain the constraint in business terms, not technical ones",
                  "technical", ["business terms"], weight=1.6, required=True),
                c("quantify", "Put a number on the effort and on the benefit",
                  "technical", ["number", "benefit"], weight=1.5, required=True),
                c("alternatives", "Bring alternatives rather than only a refusal",
                  "technical", ["alternative"], weight=1.6, required=True),
                c("their_decision", "Give them the information and let them decide",
                  "business", ["let them decide"], weight=1.5, required=True),
                c("no_jargon", "Jargon in this conversation reads as evasion",
                  "business", ["jargon"], weight=1.3),
            ],
            "I would explain the constraint in business terms rather than technical ones - "
            "what it would cost, what it would delay, and what would have to come out of scope "
            "to fit it in. I would put a number on both the effort and the benefit, because "
            "'that is difficult' is an opinion and 'six months and two hundred thousand' is a "
            "decision input. I would bring alternatives rather than only a refusal, including "
            "a smaller version that gets most of the value. Then I would let them decide, "
            "because it is their budget and their priority. And I would avoid jargon entirely, "
            "since in this particular conversation it reads as evasion.",
            [
                f("What if they choose the expensive option anyway?", "their_decision"),
                f("How would you size the smaller version?", "alternatives"),
            ],
            study_topics=["Stakeholder communication", "Business cases"],
        ),
        q(
            "IQ-CO-006", "sap_consulting", "Standard versus custom", "advanced", BEHAVE,
            "The client insists on replicating a legacy process that the standard system "
            "does differently. How do you handle it?",
            [
                c("why_legacy", "Find out why the legacy process is the way it is",
                  "technical", ["why the legacy"], weight=1.6, required=True),
                c("show_standard", "Show the standard process working with their own data",
                  "technical", ["their own data"], weight=1.5, required=True),
                c("cost_of_custom", "Make the lifetime cost of the customisation explicit",
                  "technical", ["lifetime cost"], weight=1.5, required=True),
                c("real_constraints", "Some legacy processes exist for a real regulatory reason",
                  "business", ["regulatory"], weight=1.5, required=True),
                c("document", "If they still insist, record the decision and move on",
                  "business", ["record the decision"], weight=1.4),
            ],
            "First I would find out why the legacy process is the way it is, because some of "
            "it is habit and some of it is a real constraint, and the two look identical in a "
            "workshop. Then I would show the standard process working with their own data "
            "rather than in a demo system, since most resistance is about the unfamiliar "
            "rather than about the function. I would make the lifetime cost of the "
            "customisation explicit, including upgrades and testing, so the choice is "
            "informed. Where the legacy process turns out to exist for a genuine regulatory "
            "reason, that settles it. And if they still insist without one, I would record the "
            "decision and its cost and move on, because dying on that hill helps nobody.",
            [
                f("How do you tell habit from a real constraint?", "real_constraints"),
                f("What do you write down when they overrule you?", "document"),
            ],
            study_topics=["Fit to standard", "Client management"],
        ),
        q(
            "IQ-CO-007", "sap_consulting", "Missed deadlines", "intermediate", BEHAVE,
            "You realise you will miss a deadline that other people are depending on. "
            "What do you do?",
            [
                c("early", "Say so as early as you know, not on the day",
                  "technical", ["as early as"], weight=1.6, required=True),
                c("specifics", "Bring the new date, the reason and what changed",
                  "technical", ["new date", "reason"], weight=1.5, required=True),
                c("mitigation", "Bring options: partial delivery, resequencing, extra help",
                  "technical", ["partial delivery"], weight=1.5, required=True),
                c("impact_on_others", "Say who else is affected, not just that you are late",
                  "business", ["who else is affected"], weight=1.5, required=True),
                c("no_excuses", "Own it without a defence",
                  "business", ["own it"], weight=1.3),
            ],
            "I would say so as early as I know rather than on the day it is due, because the "
            "value of the warning falls to nothing as the date approaches. I would bring the "
            "new date, the reason and what changed since the original estimate, along with "
            "options: a partial delivery of the part they need first, resequencing something "
            "else, or extra help. I would also say who else is affected, because the person I "
            "am telling has their own dependencies and 'I am late' is not enough for them to "
            "act on. And I would own it without a defence, since the explanation matters far "
            "less to them than the new date does.",
            [
                f("What would you deliver partially, and how would you choose?",
                  "mitigation"),
                f("How would you avoid the same estimate error next time?", "specifics"),
            ],
            study_topics=["Delivery communication", "Estimation"],
        ),
        q(
            "IQ-CO-008", "sap_consulting", "Knowledge transfer", "foundational", BEHAVE,
            "How do you hand over to a client team so that they can run the solution "
            "without you?",
            [
                c("start_early", "Knowledge transfer starts during the build, not at the end",
                  "technical", ["during the build"], weight=1.6, required=True),
                c("do_it_themselves", "They do the work with you watching, not the reverse",
                  "technical", ["watching"], weight=1.6, required=True),
                c("documentation", "Documentation aimed at somebody who was not there",
                  "technical", ["not there"], weight=1.4, required=True),
                c("named_owners", "Every part of the solution needs a named owner on their side",
                  "business", ["named owner"], weight=1.5, required=True),
                c("test_it", "Test the handover by letting them handle a real issue",
                  "business", ["real issue"], weight=1.4),
            ],
            "Knowledge transfer starts during the build rather than being an event at the end, "
            "because somebody who watched a decision being made understands the result far "
            "better than somebody who reads about it. Towards the end they do the work with me "
            "watching, not the other way round. The documentation has to be written for "
            "somebody who was not there, which is a different document from the one that makes "
            "sense to the people who were. Every part of the solution needs a named owner on "
            "their side, and I would test the handover by letting them handle a real issue "
            "while I am still available, because that is the only honest measure of whether it "
            "worked.",
            [
                f("What would you do if no owner is nominated?", "named_owners"),
                f("How would you know the handover was successful?", "test_it"),
            ],
            study_topics=["Knowledge transfer", "Handover"],
        ),
        q(
            "IQ-CO-009", "sap_consulting", "Distributed teams", "intermediate", BEHAVE,
            "How do you work effectively with a delivery team in another time zone?",
            [
                c("overlap", "Protect the overlap hours for the things that need conversation",
                  "technical", ["overlap"], weight=1.6, required=True),
                c("written_clarity", "Write specifications that survive without a conversation",
                  "technical", ["survive without"], weight=1.6, required=True),
                c("handover_rhythm", "Establish a daily handover in both directions",
                  "technical", ["daily handover"], weight=1.4, required=True),
                c("trust", "Treat them as colleagues rather than as a resource pool",
                  "business", ["colleagues"], weight=1.5, required=True),
                c("blocking", "A blocked question costs a full day, so unblock fast",
                  "business", ["blocked", "full day"], weight=1.4),
            ],
            "I would protect the overlap hours for the things that genuinely need a "
            "conversation, and do everything else in writing. That means writing "
            "specifications that survive without a conversation, which is a real skill and "
            "worth the extra hour. A daily handover in both directions keeps the work moving "
            "rather than each side waiting. I would treat them as colleagues rather than as a "
            "resource pool, because the quality difference between the two is enormous and "
            "entirely predictable. And I would answer questions fast, since a blocked question "
            "costs a full day when the answer only comes tomorrow morning.",
            [
                f("How would you handle a design disagreement across time zones?",
                  "written_clarity"),
                f("What would you do when there is no overlap at all?", "overlap"),
            ],
            study_topics=["Distributed delivery", "Written communication"],
        ),
        q(
            "IQ-CO-010", "sap_consulting", "Data migration pressure", "advanced", BEHAVE,
            "Two weeks before cutover the migrated data is still failing validation. How do "
            "you handle it?",
            [
                c("quantify", "Quantify what is failing and how badly",
                  "technical", ["quantify", "failing"], weight=1.6, required=True),
                c("classify", "Separate must-fix data from data that can follow later",
                  "technical", ["must-fix", "follow later"], weight=1.6, required=True),
                c("source_owner", "The business owns the data, so they own the correction",
                  "technical", ["own the correction"], weight=1.5, required=True),
                c("go_live_criteria", "Agree explicit data quality criteria for go-live",
                  "business", ["criteria for go-live"], weight=1.5, required=True),
                c("honesty", "Do not let optimism decide a cutover date",
                  "business", ["optimism"], weight=1.4),
            ],
            "I would quantify what is failing and how badly first, because 'the data is bad' "
            "is not something anybody can act on. Then I would separate the must-fix records "
            "from the ones that can follow later, since the open items and the active master "
            "data matter on day one and ten years of history does not. The business owns the "
            "data, so they own the correction, and my job is to make the failures visible in "
            "terms they can work with rather than as a technical error log. I would get "
            "explicit data quality criteria for go-live agreed, so the decision two weeks "
            "later is a measurement rather than an argument. And I would be clear that "
            "optimism must not decide a cutover date, because bad data at go-live is paid for "
            "every day afterwards.",
            [
                f("What data quality criteria would you propose?", "go_live_criteria"),
                f("How would you present the failures to a business owner?", "source_owner"),
            ],
            study_topics=["Data migration", "Cutover readiness"],
        ),
        q(
            "IQ-CO-011", "sap_consulting", "Stakeholder engagement", "intermediate", BEHAVE,
            "A key stakeholder keeps missing workshops and then objects to the decisions. "
            "How do you deal with it?",
            [
                c("find_out_why", "Find out why they are not attending before escalating",
                  "technical", ["why they are not attending"], weight=1.6, required=True),
                c("adapt", "Offer a format that fits how they actually work",
                  "technical", ["format"], weight=1.5, required=True),
                c("record", "Keep decisions recorded and circulated with a response deadline",
                  "technical", ["response deadline"], weight=1.6, required=True),
                c("delegate", "Ask for a delegate with authority if they cannot attend",
                  "business", ["delegate"], weight=1.4, required=True),
                c("escalate_late", "Escalate only when the pattern is affecting delivery",
                  "business", ["pattern"], weight=1.3),
            ],
            "I would find out why they are not attending first, because it is usually "
            "workload or the sessions being aimed at the wrong level rather than "
            "indifference. Then I would offer a format that fits how they actually work: a "
            "short briefing, a written summary, or a decision list they can review. Decisions "
            "get recorded and circulated with a response deadline, so silence becomes "
            "agreement in a documented way rather than in an argument later. I would ask for a "
            "delegate with authority when they genuinely cannot attend. Escalation comes last "
            "and only when the pattern is affecting delivery, because escalating a busy "
            "stakeholder early buys a grudge and nothing else.",
            [
                f("What would you put in the written decision summary?", "record"),
                f("What do you do if the delegate has no authority?", "delegate"),
            ],
            study_topics=["Stakeholder engagement", "Decision governance"],
        ),
        q(
            "IQ-CO-012", "sap_consulting", "Professional honesty", "foundational", BEHAVE,
            "A client asks you a technical question in a meeting and you do not know the "
            "answer. What do you do?",
            [
                c("say_so", "Say that you do not know",
                  "technical", ["do not know", "don't know"], weight=1.6, required=True),
                c("commit_to_answer", "Commit to a specific time to come back with the answer",
                  "technical", ["come back"], weight=1.6, required=True),
                c("partial", "Give what you do know and mark clearly where the line is",
                  "technical", ["where the line is"], weight=1.4, required=True),
                c("follow_through", "Then actually follow through",
                  "business", ["follow through"], weight=1.5, required=True),
                c("credibility", "Guessing once costs more credibility than admitting it ever does",
                  "business", ["guessing", "credibility"], weight=1.5, required=True),
            ],
            "I would say that I do not know, give whatever part of it I do know, and mark "
            "clearly where the line is between the two. Then I would commit to a specific time "
            "to come back with the answer, and actually follow through, because the commitment "
            "is the part that builds trust rather than the admission. Guessing in a meeting "
            "costs far more credibility than admitting a gap ever does: the guess gets written "
            "down, acted on, and found out later, usually by somebody who was not in the room.",
            [
                f("What if the client pushes for an answer immediately?", "partial"),
                f("How would you handle discovering later that you had guessed wrong?",
                  "credibility"),
            ],
            wrong=[
                w("bluff",
                  "Guessing an answer to maintain confidence is offered as the approach.",
                  ["give my best guess to keep their confidence", "bluff it"],
                  "A guess presented as an answer gets acted on. Saying you will confirm and "
                  "then confirming costs one day and builds trust."),
            ],
            study_topics=["Professional judgement", "Client trust"],
        ),
    ]


#: The documented anchors. Each is scored four ways by the generator and the
#: results are recorded in the baseline, so a change in the scoring engine or in
#: the bank shows up as a diff rather than as a surprise.
ANCHORS: list[tuple[str, InterviewMode]] = [
    ("IQ-MM-003", InterviewMode.TECHNICAL),
    ("IQ-IN-002", InterviewMode.TECHNICAL),
    ("IQ-AC-002", InterviewMode.ARCHITECTURE),
    ("IQ-CO-002", InterviewMode.BEHAVIORAL),
    ("IQ-SC-001", InterviewMode.PRACTICE),
    ("IQ-PR-003", InterviewMode.PRACTICE),
    ("IQ-BN-001", InterviewMode.RAPID_FIRE),
]


# ---------------------------------------------------------------------------
# Verification, manifest and baseline
# ---------------------------------------------------------------------------


def _check_reference_answers(bank: Any) -> list[str]:
    """Mark every reference answer against its own rubric.

    A reference answer is the bank's own idea of a complete answer, so it must
    cover every concept it lists and must trip none of the wrong-statement
    patterns. When it does not, the keyword list is wrong - and a candidate who
    writes exactly the model answer would silently lose marks for it.
    """
    config = get_interview_config()
    problems: list[str] = []

    for question in bank.questions:
        score = score_answer(
            question, question.reference_answer, config, mode=InterviewMode.PRACTICE
        )
        missing = [match.label for match in score.concept_matches if not match.matched]
        if missing:
            problems.append(
                f"{question.question_id}: the reference answer does not match its own "
                f"concept(s): {'; '.join(missing)}"
            )
        if score.incorrect_statement_matches:
            problems.append(
                f"{question.question_id}: the reference answer trips its own wrong-statement "
                f"pattern(s): "
                f"{'; '.join(item.label for item in score.incorrect_statement_matches)}"
            )
        if score.non_answer:
            problems.append(f"{question.question_id}: the reference answer reads as a non-answer")
    return problems


def _weak_answer(question: Any) -> str:
    """Build a partial answer that covers roughly the first concept only.

    Derived from the question rather than authored, so it stays honest when the
    bank changes: it is the first keyword of the first concept wrapped in an
    otherwise contentless sentence.
    """
    keyword = question.expected_concepts[0].keywords[0]
    return (
        f"I think this is mainly about {keyword}. I have seen it on a project but I would "
        f"have to check the details before I said more."
    )


def _anchor_rows(bank: Any) -> list[dict[str, Any]]:
    """Score the documented anchors with the real engine, with AI switched off."""
    config = get_interview_config()
    rows: list[dict[str, Any]] = []

    for question_id, mode in ANCHORS:
        question = bank.get(question_id)
        answers = {
            "reference": question.reference_answer,
            "partial": _weak_answer(question),
            "non_answer": "I don't know",
        }
        if question.incorrect_statements:
            answers["incorrect"] = (
                question.reference_answer
                + " "
                + question.incorrect_statements[0].patterns[0]
                + "."
            )

        for label, text in answers.items():
            score = score_answer(question, text, config, mode=mode)
            rows.append(
                {
                    "question_id": question_id,
                    "mode": mode.value,
                    "answer_kind": label,
                    "overall_score": score.overall_score,
                    "band": score.overall_band.value,
                    "passed": score.passed,
                    "non_answer": score.non_answer,
                    "concepts_matched": sum(
                        1 for match in score.concept_matches if match.matched
                    ),
                    "concepts_expected": len(score.concept_matches),
                    "incorrect_statements": len(score.incorrect_statement_matches),
                    "dimensions": {
                        item.dimension.value: item.score
                        for item in score.dimensions
                        if item.applicable
                    },
                }
            )
    return rows


def _write_manifest(bank: Any, anchors: list[dict[str, Any]]) -> None:
    """Write the manifest that documents what each anchor is expected to show."""
    info = bank.info()
    payload = {
        "manifest": MANIFEST_NOTE,
        "bank_version": bank.bank_version,
        "question_count": len(bank.questions),
        "by_track": info.by_track,
        "by_difficulty": info.by_difficulty,
        "by_mode": info.by_mode,
        "topics": info.topics,
        "expectations": [
            {
                "id": "IC-A01",
                "condition": "Every reference answer covers every concept of its own rubric.",
                "why": (
                    "The reference answer is the bank's own model answer. If it does not "
                    "match its own keyword list, a candidate writing the perfect answer "
                    "loses marks for it."
                ),
            },
            {
                "id": "IC-A02",
                "condition": "A reference answer scores strictly higher than a partial answer.",
                "why": "A rubric that cannot separate a full answer from a vague one is not a rubric.",
            },
            {
                "id": "IC-A03",
                "condition": (
                    "A configured non-answer scores zero on every dimension and is reported "
                    "as a non-answer rather than as a very low answer."
                ),
                "why": "Silence and a wrong answer are different things and are coached differently.",
            },
            {
                "id": "IC-A04",
                "condition": (
                    "Adding a known-wrong statement to a complete answer lowers technical "
                    "accuracy and leaves completeness unchanged."
                ),
                "why": (
                    "Saying something incorrect does not make an answer less complete. "
                    "Spreading the penalty would make the same mistake cost different "
                    "amounts on different questions."
                ),
            },
            {
                "id": "IC-A05",
                "condition": (
                    "Scores are identical with use_ai=true (mock provider) and use_ai=false."
                ),
                "why": "The rubric scores; the provider only ever writes prose.",
            },
        ],
        "anchors": [
            {"question_id": question_id, "mode": mode.value} for question_id, mode in ANCHORS
        ],
        "anchor_results": anchors,
    }
    MANIFEST_JSON.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    lines = [
        "# SAP Interview Coach - scenario manifest",
        "",
        MANIFEST_NOTE,
        "",
        f"- **Bank version:** {bank.bank_version}",
        f"- **Questions:** {len(bank.questions)}",
        f"- **Tracks:** {len(info.by_track)}",
        f"- **Topics:** {len(info.topics)}",
        "",
        "## Coverage",
        "",
        "| Track | Questions |",
        "| --- | --- |",
    ]
    lines.extend(f"| {name} | {count} |" for name, count in info.by_track.items())
    lines.extend(
        [
            "",
            "| Difficulty | Questions |",
            "| --- | --- |",
        ]
    )
    lines.extend(f"| {name} | {count} |" for name, count in info.by_difficulty.items())
    lines.extend(
        [
            "",
            "| Interview mode | Questions available |",
            "| --- | --- |",
        ]
    )
    lines.extend(f"| {name} | {count} |" for name, count in info.by_mode.items())
    lines.extend(
        [
            "",
            "## What the anchors prove",
            "",
            "| ID | Condition | Why it matters |",
            "| --- | --- | --- |",
        ]
    )
    lines.extend(
        f"| {item['id']} | {item['condition']} | {item['why']} |"
        for item in payload["expectations"]
    )
    lines.extend(
        [
            "",
            "## Anchor questions",
            "",
            "Each anchor below is scored four ways: the bank's own reference answer, a "
            "partial answer, an answer with a known-wrong statement appended, and a "
            "configured non-answer. The recorded numbers live in "
            "`expected_interview_baseline.json`.",
            "",
            "| Question | Mode | Track | Difficulty | Topic |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for question_id, mode in ANCHORS:
        question = bank.get(question_id)
        lines.append(
            f"| {question_id} | {mode.value} | {question.track.value} | "
            f"{question.difficulty.value} | {question.topic} |"
        )
    lines.extend(
        [
            "",
            "## How an answer is marked",
            "",
            "Concept coverage drives technical accuracy, completeness, business understanding "
            "and architecture. The shape of the answer - length, sentence length, signposting, "
            "filler - drives clarity. A known-wrong statement costs technical accuracy points "
            "and nothing else. Every threshold is in "
            "`app/modules/interview_coach/config/interview_rules.json`.",
            "",
            "No score on this page was produced by a language model.",
            "",
        ]
    )
    MANIFEST_MD.write_text("\n".join(lines), encoding="utf-8")


def _write_baseline(bank: Any, anchors: list[dict[str, Any]]) -> None:
    """Record what the engine produces today for the documented anchors."""
    payload = {
        "bank_version": bank.bank_version,
        "config_version": get_interview_config().config_version,
        "note": (
            "Recorded by reading data/sample/sample_interview_questions.json back through the "
            "real loader and scoring with the real engine, AI disabled. Regenerate with "
            "python scripts/generate_interview_sample_data.py."
        ),
        "rubric_fingerprints": {
            question.question_id: bank.fingerprint(question.question_id)
            for question in bank.questions
        },
        "anchors": anchors,
    }
    BASELINE_FILE.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _summarise(bank: Any, anchors: list[dict[str, Any]]) -> None:
    """Print what was written, so a run can be checked without opening a file."""
    info = bank.info()
    print(f"Question bank v{bank.bank_version}: {len(bank.questions)} questions")
    for name, count in info.by_track.items():
        print(f"  {name:<24} {count:>3}")
    print()
    print("Anchor scores (reference / partial / incorrect / non-answer):")
    grouped: dict[str, dict[str, float]] = {}
    for row in anchors:
        grouped.setdefault(row["question_id"], {})[row["answer_kind"]] = row["overall_score"]
    for question_id, scores in grouped.items():
        parts = " / ".join(
            f"{kind}={scores[kind]}" for kind in ("reference", "partial", "incorrect", "non_answer")
            if kind in scores
        )
        print(f"  {question_id}: {parts}")


def main() -> None:
    """Author the bank, verify it, then write the manifest and the baseline."""
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    questions = build_questions()

    payload = {
        "bank_version": BANK_VERSION,
        "description": (
            "Fictional SAP interview questions across nine tracks, with explicit rubrics. "
            "Generated by scripts/generate_interview_sample_data.py."
        ),
        "manifest": MANIFEST_NOTE,
        "questions": questions,
    }
    BANK_FILE.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"Wrote {BANK_FILE.relative_to(PROJECT_ROOT)} ({len(questions)} questions)")

    # Read it back through the real loader: the file is the artefact, not the
    # literals above, and a value that changes on the round trip has to be
    # caught here rather than by a user.
    bank = load_question_bank(BANK_FILE)

    problems = _check_reference_answers(bank)
    if problems:
        print("\nThe bank failed its own marking check:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        raise SystemExit(1)
    print("Every reference answer matches every concept of its own rubric.")

    anchors = _anchor_rows(bank)
    _write_manifest(bank, anchors)
    _write_baseline(bank, anchors)
    print(f"Wrote {MANIFEST_JSON.relative_to(PROJECT_ROOT)}")
    print(f"Wrote {MANIFEST_MD.relative_to(PROJECT_ROOT)}")
    print(f"Wrote {BASELINE_FILE.relative_to(PROJECT_ROOT)}")
    print()
    _summarise(bank, anchors)


if __name__ == "__main__":
    main()
