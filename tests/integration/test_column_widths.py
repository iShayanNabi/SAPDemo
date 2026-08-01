"""Every declared column has to be wide enough for what the code writes into it.

This file exists because of a bug that eleven hundred green tests could not see.

``ai_prompt_version`` was ``String(20)`` on ``po_analyses``, and the value the
code writes into it is ``po_risk_narrative_v1.0.0`` - 24 characters. It had been
wrong since the day it was written. **SQLite does not enforce VARCHAR length**,
so it stored the value happily, and the entire test suite runs on SQLite.
PostgreSQL enforces it, so the first time the stack was started against a real
database two of the ten modules failed to seed and the demonstration came up
missing its purchase order and invoice data. Nothing in the application logged
an error a person would have looked at.

The lesson generalises past this one column: **a constraint the test database
does not enforce is a constraint that is not tested**. So these tests compare
the declared widths against the constants the code actually writes, in plain
Python, with no database involved at all - which means they hold whichever
engine is configured.
"""

from __future__ import annotations

import pytest
from sqlalchemy import String

from app.models import Base
from app.services.ai import prompts

#: Every prompt version constant the application can write to a
#: ``ai_prompt_version`` column, collected from the module that defines them
#: rather than listed here - a new module's constant is picked up automatically.
PROMPT_VERSIONS: dict[str, str] = {
    name: value
    for name, value in vars(prompts).items()
    if name.endswith("PROMPT_VERSION") and isinstance(value, str)
}


def _string_columns(column_name: str) -> list[tuple[str, int]]:
    """Return ``(table, declared length)`` for every table holding ``column_name``."""
    found = []
    for table_name, table in Base.metadata.tables.items():
        column = table.c.get(column_name)
        if column is None:
            continue
        if isinstance(column.type, String) and column.type.length:
            found.append((table_name, column.type.length))
    return found


class TestPromptVersionColumns:
    def test_the_constants_were_found(self):
        """A guard on the guard: an empty list would make every test below pass."""
        assert len(PROMPT_VERSIONS) >= 10, PROMPT_VERSIONS

    def test_every_prompt_version_column_was_found(self):
        assert len(_string_columns("ai_prompt_version")) >= 10

    @pytest.mark.parametrize("table,length", _string_columns("ai_prompt_version"))
    def test_each_column_fits_the_longest_prompt_version_in_the_project(
        self, table: str, length: int
    ):
        """Any module's narrative may be written by any prompt version.

        Rather than matching each table to its own constant - which is the
        mapping that was wrong in the first place - every column is required to
        hold the longest value the project defines. One width, no per-table
        reasoning to get wrong.
        """
        longest_name, longest = max(PROMPT_VERSIONS.items(), key=lambda item: len(item[1]))
        assert length >= len(longest), (
            f"{table}.ai_prompt_version is String({length}), but "
            f"{longest_name} is {len(longest)} characters ({longest!r}). "
            f"SQLite will accept this and PostgreSQL will not."
        )

    def test_the_columns_carry_headroom_for_the_next_version_bump(self):
        """Exactly-fits is how two more columns were one character from breaking."""
        longest = max(len(value) for value in PROMPT_VERSIONS.values())
        for table, length in _string_columns("ai_prompt_version"):
            assert length >= longest + 8, (
                f"{table}.ai_prompt_version is String({length}) and the longest value is "
                f"{longest}. That works today and breaks on the next version bump."
            )


class TestOtherFixedVocabularyColumns:
    """Columns holding a value from a known, finite set.

    These are the other places where a declared width can be quietly too small,
    because the value is chosen by the code rather than supplied by a user.
    """

    @pytest.mark.parametrize("table,length", _string_columns("output_origin"))
    def test_output_origin_fits_every_origin(self, table: str, length: int):
        from app.schemas.common import OutputOrigin

        longest = max(len(origin.value) for origin in OutputOrigin)
        assert length >= longest, f"{table}.output_origin is String({length}), need {longest}"

    @pytest.mark.parametrize("table,length", _string_columns("ai_output_origin"))
    def test_ai_output_origin_fits_every_origin(self, table: str, length: int):
        from app.schemas.common import OutputOrigin

        longest = max(len(origin.value) for origin in OutputOrigin)
        assert length >= longest, f"{table}.ai_output_origin is String({length}), need {longest}"

    @pytest.mark.parametrize("table,length", _string_columns("ai_provider"))
    def test_ai_provider_fits_every_provider_name(self, table: str, length: int):
        # The resolved provider names, plus room for a longer one later.
        longest = max(len(name) for name in ("mock", "anthropic", "openai"))
        assert length >= longest, f"{table}.ai_provider is String({length}), need {longest}"

    @pytest.mark.parametrize("table,length", _string_columns("severity"))
    def test_severity_fits_every_severity(self, table: str, length: int):
        from app.schemas.common import Severity

        longest = max(len(value.value) for value in Severity)
        assert length >= longest, f"{table}.severity is String({length}), need {longest}"


class TestTheEngineDifferenceIsWrittenDown:
    """The reason these tests exist has to survive the person who wrote them."""

    def test_the_migration_explains_why_the_columns_were_widened(self):
        from app.core.config import PROJECT_ROOT

        migration = (
            PROJECT_ROOT
            / "migrations"
            / "versions"
            / "b8e6a24f1d35_widen_ai_prompt_version_columns.py"
        )
        assert migration.is_file()
        text = migration.read_text(encoding="utf-8")
        assert "SQLite does not enforce VARCHAR length" in text
        assert "StringDataRightTruncation" in text
