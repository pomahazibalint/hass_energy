"""What the house did with its energy, what the panels were worth, and what consuming cost."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from hass_energy.billing import (
    Bill,
    Flows,
    Hour,
    HourCost,
    MeterReadings,
    Prices,
    PriceSchedule,
    SettlementMode,
    SettlementPeriod,
    TariffTerms,
    allocate,
    calculate,
    device_share,
    marginal,
    settle,
    solar_value,
    with_battery,
)

BUDAPEST = ZoneInfo("Europe/Budapest")
UTC = ZoneInfo("UTC")
PERIOD = SettlementPeriod(date(2025, 3, 1), date(2026, 3, 1))
SCHEDULE = PriceSchedule([Prices(date(2025, 1, 1), subsidized=30.0, market=60.0, feed_in=5.0)])
TERMS = TariffTerms()
VAT = 1.27
START = datetime(2025, 6, 1, 10, tzinfo=UTC)


def flows(*hours: dict[str, float]) -> list[Flows]:
    return [Flows(START + timedelta(hours=i), **hour) for i, hour in enumerate(hours)]


def allocated(hours: list[Hour], terms: TariffTerms = TERMS) -> tuple[Bill, list[HourCost]]:
    return allocate(PERIOD, hours, SCHEDULE, terms, standing_charge_months=12, tz=BUDAPEST)


def consumption_cost(hours: list[Flows], terms: TariffTerms = TERMS) -> list[float]:
    return marginal(
        PERIOD,
        hours,
        [hour.without_consumption() for hour in hours],
        SCHEDULE,
        terms,
        standing_charge_months=12,
        tz=BUDAPEST,
    )


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
    bill, costs = allocated(list(series))
    bill_without, costs_without = allocated([hour.without_solar() for hour in series])
    hourly = solar_value(costs, costs_without)

    assert sum(hourly) == pytest.approx(bill_without.net_position - bill.net_position, abs=1)
    assert bill_without.net_position > bill.net_position


def test_the_panels_are_worth_what_they_saved_under_each_mode() -> None:
    """Under szaldó a kept kWh is worth the band price; under gross the same.

    The difference between the modes is export: netted against import under
    szaldó, bought at the feed-in price under gross.
    """

    series = flows({"imported_kwh": 10.0, "exported_kwh": 4.0, "produced_kwh": 7.0})
    for mode in SettlementMode:
        terms = TariffTerms(mode=mode)
        bill, costs = allocated(list(series), terms)
        bill_without, costs_without = allocated([hour.without_solar() for hour in series], terms)
        direct = calculate(
            PERIOD, MeterReadings(13.0, 0.0), SCHEDULE, terms, standing_charge_months=12
        )
        assert bill_without.net_position == direct.net_position
        assert sum(solar_value(costs, costs_without)) == pytest.approx(
            bill_without.net_position - bill.net_position, abs=1
        )


def test_no_panels_are_worth_nothing() -> None:
    series = flows({"imported_kwh": 2.0}, {"imported_kwh": 3.0, "exported_kwh": 0.0})
    _, costs = allocated(list(series))
    _, costs_without = allocated([hour.without_solar() for hour in series])

    assert solar_value(costs, costs_without) == [0.0, 0.0]


def test_the_two_allocations_must_cover_the_same_hours() -> None:
    _, costs = allocated(list(flows({"imported_kwh": 2.0})))

    with pytest.raises(ValueError):
        solar_value(costs, [])


def test_flows_cannot_be_negative() -> None:
    with pytest.raises(ValueError):
        Flows(START, produced_kwh=-1.0)


def test_without_consumption_the_grid_share_is_not_imported() -> None:
    hour = Flows(START, imported_kwh=2.0, produced_kwh=1.0)
    without = hour.without_consumption()

    assert without.imported_kwh == 0.0
    assert without.exported_kwh == pytest.approx(1.0)


def test_without_consumption_what_was_kept_is_exported_instead() -> None:
    hour = Flows(START, exported_kwh=1.0, produced_kwh=4.0, discharged_kwh=0.5)
    without = hour.without_consumption()

    assert without.imported_kwh == 0.0
    assert without.exported_kwh == pytest.approx(4.5)


def test_an_hour_of_shortfall_has_nothing_to_not_consume() -> None:
    hour = Flows(START, imported_kwh=0.5, exported_kwh=2.0)

    assert hour.without_consumption() == Hour(START, imported_kwh=0.5, exported_kwh=2.0)


def test_under_szaldo_a_kwh_consumed_is_worth_the_band_price() -> None:
    """Whether it came from the grid or the panels: it would have netted."""

    series = flows(
        {"imported_kwh": 2.0},
        {"produced_kwh": 2.0},
    )

    assert consumption_cost(series) == pytest.approx([2 * 30 * VAT, 2 * 30 * VAT])


def test_under_szaldo_consumption_in_surplus_is_worth_the_feed_in_price() -> None:
    """Once the period is in surplus a kWh not consumed is bought at the feed-in price."""

    series = flows(
        {"exported_kwh": 100.0, "produced_kwh": 100.0},
        {"produced_kwh": 3.0},
    )

    assert consumption_cost(series)[1] == pytest.approx(3 * 5.0)


def test_under_gross_settlement_the_source_of_a_kwh_decides_its_cost() -> None:
    series = flows(
        {"imported_kwh": 2.0},
        {"produced_kwh": 2.0},
        {"imported_kwh": 1.0, "produced_kwh": 1.0},
    )

    costs = consumption_cost(series, TariffTerms(mode=SettlementMode.BRUTTO))

    assert costs == pytest.approx([2 * 30 * VAT, 2 * 5.0, 30 * VAT + 5.0])


def test_the_cost_of_an_hour_does_not_move_when_later_hours_arrive() -> None:
    first = flows({"imported_kwh": 2.0}, {"produced_kwh": 1.0, "imported_kwh": 1.0})
    later = [*first, Flows(START + timedelta(hours=2), exported_kwh=500.0, produced_kwh=500.0)]

    assert consumption_cost(later)[:2] == consumption_cost(first)


def test_the_cost_of_consuming_is_not_negative() -> None:
    series = flows(
        {"imported_kwh": 5.0},
        {"exported_kwh": 3.0, "produced_kwh": 4.0},
        {"imported_kwh": 0.5, "exported_kwh": 2.0},
    )

    assert min(consumption_cost(series)) >= 0.0
    assert consumption_cost(series)[2] == 0.0


def test_every_hour_needs_an_alternative_for_the_same_hour() -> None:
    series = flows({"imported_kwh": 2.0}, {"imported_kwh": 1.0})

    def against(instead: list[Flows]) -> list[float]:
        return marginal(
            PERIOD, series, instead, SCHEDULE, TERMS, standing_charge_months=12, tz=BUDAPEST
        )

    with pytest.raises(ValueError):
        against(series[:1])
    with pytest.raises(ValueError):
        against(list(reversed(series)))


def test_a_device_takes_its_share_of_the_hour() -> None:
    assert device_share(1.0, 4.0) == pytest.approx((0.25, 0.0))
    assert device_share(0.0, 4.0) == (0.0, 0.0)


def test_a_device_cannot_have_used_more_than_the_house() -> None:
    share, excess = device_share(5.0, 4.0)

    assert share == 1.0
    assert excess == pytest.approx(1.0)
    assert device_share(2.0, 0.0) == pytest.approx((0.0, 2.0))


def test_a_device_share_cannot_be_negative() -> None:
    with pytest.raises(ValueError):
        device_share(-1.0, 4.0)


def test_a_battery_catches_export_and_serves_later_import() -> None:
    series = flows({"exported_kwh": 3.0}, {"imported_kwh": 2.0}, {"imported_kwh": 2.0})

    simulated = with_battery(series, capacity_kwh=10.0, round_trip_efficiency=1.0)

    assert [(h.imported_kwh, h.exported_kwh) for h in simulated] == pytest.approx(
        [(0.0, 0.0), (0.0, 0.0), (1.0, 0.0)]
    )


def test_a_battery_holds_no_more_than_its_capacity() -> None:
    series = flows({"exported_kwh": 5.0}, {"imported_kwh": 5.0})

    simulated = with_battery(series, capacity_kwh=2.0, round_trip_efficiency=1.0)

    assert simulated[0].exported_kwh == pytest.approx(3.0)
    assert simulated[1].imported_kwh == pytest.approx(3.0)


def test_a_battery_loses_its_round_trip_inefficiency_on_the_way_out() -> None:
    series = flows({"exported_kwh": 2.0}, {"imported_kwh": 5.0})

    simulated = with_battery(series, capacity_kwh=10.0, round_trip_efficiency=0.5)

    assert simulated[1].imported_kwh == pytest.approx(4.0)


def test_a_battery_is_worth_something_under_gross_settlement() -> None:
    series = flows({"exported_kwh": 3.0, "produced_kwh": 3.0}, {"imported_kwh": 3.0})
    gross = TariffTerms(mode=SettlementMode.BRUTTO)
    real = settle(PERIOD, series, SCHEDULE, gross, standing_charge_months=12, tz=BUDAPEST)
    with_one = settle(
        PERIOD,
        with_battery(series, 10.0, 1.0),
        SCHEDULE,
        gross,
        standing_charge_months=12,
        tz=BUDAPEST,
    )

    assert real.net_position - with_one.net_position == pytest.approx(3 * 30 * VAT - 3 * 5.0, abs=1)


def test_a_battery_needs_a_sane_capacity_and_efficiency() -> None:
    with pytest.raises(ValueError):
        with_battery([], capacity_kwh=-1.0, round_trip_efficiency=0.9)
    with pytest.raises(ValueError):
        with_battery([], capacity_kwh=1.0, round_trip_efficiency=0.0)
