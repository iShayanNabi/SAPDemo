"""Projecting stock forward and deciding what to order.

The forecast says how much will be *demanded*. This module answers the questions
a planner actually asks: when do I run out, when should I order, how much, how
much buffer should I be holding, and is this material dead on the shelf.

**The projection walks days, not periods.** A monthly forecast tells you 300
units will go in March; it does not tell you that the stock runs out on the 12th.
Reporting "March" as a shortage date is not good enough to act on, and reporting
the 1st or the 31st would be wrong. So the projection consumes the period's
forecast evenly across that period's *actual* calendar days - 28 in February, 31
in March - and places each open purchase-order quantity on the exact day it is
expected. Every date this module reports is a real date on which the stock
position crosses a real line.

**Two positions are tracked, because two different questions need them.** Stock
on hand answers "have I run out?". Inventory position - stock on hand plus what
is already on order and not yet arrived - answers "should I order more?". Using
stock on hand for the reorder trigger is the classic way to order twice for the
same shortage.

Every figure here is arithmetic on the forecast and the configured policy. None
of it is estimated by a model and none of it is a commitment: an estimated
shortage date is a planning indication, which is why the module reports the
assumptions alongside the numbers.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from app.core.logging import get_logger
from app.core.rounding import decimal_mean, round_half_up
from app.modules.inventory.normalizer import InventorySeries
from app.modules.inventory.thresholds import InventoryConfig

logger = get_logger(__name__)

__all__ = [
    "ForecastPoint",
    "ProjectedPeriod",
    "ProjectionResult",
    "ReorderRecommendation",
    "StockHealth",
    "build_forecast_points",
    "project_inventory",
]


@dataclass
class ForecastPoint:
    """One forecast period: the quantity and the interval around it."""

    index: int
    period_date: date
    period_end_date: date
    period_days: int
    demand: float
    lower: float | None = None
    upper: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "period_date": self.period_date.isoformat(),
            "period_end_date": self.period_end_date.isoformat(),
            "period_days": self.period_days,
            "demand": self.demand,
            "lower": self.lower,
            "upper": self.upper,
        }


@dataclass
class ProjectedPeriod:
    """The projected stock position at the end of one future period."""

    index: int
    period_date: date
    period_end_date: date
    opening_inventory: float
    forecast_demand: float
    scheduled_receipts: float
    projected_ending: float
    projected_ending_low: float
    projected_ending_high: float
    inventory_position: float
    below_safety_stock: bool = False
    stockout: bool = False
    days_of_cover: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "period_date": self.period_date.isoformat(),
            "period_end_date": self.period_end_date.isoformat(),
            "opening_inventory": self.opening_inventory,
            "forecast_demand": self.forecast_demand,
            "scheduled_receipts": self.scheduled_receipts,
            "projected_ending": self.projected_ending,
            "projected_ending_low": self.projected_ending_low,
            "projected_ending_high": self.projected_ending_high,
            "inventory_position": self.inventory_position,
            "below_safety_stock": self.below_safety_stock,
            "stockout": self.stockout,
            "days_of_cover": self.days_of_cover,
        }


@dataclass
class ReorderRecommendation:
    """What to order, when, and the policy the numbers came from."""

    lead_time_days: int = 0
    lead_time_source: str = "file"
    review_period_days: int = 0
    service_level: float = 0.0
    service_level_z: float = 0.0
    safety_stock_basis: str = ""
    demand_sigma_per_period: float | None = None
    expected_lead_time_demand: float | None = None
    recommended_safety_stock: float | None = None
    calculated_reorder_point: float | None = None
    reorder_point_at_trigger: float | None = None
    master_safety_stock: float | None = None
    master_reorder_point: float | None = None
    effective_safety_stock: float | None = None
    safety_stock_gap: float | None = None
    reorder_point_gap: float | None = None
    recommended_reorder_date: date | None = None
    recommended_reorder_quantity: float | None = None
    order_urgency: str = "not_required"
    expedite_recommended: bool = False
    expedite_reason: str | None = None
    target_stock_level: float | None = None
    inventory_position_at_reorder: float | None = None
    rationale: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "lead_time_days": self.lead_time_days,
            "lead_time_source": self.lead_time_source,
            "review_period_days": self.review_period_days,
            "service_level": self.service_level,
            "service_level_z": self.service_level_z,
            "safety_stock_basis": self.safety_stock_basis,
            "demand_sigma_per_period": self.demand_sigma_per_period,
            "expected_lead_time_demand": self.expected_lead_time_demand,
            "recommended_safety_stock": self.recommended_safety_stock,
            "calculated_reorder_point": self.calculated_reorder_point,
            "reorder_point_at_trigger": self.reorder_point_at_trigger,
            "master_safety_stock": self.master_safety_stock,
            "master_reorder_point": self.master_reorder_point,
            "effective_safety_stock": self.effective_safety_stock,
            "safety_stock_gap": self.safety_stock_gap,
            "reorder_point_gap": self.reorder_point_gap,
            "recommended_reorder_date": (
                self.recommended_reorder_date.isoformat()
                if self.recommended_reorder_date
                else None
            ),
            "recommended_reorder_quantity": self.recommended_reorder_quantity,
            "order_urgency": self.order_urgency,
            "expedite_recommended": self.expedite_recommended,
            "expedite_reason": self.expedite_reason,
            "target_stock_level": self.target_stock_level,
            "inventory_position_at_reorder": self.inventory_position_at_reorder,
            "rationale": list(self.rationale),
        }


@dataclass
class StockHealth:
    """Whether the stock is moving, over-held or dead."""

    days_of_cover: float | None = None
    annual_turnover: float | None = None
    average_inventory: float | None = None
    movement_class: str = "unknown"
    is_slow_moving: bool = False
    is_dead_stock: bool = False
    trailing_zero_demand_periods: int = 0
    zero_demand_period_pct: float = 0.0
    overstock_risk: str = "none"
    overstock_excess_quantity: float | None = None
    overstock_threshold_days: float = 0.0
    classification_basis: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "days_of_cover": self.days_of_cover,
            "annual_turnover": self.annual_turnover,
            "average_inventory": self.average_inventory,
            "movement_class": self.movement_class,
            "is_slow_moving": self.is_slow_moving,
            "is_dead_stock": self.is_dead_stock,
            "trailing_zero_demand_periods": self.trailing_zero_demand_periods,
            "zero_demand_period_pct": self.zero_demand_period_pct,
            "overstock_risk": self.overstock_risk,
            "overstock_excess_quantity": self.overstock_excess_quantity,
            "overstock_threshold_days": self.overstock_threshold_days,
            "classification_basis": list(self.classification_basis),
        }


@dataclass
class ProjectionResult:
    """The projected stock path and everything derived from it."""

    opening_inventory: float | None = None
    opening_inventory_date: date | None = None
    periods: list[ProjectedPeriod] = field(default_factory=list)
    predicted_shortage_date: date | None = None
    days_to_shortage: int | None = None
    predicted_below_safety_stock_date: date | None = None
    shortage_within_horizon: bool = False
    minimum_projected_inventory: float | None = None
    minimum_projected_inventory_date: date | None = None
    ending_projected_inventory: float | None = None
    scheduled_receipt_total: float = 0.0
    unscheduled_open_quantity: float = 0.0
    reorder: ReorderRecommendation = field(default_factory=ReorderRecommendation)
    health: StockHealth = field(default_factory=StockHealth)
    available: bool = True
    unavailable_reason: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "opening_inventory": self.opening_inventory,
            "opening_inventory_date": (
                self.opening_inventory_date.isoformat() if self.opening_inventory_date else None
            ),
            "periods": [item.to_dict() for item in self.periods],
            "predicted_shortage_date": (
                self.predicted_shortage_date.isoformat() if self.predicted_shortage_date else None
            ),
            "days_to_shortage": self.days_to_shortage,
            "predicted_below_safety_stock_date": (
                self.predicted_below_safety_stock_date.isoformat()
                if self.predicted_below_safety_stock_date
                else None
            ),
            "shortage_within_horizon": self.shortage_within_horizon,
            "minimum_projected_inventory": self.minimum_projected_inventory,
            "minimum_projected_inventory_date": (
                self.minimum_projected_inventory_date.isoformat()
                if self.minimum_projected_inventory_date
                else None
            ),
            "ending_projected_inventory": self.ending_projected_inventory,
            "scheduled_receipt_total": self.scheduled_receipt_total,
            "unscheduled_open_quantity": self.unscheduled_open_quantity,
            "reorder": self.reorder.to_dict(),
            "health": self.health.to_dict(),
            "available": self.available,
            "unavailable_reason": self.unavailable_reason,
            "notes": list(self.notes),
        }


# ---------------------------------------------------------------------------
# Forecast points
# ---------------------------------------------------------------------------


def build_forecast_points(
    series: InventorySeries,
    point_forecast: list[float],
    interval_factors: list[float],
    sigma: float,
    config: InventoryConfig,
    confidence_level: float | None = None,
) -> list[ForecastPoint]:
    """Attach dates and a prediction interval to a bare list of forecast values.

    The interval is ``forecast +- z * sigma * factor_h``. ``sigma`` is the
    model's residual standard deviation and ``factor_h`` is how that error grows
    with the horizon for that model - flat for a moving average, widening for the
    exponential-smoothing family.
    """
    z_score = config.forecast.z_for(confidence_level)
    decimals = config.forecast.decimals
    last_index = series.periods[-1].index if series.periods else 0

    points: list[ForecastPoint] = []
    for step, value in enumerate(point_forecast, start=1):
        index = last_index + step
        factor = interval_factors[step - 1] if step - 1 < len(interval_factors) else 1.0
        half_width = z_score * sigma * factor
        demand = float(value)
        lower = demand - half_width
        upper = demand + half_width

        if config.forecast.clip_negative_forecast:
            demand = max(0.0, demand)
        if config.forecast.clip_negative_interval:
            lower = max(0.0, lower)

        points.append(
            ForecastPoint(
                index=index,
                period_date=series.grid.date_at(index),
                period_end_date=series.grid.end_date_at(index),
                period_days=series.grid.length_days(index),
                demand=round_half_up(demand, decimals),
                lower=round_half_up(lower, decimals),
                upper=round_half_up(upper, decimals),
            )
        )
    return points


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------


def project_inventory(
    series: InventorySeries,
    points: list[ForecastPoint],
    sigma: float,
    config: InventoryConfig,
    as_of: date,
) -> ProjectionResult:
    """Walk the stock position forward day by day and derive the recommendations."""
    result = ProjectionResult(unscheduled_open_quantity=series.unscheduled_open_quantity)
    decimals = config.forecast.decimals

    result.health = _classify_stock(series, points, config)

    opening = series.closing_inventory
    if opening is None:
        result.available = False
        result.unavailable_reason = (
            "The file has no ending inventory for this material, so there is no stock position "
            "to project forward. The demand forecast and its accuracy are still reported."
        )
        result.reorder = _reorder_policy(series, points, sigma, config, as_of, None, None)
        return result

    result.opening_inventory = round_half_up(opening, decimals)
    result.opening_inventory_date = series.closing_inventory_date

    if not points:
        result.available = False
        result.unavailable_reason = "There is no demand forecast to project the stock against."
        return result

    receipts_by_date: dict[date, float] = {}
    for order in series.open_purchase_orders:
        if order.expected_date is not None:
            receipts_by_date[order.expected_date] = (
                receipts_by_date.get(order.expected_date, 0.0) + float(order.quantity)
            )
    result.scheduled_receipt_total = round_half_up(sum(receipts_by_date.values()), decimals)

    reorder = _reorder_policy(series, points, sigma, config, as_of, opening, receipts_by_date)
    safety_line = reorder.effective_safety_stock or 0.0

    # The reorder point is evaluated **forward from each day**, not once at the
    # start of the horizon. For a seasonal material the two differ enough to
    # matter: 21 days of cover in July is not 21 days of cover in November, and
    # a trigger set on July's demand fires far too late to protect November's.
    # ``calculated_reorder_point`` stays the static policy figure to compare
    # against the material master; the walk below uses the forward-looking one.
    daily_demand_rates = _daily_demand_rates(points)
    tail_rate = daily_demand_rates[-1] if daily_demand_rates else 0.0
    policy_safety = reorder.recommended_safety_stock or 0.0

    # The daily walk. Stock on hand answers "have I run out"; inventory position
    # - on hand plus what is still on order - answers "should I order".
    stock = float(opening)
    outstanding = float(sum(receipts_by_date.values()))
    lower_path = float(opening)
    upper_path = float(opening)

    shortage_date: date | None = None
    below_safety_date: date | None = None
    reorder_trigger_date: date | None = None
    position_at_trigger: float | None = None
    reorder_point_at_trigger: float | None = None
    minimum_stock = stock
    minimum_date = result.opening_inventory_date or as_of
    day_index = 0

    for point in points:
        period_opening = stock
        period_receipts = 0.0
        daily_demand = point.demand / point.period_days if point.period_days else point.demand
        daily_lower = (
            (point.lower or 0.0) / point.period_days if point.period_days else (point.lower or 0.0)
        )
        daily_upper = (
            (point.upper or 0.0) / point.period_days if point.period_days else (point.upper or 0.0)
        )

        for offset in range(point.period_days):
            day = point.period_date + timedelta(days=offset)
            arriving = receipts_by_date.get(day, 0.0)
            if arriving:
                stock += arriving
                lower_path += arriving
                upper_path += arriving
                outstanding -= arriving
                period_receipts += arriving

            stock -= daily_demand
            # The pessimistic stock path consumes the top of the demand interval.
            lower_path -= daily_upper
            upper_path -= daily_lower

            position = stock + max(0.0, outstanding)

            if reorder_trigger_date is None:
                cover_needed = _demand_over_next_days(
                    daily_demand_rates, day_index + 1, reorder.lead_time_days, tail_rate
                )
                dynamic_reorder_point = cover_needed + policy_safety
                if position <= dynamic_reorder_point:
                    reorder_trigger_date = day
                    position_at_trigger = position
                    reorder_point_at_trigger = dynamic_reorder_point
            day_index += 1
            if below_safety_date is None and safety_line > 0 and stock < safety_line:
                below_safety_date = day
            if shortage_date is None and stock < 0:
                shortage_date = day
            if stock < minimum_stock:
                minimum_stock = stock
                minimum_date = day

        result.periods.append(
            ProjectedPeriod(
                index=point.index,
                period_date=point.period_date,
                period_end_date=point.period_end_date,
                opening_inventory=round_half_up(period_opening, decimals),
                forecast_demand=point.demand,
                scheduled_receipts=round_half_up(period_receipts, decimals),
                projected_ending=round_half_up(stock, decimals),
                projected_ending_low=round_half_up(lower_path, decimals),
                projected_ending_high=round_half_up(upper_path, decimals),
                inventory_position=round_half_up(stock + max(0.0, outstanding), decimals),
                below_safety_stock=bool(safety_line > 0 and stock < safety_line),
                stockout=stock < 0,
                days_of_cover=_days_of_cover(stock, daily_demand),
            )
        )

    result.predicted_shortage_date = shortage_date
    result.predicted_below_safety_stock_date = below_safety_date
    result.minimum_projected_inventory = round_half_up(minimum_stock, decimals)
    result.minimum_projected_inventory_date = minimum_date
    result.ending_projected_inventory = result.periods[-1].projected_ending

    if shortage_date is not None:
        result.days_to_shortage = (shortage_date - as_of).days
        result.shortage_within_horizon = (
            result.days_to_shortage <= config.stock_health.shortage_horizon_days
        )

    reorder.reorder_point_at_trigger = (
        None
        if reorder_point_at_trigger is None
        else round_half_up(reorder_point_at_trigger, decimals)
    )
    _finalise_reorder(reorder, reorder_trigger_date, position_at_trigger, points, config, as_of)
    _check_expedite(reorder, shortage_date, receipts_by_date, result)
    result.reorder = reorder

    if series.unscheduled_open_quantity > 0:
        result.notes.append(
            f"{series.unscheduled_open_quantity:g} unit(s) are on order with no usable expected "
            "date (missing, or already in the past). They are excluded from the projected stock, "
            "so the projection is the more cautious of the two readings."
        )
    if series.missing_period_indexes:
        result.notes.append(
            f"{len(series.missing_period_indexes)} period(s) had no row in the file and were "
            f"treated as {config.period.missing_period_fill} demand before forecasting."
        )
    return result


def _daily_demand_rates(points: list[ForecastPoint]) -> list[float]:
    """Expand the per-period forecast into a per-calendar-day rate."""
    rates: list[float] = []
    for point in points:
        if point.period_days <= 0:
            continue
        rates.extend([point.demand / point.period_days] * point.period_days)
    return rates


def _demand_over_next_days(
    rates: list[float], start_index: int, days: int, tail_rate: float
) -> float:
    """Forecast demand over the ``days`` following ``start_index``.

    Beyond the end of the horizon the final period's daily rate is carried
    forward, so a lead time that runs past the last forecast period still
    produces a figure instead of silently shrinking to whatever is left.
    """
    if days <= 0:
        return 0.0
    end = start_index + days
    inside = rates[max(0, start_index) : min(end, len(rates))]
    total = sum(inside)
    if end > len(rates):
        total += tail_rate * (end - max(len(rates), start_index))
    return total


def _days_of_cover(stock: float, daily_demand: float) -> float | None:
    """How many days the stock lasts at the forecast rate."""
    if daily_demand <= 0:
        return None
    return round_half_up(max(0.0, stock) / daily_demand, 1)


# ---------------------------------------------------------------------------
# Reorder policy
# ---------------------------------------------------------------------------


def _reorder_policy(
    series: InventorySeries,
    points: list[ForecastPoint],
    sigma: float,
    config: InventoryConfig,
    as_of: date,
    opening: float | None,
    receipts_by_date: dict[date, float] | None,
) -> ReorderRecommendation:
    """Calculate safety stock and the reorder point.

    Safety stock covers demand variability over the lead time at the configured
    service level: ``z * sigma_period * sqrt(lead_time / period_length)``. The
    square root is the standard way to scale a per-period standard deviation to a
    lead time of a different length, and it assumes period-to-period demand
    errors are independent - which is the assumption stated on the output.
    """
    settings = config.reorder
    decimals = config.forecast.decimals

    lead_time = series.lead_time_days
    lead_time_source = "file"
    if lead_time is None or lead_time < 0:
        lead_time = settings.default_lead_time_days
        lead_time_source = "configuration default"

    period_days = series.grid.days or 1
    z_score = settings.z_for()

    if settings.safety_stock_basis == "demand_variation":
        sigma_period = _historic_sigma(series)
        basis_label = "variation in historical demand"
    else:
        sigma_period = float(sigma)
        basis_label = "the selected model's forecast error"

    lead_time_periods = lead_time / period_days if period_days else 0.0
    safety_stock = z_score * sigma_period * math.sqrt(max(0.0, lead_time_periods))
    safety_stock = round_half_up(max(0.0, safety_stock), decimals)

    lead_time_demand = _demand_over_days(points, as_of, lead_time, from_date=None)
    reorder_point = round_half_up((lead_time_demand or 0.0) + safety_stock, decimals)

    master_safety = series.safety_stock
    master_reorder = series.reorder_point
    effective_safety = (
        master_safety
        if settings.respect_master_safety_stock and master_safety is not None
        else safety_stock
    )

    recommendation = ReorderRecommendation(
        lead_time_days=int(lead_time),
        lead_time_source=lead_time_source,
        review_period_days=settings.review_period_days,
        service_level=settings.service_level,
        service_level_z=z_score,
        safety_stock_basis=settings.safety_stock_basis,
        demand_sigma_per_period=round_half_up(sigma_period, decimals),
        expected_lead_time_demand=(
            None if lead_time_demand is None else round_half_up(lead_time_demand, decimals)
        ),
        recommended_safety_stock=safety_stock,
        calculated_reorder_point=reorder_point,
        master_safety_stock=master_safety,
        master_reorder_point=master_reorder,
        effective_safety_stock=(
            None if effective_safety is None else round_half_up(effective_safety, decimals)
        ),
    )

    if master_safety is not None:
        recommendation.safety_stock_gap = round_half_up(safety_stock - master_safety, decimals)
    if master_reorder is not None:
        recommendation.reorder_point_gap = round_half_up(reorder_point - master_reorder, decimals)

    recommendation.rationale.append(
        f"Safety stock = z({settings.service_level:.0%}) {z_score:g} x {sigma_period:g} "
        f"(per-period sigma from {basis_label}) x sqrt({lead_time}/{period_days} periods of lead "
        f"time) = {safety_stock:g}."
    )
    recommendation.rationale.append(
        f"Reorder point = forecast demand over the {lead_time}-day lead time "
        f"({recommendation.expected_lead_time_demand}) + safety stock ({safety_stock:g}) "
        f"= {reorder_point:g}. This is the static figure to compare against the material "
        "master; the reorder date below is found with the demand expected over the lead time "
        "from that date, which differs whenever demand is seasonal or trending."
    )
    if lead_time_source != "file":
        recommendation.rationale.append(
            f"The file carries no lead time for this material, so the configured default of "
            f"{lead_time} days was used. Both figures move if the real lead time differs."
        )
    if settings.respect_master_safety_stock and master_safety is not None:
        recommendation.rationale.append(
            f"The projection's safety-stock line uses the {master_safety:g} held in the material "
            f"master, because that is what the business runs on today. The recommended "
            f"{safety_stock:g} is reported next to it for comparison."
        )
    if opening is None:
        recommendation.rationale.append(
            "No reorder date or quantity could be calculated: the file has no ending inventory "
            "for this material, so there is no stock position to trigger against."
        )
    return recommendation


def _finalise_reorder(
    recommendation: ReorderRecommendation,
    trigger_date: date | None,
    position_at_trigger: float | None,
    points: list[ForecastPoint],
    config: InventoryConfig,
    as_of: date,
) -> None:
    """Turn the reorder trigger found by the daily walk into a date and a quantity."""
    settings = config.reorder
    decimals = config.forecast.decimals

    if recommendation.calculated_reorder_point is None:
        return

    if trigger_date is None:
        recommendation.order_urgency = "not_required"
        recommendation.recommended_reorder_quantity = 0.0
        recommendation.rationale.append(
            "The projected inventory position stays above the reorder point for the whole "
            "horizon, so no replenishment order is needed inside it."
        )
        return

    # An inventory position already at or below the reorder point on the first
    # projected day means the trigger was passed before the horizon started.
    immediate = trigger_date <= as_of + timedelta(days=1)
    recommendation.recommended_reorder_date = max(trigger_date, as_of)
    recommendation.order_urgency = "immediate" if immediate else "scheduled"
    recommendation.inventory_position_at_reorder = (
        None if position_at_trigger is None else round_half_up(position_at_trigger, decimals)
    )

    if (
        recommendation.reorder_point_at_trigger is not None
        and recommendation.calculated_reorder_point is not None
        and abs(recommendation.reorder_point_at_trigger - recommendation.calculated_reorder_point)
        > 0.01
    ):
        recommendation.rationale.append(
            f"On {recommendation.recommended_reorder_date.isoformat()} the demand expected over "
            f"the following {recommendation.lead_time_days} days is different from today's, so "
            f"the reorder point that actually triggered was "
            f"{recommendation.reorder_point_at_trigger:g} rather than the static "
            f"{recommendation.calculated_reorder_point:g}."
        )

    cover_days = recommendation.lead_time_days + settings.review_period_days
    cover_demand = _demand_over_days(
        points, as_of, cover_days, from_date=recommendation.recommended_reorder_date
    ) or 0.0
    target = cover_demand + (recommendation.recommended_safety_stock or 0.0)
    recommendation.target_stock_level = round_half_up(target, decimals)

    raw_quantity = target - (position_at_trigger or 0.0)
    quantity = _round_up_to_multiple(max(0.0, raw_quantity), settings.rounding_multiple)
    if quantity > 0:
        quantity = max(quantity, settings.minimum_order_quantity)
        quantity = _round_up_to_multiple(quantity, settings.rounding_multiple)
    recommendation.recommended_reorder_quantity = round_half_up(quantity, decimals)

    recommendation.rationale.append(
        f"Order-up-to level = forecast demand over the {cover_days}-day cover window "
        f"(lead time {recommendation.lead_time_days} + review period "
        f"{settings.review_period_days}) of {round_half_up(cover_demand, decimals):g} + safety "
        f"stock {recommendation.recommended_safety_stock:g} = {recommendation.target_stock_level:g}."
    )
    recommendation.rationale.append(
        f"Recommended quantity = order-up-to level {recommendation.target_stock_level:g} - "
        f"projected inventory position {recommendation.inventory_position_at_reorder:g} on "
        f"{recommendation.recommended_reorder_date.isoformat()} = "
        f"{recommendation.recommended_reorder_quantity:g}"
        + (
            f", rounded up to a multiple of {settings.rounding_multiple:g}."
            if settings.rounding_multiple != 1
            else "."
        )
    )
    if immediate:
        recommendation.rationale.append(
            "The inventory position is already at or below the reorder point, so this order is "
            "due now rather than on a future date."
        )


def _check_expedite(
    recommendation: ReorderRecommendation,
    shortage_date: date | None,
    receipts_by_date: dict[date, float],
    result: ProjectionResult,
) -> None:
    """Flag the case where a new order cannot arrive in time to help.

    Ordering more is the wrong answer when the stock runs out *before* the
    reorder point is even reached. That happens for a real reason: quantity is
    already on order, so the inventory position stays healthy while the stock on
    hand does not - the delivery is simply expected too late. The action is to
    expedite the existing order, not to raise another one, and saying "reorder on
    the 10th" next to "you run out on the 14th" without explaining why would read
    as a contradiction.
    """
    if shortage_date is None:
        return

    reorder_date = recommendation.recommended_reorder_date
    if reorder_date is not None and reorder_date < shortage_date:
        return

    late_receipts = sorted(day for day in receipts_by_date if day >= shortage_date)
    if late_receipts:
        first = late_receipts[0]
        recommendation.expedite_recommended = True
        recommendation.expedite_reason = (
            f"Stock on hand runs out on {shortage_date.isoformat()}, but the next open purchase "
            f"order is not expected until {first.isoformat()}. Because that quantity already "
            "counts towards the inventory position, the reorder point is not reached first - so "
            "the action is to pull the existing order forward, not to raise another one."
        )
    else:
        recommendation.expedite_recommended = True
        recommendation.expedite_reason = (
            f"Stock on hand runs out on {shortage_date.isoformat()} before the projected "
            "inventory position reaches the reorder point. The reorder point is too low to "
            "protect this demand over the current lead time."
        )
    result.notes.append(recommendation.expedite_reason)


def _round_up_to_multiple(value: float, multiple: float) -> float:
    """Round an order quantity up to the next whole multiple."""
    if multiple <= 0:
        return value
    return math.ceil(value / multiple - 1e-9) * multiple


def _historic_sigma(series: InventorySeries) -> float:
    """Standard deviation of the historical demand per period."""
    values = series.demand_values
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)


def _demand_over_days(
    points: list[ForecastPoint],
    as_of: date,
    days: int,
    from_date: date | None,
) -> float | None:
    """Forecast demand over ``days`` calendar days starting at ``from_date``.

    Each period's forecast is spread evenly across that period's real calendar
    days. When the window runs past the end of the horizon, the daily rate of the
    final forecast period is carried forward and the caller is expected to say so
    - which the rationale does.
    """
    if not points or days <= 0:
        return 0.0 if points else None

    start = from_date or max(as_of, points[0].period_date)
    end = start + timedelta(days=days)
    total = 0.0

    for point in points:
        if point.period_days <= 0:
            continue
        daily = point.demand / point.period_days
        overlap_start = max(start, point.period_date)
        overlap_end = min(end, point.period_end_date + timedelta(days=1))
        overlap = (overlap_end - overlap_start).days
        if overlap > 0:
            total += daily * overlap

    last = points[-1]
    horizon_end = last.period_end_date + timedelta(days=1)
    if end > horizon_end and last.period_days > 0:
        total += (last.demand / last.period_days) * (end - horizon_end).days

    return total


# ---------------------------------------------------------------------------
# Stock health
# ---------------------------------------------------------------------------


def _classify_stock(
    series: InventorySeries, points: list[ForecastPoint], config: InventoryConfig
) -> StockHealth:
    """Classify movement, slow-moving status, dead stock and overstock risk."""
    settings = config.stock_health
    decimals = config.forecast.decimals
    health = StockHealth(overstock_threshold_days=settings.overstock_days_of_cover)

    values = series.demand_values
    if not values:
        health.movement_class = "no_data"
        return health

    zero_periods = sum(1 for value in values if value == 0)
    health.zero_demand_period_pct = round_half_up(zero_periods / len(values) * 100.0)

    trailing = 0
    for value in reversed(values):
        if value == 0:
            trailing += 1
        else:
            break
    health.trailing_zero_demand_periods = trailing

    # Annualised turnover over the most recent year of periods.
    per_year = series.grid.periods_per_year
    window = series.periods[-per_year:] if len(series.periods) > per_year else series.periods
    window_demand = sum(period.demand for period in window)
    inventories = [
        period.ending_inventory for period in window if period.ending_inventory is not None
    ]
    average_inventory = decimal_mean(inventories) if inventories else None
    health.average_inventory = average_inventory

    scale = per_year / len(window) if window else 1.0
    if average_inventory and average_inventory > 0:
        health.annual_turnover = round_half_up(window_demand * scale / average_inventory)

    stock_on_hand = series.closing_inventory
    daily_demand = _average_daily_forecast_demand(points)
    if stock_on_hand is not None and daily_demand and daily_demand > 0:
        health.days_of_cover = round_half_up(max(0.0, stock_on_hand) / daily_demand, 1)

    # Movement class. Turnover is the primary signal; when there is no usable
    # inventory history to divide by, the share of periods with no demand at all
    # is used instead, and the output says which one was applied.
    if health.annual_turnover is not None:
        turnover = health.annual_turnover
        if turnover >= settings.fast_moving_turnover:
            health.movement_class = "fast_moving"
        elif turnover >= settings.slow_moving_turnover:
            health.movement_class = "medium_moving"
        elif turnover >= settings.very_slow_turnover:
            health.movement_class = "slow_moving"
        else:
            health.movement_class = "very_slow_moving"
        health.classification_basis.append(
            f"Annualised turnover of {turnover:g} (demand over the last "
            f"{len(window)} period(s), scaled to a year, divided by average stock held)."
        )
    elif health.zero_demand_period_pct >= settings.slow_moving_zero_demand_pct:
        health.movement_class = "slow_moving"
        health.classification_basis.append(
            f"No usable stock history to compute turnover, so the classification uses the share "
            f"of periods with no demand at all ({health.zero_demand_period_pct:g}%)."
        )
    else:
        health.movement_class = "medium_moving"
        health.classification_basis.append(
            "No usable stock history to compute turnover; demand occurred in most periods, so "
            "the material is not treated as slow-moving."
        )

    health.is_slow_moving = health.movement_class in {"slow_moving", "very_slow_moving"} or (
        health.zero_demand_period_pct >= settings.slow_moving_zero_demand_pct
    )
    if (
        health.zero_demand_period_pct >= settings.slow_moving_zero_demand_pct
        and health.movement_class in {"fast_moving", "medium_moving"}
    ):
        health.classification_basis.append(
            f"Demand was zero in {health.zero_demand_period_pct:g}% of periods, above the "
            f"{settings.slow_moving_zero_demand_pct:g}% threshold, so the material is flagged as "
            "slow-moving despite its turnover."
        )

    has_stock = bool(stock_on_hand and stock_on_hand > 0)
    health.is_dead_stock = trailing >= settings.dead_stock_zero_demand_periods and (
        has_stock or not settings.dead_stock_requires_stock_on_hand
    )
    if health.is_dead_stock:
        health.classification_basis.append(
            f"No demand in the last {trailing} consecutive period(s), at or above the "
            f"{settings.dead_stock_zero_demand_periods}-period dead-stock threshold"
            + (f", with {stock_on_hand:g} unit(s) still on hand." if has_stock else ".")
        )

    # Overstock: measured in days of cover, and quantified as the quantity held
    # beyond the configured cover window plus safety stock.
    cover = health.days_of_cover
    if cover is None and stock_on_hand is not None and (not daily_demand or daily_demand <= 0):
        if stock_on_hand > 0:
            health.overstock_risk = "high"
            health.overstock_excess_quantity = round_half_up(stock_on_hand, decimals)
            health.classification_basis.append(
                "Forecast demand is zero for the whole horizon, so the stock on hand has no "
                "projected consumption at all."
            )
    elif cover is not None:
        if cover >= settings.critical_overstock_days_of_cover:
            health.overstock_risk = "high"
        elif cover >= settings.overstock_days_of_cover:
            health.overstock_risk = "medium"
        else:
            health.overstock_risk = "none"

        if health.overstock_risk != "none" and daily_demand:
            keep = daily_demand * settings.excess_cover_days + float(series.safety_stock or 0.0)
            excess = max(0.0, float(stock_on_hand or 0.0) - keep)
            health.overstock_excess_quantity = round_half_up(excess, decimals)
            health.classification_basis.append(
                f"{cover:g} days of cover at the forecast demand rate, against an overstock "
                f"threshold of {settings.overstock_days_of_cover:g} days. Excess is the stock "
                f"held beyond {settings.excess_cover_days:g} days of cover plus safety stock."
            )

    return health


def _average_daily_forecast_demand(points: list[ForecastPoint]) -> float | None:
    """Average forecast demand per calendar day across the horizon."""
    if not points:
        return None
    total_days = sum(point.period_days for point in points)
    if total_days <= 0:
        return None
    return sum(point.demand for point in points) / total_days
