"""The ten module identifiers, asserted across both languages.

``frontend/lib/demo.ts`` builds the links and ``streamlit_app/components/routing.py``
answers them, and between the two there is a network. Nothing forces them to
agree: a public button pointing at an identifier this application does not have
lands the visitor on the home page with a "not recognized" message, and the only
symptom is one tool being slightly annoying to reach. That is a bug nobody
reports and nobody notices in a green suite, so it is asserted here.

**Why the list is written twice rather than shared.** One checked-in JSON file
read by both sides is the obvious answer and it does not work here: the website
image is built with ``context: ./frontend`` (see ``docker-compose.selfhosted.yml``),
so a file at the repository root is not in the build context and ``next build``
cannot import it. Moving the file under ``frontend/`` would invert the problem -
the Python application would then be reading its routing table out of the
website's source tree, and the two are deployed as separate containers. So each
side owns a typed list in the language it is written in, and this test is the
seam: it parses the TypeScript rather than importing it, because the alternative
is running Node from a Python test to ask a question that is answered by ten
string literals.
"""

from __future__ import annotations

import re

import pytest

from app.core.config import PROJECT_ROOT
from streamlit_app.components.routing import DEMO_MODULE_PAGES, MODULE_QUERY_PARAM

DEMO_TS = PROJECT_ROOT / "frontend" / "lib" / "demo.ts"
MODULES_TS = PROJECT_ROOT / "frontend" / "content" / "modules.ts"

#: The mapping as a human agreed it, and the third independent copy of it. The
#: frontend has one, the Streamlit application has one, and neither is allowed
#: to be the authority for this test - two files that drifted together would
#: otherwise agree with each other and be wrong.
EXPECTED_IDENTIFIERS = {
    "po-risk",
    "spend-analytics",
    "supplier-recommendation",
    "invoice-validator",
    "supplier-risk",
    "contract-assistant",
    "inventory-predictor",
    "test-case-generator",
    "blueprint-generator",
    "interview-coach",
}

#: Which public tool page carries which identifier, by its URL slug.
EXPECTED_BY_SLUG = {
    "purchase-order-risk-checker": "po-risk",
    "spend-analytics-dashboard": "spend-analytics",
    "supplier-recommendation-engine": "supplier-recommendation",
    "invoice-validator": "invoice-validator",
    "supplier-risk-copilot": "supplier-risk",
    "contract-assistant": "contract-assistant",
    "inventory-predictor": "inventory-predictor",
    "sap-test-case-generator": "test-case-generator",
    "sap-blueprint-generator": "blueprint-generator",
    "sap-interview-coach": "interview-coach",
}


def _frontend_identifiers() -> list[str]:
    """The ten values of ``DEMO_MODULE_IDS`` in ``frontend/lib/demo.ts``."""
    source = DEMO_TS.read_text(encoding="utf-8")
    match = re.search(r"export const DEMO_MODULE_IDS = \[(.*?)\] as const;", source, re.DOTALL)
    assert match, "DEMO_MODULE_IDS is not declared as an `as const` array in lib/demo.ts"
    return re.findall(r"'([^']+)'", match.group(1))


def _frontend_slug_to_module() -> dict[str, str]:
    """``slug -> demoModule`` as declared in ``frontend/content/modules.ts``.

    The two fields are adjacent in every entry, which is what makes a regular
    expression honest here rather than clever: it matches the pair, so a
    ``demoModule`` moved to another module is a failure rather than a
    coincidence of ordering.
    """
    source = MODULES_TS.read_text(encoding="utf-8")
    pairs = re.findall(
        r"slug: '([^']+)',\s*\n\s*demoModule: '([^']+)',",
        source,
    )
    return dict(pairs)


class TestTheIdentifiersMatchAcrossLanguages:
    def test_the_frontend_declares_exactly_the_agreed_ten(self):
        found = _frontend_identifiers()
        assert len(found) == 10, found
        assert set(found) == EXPECTED_IDENTIFIERS

    def test_the_application_declares_exactly_the_agreed_ten(self):
        assert set(DEMO_MODULE_PAGES) == EXPECTED_IDENTIFIERS

    def test_neither_side_has_one_the_other_does_not(self):
        frontend = set(_frontend_identifiers())
        application = set(DEMO_MODULE_PAGES)
        assert frontend - application == set(), "the website links to a module that cannot open"
        assert application - frontend == set(), "a module can be opened that nothing links to"

    def test_the_query_parameter_is_spelled_the_same_on_both_sides(self):
        source = DEMO_TS.read_text(encoding="utf-8")
        match = re.search(r"export const DEMO_MODULE_PARAM = '([^']+)';", source)
        assert match, "DEMO_MODULE_PARAM is not declared in lib/demo.ts"
        assert match.group(1) == MODULE_QUERY_PARAM


class TestEachToolPageCarriesTheRightIdentifier:
    def test_every_tool_declares_one(self):
        found = _frontend_slug_to_module()
        assert found == EXPECTED_BY_SLUG

    @pytest.mark.parametrize(("slug", "identifier"), sorted(EXPECTED_BY_SLUG.items()))
    def test_each_identifier_opens_the_module_that_tool_describes(
        self, slug: str, identifier: str
    ):
        """The link a visitor follows has to reach the tool they read about.

        Asserted through the page file the identifier resolves to, because that
        is the thing that is actually opened - and a mapping that is merely
        *consistent* on both sides can still send the contract page's link to
        the inventory forecaster.
        """
        expected_page = {
            "purchase-order-risk-checker": "1_PO_Risk_Checker.py",
            "spend-analytics-dashboard": "2_Spend_Analytics.py",
            "supplier-recommendation-engine": "3_Supplier_Recommendations.py",
            "invoice-validator": "4_Invoice_Validator.py",
            "supplier-risk-copilot": "5_Supplier_Risk_Copilot.py",
            "contract-assistant": "6_Contract_Assistant.py",
            "inventory-predictor": "7_Inventory_Predictor.py",
            "sap-test-case-generator": "8_Test_Case_Generator.py",
            "sap-blueprint-generator": "9_SAP_Blueprint_Generator.py",
            "sap-interview-coach": "10_SAP_Interview_Coach.py",
        }[slug]
        assert DEMO_MODULE_PAGES[identifier] == f"pages/{expected_page}"

    def test_a_missing_or_extra_identifier_fails_this_test(self):
        """The guard's own guard.

        These parsers return lists, and a regular expression that stopped
        matching would return an empty one - which compares equal to nothing
        and would make every assertion above pass vacuously if written with
        subset comparisons. Both are asserted to have found ten things.
        """
        assert len(_frontend_identifiers()) == 10
        assert len(_frontend_slug_to_module()) == 10
        assert len(DEMO_MODULE_PAGES) == 10


class TestTheParameterIsNavigationAndNotAccess:
    """The one claim this feature must never quietly stop honouring.

    A module identifier says which page to open. It says nothing about who is
    asking, and no code on either side may come to depend on it as though it
    did. These are cheap source assertions rather than behavioural ones, and
    they are here because the failure they describe would be silent.
    """

    def test_the_router_has_no_authentication_or_authorisation_logic(self):
        source = (
            PROJECT_ROOT / "streamlit_app" / "components" / "routing.py"
        ).read_text(encoding="utf-8")
        code = "\n".join(
            line for line in source.splitlines() if not line.strip().startswith("#")
        )
        for forbidden in ["cf-access", "CF_Authorization", "jwt", "jwks", "verify_token"]:
            assert forbidden.lower() not in code.lower(), forbidden

    def test_the_router_never_imports_or_executes_the_value(self):
        source = (
            PROJECT_ROOT / "streamlit_app" / "components" / "routing.py"
        ).read_text(encoding="utf-8")
        for forbidden in [
            "import_module",
            "__import__",
            "eval(",
            "exec(",
            "importlib",
            "os.path.join",
            "open(",
        ]:
            assert forbidden not in source, forbidden
