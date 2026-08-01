"""Readers that turn an accepted upload into a pandas DataFrame.

CSV, XLSX and JSON are supported. Everything is read as *text first*
(``dtype=str``) so that SAP identifiers keep their leading zeros
(``0000004711`` must not become ``4711``). Type coercion happens later, in the
normaliser, where failures can be reported as data quality issues.
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.core.config import settings
from app.core.exceptions import FileValidationError
from app.core.logging import get_logger
from app.services.files.validation import decode_text

logger = get_logger(__name__)

_CSV_CANDIDATE_SEPARATORS = (",", ";", "\t", "|")


@dataclass(frozen=True)
class ReadResult:
    """A parsed dataset plus a little information about how it was parsed."""

    dataframe: pd.DataFrame
    source_columns: list[str]
    row_count: int
    notes: list[str]


def read_tabular(content: bytes, extension: str) -> ReadResult:
    """Parse ``content`` into a DataFrame based on ``extension``."""
    extension = extension.lower()
    if extension == ".csv":
        frame, notes = _read_csv(content)
    elif extension == ".xlsx":
        frame, notes = _read_xlsx(content)
    elif extension == ".json":
        frame, notes = _read_json(content)
    else:  # pragma: no cover - validation rejects this earlier
        raise FileValidationError(f"Unsupported file type '{extension}'.")

    frame = _post_process(frame)

    if frame.empty:
        raise FileValidationError("The file contains no data rows.")
    if len(frame) > settings.max_rows_per_upload:
        raise FileValidationError(
            f"The file has {len(frame):,} rows which exceeds the "
            f"{settings.max_rows_per_upload:,} row limit.",
            details={"row_count": len(frame), "max_rows": settings.max_rows_per_upload},
        )

    return ReadResult(
        dataframe=frame,
        source_columns=[str(c) for c in frame.columns],
        row_count=len(frame),
        notes=notes,
    )


def _read_csv(content: bytes) -> tuple[pd.DataFrame, list[str]]:
    """Read a CSV, sniffing the delimiter from the header line."""
    text = decode_text(content)
    if text is None:
        raise FileValidationError("The CSV file could not be decoded as text.")

    separator = _detect_separator(text)

    # The C parser first, the Python parser as the fallback. The C one is about
    # twice as fast on the demo spend file and the gap widens with row count -
    # on a file at the 200,000 row limit it is the difference between a couple
    # of seconds and several. The Python parser is more forgiving of ragged
    # rows, so it stays as the second attempt rather than being replaced: a file
    # that only it can read still gets read, and the note says which one did it.
    common = {
        "sep": separator,
        "dtype": str,
        "keep_default_na": True,
        "skip_blank_lines": True,
    }
    try:
        frame = pd.read_csv(io.StringIO(text), engine="c", **common)
        notes = [f"CSV parsed with '{separator}' delimiter."]
    except (pd.errors.ParserError, ValueError) as first_error:
        logger.info("The C parser rejected the CSV (%s); retrying with the Python parser.", first_error)
        try:
            frame = pd.read_csv(io.StringIO(text), engine="python", **common)
        except Exception as exc:  # noqa: BLE001 - surfaced as a safe message
            logger.warning("CSV parsing failed: %s", exc)
            raise FileValidationError(
                "The CSV file could not be parsed. Check for inconsistent column counts."
            ) from exc
        notes = [
            f"CSV parsed with '{separator}' delimiter using the tolerant parser "
            f"(the fast parser rejected the file)."
        ]
    except Exception as exc:  # noqa: BLE001 - surfaced as a safe message
        logger.warning("CSV parsing failed: %s", exc)
        raise FileValidationError(
            "The CSV file could not be parsed. Check for inconsistent column counts."
        ) from exc

    return frame, notes


def _detect_separator(text: str) -> str:
    """Pick the delimiter that yields the most columns on the header line."""
    header = text.splitlines()[0] if text.splitlines() else ""
    counts = {sep: header.count(sep) for sep in _CSV_CANDIDATE_SEPARATORS}
    best = max(counts, key=lambda sep: counts[sep])
    return best if counts[best] > 0 else ","


def _read_xlsx(content: bytes) -> tuple[pd.DataFrame, list[str]]:
    """Read the first worksheet of an XLSX workbook."""
    try:
        workbook = pd.ExcelFile(io.BytesIO(content), engine="openpyxl")
        sheet_name = workbook.sheet_names[0]
        frame = workbook.parse(sheet_name=sheet_name, dtype=str)
    except FileValidationError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("XLSX parsing failed: %s", exc)
        raise FileValidationError("The Excel workbook could not be read.") from exc

    notes = [f"Worksheet '{sheet_name}' loaded."]
    if len(workbook.sheet_names) > 1:
        notes.append(
            "The workbook has multiple worksheets; only the first one was analysed."
        )
    return frame, notes


def _read_json(content: bytes) -> tuple[pd.DataFrame, list[str]]:
    """Read JSON supplied as a list of objects or ``{"records": [...]}``."""
    text = decode_text(content)
    if text is None:
        raise FileValidationError("The JSON file could not be decoded as text.")
    try:
        payload: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        raise FileValidationError(
            f"The JSON file is not valid: line {exc.lineno}, column {exc.colno}."
        ) from exc

    notes: list[str] = []
    if isinstance(payload, dict):
        for key in ("records", "data", "items", "rows", "value"):
            if isinstance(payload.get(key), list):
                notes.append(f"Records read from the '{key}' property.")
                payload = payload[key]
                break
        else:
            raise FileValidationError(
                "The JSON object must contain a list under 'records', 'data', "
                "'items', 'rows' or 'value'."
            )

    if not isinstance(payload, list) or not payload:
        raise FileValidationError("The JSON file must contain a non-empty list of records.")
    if not all(isinstance(row, dict) for row in payload):
        raise FileValidationError("Every JSON record must be an object with named fields.")

    frame = pd.DataFrame(payload).astype("object")
    return frame, notes


def _post_process(frame: pd.DataFrame) -> pd.DataFrame:
    """Trim headers/values and drop fully empty rows and unnamed columns."""
    frame = frame.copy()
    frame.columns = [str(column).strip() for column in frame.columns]

    # Drop the index column pandas writes when a file was exported with index=True.
    drop = [c for c in frame.columns if c.lower().startswith("unnamed:") or c == ""]
    if drop:
        frame = frame.drop(columns=drop)

    for column in frame.columns:
        frame[column] = _clean_column(frame[column])

    frame = frame.dropna(axis=0, how="all")
    return frame.reset_index(drop=True)


#: Values that mean "there is nothing here", whatever the file says.
_NULL_PLACEHOLDERS = frozenset({"", "nan", "none", "null", "#n/a", "n/a", "na", "-"})


def _clean_column(series: pd.Series) -> pd.Series:
    """Trim and null-normalise a whole column at once where that is possible.

    ``series.map(_clean_cell)`` is a Python call per cell. On a file at the
    200,000 row limit with 33 columns that is 6.6 million calls, and it costs as
    much as parsing the file did. CSV and XLSX are both read with ``dtype=str``,
    so in practice every column is text and missing values - which pandas can
    strip and compare vectorised, in C.

    The routing is decided by :func:`pandas.api.types.infer_dtype`, which
    inspects the *values*, not by the column's declared dtype. That is not a
    stylistic preference: pandas 3.0 returns a dedicated ``StringDtype`` from
    ``read_csv(dtype=str)`` rather than ``object``, so a check written as
    ``series.dtype != object`` skips every text column in the project and
    returns it untrimmed. It looks like a fast path and is a silent behaviour
    change.

    The elementwise path is kept for the case that requires it: JSON records
    carry real numbers and booleans, and ``.str.strip()`` turns a non-string
    into ``NaN``.
    """
    kind = pd.api.types.infer_dtype(series, skipna=True)

    if kind == "empty":
        # Every value is missing. Normalise them all to None.
        return pd.Series([None] * len(series), index=series.index, dtype=object)

    if kind == "string":
        # Strip and compare while the column is still pandas' string dtype -
        # both are vectorised there. Converting to ``object`` first costs more
        # than the per-cell loop it was meant to replace.
        stripped = series.str.strip()
        blank = (stripped.isna() | stripped.str.lower().isin(_NULL_PLACEHOLDERS)).to_numpy()
        # ``copy=True`` matters: with no missing values pandas hands back a
        # read-only view of its own buffer, and writing the nulls into it raises.
        values = stripped.to_numpy(dtype=object, na_value=None, copy=True)
        values[blank] = None
        return pd.Series(values, index=series.index, dtype=object)

    if kind in {"integer", "floating", "boolean", "decimal"}:
        # Nothing to trim, but a missing value still has to arrive as ``None``
        # rather than ``NaN`` - the integer cast downstream cannot take a NaN,
        # which is the shared-code bug module 5's missing-data sample found.
        if series.isna().any():
            return series.astype(object).where(series.notna(), other=None)
        return series

    # Mixed content: dates from a workbook, a JSON column holding both numbers
    # and strings. The per-cell rule handles every type, so use it.
    return series.map(_clean_cell)


def _clean_cell(value: Any) -> Any:
    """Trim whitespace and turn blank/NA placeholders into ``None``."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text == "" or text.lower() in _NULL_PLACEHOLDERS:
        return None
    return text


def preview_records(frame: pd.DataFrame, limit: int = 10) -> list[dict[str, Any]]:
    """Return the first ``limit`` rows as JSON-safe dictionaries."""
    head = frame.head(limit)
    records: list[dict[str, Any]] = []
    for _, row in head.iterrows():
        record = {}
        for column, value in row.items():
            record[str(column)] = None if pd.isna(value) else str(value)
        records.append(record)
    return records
