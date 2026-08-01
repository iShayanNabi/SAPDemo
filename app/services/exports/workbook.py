"""Shared workbook serialisation for every XLSX export.

One function, one reason to exist: **Excel has no concept of a timezone.**
openpyxl refuses to write a timezone-aware ``datetime`` and raises
``TypeError: Excel does not support timezones in datetimes``.

Every timestamp in this project is UTC and aware (see
:class:`app.models.base.UtcDateTime`), which is right for an API and fatal for a
worksheet. Each builder used to strip ``tzinfo`` in its own value-flattening
helper - which worked for the cells that went through the helper and broke for
the summary sheets that wrote a value straight in. On SQLite the values came
back naive and nothing failed; the same export against PostgreSQL, where the
driver returns the offset, raised on the first analysis anybody tried to
download.

Normalising here rather than at each cell means the guarantee holds for cells a
future builder writes without knowing about this rule at all.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone

from openpyxl.workbook import Workbook

__all__ = ["workbook_to_bytes"]


def workbook_to_bytes(workbook: Workbook) -> bytes:
    """Serialise ``workbook`` to XLSX bytes, converting timestamps to naive UTC.

    The value written is the UTC wall-clock time, so a cell reads the same as
    the API's ISO-8601 string with the ``Z`` removed. Nothing is shifted into a
    local timezone: the reader of a spreadsheet cannot see which timezone a bare
    timestamp is in, so the only defensible choice is the one the rest of the
    lab already publishes.
    """
    _strip_timezones(workbook)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _strip_timezones(workbook: Workbook) -> None:
    """Replace every aware datetime cell with its naive UTC equivalent."""
    for sheet in workbook.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                value = cell.value
                if isinstance(value, datetime) and value.tzinfo is not None:
                    cell.value = value.astimezone(timezone.utc).replace(tzinfo=None)
