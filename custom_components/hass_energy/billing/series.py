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

The same walk answers a second question that does not reconcile: what an
hour would have saved had the meters done something else in it. That is a
marginal measure, chronological like the first, and it is what the cost of
consuming in a given hour means to the household.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, tzinfo

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
    #: Subsidized energy still to be had after the hour, on the hour's own
    #: side of 1 August. Under szaldó it can grow again, when export cancels
    #: import that had used it.
    allowance_remaining_kwh: float = 0.0
    #: When the hour's allowance year ends, which is when what it leaves
    #: unused is lost.
    side_end: date | None = None


class _Ledger:
    """The period's quantities so far, by price period, and the bill they make.

    Hours are assigned to price periods by the local day they started on,
    which is how the invoice draws its boundaries. An hour outside the period
    is an error: the caller decides the period.
    """

    def __init__(
        self,
        period: SettlementPeriod,
        schedule: PriceSchedule,
        terms: TariffTerms,
        standing_charge_months: int,
        tz: tzinfo,
    ) -> None:
        self._period = period
        self._schedule = schedule
        self._terms = terms
        self._months = standing_charge_months
        self._tz = tz
        segments = schedule.segments(period.start, period.end)
        self._starts = [segment.start for segment in segments]
        self.imported = [0.0] * len(segments)
        self.exported = [0.0] * len(segments)
        #: The local day of the latest hour added: what the bill is as of.
        self.as_of: date | None = None

    def index(self, hour: Hour) -> int:
        day = hour.start.astimezone(self._tz).date()
        if not self._period.start <= day < self._period.end:
            raise ValueError(f"The hour starting {hour.start} is outside the period.")
        return bisect_right(self._starts, day) - 1

    def add(self, hour: Hour) -> None:
        index = self.index(hour)
        self.imported[index] += hour.imported_kwh
        self.exported[index] += hour.exported_kwh
        day = hour.start.astimezone(self._tz).date()
        self.as_of = day if self.as_of is None else max(self.as_of, day)

    def bill(self, extra: Hour | None = None) -> Bill:
        """The bill over everything added so far, plus one hour not yet added."""

        imported = list(self.imported)
        exported = list(self.exported)
        as_of = self.as_of
        if extra is not None:
            index = self.index(extra)
            imported[index] += extra.imported_kwh
            exported[index] += extra.exported_kwh
            day = extra.start.astimezone(self._tz).date()
            as_of = day if as_of is None else max(as_of, day)
        return calculate(
            self._period,
            MeterReadings(sum(imported), sum(exported)),
            self._schedule,
            self._terms,
            standing_charge_months=self._months,
            consumption_by_segment=imported,
            feed_in_by_segment=exported,
            as_of=as_of,
        )


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
    each hour, in the order given.
    """

    ledger = _Ledger(period, schedule, terms, standing_charge_months, tz)
    before = ledger.bill()
    costs: list[HourCost] = []
    for hour in hours:
        ledger.add(hour)
        after = ledger.bill()
        day = hour.start.astimezone(tz).date()
        side = after.side_on(day)
        costs.append(
            HourCost(
                hour.start,
                after.energy_gross - before.energy_gross,
                after.surplus_net - before.surplus_net,
                after.allowance_remaining_on(day),
                side.end if side else None,
            )
        )
        before = after

    return before, costs


def settle(
    period: SettlementPeriod,
    hours: Sequence[Hour],
    schedule: PriceSchedule,
    terms: TariffTerms,
    *,
    standing_charge_months: int,
    tz: tzinfo,
) -> Bill:
    """The bill after every hour, without the walk.

    What ``allocate`` returns first, for a caller that wants only the end:
    the hours are added to the ledger and billed once.
    """

    ledger = _Ledger(period, schedule, terms, standing_charge_months, tz)
    for hour in hours:
        ledger.add(hour)
    return ledger.bill()


def _position(bill: Bill) -> float:
    """The energy charge less the surplus, before the surplus is rounded.

    A running figure whose hourly differences are what matter, so the
    per-line rounding of the invoice would only lose the small hours.
    """

    return bill.energy_gross - bill.surplus_exact


def marginal(
    period: SettlementPeriod,
    hours: Sequence[Hour],
    instead: Sequence[Hour],
    schedule: PriceSchedule,
    terms: TariffTerms,
    *,
    standing_charge_months: int,
    tz: tzinfo,
) -> list[float]:
    """What each hour cost over what it would have cost had the meters done
    ``instead`` in that hour alone, with every earlier hour as it was.

    Chronological like ``allocate``: an hour's figure uses only the hours up
    to it, so a past hour does not move when later hours arrive. Unlike
    ``allocate`` it does not sum to anything; it answers what each hour was
    worth not having.
    """

    if len(hours) != len(instead):
        raise ValueError("Every hour needs an alternative.")
    ledger = _Ledger(period, schedule, terms, standing_charge_months, tz)
    savings: list[float] = []
    for hour, other in zip(hours, instead, strict=True):
        if other.start != hour.start:
            raise ValueError(f"The alternative for {hour.start} is for {other.start}.")
        without = ledger.bill(other)
        ledger.add(hour)
        savings.append(_position(ledger.bill()) - _position(without))
    return savings
