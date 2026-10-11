from datetime import timedelta

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
from custom_components.hass_energy.coordinator import SettlementCoordinator
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .conftest import EXPORT_ENTITY, IMPORT_ENTITY


def coordinator(entry: MockConfigEntry) -> SettlementCoordinator:
    data: SettlementCoordinator = entry.runtime_data
    return data


async def move(hass: HomeAssistant, entity: str, value: float) -> None:
    hass.states.async_set(entity, str(value))
    await hass.async_block_till_done()


async def test_the_first_reading_is_only_a_baseline(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """A meter's absolute value says nothing about what happened before."""

    state = coordinator(entry).state

    assert state.imported == 0
    assert state.exported == 0
    assert state.last_import == 1000.0


async def test_movement_is_accrued(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await move(hass, IMPORT_ENTITY, 1010.0)
    await move(hass, IMPORT_ENTITY, 1025.5)
    await move(hass, EXPORT_ENTITY, 2030.0)

    state = coordinator(entry).state
    assert state.imported == 25.5
    assert state.exported == 30.0


async def test_a_meter_that_restarts_is_not_a_negative_quantity(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await move(hass, IMPORT_ENTITY, 1010.0)
    # The source resets its own total, as a replaced meter would.
    await move(hass, IMPORT_ENTITY, 4.0)

    assert coordinator(entry).state.imported == 14.0


async def test_a_small_dip_is_a_glitch_and_not_a_restart(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """A stale value replayed on reconnect must not add the meter's lifetime total."""

    await move(hass, IMPORT_ENTITY, 1010.0)
    await move(hass, IMPORT_ENTITY, 1009.5)
    await move(hass, IMPORT_ENTITY, 1012.0)

    state = coordinator(entry).state
    assert state.imported == 12.0
    assert state.last_import == 1012.0


async def test_the_baseline_waits_out_a_glitch(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """Moving the baseline down with the glitch would count the recovery twice."""

    await move(hass, IMPORT_ENTITY, 1010.0)
    await move(hass, IMPORT_ENTITY, 1009.0)

    assert coordinator(entry).state.last_import == 1010.0
    assert coordinator(entry).state.imported == 10.0


async def test_unusable_readings_are_ignored(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await move(hass, IMPORT_ENTITY, 1010.0)
    hass.states.async_set(IMPORT_ENTITY, "unavailable")
    await hass.async_block_till_done()
    await move(hass, IMPORT_ENTITY, 1020.0)

    assert coordinator(entry).state.imported == 20.0


async def test_energy_is_recorded_against_the_prices_in_force(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """The bucket key is the price period, which is what makes the split exact."""

    await move(hass, IMPORT_ENTITY, 1100.0)

    assert set(coordinator(entry).state.buckets) == {"2025-08-01"}


async def test_the_settlement_is_derived_from_what_was_recorded(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await move(hass, IMPORT_ENTITY, 1500.0)
    await move(hass, EXPORT_ENTITY, 2200.0)

    bill = coordinator(entry).data

    assert bill.readings.imported_kwh == 500.0
    assert bill.readings.exported_kwh == 200.0
    assert bill.billed_kwh == 300.0
    assert bill.surplus_kwh == 0.0


async def test_net_export_produces_a_surplus_and_no_energy_charge(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await move(hass, IMPORT_ENTITY, 1100.0)
    await move(hass, EXPORT_ENTITY, 2400.0)

    bill = coordinator(entry).data

    assert bill.billed_kwh == 0
    assert bill.surplus_kwh == 300.0
    assert bill.energy_net == 0
    # The standing charge is owed regardless.
    assert bill.gross_total == 1836


async def test_gross_settlement_bills_all_withdrawal_and_buys_all_feed_in(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """Under brutto nothing is netted, however the meters compare."""

    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_MODE: "brutto"}
    )
    await hass.async_block_till_done()
    # More fed in than withdrawn: under szaldó there would be nothing to bill.
    await move(hass, IMPORT_ENTITY, 1500.0)
    await move(hass, EXPORT_ENTITY, 2800.0)

    bill = coordinator(entry).data

    assert bill.billed_kwh == 500.0
    assert bill.subsidized_kwh + bill.market_kwh == 500.0
    assert bill.energy_net == 500.0 * 40.0
    assert bill.surplus_kwh == 800.0
    assert sum(line.kwh for line in bill.surplus) == 800.0
    assert bill.surplus_net == forint(800.0 * 6.0)


async def test_changing_the_contract_revalues_the_same_quantities(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """Editing an option must never move a recorded kWh."""

    # Export matters: the two bases only differ once netting is in play.
    await move(hass, IMPORT_ENTITY, 4000.0)
    await move(hass, EXPORT_ENTITY, 4500.0)
    before = coordinator(entry).state.imported
    charged_before = coordinator(entry).data.energy_net
    assert charged_before > 0

    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_ALLOWANCE_BASIS: "gross"}
    )
    await hass.async_block_till_done()

    after = coordinator(entry)
    assert after.state.imported == before
    assert after.data.energy_net != charged_before


async def test_the_marginal_price_follows_the_allowance_basis(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """Under the gross basis withdrawal alone can exhaust the allowance."""

    # 3 000 withdrawn against 2 800 fed in: 200 billed, far inside the
    # allowance on the netted basis, but 3 000 withdrawn is past it.
    await move(hass, IMPORT_ENTITY, 4000.0)
    await move(hass, EXPORT_ENTITY, 4800.0)
    assert coordinator(entry).current_unit_price() == 40.0

    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_ALLOWANCE_BASIS: "gross"}
    )
    await hass.async_block_till_done()

    assert coordinator(entry).current_unit_price() == 80.0
    assert coordinator(entry).data.allowance_remaining_kwh == 0


async def test_a_backdated_price_revalues_history(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await move(hass, IMPORT_ENTITY, 1500.0)
    before = coordinator(entry).data.energy_net

    prices = [*entry.options[CONF_PRICES]]
    prices[-1] = {**prices[-1], "subsidized": 80.0}
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_PRICES: prices}
    )
    await hass.async_block_till_done()

    assert coordinator(entry).data.energy_net > before
    assert coordinator(entry).state.imported == 500.0


async def test_closing_a_settlement_starts_a_new_period(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """The boundary follows the meter reading, not the calendar."""

    await move(hass, IMPORT_ENTITY, 1500.0)
    reading_date = dt_util.now().date()

    await hass.services.async_call(
        DOMAIN,
        SERVICE_CLOSE_SETTLEMENT,
        {ATTR_READING_DATE: reading_date},
        blocking=True,
    )

    state = coordinator(entry).state
    assert state.start == reading_date
    assert state.imported == 0
    # The meter did not go back to zero just because the period did.
    assert state.last_import == 1500.0


async def test_energy_since_the_reading_carries_into_the_new_period(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """The reading is entered days after it happened; the days between are not lost."""

    today = dt_util.now().date()
    coordinator(entry).seed(today - timedelta(days=10), imported=100.0, exported=50.0)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_CLOSE_SETTLEMENT,
        {ATTR_READING_DATE: today - timedelta(days=4)},
        blocking=True,
    )

    state = coordinator(entry).state
    assert state.start == today - timedelta(days=4)
    assert state.imported == pytest.approx(40.0)
    assert state.exported == pytest.approx(20.0)


async def test_accrual_continues_after_a_settlement_closes(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await move(hass, IMPORT_ENTITY, 1500.0)
    await hass.services.async_call(
        DOMAIN, SERVICE_CLOSE_SETTLEMENT, {}, blocking=True
    )

    await move(hass, IMPORT_ENTITY, 1520.0)

    assert coordinator(entry).state.imported == 20.0


async def test_quantities_survive_a_restart(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await move(hass, IMPORT_ENTITY, 1600.0)

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert coordinator(entry).state.imported == 600.0
