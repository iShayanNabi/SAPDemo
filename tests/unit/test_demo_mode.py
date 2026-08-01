"""Public demonstration mode, at the level of the settings and the guards.

The API-level behaviour is in ``tests/api/test_demo_api.py``. This file covers
the decisions those routes rest on, because each of them is a place where a
plausible-looking change would quietly re-open the demonstration:

* demo mode must win over a configured provider key,
* the guard must refuse *before* a payload is read,
* the trusted-ingest escape hatch must not survive its own block.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.demo import (
    DEMO_BANNER_HEADLINE,
    DO_NOT_SUBMIT,
    DemoModeError,
    describe_demo_state,
    ensure_uploads_allowed,
    is_trusted_ingest,
    trusted_ingest,
    uploads_allowed,
)


def _settings(**overrides: object) -> Settings:
    """Build a Settings instance without touching the process environment."""
    # _env_file=None so a developer's own .env cannot change the answer.
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


class TestTheDefaultsAreOff:
    def test_demo_mode_is_off_by_default(self):
        assert _settings().demo_mode is False

    def test_uploads_are_enabled_when_demo_mode_is_off(self):
        assert _settings().uploads_enabled is True

    def test_the_demo_switches_do_nothing_while_demo_mode_is_off(self):
        # A half-applied demo configuration must not disable uploads on a
        # laptop. Only demo_mode turns the mode on.
        settings = _settings(demo_allow_uploads=False, demo_use_mock_ai=True)
        assert settings.uploads_enabled is True

    def test_a_real_provider_is_still_used_when_demo_mode_is_off(self):
        settings = _settings(ai_provider="anthropic", anthropic_api_key="sk-ant-test-key")
        assert settings.resolved_ai_provider() == "anthropic"


class TestDemoModeChangesExactlyThreeThings:
    def test_uploads_are_refused(self):
        assert _settings(demo_mode=True).uploads_enabled is False

    def test_uploads_can_be_re_enabled_deliberately(self):
        # Documented, discouraged, and possible - a private demonstration on a
        # trusted network is a real use.
        settings = _settings(demo_mode=True, demo_allow_uploads=True)
        assert settings.uploads_enabled is True

    def test_a_provider_key_present_in_the_environment_is_ignored(self):
        """The bill and the egress path nobody chose.

        A public demonstration that silently started calling Anthropic because
        a key happened to be exported is the failure this asserts against.
        """
        settings = _settings(
            demo_mode=True,
            ai_provider="anthropic",
            anthropic_api_key="sk-ant-a-real-looking-key",
        )
        assert settings.resolved_ai_provider() == "mock"

    def test_an_openai_key_is_ignored_too(self):
        settings = _settings(
            demo_mode=True, ai_provider="openai", openai_api_key="sk-a-real-looking-key"
        )
        assert settings.resolved_ai_provider() == "mock"

    def test_mock_can_be_turned_off_only_deliberately(self):
        settings = _settings(
            demo_mode=True,
            demo_use_mock_ai=False,
            ai_provider="anthropic",
            anthropic_api_key="sk-ant-key",
        )
        assert settings.resolved_ai_provider() == "anthropic"


class TestTheUploadGuard:
    def test_it_permits_uploads_outside_demo_mode(self, monkeypatch):
        monkeypatch.setattr("app.core.demo.settings", _settings())
        assert uploads_allowed() is True
        ensure_uploads_allowed()  # must not raise

    def test_it_refuses_in_demo_mode_with_a_403(self, monkeypatch):
        monkeypatch.setattr("app.core.demo.settings", _settings(demo_mode=True))
        assert uploads_allowed() is False
        with pytest.raises(DemoModeError) as raised:
            ensure_uploads_allowed()
        assert raised.value.http_status == 403
        assert raised.value.code == "demo_mode_restricted"

    def test_the_message_names_the_thing_that_was_refused(self, monkeypatch):
        monkeypatch.setattr("app.core.demo.settings", _settings(demo_mode=True))
        with pytest.raises(DemoModeError) as raised:
            ensure_uploads_allowed("document")
        # A contract upload must not be told its spreadsheet was rejected.
        assert "document" in raised.value.message

    def test_the_message_leaks_no_path_or_provider(self, monkeypatch):
        monkeypatch.setattr("app.core.demo.settings", _settings(demo_mode=True))
        with pytest.raises(DemoModeError) as raised:
            ensure_uploads_allowed()
        message = raised.value.message
        for forbidden in ("/app", "/Users", "postgresql://", "sk-", "anthropic"):
            assert forbidden not in message


class TestTrustedIngest:
    """The escape hatch, and the two ways it could become a hole."""

    def test_it_permits_ingestion_of_bundled_data(self, monkeypatch):
        monkeypatch.setattr("app.core.demo.settings", _settings(demo_mode=True))
        with trusted_ingest():
            assert uploads_allowed() is True
            ensure_uploads_allowed()  # must not raise

    def test_it_does_not_survive_its_own_block(self, monkeypatch):
        """The check that makes the flag safe rather than a permanent bypass."""
        monkeypatch.setattr("app.core.demo.settings", _settings(demo_mode=True))
        with trusted_ingest():
            pass
        assert is_trusted_ingest() is False
        with pytest.raises(DemoModeError):
            ensure_uploads_allowed()

    def test_it_is_restored_even_when_the_block_raises(self, monkeypatch):
        monkeypatch.setattr("app.core.demo.settings", _settings(demo_mode=True))
        with pytest.raises(ValueError), trusted_ingest():
            raise ValueError("something went wrong mid-seed")
        assert is_trusted_ingest() is False
        with pytest.raises(DemoModeError):
            ensure_uploads_allowed()

    def test_nesting_restores_the_outer_state_rather_than_clearing_it(self, monkeypatch):
        monkeypatch.setattr("app.core.demo.settings", _settings(demo_mode=True))
        with trusted_ingest():
            with trusted_ingest():
                assert is_trusted_ingest() is True
            # The inner block must not switch the outer one off - the seeder
            # calls the demo loader, so these really do nest.
            assert is_trusted_ingest() is True
        assert is_trusted_ingest() is False


class TestTheDescribedState:
    def test_it_carries_no_secret(self, monkeypatch):
        monkeypatch.setattr(
            "app.core.demo.settings",
            _settings(
                demo_mode=True,
                anthropic_api_key="sk-ant-should-never-appear",
                openai_api_key="sk-should-never-appear",
                database_url="postgresql+psycopg://user:hunter2@database:5432/db",
            ),
        )
        rendered = str(describe_demo_state())
        for forbidden in ("sk-ant-", "hunter2", "postgresql", "/Users", "/app"):
            assert forbidden not in rendered

    def test_it_states_the_banner_and_the_warning_list(self, monkeypatch):
        monkeypatch.setattr("app.core.demo.settings", _settings(demo_mode=True))
        state = describe_demo_state()
        assert state["banner_headline"] == DEMO_BANNER_HEADLINE
        assert state["do_not_submit"] == list(DO_NOT_SUBMIT)
        assert state["uploads_enabled"] is False
        assert state["ai_is_mock"] is True

    def test_it_names_every_category_a_visitor_must_not_submit(self):
        joined = " ".join(DO_NOT_SUBMIT).lower()
        for expected in ("confidential", "personal", "sap", "supplier", "proprietary"):
            assert expected in joined

    def test_it_admits_there_is_no_authentication(self, monkeypatch):
        """The limitation must be stated, not implied by its absence."""
        monkeypatch.setattr("app.core.demo.settings", _settings(demo_mode=True))
        statement = str(describe_demo_state()["authentication"]).lower()
        assert "no user accounts" in statement
        assert "does not replace" in statement or "not replace" in statement
