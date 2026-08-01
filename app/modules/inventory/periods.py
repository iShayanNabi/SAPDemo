"""Turning dated rows into evenly spaced periods.

A forecasting model does not see dates, it sees a list of numbers whose position
in the list *is* the time step. Getting from one to the other is the part of an
inventory forecast that quietly goes wrong, in two ways this module exists to
prevent:

1. **A file does not say what its frequency is.** ``2025-01-31``, ``2025-02-28``,
   ``2025-03-31`` is monthly data whose gaps are 28, 30 and 31 days. The
   frequency is therefore inferred from the *median* gap between consecutive
   dates and matched to the closest configured granularity, rather than assumed.

2. **A missing period is not the same as a zero.** If March is simply absent
   from the file, reading the list positionally would put April where March
   belongs and shift every seasonal index by one. Every series is therefore laid
   out on a complete grid of periods first, and the periods that had no row are
   recorded by index so they can be reported as data-quality warnings rather
   than disappearing into the numbers.

Monthly and quarterly periods use calendar arithmetic, so a month is a month and
not 30 days. Daily and weekly periods are counted from the first observation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from app.modules.inventory.thresholds import InventoryConfig

__all__ = [
    "PeriodGrid",
    "add_months",
    "infer_frequency",
    "month_start",
    "quarter_start",
]


def month_start(value: date) -> date:
    """First day of the month ``value`` falls in."""
    return date(value.year, value.month, 1)


def quarter_start(value: date) -> date:
    """First day of the calendar quarter ``value`` falls in."""
    return date(value.year, ((value.month - 1) // 3) * 3 + 1, 1)


def add_months(value: date, months: int) -> date:
    """Add ``months`` calendar months to the first day of a month."""
    total = (value.year * 12 + (value.month - 1)) + months
    return date(total // 12, total % 12 + 1, 1)


def infer_frequency(dates: list[date], config: InventoryConfig) -> tuple[str, float]:
    """Infer the period granularity from the gaps between ``dates``.

    Returns ``(frequency_name, median_gap_days)``. With fewer than two distinct
    dates there is no gap to measure, so the configured default is returned and
    the caller can report that the frequency was assumed rather than observed.
    """
    unique = sorted(set(dates))
    if len(unique) < 2:
        return config.period.default_frequency, 0.0

    gaps = [(later - earlier).days for earlier, later in zip(unique, unique[1:])]
    gaps = [gap for gap in gaps if gap > 0]
    if not gaps:
        return config.period.default_frequency, 0.0

    gaps.sort()
    middle = len(gaps) // 2
    median_gap = (
        float(gaps[middle])
        if len(gaps) % 2
        else (gaps[middle - 1] + gaps[middle]) / 2.0
    )

    # Compare on the ratio, not the absolute difference: 45 days is much closer
    # to a month (x1.5) than to a quarter (x0.49), even though the absolute
    # distances are 15 and 46.
    def closeness(name: str) -> tuple[float, int]:
        days = float(config.period.frequencies[name].days)
        ratio = median_gap / days if median_gap >= days else days / median_gap
        return ratio, config.period.frequencies[name].days

    best = min(config.period.frequencies, key=closeness)
    return best, median_gap


@dataclass(frozen=True)
class PeriodGrid:
    """An evenly spaced sequence of periods of one granularity.

    ``origin`` is the canonical start date of period 0. Every other period is
    addressed by its integer offset from it, which is exactly the index a
    forecasting model works in.
    """

    frequency: str
    days: int
    periods_per_year: int
    season_length: int
    origin: date

    @classmethod
    def build(cls, frequency: str, first_date: date, config: InventoryConfig) -> PeriodGrid:
        """Build the grid a series of this frequency lives on."""
        spec = config.period.spec(frequency)
        return cls(
            frequency=frequency,
            days=spec.days,
            periods_per_year=spec.periods_per_year,
            season_length=config.season_length_for(frequency),
            origin=cls._canonical(frequency, first_date),
        )

    @staticmethod
    def _canonical(frequency: str, value: date) -> date:
        """Snap a date onto the start of the period that contains it."""
        if frequency == "monthly":
            return month_start(value)
        if frequency == "quarterly":
            return quarter_start(value)
        return value

    def start_of(self, value: date) -> date:
        """Canonical start date of the period containing ``value``."""
        if self.frequency in {"monthly", "quarterly"}:
            return self._canonical(self.frequency, value)
        # Daily and weekly periods are counted from the origin, so a date lands
        # in the bucket it is nearest *below* - never in a bucket that has not
        # started yet.
        offset = (value - self.origin).days
        step = 1 if self.frequency == "daily" else 7
        buckets = offset // step if offset >= 0 else -((-offset + step - 1) // step)
        return self.origin + timedelta(days=buckets * step)

    def index_of(self, value: date) -> int:
        """Integer position of the period containing ``value``."""
        start = self.start_of(value)
        if self.frequency == "monthly":
            return (start.year - self.origin.year) * 12 + (start.month - self.origin.month)
        if self.frequency == "quarterly":
            months = (start.year - self.origin.year) * 12 + (start.month - self.origin.month)
            return months // 3
        step = 1 if self.frequency == "daily" else 7
        return (start - self.origin).days // step

    def date_at(self, index: int) -> date:
        """Start date of the period at integer position ``index``."""
        if self.frequency == "monthly":
            return add_months(self.origin, index)
        if self.frequency == "quarterly":
            return add_months(self.origin, index * 3)
        step = 1 if self.frequency == "daily" else 7
        return self.origin + timedelta(days=index * step)

    def end_date_at(self, index: int) -> date:
        """Last day of the period at integer position ``index``."""
        return self.date_at(index + 1) - timedelta(days=1)

    def length_days(self, index: int) -> int:
        """Actual number of days in the period at ``index``.

        Calendar months are not all 30 days long, and a shortage date that is
        interpolated inside a period has to know which month it is standing in.
        """
        return (self.date_at(index + 1) - self.date_at(index)).days

    def dates(self, start_index: int, count: int) -> list[date]:
        """Start dates of ``count`` consecutive periods from ``start_index``."""
        return [self.date_at(start_index + offset) for offset in range(count)]
