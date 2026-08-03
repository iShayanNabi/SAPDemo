"""Turning a ``?module=`` query parameter into a page, or refusing to.

The routing decision is a pure function on purpose, so the cases that matter -
all of which are somebody typing something into a URL bar - can be asserted
without a browser, a server or a Streamlit session.

What is being defended here is narrow and worth stating: the value is a string a
stranger controls, and the *only* legitimate use for it is a lookup in a fixed
table. Every test below is a variation on "and this one is not in the table
either" - traversal, a file name, an import path, a scheme, a URL, an encoded
attempt, a repeat, something enormous. None of them is special-cased in the code
and none needs to be, which is the property this file exists to keep true: the
day somebody replaces the table with a path join, most of these start passing a
page name to Streamlit and this suite says so.
"""

from __future__ import annotations

import pytest

from streamlit_app.components.routing import (
    DEMO_MODULE_PAGES,
    MODULE_QUERY_PARAM,
    UNRECOGNISED_MODULE_MESSAGE,
    resolve_module_route,
)

#: The ten identifiers and the page each must open, written out rather than
#: imported from the mapping under test. A test that read its expectation from
#: the code would agree with any mapping, including one that opens the invoice
#: page for the contract link.
EXPECTED_PAGES = {
    "po-risk": "pages/1_PO_Risk_Checker.py",
    "spend-analytics": "pages/2_Spend_Analytics.py",
    "supplier-recommendation": "pages/3_Supplier_Recommendations.py",
    "invoice-validator": "pages/4_Invoice_Validator.py",
    "supplier-risk": "pages/5_Supplier_Risk_Copilot.py",
    "contract-assistant": "pages/6_Contract_Assistant.py",
    "inventory-predictor": "pages/7_Inventory_Predictor.py",
    "test-case-generator": "pages/8_Test_Case_Generator.py",
    "blueprint-generator": "pages/9_SAP_Blueprint_Generator.py",
    "interview-coach": "pages/10_SAP_Interview_Coach.py",
}


class TestTheAllowlist:
    def test_there_are_exactly_ten_identifiers(self):
        assert len(DEMO_MODULE_PAGES) == 10
        assert len(set(DEMO_MODULE_PAGES)) == 10

    def test_each_identifier_opens_its_own_page(self):
        assert dict(DEMO_MODULE_PAGES) == EXPECTED_PAGES

    def test_no_two_identifiers_open_the_same_page(self):
        assert len(set(DEMO_MODULE_PAGES.values())) == 10

    def test_every_page_named_here_exists_on_disk(self):
        from app.core.config import PROJECT_ROOT

        for identifier, page in DEMO_MODULE_PAGES.items():
            path = PROJECT_ROOT / "streamlit_app" / page
            assert path.is_file(), f"{identifier} names a page that is not there: {page}"

    def test_the_query_parameter_is_the_one_the_website_writes(self):
        assert MODULE_QUERY_PARAM == "module"


class TestSelection:
    @pytest.mark.parametrize(("identifier", "page"), sorted(EXPECTED_PAGES.items()))
    def test_each_identifier_resolves_to_its_module(self, identifier: str, page: str):
        route = resolve_module_route([identifier])
        assert route.outcome == "selected"
        assert route.module == identifier
        assert route.page == page
        assert route.is_selected
        assert not route.should_warn

    @pytest.mark.parametrize(
        "value",
        ["  po-risk  ", "PO-RISK", "Po-Risk", "\tspend-analytics\n"],
    )
    def test_whitespace_and_case_survive_a_copied_link(self, value: str):
        route = resolve_module_route([value])
        assert route.is_selected
        assert route.module == value.strip().lower()

    def test_the_page_is_looked_up_rather_than_built_from_the_value(self):
        """The identifier never appears inside the path it selects.

        If it did, the path would be a function of the input, which is the one
        shape this must not have.
        """
        for identifier, page in DEMO_MODULE_PAGES.items():
            assert identifier not in page


class TestFallingBackToTheHomePage:
    @pytest.mark.parametrize("values", [None, [], [""], ["   "], ["\t\n"]])
    def test_an_absent_or_blank_parameter_asks_for_nothing(self, values):
        """Nothing was requested, so nothing is said about it.

        A blank parameter is silence rather than an error: telling a visitor
        their module was not recognised when they never named one is a message
        about a mistake they did not make.
        """
        route = resolve_module_route(values)
        assert route.outcome == "absent"
        assert route.page is None
        assert not route.should_warn

    @pytest.mark.parametrize(
        "value",
        [
            # Traversal, in every spelling that reaches a path join.
            "../",
            "../../etc/passwd",
            "..%2f..%2fetc%2fpasswd",
            "%2e%2e%2f",
            "....//",
            "/etc/passwd",
            "\\windows\\system32",
            # A file, a page, an import path.
            "file.py",
            "Home.py",
            "pages/1_PO_Risk_Checker.py",
            "1_PO_Risk_Checker",
            "package.module",
            "streamlit_app.components.routing",
            "app.modules.po_risk.engine",
            # A destination rather than an identifier.
            "javascript:alert(1)",
            "data:text/html,<script>alert(1)</script>",
            "file:///etc/passwd",
            "https://evil.example.com",
            "//evil.example.com",
            "http://demo.solveaihub.com/?module=po-risk",
            # Near misses on a real identifier.
            "po_risk",
            "po-risk!",
            "po-risk;spend-analytics",
            "po-risk%20",
            "purchase-order-risk-checker",
            "Purchase Order Risk Checker",
            # Something else entirely.
            "1",
            "-",
            "null",
            "None",
            "*",
            "{{7*7}}",
            "<script>alert(1)</script>",
            "'; DROP TABLE uploaded_files; --",
        ],
    )
    def test_an_unknown_value_never_becomes_a_destination(self, value: str):
        route = resolve_module_route([value])
        assert route.outcome == "unrecognised"
        assert route.page is None
        assert route.module is None
        assert route.should_warn
        assert not route.is_selected

    @pytest.mark.parametrize(
        "value",
        [
            "pö-risk",
            "po‑risk",  # a non-breaking hyphen, which looks identical
            "po-risk\u202e",  # a right-to-left override
            "рo-risk",  # a Cyrillic first letter
            "🙂",
        ],
    )
    def test_a_unicode_lookalike_is_not_a_match(self, value: str):
        assert resolve_module_route([value]).outcome == "unrecognised"

    def test_an_enormous_value_is_refused_without_being_processed(self):
        assert resolve_module_route(["a" * 100_000]).outcome == "unrecognised"

    @pytest.mark.parametrize(
        "values",
        [
            ["po-risk", "spend-analytics"],
            ["po-risk", "po-risk"],
            ["po-risk", "../../etc/passwd"],
            ["", "po-risk"],
            ["po-risk", "spend-analytics", "invoice-validator"],
        ],
    )
    def test_repeated_values_have_no_correct_answer_and_are_refused(self, values):
        """Two modules named in one link is a link nobody can honour.

        Taking the first or the last would be a guess about intent. The home
        page is the honest answer, and every module is one click from it.
        """
        route = resolve_module_route(values)
        assert route.outcome == "unrecognised"
        assert route.page is None

    def test_a_non_string_value_is_refused(self):
        assert resolve_module_route([None]).outcome == "unrecognised"  # type: ignore[list-item]
        assert resolve_module_route([42]).outcome == "unrecognised"  # type: ignore[list-item]


class TestTheMessageShownToAVisitor:
    def test_it_says_what_happened_and_what_is_being_shown(self):
        assert UNRECOGNISED_MODULE_MESSAGE == (
            "The requested module was not recognized. Showing the demo homepage."
        )

    def test_it_exposes_no_path_no_file_and_no_python_module(self):
        lowered = UNRECOGNISED_MODULE_MESSAGE.lower()
        for leak in [".py", "pages/", "streamlit", "traceback", "app.", "/", "\\"]:
            assert leak not in lowered, leak

    def test_it_does_not_repeat_what_was_asked_for(self):
        """A fixed sentence, not a template.

        Echoing the value would put a stranger's string on the page, and the
        only thing worth telling a visitor is which page they are now on.
        """
        assert "%s" not in UNRECOGNISED_MODULE_MESSAGE
        assert "{" not in UNRECOGNISED_MODULE_MESSAGE
