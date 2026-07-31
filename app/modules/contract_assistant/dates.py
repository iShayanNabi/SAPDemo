"""Date, duration and notice-period extraction.

Contracts write dates in every style a jurisdiction has ever invented, so the
parser accepts the ones that actually occur - ``1 January 2026``,
``January 1, 2026``, ``2026-01-01``, ``01/01/2026``, ``the 1st day of January
2026`` - and refuses everything else rather than guessing.

The ambiguous case (``03/04/2026``) is resolved by ``dates.day_first`` in the
configuration, not by a hardcoded assumption, and the choice is reported on the
result so a reader can see which way it was read.

Nothing here is AI-assisted. A date is a calculation, and a calculation the
code can do reliably never goes to a model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from app.core.logging import get_logger
from app.modules.contract_assistant.thresholds import ContractAssistantConfig

logger = get_logger(__name__)

MONTHS: dict[str, int] = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9, "october": 10,
    "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}

_MONTH_ALTERNATIVES = "|".join(sorted(MONTHS, key=len, reverse=True))

#: ``1 January 2026`` / ``1st of January 2026`` / ``the 1st day of January 2026``
_DAY_MONTH_YEAR = re.compile(
    rf"\b(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\s+(?:day\s+of\s+)?(?:of\s+)?"
    rf"(?P<month>{_MONTH_ALTERNATIVES})\b\.?,?\s+(?P<year>\d{{4}})",
    re.IGNORECASE,
)
#: ``January 1, 2026`` / ``Jan 1 2026``
_MONTH_DAY_YEAR = re.compile(
    rf"\b(?P<month>{_MONTH_ALTERNATIVES})\b\.?\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?,?\s+(?P<year>\d{{4}})",
    re.IGNORECASE,
)
#: ``2026-01-01`` (ISO, unambiguous)
_ISO = re.compile(r"\b(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})\b")
#: ``01/01/2026``, ``01.01.2026``, ``01-01-2026`` - order decided by configuration
_NUMERIC = re.compile(r"\b(?P<first>\d{1,2})[./-](?P<second>\d{1,2})[./-](?P<year>\d{2,4})\b")

#: Ordered so an unambiguous format always wins over an ambiguous one.
_DATE_PATTERNS = (_ISO, _DAY_MONTH_YEAR, _MONTH_DAY_YEAR, _NUMERIC)


@dataclass
class ParsedDate:
    """A date found in the document, with the text it was read from."""

    value: date
    matched_text: str
    offset: int
    format_basis: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value.isoformat(),
            "matched_text": self.matched_text,
            "offset": self.offset,
            "format_basis": self.format_basis,
        }


@dataclass
class ParsedDuration:
    """A duration found in the document (a term length or a notice period)."""

    days: int
    count: str
    unit: str
    matched_text: str
    offset: int

    @property
    def label(self) -> str:
        return f"{self.count} {self.unit}".strip()

    def to_dict(self) -> dict[str, Any]:
        return {
            "days": self.days,
            "count": self.count,
            "unit": self.unit,
            "label": self.label,
            "matched_text": self.matched_text,
            "offset": self.offset,
        }


def parse_date(text: str, config: ContractAssistantConfig) -> ParsedDate | None:
    """Parse the first date in ``text``, or return ``None``.

    Returning ``None`` matters more than it looks: a contract register that
    shows "not stated" is honest, while one that shows a guessed date is worse
    than useless.
    """
    if not text:
        return None
    for pattern in _DATE_PATTERNS:
        match = pattern.search(text)
        if match is None:
            continue
        parsed = _build_date(match, pattern, config)
        if parsed is not None:
            return parsed
    return None


def find_dates(text: str, config: ContractAssistantConfig) -> list[ParsedDate]:
    """Return every date in ``text``, in document order, de-duplicated by offset."""
    found: dict[int, ParsedDate] = {}
    for pattern in _DATE_PATTERNS:
        for match in pattern.finditer(text):
            if any(
                existing.offset <= match.start() < existing.offset + len(existing.matched_text)
                for existing in found.values()
            ):
                continue
            parsed = _build_date(match, pattern, config)
            if parsed is not None:
                found[parsed.offset] = parsed
    return [found[key] for key in sorted(found)]


def _build_date(
    match: re.Match[str], pattern: re.Pattern[str], config: ContractAssistantConfig
) -> ParsedDate | None:
    """Turn one regex match into a :class:`ParsedDate`, or ``None`` when invalid."""
    groups = match.groupdict()
    try:
        if pattern is _ISO:
            year, month, day = int(groups["year"]), int(groups["month"]), int(groups["day"])
            basis = "iso"
        elif pattern is _NUMERIC:
            first, second = int(groups["first"]), int(groups["second"])
            year = _expand_year(int(groups["year"]))
            if config.dates.day_first:
                day, month, basis = first, second, "numeric_day_first"
            else:
                month, day, basis = first, second, "numeric_month_first"
            # A value above 12 can only be a day, whatever the configured order.
            if month > 12 >= day:
                day, month = month, day
                basis += "_corrected"
        else:
            month_name = groups["month"].lower().rstrip(".")
            month = MONTHS.get(month_name, 0)
            day, year = int(groups["day"]), int(groups["year"])
            basis = "day_month_year" if pattern is _DAY_MONTH_YEAR else "month_day_year"
        return ParsedDate(
            value=date(year, month, day),
            matched_text=match.group(0).strip(),
            offset=match.start(),
            format_basis=basis,
        )
    except (ValueError, KeyError):
        # An impossible date (31 February) is not a date. Say nothing.
        return None


def _expand_year(year: int) -> int:
    """Expand a two digit year the way business documents mean it."""
    if year >= 100:
        return year
    return 2000 + year if year < 70 else 1900 + year


def find_first_by_patterns(
    text: str, patterns: list[re.Pattern[str]], config: ContractAssistantConfig
) -> ParsedDate | None:
    """Find the first date reachable through one of ``patterns``.

    The pattern isolates the *phrase* ("effective as of ..."), then the date
    parser reads the date out of the captured group. Splitting it this way is
    what stops a signature date at the bottom of page 9 from being reported as
    the effective date.
    """
    for pattern in patterns:
        for match in pattern.finditer(text):
            has_group = "date" in match.groupdict() and match.group("date") is not None
            fragment = match.group("date") if has_group else match.group(0)
            parsed = parse_date(fragment, config)
            if parsed is None:
                continue
            # Re-anchor the offset onto the whole text so the citation points at
            # the phrase, not at an offset inside the captured fragment. The
            # matched text is trimmed to end at the date, because the capture
            # group is deliberately generous and would otherwise quote half a
            # sentence back at the reader.
            fragment_start = match.start("date") if has_group else match.start()
            phrase_end = fragment_start + parsed.offset + len(parsed.matched_text)
            return ParsedDate(
                value=parsed.value,
                matched_text=text[match.start() : phrase_end].strip(),
                offset=fragment_start + parsed.offset,
                format_basis=parsed.format_basis,
            )
    return None


def find_duration(
    text: str, patterns: list[re.Pattern[str]], config: ContractAssistantConfig
) -> ParsedDuration | None:
    """Find the first duration reachable through one of ``patterns``."""
    for pattern in patterns:
        for match in pattern.finditer(text):
            groups = match.groupdict()
            count, unit = groups.get("count"), groups.get("unit")
            if not count or not unit:
                continue
            days = config.dates.to_days(count, unit)
            if days is None:
                continue
            return ParsedDuration(
                days=days,
                count=count.strip(),
                unit=unit.strip(),
                matched_text=match.group(0).strip(),
                offset=match.start(),
            )
    return None


def find_all_durations(
    text: str, patterns: list[re.Pattern[str]], config: ContractAssistantConfig
) -> list[ParsedDuration]:
    """Return every duration reachable through ``patterns``, in document order."""
    results: list[ParsedDuration] = []
    seen: set[int] = set()
    for pattern in patterns:
        for match in pattern.finditer(text):
            if match.start() in seen:
                continue
            groups = match.groupdict()
            count, unit = groups.get("count"), groups.get("unit")
            if not count or not unit:
                continue
            days = config.dates.to_days(count, unit)
            if days is None:
                continue
            seen.add(match.start())
            results.append(
                ParsedDuration(
                    days=days,
                    count=count.strip(),
                    unit=unit.strip(),
                    matched_text=match.group(0).strip(),
                    offset=match.start(),
                )
            )
    return sorted(results, key=lambda item: item.offset)


def add_days(start: date | None, days: int | None) -> date | None:
    """Add ``days`` to ``start``, preserving ``None``."""
    if start is None or days is None:
        return None
    return start + timedelta(days=days)


def add_duration(start: date | None, duration: ParsedDuration | None) -> date | None:
    """Advance ``start`` by ``duration`` using calendar arithmetic.

    ``dates.unit_days`` treats a month as 30 days, which is right for comparing
    a notice period against a threshold and wrong for computing a renewal date:
    twelve months after 1 April is 1 April, not 27 March. Months and years are
    therefore added on the calendar; everything smaller is added in days.
    """
    if start is None or duration is None:
        return None
    unit = duration.unit.lower().rstrip("s")
    if unit == "month":
        return add_months(start, duration.days // 30)
    if unit == "year":
        return add_months(start, (duration.days // 365) * 12)
    return start + timedelta(days=duration.days)


def config_unit_days(unit: str) -> int:
    """Days per unit for the calendar-free units (used by :func:`add_duration`)."""
    return {"day": 1, "week": 7, "month": 30, "year": 365}.get(unit, 0)


def add_months(start: date | None, months: int) -> date | None:
    """Add whole calendar months, clamping the day to the target month's length."""
    if start is None:
        return None
    total = start.month - 1 + months
    year = start.year + total // 12
    month = total % 12 + 1
    day = min(start.day, _days_in_month(year, month))
    return date(year, month, day)


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - timedelta(days=1)).day


def days_between(earlier: date | None, later: date | None) -> int | None:
    """Days from ``earlier`` to ``later``, preserving ``None``."""
    if earlier is None or later is None:
        return None
    return (later - earlier).days
