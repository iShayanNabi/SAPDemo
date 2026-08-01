"""Widen every ai_prompt_version column to 64 characters.

Revision ID: b8e6a24f1d35
Revises: a7d5f31c9e28
Create Date: 2026-08-01

Why this exists
---------------
``ai_prompt_version`` was declared ``String(20)`` on ``po_analyses`` and
``String(30)`` on ``invoice_validations``. The values written into them are
``po_risk_narrative_v1.0.0`` (24 characters) and
``invoice_validator_narrative_v1.0.0`` (34 characters).

Both have been too long since the day they were written, and nothing noticed,
because **SQLite does not enforce VARCHAR length**. It accepts a 34-character
string into a ``VARCHAR(30)`` without complaint, and the entire test suite runs
on SQLite. PostgreSQL enforces it and raises ``StringDataRightTruncation``, so
the bug appeared the first time the stack was started against a real database -
two of the ten modules failed to seed, and the demonstration came up missing its
purchase order and invoice data.

Two more columns - ``supplier_recommendations`` and ``supplier_risk_assessments``
- held values of exactly 30 characters in a ``String(30)``. They worked, and
they would have broken on the next version bump that added a character.

So every ``ai_prompt_version`` in the project is widened to the same 64, rather
than each being nudged to fit the value it happens to hold today. The column
records a short identifier chosen by this codebase; the narrow limit bought
nothing and cost a silent divergence between the database the tests use and the
database the deployment uses.

``batch_alter_table`` is used because SQLite cannot ``ALTER COLUMN`` in place -
Alembic rebuilds the table instead. On SQLite the change is cosmetic (the limit
was never enforced there); on PostgreSQL it is the fix.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b8e6a24f1d35"
down_revision = "a7d5f31c9e28"
branch_labels = None
depends_on = None

#: ``(table, previous width)`` for every column being widened.
_COLUMNS: tuple[tuple[str, int], ...] = (
    ("po_analyses", 20),
    ("spend_analyses", 30),
    ("supplier_recommendations", 30),
    ("invoice_validations", 30),
    ("supplier_risk_assessments", 30),
    ("contracts", 40),
    ("inventory_forecasts", 40),
    ("test_suites", 40),
    ("test_cases", 40),
    ("blueprints", 40),
    ("blueprint_sections", 40),
    ("interview_answers", 40),
)

NEW_WIDTH = 64


def upgrade() -> None:
    """Widen every ai_prompt_version column to 64 characters."""
    for table, previous in _COLUMNS:
        with op.batch_alter_table(table) as batch:
            batch.alter_column(
                "ai_prompt_version",
                existing_type=sa.String(previous),
                type_=sa.String(NEW_WIDTH),
                existing_nullable=True,
            )


def downgrade() -> None:
    """Narrow the columns back.

    This can fail on PostgreSQL, and that is correct rather than unfortunate:
    a stored value longer than the old limit cannot be narrowed without losing
    it, and silently truncating a recorded prompt version would make the
    provenance of every affected analysis wrong. Clear the offending rows first
    if a downgrade is genuinely wanted.
    """
    for table, previous in _COLUMNS:
        with op.batch_alter_table(table) as batch:
            batch.alter_column(
                "ai_prompt_version",
                existing_type=sa.String(NEW_WIDTH),
                type_=sa.String(previous),
                existing_nullable=True,
            )
