"""Allocating the bill to hours."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from hass_energy.billing import (
    Hour,
    MeterReadings,
    Prices,
    PriceSchedule,
    SettlementMode,
    SettlementPeriod,
    TariffTerms,
    allocate,
    calculate,
    forint,
)

BUDAPEST = ZoneInfo("Europe/Budapest")
UTC = ZoneInfo("UTC")
PERIOD = SettlementPeriod(date(2025, 3, 1), date(2026, 3, 1))
SCHEDULE = PriceSchedule(
    [
        Prices(date(2025, 1, 1), subsidized=30.0, market=60.0, feed_in=5.0),
        Prices(date(2025, 8, 1), subsidized=40.0, market=80.0, feed_in=6.0),
    ]
)
TERMS = TariffTerms()


def hours(start: datetime, *quantities: tuple[float, float]) -> list[Hour]:
    return [
        Hour(start + timedelta(hours=i), imported_kwh=imported, exported_kwh=exported)
        for i, (imported, exported) in enumerate(quantities)
    ]


def test_the_hours_sum_to_the_bill() -> None:
    """Whatever the allocation says about an hour, the period reconciles."""

    series = hours(
        datetime(2025, 7, 31, 20, tzinfo=UTC),
        (3.0, 0.0),
        (0.0, 4.0),
        (0.0, 2.5),
        (1.5, 0.0),
        (0.0, 0.0),
        (2.0, 1.0),
    )

    bill, costs = allocate(
        PERIOD, series, SCHEDULE, TERMS, standing_charge_months=12, tz=BUDAPEST
    )

    assert bill.readings == MeterReadings(6.5, 7.5)
    assert sum(cost.grid_cost for cost in costs) == pytest.approx(bill.energy_gross)
    assert sum(cost.compensation for cost in costs) == bill.surplus_net
    assert [cost.start for cost in costs] == [hour.start for hour in series]


def test_export_that_cancels_earlier_import_is_a_negative_cost() -> None:
    series = hours(datetime(2025, 6, 1, 10, tzinfo=UTC), (10.0, 0.0), (0.0, 4.0))

    _, costs = allocate(PERIOD, series, SCHEDULE, TERMS, standing_charge_months=12, tz=BUDAPEST)

    assert costs[0].grid_cost == pytest.approx(10 * 30.0 * 1.27)
    assert costs[1].grid_cost == pytest.approx(-4 * 30.0 * 1.27)
    assert costs[1].compensation == 0


def test_surplus_beyond_netting_is_compensation() -> None:
    series = hours(datetime(2025, 6, 1, 10, tzinfo=UTC), (0.0, 100.0), (0.0, 100.0))

    bill, costs = allocate(
        PERIOD, series, SCHEDULE, TERMS, standing_charge_months=12, tz=BUDAPEST
    )

    assert [cost.grid_cost for cost in costs] == [0.0, 0.0]
    assert [cost.compensation for cost in costs] == [forint(500.0), forint(500.0)]
    assert bill.surplus_net == 1000


def test_an_hour_belongs_to_the_local_day_it_started_on() -> None:
    """22:00 UTC on 31 July is already 1 August in Budapest, and priced so."""

    series = hours(datetime(2025, 7, 31, 21, tzinfo=UTC), (1.0, 0.0), (1.0, 0.0))

    bill, costs = allocate(
        PERIOD, series, SCHEDULE, TERMS, standing_charge_months=12, tz=BUDAPEST
    )

    assert [round(line.unit_price) for line in bill.subsidized] == [30, 40]
    assert costs[0].grid_cost == pytest.approx(30.0 * 1.27)
    assert costs[1].grid_cost == pytest.approx(40.0 * 1.27)


def test_the_allocation_matches_a_direct_settlement() -> None:
    """Hour by hour or all at once, the same energy is the same bill."""

    series = hours(
        datetime(2025, 7, 31, 20, tzinfo=UTC),
        (300.0, 100.0),
        (200.0, 50.0),
        (0.0, 400.0),
        (100.0, 0.0),
    )
    terms = TariffTerms(mode=SettlementMode.BRUTTO)

    bill, _ = allocate(PERIOD, series, SCHEDULE, terms, standing_charge_months=12, tz=BUDAPEST)
    direct = calculate(
        PERIOD,
        MeterReadings(600.0, 550.0),
        SCHEDULE,
        terms,
        standing_charge_months=12,
        # The first two hours are still 31 July in Budapest.
        consumption_by_segment=[500.0, 100.0],
        feed_in_by_segment=[150.0, 400.0],
    )

    assert bill.energy_net == pytest.approx(direct.energy_net)
    assert bill.surplus_net == direct.surplus_net


def test_no_hours_is_a_bill_for_the_standing_charge_alone() -> None:
    bill, costs = allocate(PERIOD, [], SCHEDULE, TERMS, standing_charge_months=12, tz=BUDAPEST)

    assert costs == []
    assert bill.energy_net == 0
    assert bill.gross_total == 1836


def test_an_hour_outside_the_period_is_refused() -> None:
    series = hours(datetime(2026, 3, 1, 10, tzinfo=UTC), (1.0, 0.0))

    with pytest.raises(ValueError, match="outside the period"):
        allocate(PERIOD, series, SCHEDULE, TERMS, standing_charge_months=12, tz=BUDAPEST)


def test_an_hour_needs_a_timezone() -> None:
    with pytest.raises(ValueError, match="timezone"):
        Hour(datetime(2025, 6, 1, 10))
