"""The self-hosted deployment files have to keep agreeing with the application.

Like ``test_deployment_files.py``, this whole file runs without a Docker daemon:
it reads the compose files, the scripts and the environment templates as text
and as YAML.

The failures it guards against all look like nothing from the outside:

* a ``ports:`` entry appearing on the database or the API, which publishes to
  the whole network and shows up in no test that only checks the app works;
* the website joining the internal network, giving a public-facing container a
  route to the database it has no reason to have;
* a real secret reaching a committed file;
* a script that resets a database losing the check that stops it running
  against a database that is not a demonstration.
"""

from __future__ import annotations

import re
import stat
import subprocess

import pytest
import yaml

from app.core.config import PROJECT_ROOT

COMPOSE = PROJECT_ROOT / "docker-compose.selfhosted.yml"
DEBUG_COMPOSE = PROJECT_ROOT / "docker-compose.debug.yml"
ENV_EXAMPLE = PROJECT_ROOT / ".env.selfhosted.example"
FRONTEND_DOCKERFILE = PROJECT_ROOT / "frontend" / "Dockerfile"
ENTRYPOINT = PROJECT_ROOT / "docker" / "entrypoint.sh"
GITIGNORE = PROJECT_ROOT / ".gitignore"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"

SELFHOSTED_SCRIPTS = [
    "start_selfhosted.sh",
    "stop_selfhosted.sh",
    "restart_selfhosted.sh",
    "status_selfhosted.sh",
    "logs_selfhosted.sh",
    "verify_selfhosted.sh",
    "reset_public_demo.sh",
    "backup_selfhosted.sh",
    "restore_selfhosted.sh",
]


@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def compose_text() -> str:
    return COMPOSE.read_text(encoding="utf-8")


class TestTheFilesExist:
    def test_every_deployment_file_is_present(self):
        for path in (COMPOSE, DEBUG_COMPOSE, ENV_EXAMPLE, FRONTEND_DOCKERFILE, ENTRYPOINT):
            assert path.is_file(), f"{path.name} is missing"

    def test_every_self_hosting_script_is_present_and_executable(self):
        for name in SELFHOSTED_SCRIPTS:
            path = SCRIPTS_DIR / name
            assert path.is_file(), f"{name} is missing"
            mode = path.stat().st_mode
            assert mode & stat.S_IXUSR, f"{name} is not executable"

    def test_the_shared_library_exists_and_is_not_executable(self):
        """It is sourced, not run. An executable file invites being run."""
        lib = SCRIPTS_DIR / "lib" / "selfhosted.sh"
        assert lib.is_file()
        assert not lib.stat().st_mode & stat.S_IXUSR

    @pytest.mark.parametrize("name", SELFHOSTED_SCRIPTS)
    def test_every_script_parses(self, name: str):
        if not (bash := _bash()):  # pragma: no cover - bash is present on macOS and Linux
            pytest.skip("bash is not available")
        result = subprocess.run([bash, "-n", str(SCRIPTS_DIR / name)], capture_output=True)
        assert result.returncode == 0, result.stderr.decode()

    @pytest.mark.parametrize("name", SELFHOSTED_SCRIPTS)
    def test_every_script_uses_safe_shell_options(self, name: str):
        text = (SCRIPTS_DIR / name).read_text(encoding="utf-8")
        # Set once in the shared library that every script sources.
        assert "lib/selfhosted.sh" in text, f"{name} does not source the shared library"


def _bash() -> str | None:
    from shutil import which

    return which("bash")


class TestTheServices:
    def test_it_defines_exactly_the_five_expected_services(self, compose: dict):
        assert sorted(compose["services"]) == sorted(
            ["api", "cloudflared", "database", "streamlit", "website"]
        )

    def test_every_image_is_pinned_rather_than_latest(self, compose: dict):
        for name, service in compose["services"].items():
            image = service.get("image", "")
            if not image or image.startswith("sapdemo-"):
                continue  # built locally from a Dockerfile in this repository
            assert ":" in image, f"{name} has an untagged image"
            assert not image.endswith(":latest"), f"{name} uses a floating :latest tag"

    def test_no_service_hardcodes_a_platform(self, compose_text: str):
        """Forcing linux/amd64 would emulate on Apple Silicon for no benefit."""
        assert not re.search(r"^\s*platform:", compose_text, re.MULTILINE)

    def test_every_service_declares_a_restart_policy(self, compose: dict):
        for name, service in compose["services"].items():
            assert service.get("restart") == "unless-stopped", name

    def test_every_service_declares_a_health_check(self, compose: dict):
        for name, service in compose["services"].items():
            assert "healthcheck" in service, f"{name} has no healthcheck"

    def test_every_service_bounds_its_logs(self, compose: dict):
        for name, service in compose["services"].items():
            options = service.get("logging", {}).get("options", {})
            assert options.get("max-size"), f"{name} does not bound its log size"
            assert options.get("max-file"), f"{name} does not rotate its logs"

    def test_every_service_drops_privileges_where_it_can(self, compose: dict):
        for name, service in compose["services"].items():
            assert "no-new-privileges:true" in service.get("security_opt", []), name
            assert service.get("cap_drop") == ["ALL"], name

    def test_only_the_database_adds_capabilities_back(self, compose: dict):
        """A capability added anywhere else needs a reason written down."""
        with_caps = {
            name for name, service in compose["services"].items() if service.get("cap_add")
        }
        assert with_caps == {"database"}


class TestNothingIsPublished:
    def test_no_service_publishes_a_port(self, compose: dict):
        """The tunnel dials out. Nothing dials in, so nothing listens."""
        for name, service in compose["services"].items():
            assert "ports" not in service, (
                f"{name} publishes a port in the deployed configuration. "
                f"Loopback bindings belong in docker-compose.debug.yml."
            )

    def test_no_service_uses_host_networking(self, compose: dict):
        for name, service in compose["services"].items():
            assert service.get("network_mode") != "host", name

    def test_no_service_mounts_the_docker_socket(self, compose_text: str):
        assert "/var/run/docker.sock" not in compose_text

    def test_the_debug_overlay_binds_only_to_loopback(self):
        overlay = yaml.safe_load(DEBUG_COMPOSE.read_text(encoding="utf-8"))
        published = 0
        for name, service in overlay.get("services", {}).items():
            for mapping in service.get("ports", []):
                published += 1
                assert str(mapping).startswith("127.0.0.1:"), (
                    f"{name} publishes {mapping}, which binds every interface. "
                    f"Docker writes its own firewall rules, so a host firewall "
                    f"will not save this."
                )
        assert published >= 3

    def test_the_debug_overlay_never_publishes_the_database(self):
        overlay = yaml.safe_load(DEBUG_COMPOSE.read_text(encoding="utf-8"))
        assert "ports" not in overlay.get("services", {}).get("database", {})


class TestTheNetworkBoundaries:
    def test_the_internal_network_has_no_route_to_the_internet(self, compose: dict):
        assert compose["networks"]["internal"]["internal"] is True

    def test_the_database_is_on_the_internal_network_only(self, compose: dict):
        assert compose["services"]["database"]["networks"] == ["internal"]

    def test_the_api_is_on_the_internal_network_only(self, compose: dict):
        """No public hostname, and no path to one."""
        assert compose["services"]["api"]["networks"] == ["internal"]

    def test_the_website_cannot_reach_the_api_or_the_database(self, compose: dict):
        """It never calls them, so it must not be able to.

        A service on a network it does not need is an attack path nobody chose.
        """
        assert compose["services"]["website"]["networks"] == ["edge"]

    def test_streamlit_bridges_the_two_networks_because_it_is_the_only_api_client(
        self, compose: dict
    ):
        assert sorted(compose["services"]["streamlit"]["networks"]) == ["edge", "internal"]

    def test_the_tunnel_cannot_reach_the_api_or_the_database(self, compose: dict):
        """A tunnel on the internal network could be configured to publish it."""
        assert compose["services"]["cloudflared"]["networks"] == ["edge"]

    def test_streamlit_reaches_the_api_by_service_name(self, compose: dict):
        assert compose["services"]["streamlit"]["environment"]["API_BASE_URL"] == "http://api:8000"


class TestTheDatabase:
    def test_it_uses_a_named_volume_so_data_survives_a_restart(self, compose: dict):
        volumes = compose["services"]["database"]["volumes"]
        assert any(str(v).startswith("sapdemo-postgres:") for v in volumes)
        assert "sapdemo-postgres" in compose["volumes"]

    def test_it_is_given_time_to_shut_down_cleanly(self, compose: dict):
        database = compose["services"]["database"]
        # SIGTERM to postgres is a fast shutdown; being killed means the next
        # start does crash recovery.
        assert database.get("stop_signal") == "SIGINT"
        assert database.get("stop_grace_period")

    def test_its_collation_is_pinned_rather_than_inherited(self, compose: dict):
        """A database that sorts differently from the one it was dumped on is a
        restore that silently reorders."""
        args = compose["services"]["database"]["environment"]["POSTGRES_INITDB_ARGS"]
        assert "--locale=C" in args
        assert "--encoding=UTF8" in args


class TestOrdering:
    def test_the_api_waits_for_a_healthy_database(self, compose: dict):
        assert compose["services"]["api"]["depends_on"]["database"]["condition"] == "service_healthy"

    def test_streamlit_waits_for_a_healthy_api(self, compose: dict):
        assert compose["services"]["streamlit"]["depends_on"]["api"]["condition"] == "service_healthy"

    def test_the_tunnel_waits_for_both_things_it_serves(self, compose: dict):
        depends = compose["services"]["cloudflared"]["depends_on"]
        assert depends["website"]["condition"] == "service_healthy"
        assert depends["streamlit"]["condition"] == "service_healthy"

    def test_the_api_health_check_allows_for_first_run_seeding(self, compose: dict):
        """A start_period shorter than the seed restarts the container mid-seed, forever."""
        start_period = compose["services"]["api"]["healthcheck"]["start_period"]
        assert int(str(start_period).rstrip("s")) >= 180


class TestDemonstrationDefaults:
    def test_demo_mode_defaults_to_on_for_this_deployment(self, compose: dict):
        assert compose["services"]["api"]["environment"]["DEMO_MODE"] == "${DEMO_MODE:-true}"

    def test_uploads_default_to_refused(self, compose: dict):
        assert (
            compose["services"]["api"]["environment"]["DEMO_ALLOW_UPLOADS"]
            == "${DEMO_ALLOW_UPLOADS:-false}"
        )

    def test_reset_on_start_defaults_to_off(self, compose: dict):
        """A restart - an update, a power cut - must never destroy the database."""
        assert (
            compose["services"]["api"]["environment"]["DEMO_RESET_ON_START"]
            == "${DEMO_RESET_ON_START:-false}"
        )

    def test_seed_on_empty_defaults_to_on(self, compose: dict):
        assert (
            compose["services"]["api"]["environment"]["DEMO_SEED_ON_EMPTY"]
            == "${DEMO_SEED_ON_EMPTY:-true}"
        )

    def test_no_public_api_hostname_is_configured(self, compose_text: str):
        """There must be no api.[DOMAIN] route, and the file must say so.

        The first version of this test banned the substring "api.", which also
        matched "the API." in a sentence. A test that fails on prose gets
        deleted rather than fixed, so it checks for the hostname shape instead.
        """
        # No line may *route* an api hostname to anything. Checking the route
        # arrow rather than the substring is what lets the file also contain
        # the sentence saying the route is deliberately absent - the second
        # version of this test banned that sentence along with the route.
        routes = [
            line for line in compose_text.splitlines()
            if "->" in line and re.search(r"\bapi\.", line)
        ]
        assert routes == [], f"an API hostname is routed: {routes}"
        assert not re.search(r"\bapi\.[a-z0-9-]+\.(com|net|org|io|dev|app)\b", compose_text)

        # And the absence is deliberate rather than an oversight.
        assert "no api.[DOMAIN]" in compose_text


class TestTheEntrypointLifecycle:
    @pytest.fixture(scope="class")
    def entrypoint(self) -> str:
        return ENTRYPOINT.read_text(encoding="utf-8")

    def test_it_seeds_only_when_the_database_is_empty(self, entrypoint: str):
        assert "--if-empty" in entrypoint

    def test_it_resets_only_when_explicitly_asked(self, entrypoint: str):
        assert 'DEMO_RESET_ON_START:-false' in entrypoint

    def test_it_does_nothing_demonstration_related_outside_demo_mode(self, entrypoint: str):
        assert '"${DEMO_MODE:-false}" != "true"' in entrypoint

    def test_migrations_run_before_any_seeding(self, entrypoint: str):
        assert entrypoint.index("apply_migrations") < entrypoint.index("prepare_demo_data")

    def test_a_failed_seed_does_not_stop_the_api_silently(self, entrypoint: str):
        assert "WARNING: seeding did not complete" in entrypoint


class TestTheResetScript:
    @pytest.fixture(scope="class")
    def reset(self) -> str:
        return (SCRIPTS_DIR / "reset_public_demo.sh").read_text(encoding="utf-8")

    def test_it_refuses_outside_demo_mode(self, reset: str):
        assert "demo_mode_enabled" in reset
        assert "Refusing to reset" in reset

    def test_it_confirms_the_database_it_is_connected_to(self, reset: str):
        """Never operate on an unidentified database."""
        assert "current_database()" in reset
        assert "Refusing to continue" in reset

    def test_it_requires_an_explicit_confirmation_word(self, reset: str):
        assert 'confirm "' in reset and '"reset"' in reset

    def test_it_never_deletes_source_migrations_configuration_or_backups(self, reset: str):
        for forbidden in ("rm -rf /", "migrations/", "backups/", ".env"):
            assert f"rm -rf {forbidden}" not in reset
            assert f"rm {forbidden}" not in reset

    def test_it_returns_a_nonzero_status_when_it_refuses(self, reset: str):
        assert "exit 2" in reset


class TestTheBackupScripts:
    @pytest.fixture(scope="class")
    def backup(self) -> str:
        return (SCRIPTS_DIR / "backup_selfhosted.sh").read_text(encoding="utf-8")

    @pytest.fixture(scope="class")
    def restore(self) -> str:
        return (SCRIPTS_DIR / "restore_selfhosted.sh").read_text(encoding="utf-8")

    def test_the_backup_uses_a_supported_postgres_tool(self, backup: str):
        assert "pg_dump" in backup
        assert "-Fc" in backup

    def test_the_backup_writes_a_checksum(self, backup: str):
        assert "sha256" in backup

    def test_the_backup_verifies_the_dump_is_really_a_dump(self, backup: str):
        """A dump that is really an error message looks like success."""
        assert "PGDMP" in backup

    def test_the_backup_documents_its_retention(self, backup: str):
        assert "BACKUP_RETENTION" in backup
        assert "Retention" in backup

    def test_the_backup_says_it_does_not_encrypt(self, backup: str):
        assert "does not encrypt" in backup

    def test_the_restore_verifies_the_checksum_before_restoring(self, restore: str):
        assert "Checksum FAILED" in restore
        assert "Refusing to restore" in restore

    def test_the_restore_offers_a_disposable_target(self, restore: str):
        assert "--into-throwaway" in restore
        assert "DROP DATABASE IF EXISTS" in restore

    def test_the_restore_rejects_an_empty_restore_as_a_failure(self, restore: str):
        """"Restore succeeded" about an empty schema is the false assurance
        this whole script exists to prevent."""
        assert "not a usable backup" in restore

    def test_the_restore_takes_a_safety_copy_before_overwriting(self, restore: str):
        assert "pre-restore-" in restore

    def test_the_restore_requires_confirmation(self, restore: str):
        assert '"restore"' in restore


class TestNoSecretsAreCommitted:
    def test_the_env_template_holds_no_real_value(self):
        text = ENV_EXAMPLE.read_text(encoding="utf-8")
        assert "CLOUDFLARE_TUNNEL_TOKEN=\n" in text or "CLOUDFLARE_TUNNEL_TOKEN=" in text
        # A real tunnel token is a long base64 blob.
        assert not re.search(r"CLOUDFLARE_TUNNEL_TOKEN=[A-Za-z0-9+/=_-]{40,}", text)
        assert "replace-me" in text

    def test_no_environment_file_is_tracked_except_the_examples(self):
        result = subprocess.run(
            ["git", "ls-files"], cwd=PROJECT_ROOT, capture_output=True, text=True, check=False
        )
        if result.returncode != 0:  # pragma: no cover - not a git checkout
            pytest.skip("not a git repository")
        tracked = set(result.stdout.split())
        for name in tracked:
            if name.startswith(".env"):
                assert name.endswith(".example"), f"{name} is tracked and is not an example"

    def test_the_gitignore_covers_every_category_of_secret_and_state(self):
        text = GITIGNORE.read_text(encoding="utf-8")
        for pattern in (
            ".env", ".env.selfhosted", "*.key", "*.pem",
            "backups/", "*.dump", "node_modules/", ".next/",
            "cloudflared/", "postgres-data/",
        ):
            assert pattern in text, f"{pattern} is not ignored"

    def test_no_backup_or_dump_is_tracked(self):
        result = subprocess.run(
            ["git", "ls-files"], cwd=PROJECT_ROOT, capture_output=True, text=True, check=False
        )
        if result.returncode != 0:  # pragma: no cover
            pytest.skip("not a git repository")
        for name in result.stdout.split():
            assert not name.endswith((".dump", ".sql.gz")), name
            assert not name.startswith("backups/"), name

    def test_no_node_modules_or_build_output_is_tracked(self):
        result = subprocess.run(
            ["git", "ls-files"], cwd=PROJECT_ROOT, capture_output=True, text=True, check=False
        )
        if result.returncode != 0:  # pragma: no cover
            pytest.skip("not a git repository")
        for name in result.stdout.split():
            assert "node_modules/" not in name, name
            assert not name.startswith("frontend/.next/"), name

    def test_the_frontend_lockfile_exists_and_is_not_ignored(self):
        """`npm ci` needs it, so it has to be committable.

        Asserts it is not git-ignored rather than that it is already tracked:
        the second version fails on a working tree where the file is new but
        not yet staged, which is every working tree that just created it.
        """
        lockfile = PROJECT_ROOT / "frontend" / "package-lock.json"
        assert lockfile.is_file(), "frontend/package-lock.json is missing; run npm install"

        result = subprocess.run(
            ["git", "check-ignore", "frontend/package-lock.json"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, check=False,
        )
        # check-ignore exits 0 when the path IS ignored.
        assert result.returncode != 0, "frontend/package-lock.json is git-ignored, so npm ci cannot work from a clone"


class TestTheFrontendImage:
    @pytest.fixture(scope="class")
    def dockerfile(self) -> str:
        return FRONTEND_DOCKERFILE.read_text(encoding="utf-8")

    def test_it_runs_as_a_non_root_user(self, dockerfile: str):
        assert re.search(r"^USER\s+node", dockerfile, re.MULTILINE)

    def test_it_uses_a_multi_stage_build(self, dockerfile: str):
        assert dockerfile.count("FROM ") >= 3

    def test_it_pins_the_node_image(self, dockerfile: str):
        assert "node:22-bookworm-slim" in dockerfile
        assert "node:latest" not in dockerfile

    def test_it_declares_a_health_check(self, dockerfile: str):
        assert "HEALTHCHECK" in dockerfile

    #: Build arguments that are not `NEXT_PUBLIC_` and are allowed anyway.
    #:
    #: The rule that matters is "no secret may be a build argument" - they are
    #: readable in the image history and, for `NEXT_PUBLIC_`, compiled into the
    #: browser bundle. The `NEXT_PUBLIC_` prefix was a convenient proxy for that
    #: until the site needed a value that is deliberately *not* public: the
    #: pages are statically generated, so a server-side switch consumed while
    #: they render still has to arrive at build time.
    #:
    #: An allow list rather than a widened pattern, so adding a build argument
    #: is still a decision somebody has to write down here.
    NON_PUBLIC_BUILD_ARGS = {
        # Whether the Services page is linked. Read while the pages render,
        # never sent to the browser. Not a secret; just not public API surface.
        "SERVICES_PAGE_ENABLED",
    }

    def test_it_takes_only_public_values_as_build_arguments(self, dockerfile: str):
        args = re.findall(r"^ARG\s+(\w+)", dockerfile, re.MULTILINE)
        assert args, "no build arguments found; the regex or the Dockerfile changed"
        for arg in args:
            assert arg.startswith("NEXT_PUBLIC_") or arg in self.NON_PUBLIC_BUILD_ARGS, (
                f"{arg} is a build argument. Build arguments are readable in the image "
                f"history and NEXT_PUBLIC_ values are compiled into the browser bundle, "
                f"so no secret may be passed this way. Add it to NON_PUBLIC_BUILD_ARGS "
                f"with a reason if it is genuinely not a secret."
            )

    def test_no_build_argument_is_secret_shaped(self, dockerfile: str):
        """The rule the prefix check is a proxy for, asserted directly."""
        args = re.findall(r"^ARG\s+(\w+)", dockerfile, re.MULTILINE)
        for arg in args:
            assert not re.search(
                r"(SECRET|TOKEN|PASSWORD|CREDENTIAL|PRIVATE_KEY|API_KEY)", arg
            ), f"{arg} is named like a secret and must never be a build argument"

    def test_the_dockerignore_keeps_environment_files_out_of_the_context(self):
        text = (PROJECT_ROOT / "frontend" / ".dockerignore").read_text(encoding="utf-8")
        assert ".env" in text
        assert "node_modules" in text
