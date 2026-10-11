# Vendored copy. Do not edit: edits are lost the next time the engine is
# copied. The original is src/hass_energy/billing/series.py, and
# scripts/vendor_billing.py keeps this in step with it.
"""Allocating a settlement to the hours it was earned in.

Annual netting has no true hourly cost: what a kWh was worth depends on what
the meters do for the rest of the period. The one allocation that is both
causal and reconciles is the change in the bill: the cost of an hour is the
bill after it less the bill before it. The hours sum to the invoice by
construction, a past hour moves only when the contract is re-valued, and an
hour in which export cancels earlier import is a negative cost, which is what
netting means.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, tzinfo

from .bill import Bill, MeterReadings, SettlementPeriod
from .engine import calculate
from .prices import PriceSchedule
from .terms import TariffTerms


@dataclass(frozen=True)
class Hour:
    """What the meters did in one hour."""

    #: The hour's start, timezone-aware.
    start: datetime
    imported_kwh: float = 0.0
    exported_kwh: float = 0.0

    def __post_init__(self) -> None:
        if self.start.tzinfo is None:
            raise ValueError("An hour needs a timezone-aware start.")
        if self.imported_kwh < 0 or self.exported_kwh < 0:
            raise ValueError("Meter quantities cannot be negative.")


@dataclass(frozen=True)
class HourCost:
    """How the bill moved over one hour."""

    start: datetime
    #: Change in the energy charge with VAT. Negative when export cancelled
    #: earlier import.
    grid_cost: float
    #: Change in what the supplier owes for surplus. Whole currency units,
    #: because the surplus is rounded per price period.
    compensation: int


def allocate(
    period: SettlementPeriod,
    hours: Sequence[Hour],
    schedule: PriceSchedule,
    terms: TariffTerms,
    *,
    standing_charge_months: int,
    tz: tzinfo,
) -> tuple[Bill, list[HourCost]]:
    """Settle a period hour by hour.

    Returns the bill after the last hour and the movement of the bill over
    each hour, in the order given. Hours are assigned to price periods by the
    local day they started on, which is how the invoice draws its boundaries.
    An hour outside the period is an error: the caller decides the period.
    """

    segments = schedule.segments(period.start, period.end)
    starts = [segment.start for segment in segments]
    imported = [0.0] * len(segments)
    exported = [0.0] * len(segments)
    total_imported = 0.0
    total_exported = 0.0

    def bill() -> Bill:
        return calculate(
            period,
            MeterReadings(total_imported, total_exported),
            schedule,
            terms,
            standing_charge_months=standing_charge_months,
            consumption_by_segment=imported,
            feed_in_by_segment=exported,
        )

    before = bill()
    costs: list[HourCost] = []
    for hour in hours:
        day = hour.start.astimezone(tz).date()
        if not period.start <= day < period.end:
            raise ValueError(f"The hour starting {hour.start} is outside the period.")
        index = bisect_right(starts, day) - 1
        imported[index] += hour.imported_kwh
        exported[index] += hour.exported_kwh
        total_imported += hour.imported_kwh
        total_exported += hour.exported_kwh

        after = bill()
        costs.append(
            HourCost(
                hour.start,
                after.energy_gross - before.energy_gross,
                after.surplus_net - before.surplus_net,
            )
        )
        before = after

    return before, costs
