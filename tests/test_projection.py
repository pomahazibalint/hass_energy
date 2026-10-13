"""Where the period is heading, following last year's shape."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from hass_energy.billing import (
    Day,
    Hour,
    Prices,
    PriceSchedule,
    SettlementPeriod,
    TariffTerms,
    a_year_before,
    allocate,
    allowance_runs_out,
    hours_of,
    project,
)

BUDAPEST = ZoneInfo("Europe/Budapest")
PERIOD = SettlementPeriod(date(2025, 3, 1), date(2026, 3, 1))
SCHEDULE = PriceSchedule([Prices(date(2025, 1, 1), subsidized=30.0, market=60.0, feed_in=5.0)])
RATE = Day(date(2025, 6, 10), imported_kwh=10.0, exported_kwh=2.0)


def days(
    start: date, imported: list[float], exported: list[float] | None = None
) -> dict[date, Day]:
    exported = exported or [0.0] * len(imported)
    return {
        start + timedelta(days=i): Day(start + timedelta(days=i), kwh_in, kwh_out)
        for i, (kwh_in, kwh_out) in enumerate(zip(imported, exported, strict=True))
    }


def test_a_year_before_is_the_same_calendar_day() -> None:
    assert a_year_before(date(2026, 6, 10)) == date(2025, 6, 10)
    assert a_year_before(date(2028, 2, 29)) == date(2027, 2, 28)


def test_remaining_days_follow_last_years_shape_at_this_years_scale() -> None:
    """This period runs at twice last year's rate over the days they share."""

    so_far = days(date(2025, 6, 1), [20.0, 20.0])
    last_year = days(date(2024, 6, 1), [10.0, 10.0, 5.0, 15.0])

    projected = project([(date(2025, 6, 3), 1.0), (date(2025, 6, 4), 1.0)], so_far, last_year, RATE)

    assert [day.imported_kwh for day in projected] == pytest.approx([10.0, 30.0])


def test_today_is_the_fraction_of_it_still_to_come() -> None:
    so_far = days(date(2025, 6, 1), [10.0])
    last_year = days(date(2024, 6, 1), [10.0, 8.0])

    projected = project([(date(2025, 6, 2), 0.25)], so_far, last_year, RATE)

    assert projected[0].imported_kwh == pytest.approx(2.0)


def test_a_day_last_year_knows_nothing_about_is_the_straight_line() -> None:
    so_far = days(date(2025, 6, 1), [20.0])
    last_year = days(date(2024, 6, 1), [10.0])

    projected = project([(date(2025, 6, 2), 1.0), (date(2025, 6, 3), 0.5)], so_far, last_year, RATE)

    assert [day.imported_kwh for day in projected] == pytest.approx([10.0, 5.0])
    assert [day.exported_kwh for day in projected] == pytest.approx([2.0, 1.0])


def test_a_first_year_is_the_straight_line_throughout() -> None:
    so_far = days(date(2025, 6, 1), [20.0])

    projected = project([(date(2025, 6, 2), 1.0)], so_far, {}, RATE)

    assert projected == [Day(date(2025, 6, 2), 10.0, 2.0)]


def test_each_meter_is_scaled_on_its_own() -> None:
    """New panels: import scales from last year, export has nothing to scale from."""

    so_far = days(date(2025, 6, 1), [5.0], [3.0])
    last_year = days(date(2024, 6, 1), [10.0, 10.0], [0.0, 4.0])

    projected = project([(date(2025, 6, 2), 1.0)], so_far, last_year, RATE)

    assert projected[0].imported_kwh == pytest.approx(5.0)
    assert projected[0].exported_kwh == pytest.approx(RATE.exported_kwh)


def test_projected_days_settle_as_hours_on_their_local_day() -> None:
    hours = hours_of([Day(date(2025, 6, 2), 3.0, 1.0)], BUDAPEST)

    assert hours == [
        Hour(datetime(2025, 6, 2, tzinfo=BUDAPEST), imported_kwh=3.0, exported_kwh=1.0)
    ]


def test_the_allowance_runs_out_when_it_is_gone_for_good() -> None:
    """Export can restore allowance under szaldó, so it is the last time it hits zero."""

    terms = TariffTerms(annual_allowance_kwh=365.0)
    hours = hours_of(
        [
            Day(date(2025, 3, 1), imported_kwh=400.0),
            Day(date(2025, 3, 2), exported_kwh=100.0),
            Day(date(2025, 3, 3), imported_kwh=200.0),
            Day(date(2025, 3, 4), imported_kwh=10.0),
        ],
        BUDAPEST,
    )
    _, costs = allocate(PERIOD, hours, SCHEDULE, terms, standing_charge_months=12, tz=BUDAPEST)

    assert costs[0].allowance_remaining_kwh == 0.0
    assert costs[1].allowance_remaining_kwh == pytest.approx(65.0)
    assert allowance_runs_out(costs) == hours[2].start


def test_an_allowance_that_holds_runs_out_never() -> None:
    hours = hours_of([Day(date(2025, 3, 1), imported_kwh=5.0)], BUDAPEST)
    _, costs = allocate(
        PERIOD, hours, SCHEDULE, TariffTerms(), standing_charge_months=12, tz=BUDAPEST
    )

    assert allowance_runs_out(costs) is None
    assert allowance_runs_out([]) is None


def test_a_day_cannot_be_negative() -> None:
    with pytest.raises(ValueError):
        Day(date(2025, 6, 1), imported_kwh=-1.0)
