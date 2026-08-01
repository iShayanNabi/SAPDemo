"""The deployment files have to keep agreeing with the application.

Docker is optional here, and this whole file runs without a Docker daemon: it
reads the Dockerfile, the compose file and the entrypoint as text and checks the
things that go quietly wrong between a build and the code it is building.

The failure this guards against is specific. A container healthcheck that polls
a path the API no longer serves reports *unhealthy* forever - the orchestrator
restarts a working container in a loop, and the logs show nothing wrong because
nothing is. Nobody notices until a deployment, because nothing in a normal test
run touches these files at all.
"""

from __future__ import annotations

import re
import shutil
import subprocess

import pytest

from app.core.config import PROJECT_ROOT
from app.main import app

DOCKERFILE = PROJECT_ROOT / "Dockerfile"
COMPOSE = PROJECT_ROOT / "docker-compose.yml"
ENTRYPOINT = PROJECT_ROOT / "docker" / "entrypoint.sh"
DOCKERIGNORE = PROJECT_ROOT / ".dockerignore"


@pytest.fixture(scope="module")
def dockerfile() -> str:
    return DOCKERFILE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def compose() -> str:
    return COMPOSE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def entrypoint() -> str:
    return ENTRYPOINT.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def routes() -> set[str]:
    """Every path the app actually serves.

    Read from the OpenAPI document rather than by walking ``app.routes``:
    FastAPI keeps an included router nested rather than flattening its paths
    into that list, so the obvious walk finds five routes and misses all 130.
    """
    return set(app.openapi()["paths"])


class TestTheFilesExist:
    def test_every_deployment_file_is_present(self):
        for path in (DOCKERFILE, COMPOSE, ENTRYPOINT, DOCKERIGNORE):
            assert path.is_file(), f"{path.name} is missing"

    def test_the_entrypoint_is_a_valid_shell_script(self):
        """A syntax error here is a container that exits before it logs why."""
        shell = shutil.which("sh")
        if shell is None:  # pragma: no cover - every supported platform has one
            pytest.skip("no POSIX shell available")
        completed = subprocess.run(
            [shell, "-n", str(ENTRYPOINT)], capture_output=True, text=True, check=False
        )
        assert completed.returncode == 0, completed.stderr


class TestHealthchecks:
    def test_the_dockerfile_healthcheck_polls_a_route_that_exists(self, dockerfile, routes):
        """The check that catches a healthcheck outliving the route it polls."""
        urls = re.findall(r"http://127\.0\.0\.1:\d+(/[\w\-/]*)", dockerfile)
        assert urls, "the Dockerfile declares no HEALTHCHECK URL"
        for path in urls:
            assert path in routes, f"the healthcheck polls {path}, which the app does not serve"

    def test_the_compose_healthcheck_polls_the_same_route(self, compose, routes):
        api_urls = re.findall(r"http://127\.0\.0\.1:8000(/[\w\-/]*)", compose)
        assert api_urls, "the api service declares no healthcheck URL"
        for path in api_urls:
            assert path in routes, f"the compose healthcheck polls {path}, which is not served"

    def test_the_health_route_answers_without_authentication(self, api_client):
        """A healthcheck cannot log in, so this route must stay open."""
        response = api_client.get("/api/v1/health")
        assert response.status_code == 200


class TestTheImageContract:
    def test_it_builds_on_the_python_version_the_project_requires(self, dockerfile):
        """3.11 silently lacks things this codebase uses; pin it explicitly."""
        assert "python:3.12" in dockerfile

    def test_it_runs_as_a_non_root_user(self, dockerfile):
        """A container that runs as root shares that with anything it mounts."""
        assert re.search(r"^USER\s+lab", dockerfile, re.MULTILINE), (
            "the image does not drop to a non-root user"
        )
        assert dockerfile.index("USER lab") > dockerfile.index("COPY app"), (
            "the drop to a non-root user must come after the files are copied"
        )

    def test_the_entrypoint_offers_the_documented_commands(self, entrypoint, dockerfile):
        for command in ("lab-api", "lab-streamlit", "lab-migrate"):
            assert command in entrypoint, f"the entrypoint does not handle {command}"
        assert 'CMD ["lab-api"]' in dockerfile

    def test_the_entrypoint_stops_on_a_failed_migration(self, entrypoint):
        """Starting an API against a half-built schema is worse than not starting."""
        assert "set -eu" in entrypoint, "the entrypoint does not abort on error"
        assert "alembic upgrade head" in entrypoint

    def test_no_secret_can_be_baked_into_the_image(self, dockerfile):
        """.env is excluded from the build context, and nothing is hardcoded."""
        ignored = DOCKERIGNORE.read_text(encoding="utf-8")
        assert ".env" in ignored, ".env is not excluded from the build context"
        assert "*.key" in ignored
        for leak in ("ANTHROPIC_API_KEY=sk-", "OPENAI_API_KEY=sk-", "PASSWORD="):
            assert leak not in dockerfile

    def test_the_demo_data_is_in_the_image_but_the_local_state_is_not(self, dockerfile):
        ignored = DOCKERIGNORE.read_text(encoding="utf-8")
        assert "COPY data/sample" in dockerfile, "the image ships without its demo datasets"
        assert "data/uploads/*" in ignored
        assert "data/exports/*" in ignored
        assert "data/*.db" in ignored


class TestCompose:
    def test_docker_stays_optional(self, compose):
        """The optional services must not start unless they are asked for."""
        for service, profile in (("postgres", "postgres"), ("redis", "cache")):
            block = compose.split(f"\n  {service}:", 1)
            assert len(block) == 2, f"the {service} service is missing"
            assert f'profiles: ["{profile}"]' in block[1].split("\n\n")[0], (
                f"{service} is not behind a profile, so `docker compose up` would start it"
            )

    def test_the_ui_talks_to_the_api_over_http_only(self, compose):
        """The Streamlit container must not reach past the API into the database."""
        ui_block = compose.split("\n  ui:", 1)[1].split("\n  # ", 1)[0]
        assert "API_BASE_URL: http://api:8000" in ui_block
        assert "DATABASE_URL" not in ui_block, (
            "the UI container is being given a database URL; it has no business with one"
        )

    def test_the_data_volume_survives_a_restart(self, compose):
        assert "lab-data:/app/data" in compose
        assert re.search(r"^volumes:\s*$", compose, re.MULTILINE)

    def test_the_api_keys_come_from_the_environment_not_the_file(self, compose):
        """`${ANTHROPIC_API_KEY:-}` reads from the shell; a literal would be a leak."""
        assert "ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY:-}" in compose
        assert "OPENAI_API_KEY: ${OPENAI_API_KEY:-}" in compose
        assert "sk-" not in compose

    def test_mock_mode_is_the_default_in_a_container_too(self, compose):
        assert "AI_PROVIDER: ${AI_PROVIDER:-mock}" in compose

    @pytest.mark.skipif(
        shutil.which("docker") is None, reason="docker is not installed on this machine"
    )
    def test_the_compose_file_parses(self):
        """`docker compose config` needs no daemon and catches a YAML mistake."""
        completed = subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE), "config"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        assert completed.returncode == 0, completed.stderr[:500]
        assert "sap-ai-lab" in completed.stdout
