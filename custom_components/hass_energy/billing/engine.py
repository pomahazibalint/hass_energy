# Vendored copy. Do not edit: edits are lost the next time the engine is
# copied. The original is src/hass_energy/billing/engine.py, and
# scripts/vendor_billing.py keeps this in step with it.
"""Turning meter readings into a settlement."""

from __future__ import annotations

from collections.abc import Sequence

from .bill import Bill, Line, MeterReadings, SettlementPeriod, SurplusLine
from .prices import PriceSchedule, Segment
from .terms import AllowanceBasis, SettlementMode, TariffTerms


def _share_by_days(total: float, segments: Sequence[Segment]) -> list[float]:
    """Spread a quantity across segments in proportion to their length.

    A fallback. The invoices behind this model do not split this way — their
    split follows metered or profiled quantities, which is why the surplus
    lands 89% in the longer segment where a day split gives 88%. Pass the real
    per-segment quantities whenever they are known.
    """

    days = sum(segment.days for segment in segments)
    if days == 0:
        return [0.0 for _ in segments]
    return [total * segment.days / days for segment in segments]


def _allocate(
    total: float, segments: Sequence[Segment], shape: Sequence[float] | None
) -> list[float]:
    """Spread a settled quantity across segments in the proportions of a shape.

    The shape is what the meters recorded per segment. It is a proportion, not
    the quantity itself: netting decides how much is billed or bought over the
    whole period, and that total is then divided in the shape's proportions.
    Passing the recorded quantities straight through would make the lines
    disagree with the settled total whenever the two differ, which under gross
    settlement they always do.
    """

    if shape is None:
        return _share_by_days(total, segments)
    if len(shape) != len(segments):
        raise ValueError(
            f"Expected {len(segments)} per-segment quantities, got {len(shape)}."
        )
    if any(quantity < 0 for quantity in shape):
        raise ValueError("Per-segment quantities cannot be negative.")
    recorded = sum(shape)
    if not recorded:
        return _share_by_days(total, segments)
    return [total * quantity / recorded for quantity in shape]


def _bands(
    billed_kwh: float, allowance_kwh: float, allowance_used_elsewhere: float
) -> tuple[float, float]:
    """Split billed energy into the subsidized and market bands.

    ``allowance_used_elsewhere`` is what has already eaten into the allowance
    before the billed quantity is reached, which is how the gross basis leaves
    a heavy consumer with nothing left for its netted consumption.
    """

    remaining = max(allowance_kwh - allowance_used_elsewhere, 0.0)
    subsidized = min(billed_kwh, remaining)
    return subsidized, billed_kwh - subsidized


def calculate(
    period: SettlementPeriod,
    readings: MeterReadings,
    schedule: PriceSchedule,
    terms: TariffTerms,
    *,
    standing_charge_months: int,
    consumption_by_segment: Sequence[float] | None = None,
    feed_in_by_segment: Sequence[float] | None = None,
) -> Bill:
    """Settle one period.

    ``standing_charge_months`` is taken rather than derived: both reference
    invoices charge twelve months over periods of 359 and 368 days, so the
    count follows the supplier's billing months and not the calendar.

    ``consumption_by_segment`` and ``feed_in_by_segment`` give the shape of
    withdrawal and feed-in across the price periods, one figure per segment.
    Only their proportions matter: the billed and bought totals come from
    netting, and the shape says where in the period each fell. Without them the
    split falls back to days.
    """

    if standing_charge_months < 0:
        raise ValueError("Standing charge months cannot be negative.")

    segments = schedule.segments(period.start, period.end)

    if terms.mode is SettlementMode.SZALDO:
        billed_kwh = max(readings.imported_kwh - readings.exported_kwh, 0.0)
        surplus_kwh = max(readings.exported_kwh - readings.imported_kwh, 0.0)
    else:
        # Gross: everything withdrawn is billed and everything fed in is bought.
        billed_kwh = readings.imported_kwh
        surplus_kwh = readings.exported_kwh

    allowance_kwh = terms.allowance_for(period.days)
    used_elsewhere = (
        readings.imported_kwh - billed_kwh
        if terms.allowance_basis is AllowanceBasis.GROSS
        else 0.0
    )
    subsidized_kwh, market_kwh = _bands(billed_kwh, allowance_kwh, used_elsewhere)

    consumption = _allocate(billed_kwh, segments, consumption_by_segment)
    feed_in = _allocate(surplus_kwh, segments, feed_in_by_segment)

    # Each band is spread across the price periods in proportion to how much
    # energy was billed in each, then priced at the rate in force there.
    subsidized_lines: list[Line] = []
    market_lines: list[Line] = []
    for segment, quantity in zip(segments, consumption, strict=True):
        share = quantity / billed_kwh if billed_kwh else 0.0
        for band_kwh, prices, lines in (
            (subsidized_kwh, segment.prices.subsidized, subsidized_lines),
            (market_kwh, segment.prices.market, market_lines),
        ):
            if band_kwh * share:
                lines.append(Line(segment.start, segment.end, band_kwh * share, prices))

    surplus_lines = tuple(
        SurplusLine(segment.start, segment.end, quantity, segment.prices.feed_in)
        for segment, quantity in zip(segments, feed_in, strict=True)
        if quantity
    )

    return Bill(
        period=period,
        readings=readings,
        billed_kwh=billed_kwh,
        allowance_kwh=allowance_kwh,
        allowance_used_kwh=used_elsewhere + subsidized_kwh,
        subsidized=tuple(subsidized_lines),
        market=tuple(market_lines),
        standing_charge_months=standing_charge_months,
        standing_charge_net=standing_charge_months * terms.standing_charge_per_month,
        vat_percent=terms.vat_percent,
        surplus_kwh=surplus_kwh,
        surplus=surplus_lines,
    )
