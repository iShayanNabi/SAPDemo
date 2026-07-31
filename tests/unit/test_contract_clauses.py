"""Clause extraction, key dates, source references and risk rules.

These exercise the deterministic core of the Contract Assistant without a
database, a file or an AI provider - the same way modules 1-5 test their rule
engines.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.core.exceptions import ConfigurationError
from app.modules.contract_assistant.clauses import extract_values
from app.modules.contract_assistant.dates import (
    add_months,
    find_duration,
    find_first_by_patterns,
    parse_date,
)
from app.modules.contract_assistant.engine import analyze_contract
from app.modules.contract_assistant.risk_rules import RULES
from app.modules.contract_assistant.segmentation import DocumentIndex
from app.modules.contract_assistant.thresholds import (
    CLAUSE_TYPES,
    ContractAssistantConfig,
    load_contract_config,
)
from app.schemas.common import Severity
from app.services.documents.base import ExtractedPage, ExtractionResult
from tests.factories import (
    CONTRACT_AS_OF,
    CONTRACT_TEMPLATE,
    analyze_contract_text,
    contract_rule_ids,
    contract_text,
)


def _index(text: str, config: ContractAssistantConfig) -> DocumentIndex:
    return DocumentIndex([ExtractedPage(page_number=1, text=text)], config)


def _result_from(text: str, config: ContractAssistantConfig, *, as_of: date | None = None):
    extraction = ExtractionResult(
        pages=[ExtractedPage(page_number=1, text=text)],
        extractor="plain_text",
        source_format="txt",
        page_basis="char_budget",
    )
    return analyze_contract(extraction, config, as_of_date=as_of or CONTRACT_AS_OF)


# ---------------------------------------------------------------------------
# Section detection
# ---------------------------------------------------------------------------


class TestSectionDetection:
    def test_numbered_all_caps_headings_are_detected(self, contract_config):
        index = _index(CONTRACT_TEMPLATE, contract_config)
        headings = [section.label for section in index.sections]

        assert "1. TERM" in headings
        assert "5. LIMITATION OF LIABILITY" in headings
        assert "10. DISPUTE RESOLUTION" in headings

    def test_a_sentence_is_not_a_heading(self, contract_config):
        index = _index(CONTRACT_TEMPLATE, contract_config)
        headings = [section.label for section in index.sections]

        assert not any("shall pay" in heading for heading in headings)
        assert not any(heading.endswith(".") for heading in headings)

    def test_a_match_offset_resolves_to_its_page_and_section(self, contract_config):
        pages = [
            ExtractedPage(page_number=1, text="1. TERM\nThe term runs for one year."),
            ExtractedPage(page_number=2, text="2. PAYMENT TERMS\nNet 30 days from invoice."),
        ]
        index = DocumentIndex(pages, contract_config)
        offset = index.text.index("Net 30 days")

        assert index.page_for(offset) == 2
        assert index.section_for(offset).label == "2. PAYMENT TERMS"

    def test_an_excerpt_stops_at_the_section_boundary(self, contract_config):
        index = _index(CONTRACT_TEMPLATE, contract_config)
        offset = index.text.index("net 30 days")

        excerpt = index.excerpt(offset)

        assert "net 30 days" in excerpt
        # The next clause must not bleed into the quotation.
        assert "PRICING" not in excerpt


# ---------------------------------------------------------------------------
# Clause extraction
# ---------------------------------------------------------------------------


class TestClauseExtraction:
    def test_the_template_contract_finds_its_clauses(self):
        result = analyze_contract_text()

        for clause_type in (
            "term", "termination", "payment_terms", "pricing", "liability",
            "indemnification", "confidentiality", "data_privacy", "governing_law",
            "dispute_resolution",
        ):
            assert result.clauses[clause_type].present, clause_type

    def test_an_absent_clause_is_reported_absent_not_guessed(self):
        result = analyze_contract_text()

        for clause_type in ("insurance", "audit_rights", "force_majeure", "auto_renewal"):
            clause = result.clauses[clause_type]
            assert clause.present is False
            assert clause.confidence == 0.0
            assert clause.excerpt == ""

    def test_every_clause_type_is_reported_present_or_absent(self):
        result = analyze_contract_text()

        assert set(result.clauses) == set(CLAUSE_TYPES)

    def test_secondary_phrases_alone_do_not_create_a_clause(self, contract_config):
        """'written notice' appears everywhere; it is not a termination clause."""
        text = (
            "1. NOTICES\nAll notices must be in writing and sent by written notice to the "
            "addresses above.\n"
        )
        result = _result_from(text, contract_config)

        assert result.clauses["termination"].present is False

    def test_an_explicit_denial_of_renewal_is_not_an_auto_renewal_clause(self, contract_config):
        text = contract_text(
            "RENEWAL\nThis Agreement does not renew automatically; any extension must be agreed "
            "in writing."
        )
        result = _result_from(text, contract_config)

        assert result.clauses["auto_renewal"].present is False
        assert "CA-R001" not in contract_rule_ids(result)

    def test_a_real_auto_renewal_clause_is_found(self, contract_config):
        text = contract_text(
            "RENEWAL\nThis Agreement shall automatically renew for successive periods of twelve "
            "months unless either party gives 90 days written notice."
        )
        result = _result_from(text, contract_config)

        clause = result.clauses["auto_renewal"]
        assert clause.present is True
        assert clause.values["renewal_notice_days"] == 90
        assert clause.values["renewal_term_label"] == "twelve months"

    def test_a_heading_match_raises_confidence(self, contract_config):
        with_heading = _result_from(
            "1. CONFIDENTIALITY\nEach party shall keep Confidential Information confidential.",
            contract_config,
        )
        without_heading = _result_from(
            "1. GENERAL\nEach party shall keep Confidential Information confidential.",
            contract_config,
        )

        assert (
            with_heading.clauses["confidentiality"].confidence
            > without_heading.clauses["confidentiality"].confidence
        )

    def test_confidence_is_bounded(self):
        result = analyze_contract_text()

        for clause in result.clauses.values():
            assert 0.0 <= clause.confidence <= 1.0


class TestStructuredValues:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Payment terms are net 30 days.", 30),
            ("The Customer shall pay within 45 days of receipt of the invoice.", 45),
            ("Invoices are payable within 60 days.", 60),
            ("Payment terms NT14 apply.", 14),
        ],
    )
    def test_payment_days_are_parsed(self, text, expected, contract_config):
        values = extract_values("payment_terms", text, contract_config)
        assert values["net_days"] == expected

    def test_early_payment_discount_is_parsed(self, contract_config):
        values = extract_values(
            "payment_terms", "Net 60 days. A 2% discount applies if paid within 10 days.",
            contract_config,
        )

        assert values["net_days"] == 60
        assert values["early_payment_discount_pct"] == 2.0
        assert values["early_payment_days"] == 10

    def test_the_shortest_notice_period_wins(self, contract_config):
        values = extract_values(
            "termination",
            "Either party may terminate on 90 days written notice. The Customer may terminate "
            "for cause on 14 days written notice.",
            contract_config,
        )

        assert values["notice_period_days"] == 14
        assert set(values["notice_periods_found"]) == {"90 days", "14 days"}

    def test_a_liability_cap_amount_is_parsed(self, contract_config):
        values = extract_values(
            "liability", "Total liability shall not exceed EUR 500,000.", contract_config
        )

        assert values["amount"] == 500000.0
        assert values["currency"] == "EUR"

    def test_a_jurisdiction_is_parsed(self, contract_config):
        values = extract_values(
            "governing_law",
            "This Agreement is governed by the laws of Singapore, without regard to conflicts.",
            contract_config,
        )

        assert values["jurisdiction"] == "Singapore"

    def test_no_value_is_invented_when_none_is_stated(self, contract_config):
        values = extract_values(
            "payment_terms", "The Customer shall pay promptly on receipt.", contract_config
        )

        assert "net_days" not in values


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------


class TestDateExtraction:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("1 January 2026", date(2026, 1, 1)),
            ("the 1st day of January 2026", date(2026, 1, 1)),
            ("January 1, 2026", date(2026, 1, 1)),
            ("Jan 5 2027", date(2027, 1, 5)),
            ("2026-01-01", date(2026, 1, 1)),
            ("31 December 2027", date(2027, 12, 31)),
        ],
    )
    def test_common_date_formats_parse(self, text, expected, contract_config):
        parsed = parse_date(text, contract_config)
        assert parsed is not None
        assert parsed.value == expected

    def test_ambiguous_numeric_dates_follow_the_configured_order(self, contract_config):
        parsed = parse_date("03/04/2026", contract_config)

        assert contract_config.dates.day_first is True
        assert parsed.value == date(2026, 4, 3)
        assert parsed.format_basis == "numeric_day_first"

    def test_a_day_above_twelve_is_corrected_whatever_the_order(self, contract_config):
        parsed = parse_date("13/04/2026", contract_config)
        assert parsed.value == date(2026, 4, 13)

    def test_an_impossible_date_is_not_a_date(self, contract_config):
        assert parse_date("31 February 2026", contract_config) is None
        assert parse_date("no date at all", contract_config) is None

    def test_key_dates_come_from_the_term_clause(self):
        result = analyze_contract_text()

        assert result.key_dates["effective_date"] == date(2026, 1, 1)
        assert result.key_dates["expiration_date"] == date(2027, 12, 31)
        assert result.key_dates["effective_date_basis"] == "stated"
        assert result.key_dates["expiration_date_basis"] == "stated"

    def test_a_derived_expiry_is_labelled_as_derived(self, contract_config):
        text = (
            "1. TERM\nThis Agreement is effective as of 1 January 2026 for an initial term of "
            "three years.\n"
        )
        result = _result_from(text, contract_config)

        assert result.key_dates["expiration_date_basis"] == "derived_from_term"
        assert result.key_dates["expiration_date"] == date(2029, 1, 1)

    def test_a_term_length_elsewhere_is_not_read_as_the_contract_term(self, contract_config):
        """'a period of five years' in a confidentiality clause is not the term."""
        text = (
            "1. TERM\nThis Agreement is effective as of 1 January 2026 and shall remain in "
            "force until 31 December 2027.\n\n"
            "2. CONFIDENTIALITY\nEach party shall keep Confidential Information confidential "
            "for a period of five years after termination.\n"
        )
        result = _result_from(text, contract_config)

        assert result.key_dates["expiration_date"] == date(2027, 12, 31)
        assert result.key_dates["expiration_date_basis"] == "stated"

    def test_the_notice_deadline_is_derived_from_expiry_and_notice(self, contract_config):
        text = contract_text(
            "RENEWAL\nThis Agreement shall automatically renew for a further period of twelve "
            "months unless either party gives 90 days written notice."
        )
        result = _result_from(text, contract_config)

        assert result.key_dates["expiration_date"] == date(2027, 12, 31)
        assert result.key_dates["notice_deadline"] == date(2027, 10, 2)
        assert result.key_dates["notice_deadline_basis"] == (
            "derived_from_expiration_and_notice"
        )

    def test_add_months_uses_the_calendar_not_thirty_day_blocks(self):
        assert add_months(date(2026, 4, 1), 12) == date(2027, 4, 1)
        assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)

    def test_a_line_wrapped_date_is_still_found(self, contract_config):
        """PDF extraction hard-wraps sentences; a date must survive the break."""
        text = "1. TERM\nThis Agreement shall remain in force until 31 March\n2029."
        index = _index(text, contract_config)

        found = find_first_by_patterns(
            index.flat_text, contract_config.dates.patterns_for("expiration_date"), contract_config
        )

        assert found is not None
        assert found.value == date(2029, 3, 31)

    def test_a_notice_duration_is_converted_to_days(self, contract_config):
        found = find_duration(
            "on three months written notice",
            contract_config.dates.patterns_for("notice_period"),
            contract_config,
        )

        assert found.days == 90
        assert found.label == "three months"


# ---------------------------------------------------------------------------
# Source references
# ---------------------------------------------------------------------------


class TestSourceReferences:
    def test_every_found_clause_carries_a_page_excerpt_and_confidence(self):
        result = analyze_contract_text()
        found = [clause for clause in result.clauses.values() if clause.present]

        assert found
        for clause in found:
            reference = clause.primary_reference
            assert reference is not None
            assert reference.page_number == 1
            assert reference.excerpt.strip()
            assert 0.0 < reference.confidence <= 1.0
            assert reference.clause_type == clause.clause_type

    def test_a_reference_points_at_the_right_page_in_a_multi_page_document(
        self, contract_config
    ):
        pages = [
            ExtractedPage(page_number=1, text="1. TERM\nEffective as of 1 January 2026."),
            ExtractedPage(page_number=2, text="2. PRICING\nPrices are set out in Schedule 1."),
            ExtractedPage(
                page_number=3,
                text="3. GOVERNING LAW\nThis Agreement is governed by the laws of Germany.",
            ),
        ]
        extraction = ExtractionResult(
            pages=pages, extractor="plain_text", source_format="txt", page_basis="page_break"
        )
        result = analyze_contract(extraction, contract_config, as_of_date=CONTRACT_AS_OF)

        assert result.clauses["pricing"].page_number == 2
        assert result.clauses["governing_law"].page_number == 3

    def test_the_excerpt_is_a_real_quotation_from_the_document(self):
        result = analyze_contract_text()
        clause = result.clauses["payment_terms"]

        assert "net 30 days" in clause.excerpt

    def test_the_section_heading_is_quoted_verbatim(self):
        result = analyze_contract_text()

        assert result.clauses["liability"].section_heading == "5. LIMITATION OF LIABILITY"

    def test_obligations_carry_references_and_quote_the_sentence(self):
        result = analyze_contract_text()

        assert result.obligations
        for obligation in result.obligations:
            assert obligation.reference.page_number == 1
            assert obligation.text.strip()
            assert obligation.reference.excerpt == obligation.text

    def test_an_obligation_is_attributed_only_when_a_party_is_named(self):
        result = analyze_contract_text()
        payment = [item for item in result.obligations if item.duty_type == "payment"]

        assert payment
        assert payment[0].party_role == "customer"


# ---------------------------------------------------------------------------
# Risk rules
# ---------------------------------------------------------------------------


class TestRiskRules:
    def test_every_configured_rule_has_an_implementation(self, contract_config):
        assert set(contract_config.rules) == set(RULES)

    def test_a_clean_contract_raises_few_findings(self):
        result = analyze_contract_text()

        assert result.risk_band == "low"
        assert "CA-R005" not in contract_rule_ids(result)
        assert "CA-R003" not in contract_rule_ids(result)

    def test_short_notice_period_is_critical(self, contract_config):
        text = CONTRACT_TEMPLATE.replace("on 90 days written notice", "on 7 days written notice")
        result = _result_from(text, contract_config)

        finding = next(item for item in result.risks if item.rule_id == "CA-R002")
        assert finding.severity is Severity.CRITICAL
        assert finding.evidence["notice_period_days"] == 7

    def test_unlimited_liability_is_critical(self, contract_config):
        text = CONTRACT_TEMPLATE.replace(
            "The total aggregate liability of each party shall not exceed EUR 500,000.",
            "The Supplier shall have unlimited liability for any breach of this Agreement.",
        )
        result = _result_from(text, contract_config)

        finding = next(item for item in result.risks if item.rule_id == "CA-R005")
        assert finding.severity is Severity.CRITICAL
        # The uncapped rule must not double-count the same clause.
        assert "CA-R006" not in contract_rule_ids(result)

    def test_a_missing_data_privacy_clause_is_reported_as_critical(self, contract_config):
        text = "\n".join(
            line
            for line in CONTRACT_TEMPLATE.split("\n")
            if "personal data" not in line and "DATA PROTECTION" not in line
            and "Regulation" not in line
        )
        result = _result_from(text, contract_config)

        finding = next(
            item
            for item in result.risks
            if item.rule_id == "CA-R004" and item.clause_type == "data_privacy"
        )
        assert finding.severity is Severity.CRITICAL
        assert "data_privacy" in [item.clause_type for item in result.missing_clauses]

    def test_missing_termination_is_reported_once_not_twice(self, contract_config):
        text = "\n".join(
            line for line in CONTRACT_TEMPLATE.split("\n") if "terminate" not in line
        ).replace("2. TERMINATION", "")
        result = _result_from(text, contract_config)

        assert "CA-R003" in contract_rule_ids(result)
        termination_findings = [
            item for item in result.risks if item.clause_type == "termination"
        ]
        assert len(termination_findings) == 1

    def test_payment_terms_outside_policy_fire(self, contract_config):
        text = CONTRACT_TEMPLATE.replace("net 30 days", "net 120 days")
        result = _result_from(text, contract_config)

        finding = next(item for item in result.risks if item.rule_id == "CA-R010")
        assert finding.evidence["net_days"] == 120

    def test_an_expired_contract_is_critical(self, contract_config):
        result = _result_from(CONTRACT_TEMPLATE, contract_config, as_of=date(2028, 6, 1))

        finding = next(item for item in result.risks if item.rule_id == "CA-R008")
        assert finding.severity is Severity.CRITICAL
        assert "expired" in finding.title.lower()

    def test_every_finding_carries_a_rule_id_severity_and_action(self, contract_config):
        text = CONTRACT_TEMPLATE.replace("net 30 days", "net 120 days")
        result = _result_from(text, contract_config)

        for finding in result.risks:
            assert finding.rule_id in contract_config.rules
            assert isinstance(finding.severity, Severity)
            assert finding.explanation.strip()
            assert finding.recommended_action.strip()

    def test_a_broken_rule_does_not_lose_the_analysis(self, contract_config, monkeypatch):
        def explode(spec, context):
            raise RuntimeError("deliberate rule failure")

        monkeypatch.setitem(RULES, "CA-R014", explode)
        result = _result_from(CONTRACT_TEMPLATE, contract_config)

        assert result.rule_errors
        assert result.rule_errors[0]["rule_id"] == "CA-R014"
        assert result.rule_errors[0]["error"] == "RuntimeError"
        # Every other rule still produced its findings.
        assert result.clauses_found > 0
        assert "CA-R014" not in contract_rule_ids(result)

    def test_a_rule_can_be_disabled_for_one_run(self, contract_config):
        extraction = ExtractionResult(
            pages=[ExtractedPage(page_number=1, text=CONTRACT_TEMPLATE)],
            extractor="plain_text",
            source_format="txt",
            page_basis="char_budget",
        )
        result = analyze_contract(
            extraction, contract_config, as_of_date=CONTRACT_AS_OF, enabled_rules=["CA-R008"]
        )

        assert contract_rule_ids(result) <= {"CA-R008"}


# ---------------------------------------------------------------------------
# Configuration drives behaviour
# ---------------------------------------------------------------------------


class TestConfigurationDrivesBehaviour:
    def test_editing_the_notice_threshold_changes_the_outcome_with_no_code_change(
        self, tmp_path, contract_config
    ):
        import json
        import shutil

        from app.modules.contract_assistant.thresholds import DEFAULT_CONFIG_PATH

        target = tmp_path / "contract_rules.json"
        shutil.copy(DEFAULT_CONFIG_PATH, target)
        raw = json.loads(target.read_text(encoding="utf-8"))
        raw["rules"]["CA-R002"]["params"]["minimum_notice_days"] = 120
        target.write_text(json.dumps(raw), encoding="utf-8")

        edited = load_contract_config(target)

        # 90 days passes the shipped 30-day minimum and fails the edited 120-day one.
        assert "CA-R002" not in contract_rule_ids(_result_from(CONTRACT_TEMPLATE, contract_config))
        assert "CA-R002" in contract_rule_ids(_result_from(CONTRACT_TEMPLATE, edited))

    def test_editing_the_payment_policy_changes_the_outcome(self, tmp_path):
        import json
        import shutil

        from app.modules.contract_assistant.thresholds import DEFAULT_CONFIG_PATH

        target = tmp_path / "contract_rules.json"
        shutil.copy(DEFAULT_CONFIG_PATH, target)
        raw = json.loads(target.read_text(encoding="utf-8"))
        raw["rules"]["CA-R010"]["params"]["policy_max_days"] = 20
        target.write_text(json.dumps(raw), encoding="utf-8")

        edited = load_contract_config(target)

        assert "CA-R010" in contract_rule_ids(_result_from(CONTRACT_TEMPLATE, edited))

    def test_an_invalid_regular_expression_fails_at_load_time(self, tmp_path):
        import json
        import shutil

        from app.modules.contract_assistant.thresholds import DEFAULT_CONFIG_PATH

        target = tmp_path / "contract_rules.json"
        shutil.copy(DEFAULT_CONFIG_PATH, target)
        raw = json.loads(target.read_text(encoding="utf-8"))
        raw["clauses"]["liability"]["primary_patterns"] = ["unbalanced ( group"]
        target.write_text(json.dumps(raw), encoding="utf-8")

        with pytest.raises(ConfigurationError) as error:
            load_contract_config(target)

        assert "failed validation" in error.value.message

    def test_a_missing_clause_type_fails_at_load_time(self, tmp_path):
        import json
        import shutil

        from app.modules.contract_assistant.thresholds import DEFAULT_CONFIG_PATH

        target = tmp_path / "contract_rules.json"
        shutil.copy(DEFAULT_CONFIG_PATH, target)
        raw = json.loads(target.read_text(encoding="utf-8"))
        del raw["clauses"]["liability"]
        target.write_text(json.dumps(raw), encoding="utf-8")

        with pytest.raises(ConfigurationError):
            load_contract_config(target)

    def test_a_missing_config_file_is_reported_clearly(self, tmp_path):
        with pytest.raises(ConfigurationError) as error:
            load_contract_config(tmp_path / "nope.json")

        assert "missing" in error.value.message
