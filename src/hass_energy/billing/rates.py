"""What price an hour's consumption was worth.

The cost of consuming in an hour is a marginal figure, the bill's movement
had nothing been consumed, and it comes out of the engine as one number.
Divided by the hour's consumption it is a rate, and the rate is almost always
one of the prices in force that day: the subsidized price with VAT while the
allowance lasts and a kWh would net, the market price with VAT once it has
run out, the feed-in price once the period is in surplus or, under gross
settlement, for what the panels supplied. An hour that straddles two is
mixed. Naming the rate is what lets a figure explain itself: so many kWh at
this price, so many at that.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import tzinfo
from enum import StrEnum

from .flows import Flows
from .prices import Prices, PriceSchedule
from .terms import TariffTerms


class Rate(StrEnum):
    """The price an hour's consumption was worth, per kWh."""

    SUBSIDIZED = "subsidized"
    MARKET = "market"
    FEED_IN = "feed_in"
    MIXED = "mixed"
    #: Nothing was consumed, so there was no rate.
    NONE = "none"


#: Two rates closer than this are the same rate. The engine's hourly figures
#: carry rounding from the invoice's per-line split, never more than this.
TOLERANCE = 0.02


def rate_of(consumption_kwh: float, cost: float, prices: Prices, vat_percent: float) -> Rate:
    """Which price in force the hour's cost per kWh is."""

    if consumption_kwh <= 0:
        return Rate.NONE
    implied = cost / consumption_kwh
    with_vat = 1 + vat_percent / 100
    for rate, price in (
        (Rate.SUBSIDIZED, prices.subsidized * with_vat),
        (Rate.MARKET, prices.market * with_vat),
        (Rate.FEED_IN, prices.feed_in),
    ):
        if abs(implied - price) <= max(price, 1.0) * TOLERANCE:
            return rate
    return Rate.MIXED


def rates(
    hours: Sequence[Flows],
    costs: Sequence[float],
    schedule: PriceSchedule,
    terms: TariffTerms,
    tz: tzinfo,
) -> list[Rate]:
    """The rate of each hour, against the prices of its local day."""

    if len(hours) != len(costs):
        raise ValueError("Every hour needs its cost.")
    return [
        rate_of(
            hour.consumption_kwh,
            cost,
            schedule.at(hour.start.astimezone(tz).date()),
            terms.vat_percent,
        )
        for hour, cost in zip(hours, costs, strict=True)
    ]
