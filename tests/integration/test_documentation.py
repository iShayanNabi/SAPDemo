"""The documentation has to keep describing the software that exists.

Docs rot in one direction: the code changes and the prose does not. These tests
check the claims that are *checkable* - a file that is referenced exists, a
command that is documented runs, an endpoint that is listed is served, a count
that is quoted is right.

They deliberately do not check prose. What they check is the class of error that
sends a reader down a path that no longer works, which is the one that wastes an
afternoon.
"""

from __future__ import annotations

import re

import pytest

from app.core.config import PROJECT_ROOT
from app.main import MODULES, app

DOCS = PROJECT_ROOT / "docs"
README = PROJECT_ROOT / "README.md"

REQUIRED_DOCS = [
    "ARCHITECTURE.md",
    "LOCAL_SETUP.md",
    "TESTING.md",
    "API_OVERVIEW.md",
    "IMPLEMENTATION_STATUS.md",
    "FUTURE_WEBSITE_INTEGRATION.md",
    "API_AUTHENTICATION_PLAN.md",
    "DEPLOYMENT_OPTIONS.md",
    "FINAL_BUILD_REPORT.md",
]


@pytest.fixture(scope="module")
def readme() -> str:
    return README.read_text(encoding="utf-8")


class TestTheDocumentsExist:
    @pytest.mark.parametrize("name", REQUIRED_DOCS)
    def test_a_required_document_is_present(self, name):
        assert (DOCS / name).is_file(), f"docs/{name} is missing"

    def test_the_typescript_client_example_is_present(self):
        client = PROJECT_ROOT / "examples" / "typescript-client"
        for name in ("README.md", "package.json", "tsconfig.json"):
            assert (client / name).is_file(), f"examples/typescript-client/{name} is missing"
        for name in ("client.ts", "types.ts", "examples.ts"):
            assert (client / "src" / name).is_file(), f"src/{name} is missing"


class TestEveryReferencedFileExists:
    """A link to a file that was renamed is a dead end with no error message."""

    @pytest.mark.parametrize(
        "document",
        [README, *(DOCS / name for name in REQUIRED_DOCS)],
        ids=lambda path: path.name,
    )
    def test_the_paths_it_names_are_real(self, document):
        if not document.is_file():
            pytest.skip(f"{document.name} does not exist yet")
        text = document.read_text(encoding="utf-8")

        # Markdown links to relative paths, and bare paths in code fences.
        candidates: set[str] = set()
        candidates.update(re.findall(r"\]\((?!https?:|#)([^)#\s]+)", text))
        candidates.update(re.findall(r"`(scripts/[\w./-]+\.py)`", text))
        candidates.update(re.findall(r"`(app/[\w./-]+\.py)`", text))
        candidates.update(re.findall(r"`(docs/[\w./-]+\.md)`", text))
        candidates.update(re.findall(r"python (scripts/[\w./-]+\.py)", text))

        # A path may be written relative to the document (a markdown link) or
        # relative to the repository root (`app/core/config.py` in prose). Both
        # are legitimate; only a path that matches neither is a dead end.
        missing = [
            candidate
            for candidate in candidates
            if not (document.parent / candidate).exists()
            and not (PROJECT_ROOT / candidate).exists()
        ]
        assert missing == [], f"{document.name} references files that do not exist: {missing}"


class TestTheReadmeMatchesTheSoftware:
    def test_it_documents_every_module(self, readme):
        for module in MODULES:
            heading = f"Module {module['number']} - {module['name']}"
            assert heading in readme, f"the README has no section '{heading}'"

    def test_it_covers_the_topics_a_new_reader_needs(self, readme):
        """Each of these is somebody's first question."""
        for heading in (
            "## Quick start",
            "## Complete demonstration",
            "## Architecture",
            "## Docker",
            "## Testing",
            "## Configuration",
            "## Troubleshooting",
            "## Security",
            "## Deployment",
            "## Documentation",
        ):
            assert heading in readme, f"the README is missing '{heading}'"

    def test_every_documented_script_exists(self, readme):
        scripts = set(re.findall(r"python (scripts/[\w_]+\.py)", readme))
        assert scripts, "the README documents no scripts at all"
        missing = [name for name in scripts if not (PROJECT_ROOT / name).is_file()]
        assert missing == [], f"the README documents scripts that do not exist: {missing}"

    def test_it_names_the_python_version_the_project_requires(self, readme):
        assert "3.12" in readme

    def test_it_carries_the_standing_disclaimer(self, readme):
        lowered = readme.lower()
        assert "not connected to any sap" in lowered or "no sap system" in lowered
        assert "fictional" in lowered

    def test_it_does_not_promise_a_module_as_planned(self, readme):
        """Every module is built. A "planned" list can only be wrong now."""
        assert "planned module" not in readme.lower()


class TestDocumentedEndpointsAreServed:
    def test_every_endpoint_named_in_the_api_overview_exists(self):
        """A documented path that 404s is worse than an undocumented one."""
        overview = (DOCS / "API_OVERVIEW.md").read_text(encoding="utf-8")
        served = set(app.openapi()["paths"])

        documented = set()
        for match in re.findall(r"`(?:GET|POST|PUT|PATCH|DELETE) (/api/v1[^`\s]*)`", overview):
            # Normalise {id} style placeholders to whatever the route declares.
            documented.add(re.sub(r"\{[^}]+\}", "{}", match.rstrip("/")))

        normalised_served = {re.sub(r"\{[^}]+\}", "{}", path.rstrip("/")) for path in served}
        missing = sorted(documented - normalised_served)
        assert missing == [], f"documented but not served: {missing}"

    def test_the_module_count_the_docs_quote_is_right(self):
        assert len(MODULES) == 10
        status = (DOCS / "IMPLEMENTATION_STATUS.md").read_text(encoding="utf-8")
        for module in MODULES:
            assert module["name"] in status, f"{module['name']} is missing from the status doc"


class TestThePlanDocumentsAreUsable:
    def test_the_deployment_options_cover_the_four_paths(self):
        text = (DOCS / "DEPLOYMENT_OPTIONS.md").read_text(encoding="utf-8")
        for topic in ("virtualenv", "Docker Compose", "virtual machine", "container platform"):
            assert topic.lower() in text.lower(), f"no deployment option covers {topic}"
        for topic in ("PostgreSQL", "Redis", "CORS", "checklist"):
            assert topic.lower() in text.lower()

    def test_the_integration_doc_covers_the_seven_operations(self):
        text = (DOCS / "FUTURE_WEBSITE_INTEGRATION.md").read_text(encoding="utf-8").lower()
        for topic in (
            "health check",
            "file upload",
            "starting an analysis",
            "polling analysis status",
            "retrieving findings",
            "downloading an export",
            "copilot question",
            "handling errors",
            "signed file url",
            "openapi schema",
        ):
            assert topic in text, f"the integration doc does not cover {topic}"

    def test_it_points_at_a_typescript_client_that_typechecks(self):
        """The doc tells a reader to run it, so it has to be there."""
        text = (DOCS / "FUTURE_WEBSITE_INTEGRATION.md").read_text(encoding="utf-8")
        assert "examples/typescript-client" in text
        client = PROJECT_ROOT / "examples" / "typescript-client" / "src" / "client.ts"
        source = client.read_text(encoding="utf-8")
        # The seven operations, by the names the doc uses.
        for member in (
            "health(",
            "upload<",
            "analyze<",
            "pollUntilComplete",
            "listAll",
            "downloadExport",
            "askSupplierRiskCopilot",
        ):
            assert member in source, f"the example client has no {member}"
