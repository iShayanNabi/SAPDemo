"""Every Streamlit page has to open, in both modes.

Streamlit pages are scripts, not functions, and nothing else in this suite
executes them. A page that raises on import - a missing helper, a renamed
session key, a component called before its client exists - is invisible to a
green run and obvious to the first person who clicks the sidebar.

``streamlit.testing.v1.AppTest`` runs a page headlessly and reports whatever it
raised, which is exactly the missing coverage. The pages are HTTP clients, so a
real API is started for the duration of the module: they call the same endpoints
a browser would, over a real socket.

These are marked ``slow``. Starting uvicorn and rendering eleven pages takes
tens of seconds - worth it, and worth being able to skip with ``-m "not slow"``.
"""

from __future__ import annotations

import contextlib
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from app.core.config import PROJECT_ROOT

pytestmark = pytest.mark.slow

PAGES_DIR = PROJECT_ROOT / "streamlit_app" / "pages"
HOME = PROJECT_ROOT / "streamlit_app" / "Home.py"

#: The ten module pages, in sidebar order. Listed explicitly rather than
#: globbed: a page file that disappears must fail this test, and a glob would
#: simply find nine files and pass.
MODULE_PAGES = [
    "1_PO_Risk_Checker.py",
    "2_Spend_Analytics.py",
    "3_Supplier_Recommendations.py",
    "4_Invoice_Validator.py",
    "5_Supplier_Risk_Copilot.py",
    "6_Contract_Assistant.py",
    "7_Inventory_Predictor.py",
    "8_Test_Case_Generator.py",
    "9_SAP_Blueprint_Generator.py",
    "10_SAP_Interview_Coach.py",
]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def live_api(tmp_path_factory) -> str:
    """Run a real API on a loopback port, in public demonstration mode.

    Demo mode is the interesting configuration: it is what the published
    deployment runs, and it is the one where a page must render *without* an
    uploader and *with* a banner.
    """
    root = tmp_path_factory.mktemp("streamlit_pages")
    port = _free_port()
    env = {
        **os.environ,
        "ENVIRONMENT": "local",
        "DATABASE_URL": f"sqlite:///{root / 'pages.db'}",
        "DATA_DIR": str(root / "data"),
        "UPLOAD_DIR": str(root / "uploads"),
        "EXPORT_DIR": str(root / "exports"),
        "LOG_LEVEL": "ERROR",
        "DEMO_MODE": "true",
        "DEMO_ALLOW_UPLOADS": "false",
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port), "--log-level", "error"],
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if process.poll() is not None:  # pragma: no cover - the server died
                pytest.skip("the API process exited during start-up")
            try:
                if httpx.get(f"{base_url}/api/v1/health", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        else:  # pragma: no cover - a very slow machine
            pytest.skip("the API did not start in time")

        # Point the pages at this server.
        #
        # Setting os.environ here does nothing: app.core.config builds its
        # settings singleton at import time, and conftest imports it during
        # collection. The value has to be written onto the live object - and
        # the client module has to be dropped from sys.modules, because
        # ApiClient is a dataclass whose `base_url` default is bound when the
        # module is first imported. Without the second step the pages silently
        # talk to port 8000 and every demo-mode assertion below fails while
        # every page still renders.
        from app.core.config import settings as app_settings

        previous_base_url = app_settings.api_base_url
        app_settings.api_base_url = base_url
        for module in ("streamlit_app.components.api_client", "streamlit_app.components.demo"):
            sys.modules.pop(module, None)

        yield base_url
    finally:
        # NameError when the server never started, so the local was never bound.
        with contextlib.suppress(NameError, UnboundLocalError):
            app_settings.api_base_url = previous_base_url
        for module in ("streamlit_app.components.api_client", "streamlit_app.components.demo"):
            sys.modules.pop(module, None)
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:  # pragma: no cover
            process.kill()


def _run(path: Path):
    from streamlit.testing.v1 import AppTest

    return AppTest.from_file(str(path), default_timeout=180).run()


class TestEveryPageOpens:
    def test_the_home_page_opens(self, live_api: str):
        app = _run(HOME)
        assert not app.exception, app.exception

    @pytest.mark.parametrize("page", MODULE_PAGES)
    def test_each_module_page_opens(self, live_api: str, page: str):
        app = _run(PAGES_DIR / page)
        assert not app.exception, f"{page} raised: {app.exception}"

    def test_there_are_exactly_ten_module_pages_on_disk(self):
        found = sorted(p.name for p in PAGES_DIR.glob("*.py"))
        assert found == sorted(MODULE_PAGES)


class TestDemoModeIsVisibleAndEnforced:
    def test_the_home_page_shows_the_public_demo_banner(self, live_api: str):
        app = _run(HOME)
        banners = [warning.value for warning in app.warning]
        assert any("Public Demo" in text for text in banners), banners

    @pytest.mark.parametrize("page", MODULE_PAGES)
    def test_every_module_page_shows_the_banner(self, live_api: str, page: str):
        app = _run(PAGES_DIR / page)
        banners = [warning.value for warning in app.warning]
        assert any("Fictional Data Only" in text for text in banners), (page, banners)

    @pytest.mark.parametrize("page", MODULE_PAGES)
    def test_no_page_renders_a_file_uploader_in_demo_mode(self, live_api: str, page: str):
        """Hiding the widget is not the control, but it must still be hidden.

        The server-side refusal is asserted in tests/api/test_demo_api.py. This
        is the other half: a visitor must not be offered a control that will
        then reject them.
        """
        app = _run(PAGES_DIR / page)
        assert len(app.get("file_uploader")) == 0, f"{page} still renders an uploader"


class TestTheGuidedDemonstration:
    """The Load Demo action has to actually work, on the page, in demo mode."""

    def test_the_po_risk_page_loads_and_analyses_bundled_data(self, live_api: str):
        app = _run(PAGES_DIR / "1_PO_Risk_Checker.py")

        load = [button for button in app.button if "demonstration data" in button.label.lower()]
        assert load, [button.label for button in app.button]

        app = load[0].click().run()
        assert not app.exception, app.exception
        upload = app.session_state["upload"]
        assert upload["row_count"] > 0

        run = [button for button in app.button if button.label == "Run analysis"]
        assert run, "the Run analysis button did not appear after loading"

        app = run[0].click().run()
        assert not app.exception, app.exception
        analysis = app.session_state["analysis"]
        assert analysis["record_count"] > 0
        assert analysis["findings_count"] > 0

    def test_the_analysis_offers_a_downloadable_report(self, live_api: str):
        app = _run(PAGES_DIR / "1_PO_Risk_Checker.py")
        app = [b for b in app.button if "demonstration data" in b.label.lower()][0].click().run()
        app = [b for b in app.button if b.label == "Run analysis"][0].click().run()
        labels = [button.label for button in app.get("download_button")]
        assert any(".xlsx" in label or "Excel" in label for label in labels), labels

    def test_the_session_records_what_it_created(self, live_api: str):
        """Session-scoped views depend on this, so it has to be populated."""
        app = _run(PAGES_DIR / "1_PO_Risk_Checker.py")
        app = [b for b in app.button if "demonstration data" in b.label.lower()][0].click().run()
        app = [b for b in app.button if b.label == "Run analysis"][0].click().run()
        owned = app.session_state["_demo_owned_ids"]
        assert owned["po_analysis"], owned


#: What ``?module=<id>`` must open, by the title the page prints.
#:
#: Titles rather than file names, because a title is what a visitor sees. A
#: routing table that pointed the contract link at the inventory page would be
#: perfectly self-consistent and would fail here.
ROUTED_TITLES = {
    "po-risk": "Purchase Order Risk Checker",
    "spend-analytics": "Spend Analytics Dashboard",
    "supplier-recommendation": "Supplier Recommendation Engine",
    "invoice-validator": "Invoice Validator",
    "supplier-risk": "Supplier Risk Copilot",
    "contract-assistant": "Contract Assistant",
    "inventory-predictor": "Inventory Predictor",
    "test-case-generator": "SAP Test Case Generator",
    "blueprint-generator": "SAP Blueprint Generator",
    "interview-coach": "SAP Interview Coach",
}

HOME_TITLE = "SAP AI Application Lab"


def _run_home(module: str | None = None, values: list[str] | None = None):
    """Open the entrypoint the way a browser would, with a query string.

    ``AppTest`` runs the real multipage application, so ``st.switch_page`` in
    ``Home.py`` really navigates and the object returned is sitting on whatever
    page the visitor ended up on. That is the whole reason these are here rather
    than in the unit tests: the pure resolver says which page *should* open, and
    only this says which one *did*.
    """
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(HOME), default_timeout=180)
    if values is not None:
        app.query_params["module"] = values
    elif module is not None:
        app.query_params["module"] = module
    return app.run()


def _titles(app) -> list[str]:
    return [element.value for element in app.title]


class TestModuleLinksFromThePublicWebsite:
    """`demo.solveaihub.com/?module=<id>` has to open that module.

    The public site links to individual tools, and each of those links is a
    string arriving from outside. These drive the real application: the ten that
    must work, and the ones that must not.
    """

    @pytest.mark.parametrize(("identifier", "title"), sorted(ROUTED_TITLES.items()))
    def test_each_identifier_opens_its_own_module(
        self, live_api: str, identifier: str, title: str
    ):
        app = _run_home(identifier)
        assert not app.exception, app.exception
        assert title in _titles(app), (identifier, _titles(app))

    def test_no_parameter_opens_the_demonstration_home_page(self, live_api: str):
        app = _run_home()
        assert not app.exception, app.exception
        assert _titles(app) == [HOME_TITLE]
        assert not [info.value for info in app.info if "not recognized" in info.value]

    @pytest.mark.parametrize(
        "value",
        ["", "   ", "unknown-module", "../../etc/passwd", "pages/1_PO_Risk_Checker.py",
         "javascript:alert(1)", "https://evil.example.com", "%2e%2e%2f", "po_risk"],
    )
    def test_anything_else_stays_on_the_home_page(self, live_api: str, value: str):
        app = _run_home(value)
        assert not app.exception, app.exception
        assert _titles(app) == [HOME_TITLE], (value, _titles(app))

    def test_an_unrecognised_module_is_explained_without_naming_anything(self, live_api: str):
        app = _run_home("unknown-module")
        messages = [info.value for info in app.info]
        assert any("was not recognized" in text for text in messages), messages
        for text in messages:
            # Not the value that was asked for, and not the file layout of an
            # application whose hostname is meant to be private.
            assert "unknown-module" not in text
            assert ".py" not in text
            assert "pages/" not in text

    def test_a_blank_value_says_nothing_at_all(self, live_api: str):
        """Nothing was named, so there is nothing to explain."""
        app = _run_home("")
        assert not [info.value for info in app.info if "not recognized" in info.value]

    def test_two_modules_in_one_link_open_neither(self, live_api: str):
        app = _run_home(values=["po-risk", "spend-analytics"])
        assert _titles(app) == [HOME_TITLE]

    def test_the_parameter_is_cleared_once_it_has_been_used(self, live_api: str):
        """So a bookmark of where the visitor *ended up* is a page, not a redirect."""
        app = _run_home("po-risk")
        assert dict(app.query_params) == {}


class TestRoutingSurvivesRerunsAndManualNavigation:
    """The three ways a router like this usually goes wrong."""

    def test_going_back_to_the_home_page_does_not_bounce_forward_again(self, live_api: str):
        """The back button has to work.

        `st.switch_page` clears the query string, but the browser's history
        entry still has it - so going back re-runs `Home.py` with `?module=`
        present. Without the once-per-session flag this would switch straight
        forward again and the back button would be dead.
        """
        app = _run_home("po-risk")
        assert "Purchase Order Risk Checker" in _titles(app)

        app.switch_page("Home.py")
        app.query_params["module"] = "po-risk"
        app.run()
        assert _titles(app) == [HOME_TITLE], _titles(app)

    def test_a_fresh_visit_to_the_same_link_opens_the_module_again(self, live_api: str):
        """Refreshing the link, or opening it in a new tab, is a new session."""
        for _ in range(2):
            app = _run_home("spend-analytics")
            assert "Spend Analytics Dashboard" in _titles(app)

    def test_a_widget_rerun_does_not_move_the_visitor(self, live_api: str):
        """An ordinary interaction on the home page stays on the home page."""
        app = _run_home("unknown-module")
        assert _titles(app) == [HOME_TITLE]
        app.run()
        assert _titles(app) == [HOME_TITLE]

    def test_manual_navigation_still_reaches_any_module(self, live_api: str):
        """The link decides where a visitor starts, never where they may go."""
        app = _run_home("po-risk")
        app.switch_page("pages/6_Contract_Assistant.py").run()
        assert not app.exception, app.exception
        assert "Contract Assistant" in _titles(app)
