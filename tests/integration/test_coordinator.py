"""The settlement, derived from what the recorder holds."""

from datetime import date, timedelta

import pytest
from custom_components.hass_energy.billing import forint
from custom_components.hass_energy.const import (
    ATTR_READING_DATE,
    CONF_ALLOWANCE_BASIS,
    CONF_MODE,
    CONF_PRICES,
    DOMAIN,
    SERVICE_CLOSE_SETTLEMENT,
)
from custom_components.hass_energy.settings import price_entry
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


async def close(hass: HomeAssistant, reading_date: date) -> None:
    await hass.services.async_call(
        DOMAIN, SERVICE_CLOSE_SETTLEMENT, {ATTR_READING_DATE: reading_date}, blocking=True
    )
    await hass.async_block_till_done()


async def test_a_fresh_period_with_nothing_recorded_is_zero(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    bill = coordinator(entry).data

    assert coordinator(entry).state.start == TODAY
    assert bill.readings.imported_kwh == 0
    assert bill.readings.exported_kwh == 0
    # The standing charge is owed regardless.
    assert bill.gross_total == 1836


async def test_the_recorders_hours_are_the_periods_energy(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    await record(hass, IMPORT_ENTITY, DAY_START, [10.0, 15.5])
    await record(hass, EXPORT_ENTITY, DAY_START + timedelta(hours=2), [30.0])
    await refresh(hass, entry)

    bill = coordinator(entry).data
    assert bill.readings.imported_kwh == 25.5
    assert bill.readings.exported_kwh == 30.0
    assert coordinator(entry).observed is not None
    assert coordinator(entry).observed.first == DAY_START


async def test_hours_before_the_period_are_not_its_energy(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    await record(hass, IMPORT_ENTITY, DAY_START - timedelta(hours=2), [100.0, 100.0, 5.0])
    await refresh(hass, entry)

    assert coordinator(entry).data.readings.imported_kwh == 5.0


async def test_an_hour_is_priced_by_the_local_day_it_fell_in(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    """A price change today prices yesterday's hours at yesterday's rate."""

    yesterday = TODAY - timedelta(days=1)
    hass.config_entries.async_update_entry(
        entry,
        options={
            **entry.options,
            CONF_PRICES: [*entry.options[CONF_PRICES], price_entry(TODAY, 50.0, 90.0, 7.0)],
        },
    )
    await hass.async_block_till_done()
    await close(hass, yesterday)
    # The last hour of yesterday and the first of today, local time.
    await record(hass, IMPORT_ENTITY, DAY_START - timedelta(hours=1), [10.0, 10.0])
    await refresh(hass, entry)

    bill = coordinator(entry).data
    assert [round(line.unit_price) for line in bill.subsidized] == [40, 50]
    assert bill.energy_net == pytest.approx(10 * 40.0 + 10 * 50.0)


async def test_netting_bills_the_difference(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    await record(hass, IMPORT_ENTITY, DAY_START, [500.0])
    await record(hass, EXPORT_ENTITY, DAY_START, [200.0])
    await refresh(hass, entry)

    bill = coordinator(entry).data
    assert bill.billed_kwh == 300.0
    assert bill.surplus_kwh == 0.0


async def test_net_export_produces_a_surplus_and_no_energy_charge(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    await record(hass, IMPORT_ENTITY, DAY_START, [100.0])
    await record(hass, EXPORT_ENTITY, DAY_START, [400.0])
    await refresh(hass, entry)

    bill = coordinator(entry).data
    assert bill.billed_kwh == 0
    assert bill.surplus_kwh == 300.0
    assert bill.energy_net == 0
    assert bill.gross_total == 1836
    assert bill.surplus_net == forint(300.0 * 6.0)


async def test_gross_settlement_bills_all_withdrawal_and_buys_all_feed_in(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    """Under brutto nothing is netted, however the meters compare."""

    hass.config_entries.async_update_entry(entry, options={**entry.options, CONF_MODE: "brutto"})
    await hass.async_block_till_done()
    await record(hass, IMPORT_ENTITY, DAY_START, [500.0])
    await record(hass, EXPORT_ENTITY, DAY_START, [800.0])
    await refresh(hass, entry)

    bill = coordinator(entry).data
    assert bill.billed_kwh == 500.0
    assert bill.energy_net == 500.0 * 40.0
    assert bill.surplus_kwh == 800.0
    assert bill.surplus_net == forint(800.0 * 6.0)


async def test_changing_the_contract_revalues_the_same_hours(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    """Editing an option must never move a recorded kWh."""

    await record(hass, IMPORT_ENTITY, DAY_START, [3000.0])
    await record(hass, EXPORT_ENTITY, DAY_START, [2500.0])
    await refresh(hass, entry)
    charged_before = coordinator(entry).data.energy_net
    assert charged_before > 0

    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_ALLOWANCE_BASIS: "gross"}
    )
    await hass.async_block_till_done()

    after = coordinator(entry).data
    assert after.readings.imported_kwh == 3000.0
    assert after.energy_net != charged_before


async def test_the_marginal_price_follows_the_allowance_basis(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    """Under the gross basis withdrawal alone can exhaust the allowance."""

    await record(hass, IMPORT_ENTITY, DAY_START, [3000.0])
    await record(hass, EXPORT_ENTITY, DAY_START, [2800.0])
    await refresh(hass, entry)
    assert coordinator(entry).current_unit_price() == 40.0

    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_ALLOWANCE_BASIS: "gross"}
    )
    await hass.async_block_till_done()

    assert coordinator(entry).current_unit_price() == 80.0
    assert coordinator(entry).data.allowance_remaining_kwh == 0


async def test_a_backdated_price_applies_to_the_hours_after_its_date(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    """The record knows which hour each kWh fell in, so a backdated price lands right."""

    two_days_ago = TODAY - timedelta(days=2)
    await close(hass, two_days_ago)
    await record(hass, IMPORT_ENTITY, local_midnight(two_days_ago), [10.0])
    await record(hass, IMPORT_ENTITY, local_midnight(TODAY - timedelta(days=1)), [10.0])
    await refresh(hass, entry)
    assert coordinator(entry).data.energy_net == pytest.approx(20 * 40.0)

    hass.config_entries.async_update_entry(
        entry,
        options={
            **entry.options,
            CONF_PRICES: [
                *entry.options[CONF_PRICES],
                price_entry(TODAY - timedelta(days=1), 80.0, 90.0, 7.0),
            ],
        },
    )
    await hass.async_block_till_done()

    assert coordinator(entry).data.energy_net == pytest.approx(10 * 40.0 + 10 * 80.0)


async def test_closing_a_settlement_starts_a_new_period(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    """The boundary follows the meter reading, not the calendar."""

    await close(hass, TODAY - timedelta(days=10))
    await record(hass, IMPORT_ENTITY, local_midnight(TODAY - timedelta(days=5)), [100.0])
    await record(hass, IMPORT_ENTITY, DAY_START, [7.0])
    await refresh(hass, entry)
    assert coordinator(entry).data.readings.imported_kwh == 107.0

    await close(hass, TODAY)

    state = coordinator(entry).state
    assert state.start == TODAY
    assert coordinator(entry).data.readings.imported_kwh == 7.0


async def test_energy_since_the_reading_is_the_new_periods_whenever_it_is_entered(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    """The reading is entered days late; the days between are in the recorder."""

    await close(hass, TODAY - timedelta(days=10))
    for days_ago in range(10, 0, -1):
        await record(hass, IMPORT_ENTITY, local_midnight(TODAY - timedelta(days=days_ago)), [10.0])
    await refresh(hass, entry)
    assert coordinator(entry).data.readings.imported_kwh == 100.0

    await close(hass, TODAY - timedelta(days=4))

    assert coordinator(entry).data.readings.imported_kwh == 40.0


async def test_the_period_survives_a_restart(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    await close(hass, TODAY - timedelta(days=3))
    await record(hass, IMPORT_ENTITY, local_midnight(TODAY - timedelta(days=2)), [600.0])

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert coordinator(entry).state.start == TODAY - timedelta(days=3)
    assert coordinator(entry).data.readings.imported_kwh == 600.0


async def test_the_hourly_compile_triggers_a_refresh(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    await record(hass, IMPORT_ENTITY, DAY_START, [12.0])
    assert coordinator(entry).data.readings.imported_kwh == 0

    hass.bus.async_fire("recorder_hourly_statistics_generated")
    await hass.async_block_till_done()

    assert coordinator(entry).data.readings.imported_kwh == 12.0
