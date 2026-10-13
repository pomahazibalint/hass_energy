# Vendored copy. Do not edit: edits are lost the next time the engine is
# copied. The original is src/hass_energy/billing/projection.py, and
# scripts/vendor_billing.py keeps this in step with it.
"""Where the period is heading, following last year's shape.

A straight line from the rate so far is least reliable early in the period
and across a change of season, which is when the question matters most. The
same calendar days a year earlier know the shape; this period so far knows
the scale. Each remaining day is last year's day scaled by the ratio of this
period to the same days last year, and a day last year knows nothing about
falls back to the straight line, so a household in its first year gets the
straight line and nothing worse.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, tzinfo

from .series import Hour, HourCost


@dataclass(frozen=True)
class Day:
    """What the meters did on one local day."""

    day: date
    imported_kwh: float = 0.0
    exported_kwh: float = 0.0

    def __post_init__(self) -> None:
        if self.imported_kwh < 0 or self.exported_kwh < 0:
            raise ValueError("Meter quantities cannot be negative.")


def a_year_before(day: date) -> date:
    """The same calendar day a year earlier; 29 February looks at the 28th."""

    try:
        return day.replace(year=day.year - 1)
    except ValueError:
        return day.replace(year=day.year - 1, day=28)


#: One meter's quantity of a day.
Meter = Callable[[Day], float]
IMPORTED: Meter = lambda day: day.imported_kwh  # noqa: E731
EXPORTED: Meter = lambda day: day.exported_kwh  # noqa: E731


def _ratio(so_far: Mapping[date, Day], last_year: Mapping[date, Day], meter: Meter) -> float | None:
    """This period so far over the same days last year, for one meter.

    Over the days both know; None when they share none, or last year's
    were nothing, since nothing scales from zero.
    """

    shared = [day for day in so_far if a_year_before(day) in last_year]
    if not shared:
        return None
    then = sum(meter(last_year[a_year_before(day)]) for day in shared)
    if not then:
        return None
    now = sum(meter(so_far[day]) for day in shared)
    return now / then


def project(
    remaining: Sequence[tuple[date, float]],
    so_far: Mapping[date, Day],
    last_year: Mapping[date, Day],
    rate: Day,
) -> list[Day]:
    """What the remaining days will do.

    ``remaining`` is each day still to come and how much of it is: today
    is a fraction, the rest whole. ``so_far`` is this period's complete days
    as observed, ``last_year`` the days a year earlier, and ``rate`` the
    straight-line day of this period, used wherever last year is silent. Each
    meter is scaled on its own: a household whose panels are new has import
    to scale and no export to scale from.
    """

    scale = {meter: _ratio(so_far, last_year, meter) for meter in (IMPORTED, EXPORTED)}

    def projected(day: date, fraction: float, meter: Meter) -> float:
        then = last_year.get(a_year_before(day))
        factor = scale[meter]
        if then is None or factor is None:
            return meter(rate) * fraction
        return meter(then) * factor * fraction

    return [
        Day(
            day,
            imported_kwh=projected(day, fraction, IMPORTED),
            exported_kwh=projected(day, fraction, EXPORTED),
        )
        for day, fraction in remaining
    ]


def hours_of(days: Iterable[Day], tz: tzinfo) -> list[Hour]:
    """Projected days as the hours the engine settles.

    One per day, at the day's start: the allocation assigns an hour to a
    price period by its local day, and a day's shape within itself is not
    projected.
    """

    return [
        Hour(
            datetime.combine(one.day, time.min, tzinfo=tz),
            imported_kwh=one.imported_kwh,
            exported_kwh=one.exported_kwh,
        )
        for one in days
    ]


def allowance_runs_out(costs: Sequence[HourCost]) -> datetime | None:
    """When the allowance is gone for good, or None if it never is.

    Under szaldó export can restore allowance that earlier import used, so
    the hour it first reaches zero is not the answer; the hour after the
    last one with any left is.
    """

    if not costs or costs[-1].allowance_remaining_kwh > 0:
        return None
    for i in range(len(costs) - 1, -1, -1):
        if costs[i].allowance_remaining_kwh > 0:
            return costs[i + 1].start
    return costs[0].start
