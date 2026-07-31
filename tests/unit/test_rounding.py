"""The central rounding policy.

These exist because module 5 shipped an aggregate that gave a different answer
on two interpreters from *identical inputs*: the supplier risk invoice average
is exactly ``20.195``, and binary accumulation over 54 two-decimal values
landed a hair below the tie on one machine and a hair above it on another.

The policy under test is: interpret a float as the decimal it prints as, do the
arithmetic in ``Decimal``, and round half away from zero.
"""

from __future__ import annotations

import random
from decimal import Decimal

import pytest

from app.core.rounding import (
    DEFAULT_DECIMALS,
    decimal_mean,
    decimal_sum,
    round_half_up,
)


#: 54 two-decimal values whose exact mean is 59.375 - a rounding tie - and
#: whose naive float mean changes with summation order. Frozen here rather
#: than generated, so the test asserts a fixed, inspectable fact.
_ORDER_SENSITIVE_VALUES: list[float] = [
    16.78, 36.41, 90.42, 86.46, 59.98, 31.72,
    68.36, 39.9, 97.19, 87.22, 72.26, 42.07,
    89.2, 98.31, 87.48, 72.55, 88.2, 82.65,
    40.53, 58.47, 14.97, 23.95, 45.18, 19.08,
    24.16, 79.81, 31.24, 19.91, 87.24, 98.36,
    55.48, 99.94, 73.49, 5.31, 4.44, 51.34,
    78.93, 99.69, 21.06, 77.04, 31.78, 39.13,
    80.11, 90.82, 71.5, 30.81, 29.54, 55.75,
    57.63, 97.04, 13.29, 78.93, 77.7, 95.44,
]


class TestRoundHalfUp:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (20.195, 20.2),
            (20.194, 20.19),
            (20.196, 20.2),
            (0.005, 0.01),
            (1.005, 1.01),
            (2.675, 2.68),
            (0.0, 0.0),
            (100.0, 100.0),
        ],
    )
    def test_a_tie_always_rounds_away_from_zero(self, value, expected):
        assert round_half_up(value) == expected

    def test_negative_ties_round_away_from_zero_too(self):
        assert round_half_up(-0.125, 2) == -0.13
        assert round_half_up(-20.195) == -20.2

    def test_it_differs_from_the_builtin_where_the_builtin_is_surprising(self):
        """The built-in rounds on the *binary* value, which users cannot predict."""
        assert round(2.675, 2) == 2.67  # not what a reader expects
        assert round_half_up(2.675) == 2.68

        assert round(0.125, 2) == 0.12  # half-to-even
        assert round_half_up(0.125) == 0.13

    def test_the_default_is_two_places(self):
        assert DEFAULT_DECIMALS == 2
        assert round_half_up(1.239) == round_half_up(1.239, 2)

    def test_other_precisions_work(self):
        assert round_half_up(1.23456, 4) == 1.2346
        assert round_half_up(1.5, 0) == 2.0

    def test_a_negative_precision_is_rejected(self):
        with pytest.raises(ValueError):
            round_half_up(1.23, -1)


class TestDecimalSum:
    def test_summing_two_decimal_values_is_exact(self):
        """The float sum of these drifts; the decimal sum does not."""
        values = [20.19, 20.2, 20.21]

        assert float(decimal_sum(values)) == 60.6
        assert str(decimal_sum(values)) == "60.60"

    def test_the_sum_does_not_depend_on_order(self):
        values = [round(random.Random(7).uniform(0, 100), 2) for _ in range(200)]
        shuffled = list(values)
        random.Random(11).shuffle(shuffled)

        assert decimal_sum(values) == decimal_sum(shuffled)


class TestDecimalMean:
    def test_the_exact_tie_that_broke_module_five(self):
        """The real shape of the defect: a mean that lands exactly on a tie.

        Module 5's invoice average is exactly ``20.195`` - 54 two-decimal
        scores summing to exactly ``1090.53``. Which side of the tie naive
        float arithmetic falls on is an accident of accumulation, so the answer
        was not reproducible; the policy always reports the value a reader
        would get by hand.
        """
        values = [20.19] * 27 + [20.2] * 27

        assert decimal_sum(values) == Decimal("1090.53")
        assert decimal_sum(values) / 54 == Decimal("20.195")
        assert decimal_mean(values) == 20.2

    def test_naive_float_averaging_is_order_dependent_and_the_policy_is_not(self):
        """This is the defect itself, not a symptom of it.

        These 54 two-decimal values have an exact mean of 59.375. Summing them
        in different orders gives 59.37 or 59.38 through the built-in round,
        because the accumulated binary error changes sign. Identical inputs,
        different answer - which is exactly how a baseline recorded on one
        machine stops reproducing on another.
        """
        values = _ORDER_SENSITIVE_VALUES
        assert decimal_sum(values) / len(values) == Decimal("59.375")

        naive_results = set()
        policy_results = set()
        for seed in range(6):
            shuffled = list(values)
            random.Random(seed).shuffle(shuffled)
            naive_results.add(round(sum(shuffled) / len(shuffled), 2))
            policy_results.add(decimal_mean(shuffled))

        assert naive_results == {59.37, 59.38}, "the naive defect must still be real"
        assert policy_results == {59.38}

    def test_the_mean_does_not_depend_on_order(self):
        values = [round(random.Random(3).uniform(0, 100), 2) for _ in range(54)]
        shuffled = list(values)
        random.Random(5).shuffle(shuffled)

        assert decimal_mean(values) == decimal_mean(shuffled)

    def test_repeated_calls_are_identical(self):
        values = [round(random.Random(13).uniform(0, 100), 2) for _ in range(54)]

        assert len({decimal_mean(values) for _ in range(50)}) == 1

    def test_an_empty_input_is_none_not_zero(self):
        """'No data' and 'an average of nought' are different statements."""
        assert decimal_mean([]) is None
        assert decimal_mean(iter([])) is None

    def test_a_generator_input_works(self):
        assert decimal_mean(value for value in (10.0, 20.0)) == 15.0

    def test_the_ordinary_case_is_unchanged(self):
        assert decimal_mean([10.0, 20.0, 30.0]) == 20.0
        assert decimal_mean([1.0]) == 1.0
