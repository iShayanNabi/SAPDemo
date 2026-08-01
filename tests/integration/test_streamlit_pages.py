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
