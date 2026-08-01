"""The database contract: migrations, foreign keys, indexes.

These run against a throwaway SQLite file built by Alembic, not by
``Base.metadata.create_all``. That distinction is the point: ``create_all`` is
what the tests and local development use, Alembic is what a deployment uses, and
the two silently drifting apart is how a schema change ships green and fails on
the first real database.
"""

from __future__ import annotations

import io
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, event, inspect, text

from app.core.config import PROJECT_ROOT
from app.models import Base


@pytest.fixture(scope="module")
def migrated_engine():
    """A database built the way a deployment builds one: from an empty file."""
    with tempfile.TemporaryDirectory(prefix="sap_lab_migrations_") as directory:
        url = f"sqlite:///{Path(directory) / 'migrated.db'}"
        config = Config(str(PROJECT_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
        config.set_main_option("sqlalchemy.url", url)
        command.upgrade(config, "head")

        engine = create_engine(url)

        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _record):  # noqa: ANN001
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        yield engine
        engine.dispose()


class TestMigrations:
    def test_they_run_from_an_empty_database(self, migrated_engine):
        tables = set(inspect(migrated_engine).get_table_names())
        assert "alembic_version" in tables
        # Ten modules, plus the shared uploaded_files table.
        assert len(tables) >= 30, f"only {len(tables)} tables were created"

    def test_the_migrated_schema_matches_the_models(self, migrated_engine):
        """Autogenerate must find nothing left to do.

        A difference here means ``alembic upgrade head`` produces a database the
        application's own models disagree with - which local development never
        notices, because ``init_db()`` creates whatever is missing.
        """
        with migrated_engine.connect() as connection:
            context = MigrationContext.configure(connection, opts={"compare_type": True})
            differences = compare_metadata(context, Base.metadata)
        assert differences == [], f"the models and the migrations have drifted: {differences}"

    def test_every_model_table_exists_after_migrating(self, migrated_engine):
        """Importing one model by name would silently skip another module's tables."""
        created = set(inspect(migrated_engine).get_table_names())
        declared = set(Base.metadata.tables)
        assert declared - created == set(), f"tables no migration creates: {declared - created}"

    def test_downgrading_to_base_leaves_nothing_behind(self):
        """A migration you cannot reverse is a migration you cannot test twice."""
        with tempfile.TemporaryDirectory(prefix="sap_lab_downgrade_") as directory:
            url = f"sqlite:///{Path(directory) / 'roundtrip.db'}"
            config = Config(str(PROJECT_ROOT / "alembic.ini"))
            config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
            config.set_main_option("sqlalchemy.url", url)
            command.upgrade(config, "head")
            command.downgrade(config, "base")

            engine = create_engine(url)
            remaining = set(inspect(engine).get_table_names()) - {"alembic_version"}
            engine.dispose()
        assert remaining == set(), f"downgrade left tables behind: {sorted(remaining)}"

    def test_the_postgresql_dialect_renders(self):
        """The lab claims to be PostgreSQL-ready; this is what that claim means.

        Offline mode emits the DDL without connecting, so this runs with no
        server. It catches the SQLite-only construct that would otherwise be
        found by whoever first sets DATABASE_URL to a real PostgreSQL URL.
        """
        buffer = io.StringIO()
        config = Config(str(PROJECT_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
        config.set_main_option(
            "sqlalchemy.url", "postgresql+psycopg://user:password@localhost:5432/lab"
        )
        with redirect_stdout(buffer):
            command.upgrade(config, "head", sql=True)
        sql = buffer.getvalue()

        assert "CREATE TABLE po_analyses" in sql
        assert "CREATE TABLE interview_answers" in sql
        assert "TIMESTAMP WITH TIME ZONE" in sql, (
            "timestamps must keep their timezone on a database that can store one"
        )
        assert "password" not in sql, "the rendered DDL must not contain the credentials"


class TestForeignKeys:
    def test_every_child_table_cascades_from_its_parent(self, migrated_engine):
        """Deleting an analysis must not leave its findings orphaned.

        Without ``ON DELETE CASCADE`` a deleted upload leaves rows that no
        endpoint can reach and no report counts, which quietly inflates every
        row count taken straight from the table.
        """
        inspector = inspect(migrated_engine)
        offenders = []
        for table in inspector.get_table_names():
            for key in inspector.get_foreign_keys(table):
                rule = (key.get("options") or {}).get("ondelete", "")
                if rule.upper() != "CASCADE":
                    offenders.append(f"{table}.{key['constrained_columns']} -> {rule or 'none'}")
        assert offenders == [], f"foreign keys without ON DELETE CASCADE: {offenders}"

    def test_every_foreign_key_column_is_indexed(self, migrated_engine):
        """An unindexed foreign key turns every child lookup into a table scan."""
        inspector = inspect(migrated_engine)
        offenders = []
        for table in inspector.get_table_names():
            indexed = set()
            for index in inspector.get_indexes(table):
                if index["column_names"]:
                    indexed.add(index["column_names"][0])
            for constraint in inspector.get_unique_constraints(table):
                if constraint["column_names"]:
                    indexed.add(constraint["column_names"][0])
            for key in inspector.get_foreign_keys(table):
                column = key["constrained_columns"][0]
                if column not in indexed:
                    offenders.append(f"{table}.{column}")
        assert offenders == [], f"unindexed foreign keys: {offenders}"

    def test_sqlite_actually_enforces_them(self, migrated_engine):
        """SQLite ignores foreign keys unless the pragma is set per connection.

        The application sets it in an engine-level event listener. Without it,
        the CASCADE rules above are decoration.
        """
        with migrated_engine.connect() as connection:
            enforced = connection.execute(text("PRAGMA foreign_keys")).scalar()
        assert enforced == 1, "foreign keys are not being enforced on this connection"

    def test_the_application_engine_enforces_them_too(self):
        """The listener is registered on Engine, so it must apply to ours."""
        from app.models.session import engine

        if not engine.url.drivername.startswith("sqlite"):
            pytest.skip("only SQLite needs the pragma")
        with engine.connect() as connection:
            assert connection.execute(text("PRAGMA foreign_keys")).scalar() == 1


class TestCascadeBehaviour:
    def test_deleting_an_upload_removes_the_analysis_and_its_findings(self, db_session):
        """The cascade end to end, through the real ORM and the real session."""
        from app.models import PoAnalysis, PoFinding, UploadedFile

        upload = UploadedFile(
            id="cascade-test-upload",
            module="po_risk",
            original_filename="cascade.csv",
            stored_filename="cascade.csv",
            file_extension=".csv",
            size_bytes=10,
            sha256="0" * 64,
            row_count=1,
            column_count=1,
        )
        analysis = PoAnalysis(
            id="cascade-test-analysis",
            upload_id=upload.id,
            status="completed",
            source_filename="cascade.csv",
        )
        finding = PoFinding(
            id="cascade-test-finding",
            analysis_id=analysis.id,
            rule_id="PO-R001",
            rule_name="Test",
            risk_category="Test",
            severity="low",
            explanation="Test",
            recommended_action="Test",
        )
        db_session.add_all([upload, analysis, finding])
        db_session.commit()

        db_session.delete(upload)
        db_session.commit()

        # The session is built with expire_on_commit=False, so a plain get()
        # would answer from the identity map and "prove" a delete that never
        # reached the database. Ask the database.
        db_session.expunge_all()
        assert db_session.get(PoAnalysis, "cascade-test-analysis") is None
        assert db_session.get(PoFinding, "cascade-test-finding") is None


class TestIndexes:
    #: The tables a list endpoint orders by ``created_at DESC``. Kept explicit
    #: rather than derived from "has a created_at column", because most tables
    #: have one and are never sorted by it - ``po_findings`` is ordered by
    #: severity, ``spend_opportunities`` by saving. An index nobody queries is
    #: write cost with no read benefit.
    LISTED_NEWEST_FIRST = [
        "po_analyses",
        "spend_analyses",
        "supplier_recommendations",
        "invoice_validations",
        "supplier_risk_assessments",
        "contracts",
        "inventory_datasets",
        "inventory_forecasts",
        "test_suites",
        "blueprints",
        "interview_sessions",
    ]

    def test_the_columns_every_list_endpoint_sorts_by_are_indexed(self, migrated_engine):
        """``created_at`` is the sort key of every "newest first" list.

        An unindexed one is a full scan plus a sort on every page load, which is
        invisible on 20 demo rows and is not on 200,000.
        """
        inspector = inspect(migrated_engine)
        tables = set(inspector.get_table_names())
        offenders = []
        for table in self.LISTED_NEWEST_FIRST:
            assert table in tables, f"{table} no longer exists; update this list"
            indexed = {
                index["column_names"][0]
                for index in inspector.get_indexes(table)
                if index["column_names"]
            }
            if "created_at" not in indexed:
                offenders.append(table)
        assert offenders == [], (
            f"tables listed newest-first with no index on created_at: {offenders}"
        )
