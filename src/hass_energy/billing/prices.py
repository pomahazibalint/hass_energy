"""Prices and the periods they are valid for.

Prices change during a settlement period — the residential market price is set
quarterly by the regulator — and the bill apportions quantities across the
periods in which each price applied. A single price per settlement period
cannot express that, so prices are held as a dated schedule.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Prices:
    """The prices in force from one date until the next change.

    All are net of VAT, in the billing currency per kWh, matching how a
    Hungarian invoice states unit prices.
    """

    valid_from: date
    #: Price up to the subsidized allowance (rezsicsökkentett ár).
    subsidized: float
    #: Price above the allowance (lakossági piaci ár), set quarterly by MEKH.
    market: float
    #: Paid by the supplier for feed-in beyond what netting absorbs. This is
    #: the energy component of the tariff alone, not the retail price, which is
    #: why it is roughly a seventh of what the same kWh costs to buy back.
    feed_in: float

    def __post_init__(self) -> None:
        for name in ("subsidized", "market", "feed_in"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} price cannot be negative")


@dataclass(frozen=True)
class Segment:
    """A stretch of a settlement period over which one set of prices applied."""

    start: date
    end: date
    prices: Prices

    @property
    def days(self) -> int:
        return (self.end - self.start).days


class PriceSchedule:
    """Prices over time, newest change last."""

    def __init__(self, prices: list[Prices] | tuple[Prices, ...]) -> None:
        if not prices:
            raise ValueError("A price schedule needs at least one entry.")
        ordered = sorted(prices, key=lambda p: p.valid_from)
        starts = [p.valid_from for p in ordered]
        if len(set(starts)) != len(starts):
            raise ValueError("Two prices cannot take effect on the same day.")
        self._prices = tuple(ordered)

    @property
    def entries(self) -> tuple[Prices, ...]:
        return self._prices

    def at(self, day: date) -> Prices:
        """The prices in force on a given day."""

        applicable = [p for p in self._prices if p.valid_from <= day]
        if not applicable:
            raise ValueError(
                f"No prices are known for {day}; the schedule starts "
                f"{self._prices[0].valid_from}."
            )
        return applicable[-1]

    def segments(self, start: date, end: date) -> tuple[Segment, ...]:
        """Split a period at every price change inside it.

        A change is a boundary whether or not the numbers actually moved: the
        invoice splits on the price period, and reproducing it means splitting
        the same way.
        """

        if end <= start:
            raise ValueError("A settlement period must end after it starts.")

        boundaries = [start]
        boundaries += [p.valid_from for p in self._prices if start < p.valid_from < end]
        boundaries.append(end)

        return tuple(
            Segment(boundaries[i], boundaries[i + 1], self.at(boundaries[i]))
            for i in range(len(boundaries) - 1)
        )
