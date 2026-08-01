"""Ordering helpers that let the database do the sorting.

Two list endpoints - purchase order findings and invoice exceptions - are
ordered by *severity first, then by size of the exposure*. That is not a column
order, so both were written the obvious way::

    rows = db.scalars(statement).all()          # every matching row
    rows = sorted(rows, key=...)[offset:offset + limit]

which returns the right page and reads the whole result set to do it. With 131
demo findings that is invisible. The upload limit is 200,000 rows, and a file
that size can produce tens of thousands of findings - so every page of 25 pulls
all of them into memory, builds a Python object per row, sorts, and throws
almost all of it away. The cost is paid again on every page.

Expressing the severity order as a SQL ``CASE`` puts the whole thing back where
it belongs: the database sorts (using the ``(analysis_id, severity)`` index that
already exists), applies ``LIMIT``/``OFFSET``, and returns exactly the rows the
page needs.

The rank values are taken from :class:`app.schemas.common.Severity` rather than
written out again, so a new severity level cannot be added to the vocabulary and
silently sort last here.
"""

from __future__ import annotations

from sqlalchemy import Case, case
from sqlalchemy.orm import InstrumentedAttribute

from app.schemas.common import IssueSeverity, Severity

__all__ = ["issue_severity_rank", "severity_rank"]

#: Most serious first, which is the order every findings list is read in.
_SEVERITY_RANK: dict[str, int] = {item.value: 5 - item.rank for item in Severity}
_ISSUE_SEVERITY_RANK: dict[str, int] = {item.value: 4 - item.rank for item in IssueSeverity}

#: Anything the database holds that is not a known level sorts last rather than
#: first. A row with a corrupt severity should not lead a risk report.
_UNKNOWN_RANK = 99


def severity_rank(column: InstrumentedAttribute[str]) -> Case:
    """Return a SQL expression ordering ``column`` critical -> low.

    >>> statement.order_by(severity_rank(PoFinding.severity))
    """
    return case(_SEVERITY_RANK, value=column, else_=_UNKNOWN_RANK)


def issue_severity_rank(column: InstrumentedAttribute[str]) -> Case:
    """Return a SQL expression ordering ``column`` error -> info."""
    return case(_ISSUE_SEVERITY_RANK, value=column, else_=_UNKNOWN_RANK)
