"""Central rounding policy for reported figures.

Every score, average and percentage this lab publishes is a **decimal** figure
with a fixed number of places. Computing one with binary floating point and
then calling the built-in :func:`round` is not good enough, for two reasons
that bit module 5 in production:

1. **Accumulation drift.** Summing 54 values that are each exactly ``x.xx``
   gives a total that is off by ~1e-15, because most 2-decimal values have no
   exact binary representation. When the true mean lands on a rounding tie the
   drift alone decides which way it goes. The supplier risk invoice average is
   exactly ``20.195``; the float sum reached ``20.194999999999997`` and reported
   ``20.19`` instead of ``20.20``. The inputs were identical - only the
   accumulation differed - so the same code produced a different answer on a
   different interpreter/NumPy build.

2. **Tie-breaking.** The built-in :func:`round` is round-half-to-**even** on
   the *binary* value, so what it does at a tie depends both on the parity of
   the preceding digit and on whether the binary neighbour happens to sit above
   or below the decimal tie. Neither is something a reader can reproduce by
   hand.

The policy here is therefore:

* interpret each input float as the decimal it prints as (``Decimal(str(v))``),
  which is exactly what a user sees in the API and the UI;
* do the arithmetic in :class:`~decimal.Decimal`, so a sum of 2-decimal values
  is exact;
* round **half away from zero** (``ROUND_HALF_UP``) to the target places.

Half-up is the convention a business reader expects - ``20.195`` is reported as
``20.20``, always - and unlike half-even it does not depend on the parity of
the digit in front of it, so a figure can be checked with a pocket calculator.

Use these helpers at the point a figure becomes a **reported** value: an
average, a percentage or a score that is persisted or returned by the API.
Intermediate arithmetic stays in float, which is both faster and correct - it
is only the published boundary that needs a stable policy.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal, ROUND_HALF_UP
from typing import SupportsFloat

__all__ = [
    "DEFAULT_DECIMALS",
    "decimal_mean",
    "decimal_sum",
    "round_half_up",
]

#: The number of decimal places every reported score in this lab carries.
DEFAULT_DECIMALS = 2


def _as_decimal(value: SupportsFloat) -> Decimal:
    """Interpret a value as the decimal it prints as.

    ``Decimal(str(0.1))`` is ``0.1``; ``Decimal(0.1)`` is
    ``0.1000000000000000055511151231257827``. The first is what the user sees
    and what the arithmetic should therefore use.
    """
    if isinstance(value, Decimal):
        return value
    return Decimal(str(float(value)))


def _quantum(decimals: int) -> Decimal:
    if decimals < 0:
        raise ValueError(f"decimals must not be negative, got {decimals}")
    return Decimal(1).scaleb(-decimals)


def round_half_up(value: SupportsFloat, decimals: int = DEFAULT_DECIMALS) -> float:
    """Round ``value`` to ``decimals`` places, half away from zero.

    >>> round_half_up(20.195)
    20.2
    >>> round_half_up(2.675)          # the built-in round() gives 2.67 here
    2.68
    >>> round_half_up(-0.125, 2)
    -0.13
    """
    return float(_as_decimal(value).quantize(_quantum(decimals), rounding=ROUND_HALF_UP))


def decimal_sum(values: Iterable[SupportsFloat]) -> Decimal:
    """Sum values exactly, as decimals, with no accumulation drift.

    Summing 2-decimal values this way is exact regardless of their order, which
    is what makes an aggregate reproducible across interpreters and machines.
    """
    total = Decimal(0)
    for value in values:
        total += _as_decimal(value)
    return total


def decimal_mean(
    values: Iterable[SupportsFloat], decimals: int = DEFAULT_DECIMALS
) -> float | None:
    """Return the mean of ``values``, rounded half-up to ``decimals`` places.

    Returns ``None`` for an empty input rather than raising or returning zero:
    "no data" and "an average of nought" are different statements, and a report
    must not confuse them.

    >>> decimal_mean([20.19, 20.2])
    20.2
    >>> decimal_mean([]) is None
    True
    """
    materialised = [_as_decimal(value) for value in values]
    if not materialised:
        return None
    mean = decimal_sum(materialised) / Decimal(len(materialised))
    return float(mean.quantize(_quantum(decimals), rounding=ROUND_HALF_UP))
