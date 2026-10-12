"""What the house did with its energy, and what the panels were worth."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from hass_energy.billing import (
    Flows,
    MeterReadings,
    Prices,
    PriceSchedule,
    SettlementMode,
    SettlementPeriod,
    TariffTerms,
    allocate,
    calculate,
    solar_value,
)

BUDAPEST = ZoneInfo("Europe/Budapest")
UTC = ZoneInfo("UTC")
PERIOD = SettlementPeriod(date(2025, 3, 1), date(2026, 3, 1))
SCHEDULE = PriceSchedule([Prices(date(2025, 1, 1), subsidized=30.0, market=60.0, feed_in=5.0)])
TERMS = TariffTerms()
START = datetime(2025, 6, 1, 10, tzinfo=UTC)


def flows(*hours: dict[str, float]) -> list[Flows]:
    return [Flows(START + timedelta(hours=i), **hour) for i, hour in enumerate(hours)]


def test_consumption_is_what_entered_less_what_left() -> None:
    hour = Flows(START, imported_kwh=1.0, exported_kwh=2.0, produced_kwh=4.0)

    assert hour.consumption_kwh == pytest.approx(3.0)
    assert hour.shortfall_kwh == 0.0


def test_a_battery_moves_energy_between_hours() -> None:
    charging = Flows(START, produced_kwh=3.0, charged_kwh=2.0)
    discharging = Flows(START, discharged_kwh=2.0)

    assert charging.consumption_kwh == pytest.approx(1.0)
    assert discharging.consumption_kwh == pytest.approx(2.0)


def test_energy_that_left_without_entering_is_a_shortfall() -> None:
    """A source reporting in the wrong hour shows as an impossible balance."""

    hour = Flows(START, imported_kwh=0.5, exported_kwh=2.0)

    assert hour.consumption_kwh == 0.0
    assert hour.shortfall_kwh == pytest.approx(1.5)


def test_solar_kept_is_production_not_exported() -> None:
    assert Flows(START, produced_kwh=4.0, exported_kwh=1.0).solar_kept_kwh == pytest.approx(3.0)
    assert Flows(START, produced_kwh=1.0, exported_kwh=4.0).solar_kept_kwh == 0.0


def test_without_panels_what_they_supplied_comes_from_the_grid() -> None:
    hour = Flows(START, imported_kwh=1.0, exported_kwh=2.0, produced_kwh=5.0)
    without = hour.without_solar()

    assert without.imported_kwh == pytest.approx(4.0)
    assert without.exported_kwh == 0.0


def test_without_panels_only_export_they_could_not_have_made_remains() -> None:
    """A battery sending power out is export whether or not there are panels."""

    hour = Flows(START, exported_kwh=3.0, produced_kwh=1.0, discharged_kwh=2.0)

    assert hour.without_solar().exported_kwh == pytest.approx(2.0)


def test_the_hourly_values_sum_to_the_bill_without_the_panels() -> None:
    series = flows(
        {"imported_kwh": 2.0, "produced_kwh": 1.0},
        {"imported_kwh": 0.0, "exported_kwh": 3.0, "produced_kwh": 5.0},
        {"imported_kwh": 4.0},
    )
    kwargs = dict(standing_charge_months=12, tz=BUDAPEST)
    bill, costs = allocate(PERIOD, series, SCHEDULE, TERMS, **kwargs)
    bill_without, costs_without = allocate(
        PERIOD, [hour.without_solar() for hour in series], SCHEDULE, TERMS, **kwargs
    )
    hourly = solar_value(costs, costs_without)

    assert sum(hourly) == pytest.approx(bill_without.net_position - bill.net_position, abs=1)
    assert bill_without.net_position > bill.net_position


def test_the_panels_are_worth_what_they_saved_under_each_mode() -> None:
    """Under szaldó a kept kWh is worth the band price; under gross the same.

    The difference between the modes is export: netted against import under
    szaldó, bought at the feed-in price under gross.
    """

    series = flows({"imported_kwh": 10.0, "exported_kwh": 4.0, "produced_kwh": 7.0})
    kwargs = dict(standing_charge_months=12, tz=BUDAPEST)
    for mode in SettlementMode:
        terms = TariffTerms(mode=mode)
        bill, costs = allocate(PERIOD, series, SCHEDULE, terms, **kwargs)
        bill_without, costs_without = allocate(
            PERIOD, [hour.without_solar() for hour in series], SCHEDULE, terms, **kwargs
        )
        direct = calculate(
            PERIOD, MeterReadings(13.0, 0.0), SCHEDULE, terms, standing_charge_months=12
        )
        assert bill_without.net_position == direct.net_position
        assert sum(solar_value(costs, costs_without)) == pytest.approx(
            bill_without.net_position - bill.net_position, abs=1
        )


def test_no_panels_are_worth_nothing() -> None:
    series = flows({"imported_kwh": 2.0}, {"imported_kwh": 3.0, "exported_kwh": 0.0})
    kwargs = dict(standing_charge_months=12, tz=BUDAPEST)
    _, costs = allocate(PERIOD, series, SCHEDULE, TERMS, **kwargs)
    _, costs_without = allocate(
        PERIOD, [hour.without_solar() for hour in series], SCHEDULE, TERMS, **kwargs
    )

    assert solar_value(costs, costs_without) == [0.0, 0.0]


def test_the_two_allocations_must_cover_the_same_hours() -> None:
    series = flows({"imported_kwh": 2.0})
    kwargs = dict(standing_charge_months=12, tz=BUDAPEST)
    _, costs = allocate(PERIOD, series, SCHEDULE, TERMS, **kwargs)

    with pytest.raises(ValueError):
        solar_value(costs, [])


def test_flows_cannot_be_negative() -> None:
    with pytest.raises(ValueError):
        Flows(START, produced_kwh=-1.0)
