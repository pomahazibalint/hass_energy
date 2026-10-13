"""Where the period is heading, and what a battery would have saved."""

from datetime import date, timedelta

import pytest
from custom_components.hass_energy.const import (
    CONF_BATTERY_CAPACITY_KWH,
    CONF_BATTERY_EFFICIENCY_PERCENT,
)
from custom_components.hass_energy.diagnostics import async_get_config_entry_diagnostics
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .conftest import (
    DAY_START,
    EXPORT_ENTITY,
    IMPORT_ENTITY,
    TODAY,
    coordinator,
    local_midnight,
    record,
    refresh,
)
from .test_costs import VAT
from .test_sensor import state_of

START = TODAY - timedelta(days=10)
#: Thirteen local hours of today have passed on the frozen clock.
TODAY_LEFT = 11 / 24


async def record_days(
    hass: HomeAssistant, entity: str, first: date, kwh_per_day: list[float]
) -> None:
    """One hour per day, at the day's start, so a day's total is one row."""

    hourly = [kwh if hour == 0 else 0.0 for kwh in kwh_per_day for hour in range(24)]
    await record(hass, entity, local_midnight(first), hourly)


async def test_the_remaining_days_follow_last_years_shape(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    """Last year ran at 10 kWh a day; this period at 20, so last year's days are doubled."""

    last_year = date(2025, 10, 1)
    await record_days(hass, IMPORT_ENTITY, last_year, [10.0] * 20)
    await record_days(hass, IMPORT_ENTITY, START, [20.0] * 10)
    await coordinator(entry).async_close_settlement(START)
    await hass.async_block_till_done()

    outlook = coordinator(entry).outlook
    assert outlook is not None
    # Today and the nine days to 20 October have a day last year; the other
    # 345 are the straight line of 20 a day.
    assert outlook.days_remaining == 355
    assert outlook.days_from_last_year == 10
    so_far = 200.0
    from_last_year = 10 * 2 * TODAY_LEFT + 9 * 20.0
    straight = 345 * 20.0
    assert outlook.bill.billed_kwh == pytest.approx(so_far + from_last_year + straight)
    assert float(state_of(hass, "projected_billed_energy")) == pytest.approx(
        so_far + from_last_year + straight, abs=0.001
    )
    assert state_of(hass, "allowance_runs_out") == "2027-02-04"


async def test_a_first_year_is_the_straight_line(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    await record_days(hass, IMPORT_ENTITY, START, [5.0] * 10)
    await coordinator(entry).async_close_settlement(START)
    await hass.async_block_till_done()

    outlook = coordinator(entry).outlook
    assert outlook is not None
    assert outlook.days_from_last_year == 0
    assert outlook.bill.billed_kwh == pytest.approx(50.0 + 5.0 * (TODAY_LEFT + 354))
    assert state_of(hass, "allowance_runs_out") == STATE_UNKNOWN
    assert float(state_of(hass, "projected_total_payable")) == pytest.approx(
        outlook.bill.gross_total
    )


async def test_the_projection_includes_a_seeded_remainder_in_its_rate(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    await record(hass, IMPORT_ENTITY, DAY_START, [1.0])
    await coordinator(entry).async_seed(START, imported=101.0, exported=0.0)
    await hass.async_block_till_done()

    outlook = coordinator(entry).outlook
    assert outlook is not None
    assert outlook.bill.billed_kwh == pytest.approx(101.0 + 10.1 * (TODAY_LEFT + 354))


async def test_diagnostics_report_the_outlook(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    await record_days(hass, IMPORT_ENTITY, START, [5.0] * 10)
    await coordinator(entry).async_close_settlement(START)
    await hass.async_block_till_done()

    report = await async_get_config_entry_diagnostics(hass, entry)

    assert report["outlook"]["days_remaining"] == 355
    assert report["outlook"]["allowance_runs_out"] is None
    assert report["battery"] is None


async def test_without_a_battery_configured_there_is_no_saving(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    assert state_of(hass, "battery_saving_under_gross_settlement") == STATE_UNAVAILABLE


async def test_a_battery_is_priced_under_gross_settlement(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    """Three kWh exported then imported: a battery keeps them, and gross terms price it."""

    hass.config_entries.async_update_entry(
        entry,
        options={
            **entry.options,
            CONF_BATTERY_CAPACITY_KWH: 10.0,
            CONF_BATTERY_EFFICIENCY_PERCENT: 100.0,
        },
    )
    await hass.async_block_till_done()
    await record(hass, IMPORT_ENTITY, DAY_START, [0.0, 3.0])
    await record(hass, EXPORT_ENTITY, DAY_START, [3.0, 0.0])
    await refresh(hass, entry)

    saving = float(state_of(hass, "battery_saving_under_gross_settlement"))
    assert saving == pytest.approx(3 * 40 * VAT - 3 * 6.0, abs=2)
    report = await async_get_config_entry_diagnostics(hass, entry)
    assert report["battery"] == {
        "capacity_kwh": 10.0,
        "round_trip_efficiency": 1.0,
        "saving": int(saving),
    }
