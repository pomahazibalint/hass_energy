"""The settlement as entities."""

from datetime import date, timedelta

from custom_components.hass_energy.const import CONF_PRICES
from custom_components.hass_energy.settings import price_entry
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .conftest import DAY_START, EXPORT_ENTITY, IMPORT_ENTITY, TODAY, coordinator, record, refresh

PREFIX = "sensor.test_settlement_"


def state_of(hass: HomeAssistant, key: str) -> str:
    state = hass.states.get(PREFIX + key)
    assert state is not None, key
    return state.state


async def test_every_line_of_the_settlement_is_an_entity(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    for key in (
        "billed_energy",
        "surplus_energy",
        "subsidized_energy",
        "market_price_energy",
        "allowance_remaining",
        "energy_cost",
        "standing_charge",
        "vat",
        "total_payable",
        "surplus_owed",
        "net_position",
        "settlement_period_length",
        "current_unit_price",
        "current_feed_in_price",
    ):
        assert hass.states.get(PREFIX + key) is not None, key


async def test_money_takes_its_unit_from_the_contract(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    payable = hass.states.get(PREFIX + "total_payable")

    assert payable is not None
    assert payable.attributes["unit_of_measurement"] == "Ft"


async def test_a_silent_meter_still_owes_the_standing_charge(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    assert float(state_of(hass, "energy_cost")) == 0.0
    assert state_of(hass, "total_payable") == "1836"


async def test_a_whole_settlement_through_the_integration(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    """A whole settlement end to end: hours in, itemised bill out.

    The engine is checked against the invoice directly elsewhere. This checks
    that the integration feeds it the right things and publishes the result.
    """

    hass.config_entries.async_update_entry(
        entry,
        options={
            **entry.options,
            CONF_PRICES: [
                price_entry(date(2024, 1, 1), 36.386, 70.104, 5.11),
                price_entry(TODAY - timedelta(days=1), 36.386, 70.104, 5.11),
            ],
        },
    )
    await hass.async_block_till_done()
    await coordinator(entry).async_close_settlement(TODAY - timedelta(days=3))
    # 7 000 kWh withdrawn, 7 500 fed in, with the last day under a new price
    # period: the invoice's shape, scaled to a few days.
    two_days_ago = DAY_START - timedelta(days=2)
    yesterday = DAY_START - timedelta(days=1)
    await record(hass, IMPORT_ENTITY, two_days_ago, [6300.0])
    await record(hass, EXPORT_ENTITY, two_days_ago, [6750.0])
    await record(hass, IMPORT_ENTITY, yesterday, [700.0])
    await record(hass, EXPORT_ENTITY, yesterday, [750.0])
    await refresh(hass, entry)

    bill = coordinator(entry).data
    assert bill.readings.imported_kwh == 7000.0
    assert bill.readings.exported_kwh == 7500.0
    assert bill.billed_kwh == 0
    assert bill.surplus_kwh == 500.0
    assert bill.gross_total == 1836
    # Each price period's surplus rounded on its own: 450 and 50 kWh at 5.11.
    assert [line.rounded for line in bill.surplus] == [2300, 256]
    assert bill.surplus_net == 2556

    assert state_of(hass, "total_payable") == "1836"
    assert state_of(hass, "surplus_owed") == "2556"
    assert state_of(hass, "net_position") == "-720"


async def test_the_payable_line_carries_the_period_it_covers(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    attributes = hass.states.get(PREFIX + "total_payable").attributes  # type: ignore[union-attr]

    assert attributes["period_start"] == TODAY.isoformat()
    assert "days_elapsed" in attributes
    assert "imported_kwh" in attributes


async def test_the_feed_in_price_is_the_rate_in_force_per_kwh(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    """A price for the energy dashboard's return-to-grid option, not a bill."""

    state = hass.states.get(PREFIX + "current_feed_in_price")

    assert state is not None
    assert float(state.state) == 6.0
    assert state.attributes["unit_of_measurement"] == "Ft/kWh"


async def test_the_feed_in_price_follows_a_price_change(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    prices = [*entry.options[CONF_PRICES]]
    prices[-1] = {**prices[-1], "feed_in": 7.5}
    hass.config_entries.async_update_entry(entry, options={**entry.options, CONF_PRICES: prices})
    await hass.async_block_till_done()

    assert float(state_of(hass, "current_feed_in_price")) == 7.5
