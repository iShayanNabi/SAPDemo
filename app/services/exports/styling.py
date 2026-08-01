"""The workbook styling and value-flattening every export builder needs.

Seven builders were written before this module existed, and each of them carries
its own copy of the same four constants and the same four helpers - the navy
header fill, the white bold header font, `_write_header`, `_humanise`,
`_scalar`, `_cell`. That is a hundred-odd duplicated lines and, more to the
point, seven places a rule can drift: one builder rendering ``True`` as ``Yes``
and another as ``TRUE`` is the sort of difference nobody notices until two
reports are opened side by side.

The two builders added in Phase 5 use this module instead. The existing seven
are deliberately left alone: rewriting working exports to satisfy tidiness would
be a redesign, and the phase's job was integration, not renovation. Anything new
should import from here, and the seven can be migrated one at a time whenever
one of them is being changed for another reason.

Nothing here decides *what* goes in a report - only how a value is printed once
something else has decided it belongs there.
"""

from __future__ import annotations

import json
from typing import Any

from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.worksheet import Worksheet

__all__ = [
    "HEADER_FILL",
    "HEADER_FONT",
    "SECTION_FONT",
    "TITLE_FONT",
    "WRAP",
    "cell_value",
    "humanise",
    "scalar",
    "write_header",
    "write_key_values",
    "write_paragraph",
]

#: The navy header band every sheet in this project uses.
HEADER_FILL = PatternFill("solid", fgColor="1F3864")
HEADER_FONT = Font(color="FFFFFF", bold=True)
TITLE_FONT = Font(bold=True, size=14)
SECTION_FONT = Font(bold=True, size=11)
WRAP = Alignment(wrap_text=True, vertical="top")


def write_header(sheet: Worksheet, headers: list[str], row: int = 1) -> None:
    """Write a styled header row."""
    for column, header in enumerate(headers, start=1):
        cell = sheet.cell(row=row, column=column, value=header)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT


def humanise(key: str) -> str:
    """Turn a snake_case field name into a column label.

    ``overall_score`` -> ``Overall score``; ``spend_pct`` -> ``Spend %``;
    ``total_spend_base`` -> ``Total spend (base)``.
    """
    label = key.replace("_base", " (base)").replace("_", " ").strip()
    label = label.replace("pct", "%")
    return label[:1].upper() + label[1:]


def scalar(value: Any) -> Any:
    """Flatten a value into something a worksheet cell can hold.

    A cell holds a number, a string, a date or a boolean - not a dict and not a
    list. Structured values are serialised as JSON and truncated, because a cell
    holding 40 KB of nested data is not readable anyway and Excel has its own
    limit. Booleans become ``Yes``/``No``, which is what a reader expects in a
    report and what every existing builder already does.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(value, default=str, ensure_ascii=False)[:2000]
    return value


def cell_value(record: dict[str, Any], key: str) -> Any:
    """Read ``key`` from ``record`` and flatten it for a cell.

    A list of short strings - reasons, issues, actions - reads better joined
    with a pipe than as JSON, so that case is handled before :func:`scalar`.
    """
    value = record.get(key)
    if isinstance(value, list) and all(isinstance(item, (str, int, float)) for item in value):
        return " | ".join(str(item) for item in value)
    return scalar(value)


def write_key_values(
    sheet: Worksheet, pairs: list[tuple[str, Any]], row: int, *, label_width: int = 34
) -> int:
    """Write a two-column label/value block and return the next free row."""
    for label, value in pairs:
        sheet.cell(row=row, column=1, value=label)
        sheet.cell(row=row, column=2, value=scalar(value))
        row += 1
    sheet.column_dimensions["A"].width = max(
        label_width, sheet.column_dimensions["A"].width or 0
    )
    return row


def write_paragraph(
    sheet: Worksheet, text: str, row: int, *, width: int = 6, height: int = 4
) -> int:
    """Write a wrapped, merged block of prose and return the next free row.

    Used for disclaimers and narratives, which are the only things in these
    reports long enough to need it.
    """
    cell = sheet.cell(row=row, column=1, value=text)
    cell.alignment = WRAP
    sheet.merge_cells(start_row=row, start_column=1, end_row=row + height, end_column=width)
    return row + height + 1
