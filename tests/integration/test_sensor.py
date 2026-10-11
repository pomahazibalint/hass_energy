from datetime import date, timedelta

from custom_components.hass_energy.const import (
    ATTR_READING_DATE,
    CONF_PRICES,
    DOMAIN,
    SERVICE_CLOSE_SETTLEMENT,
)
from custom_components.hass_energy.coordinator import Bucket, PeriodState
from custom_components.hass_energy.settings import price_entry
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .conftest import EXPORT_ENTITY, IMPORT_ENTITY

PREFIX = "sensor.test_settlement_"


async def test_every_line_of_the_settlement_is_an_entity(
    hass: HomeAssistant, entry: MockConfigEntry
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
        "grid_cost_so_far",
        "export_compensation_so_far",
    ):
        assert hass.states.get(PREFIX + key) is not None, key


async def test_money_takes_its_unit_from_the_contract(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    payable = hass.states.get(PREFIX + "total_payable")

    assert payable is not None
    assert payable.attributes["unit_of_measurement"] == "Ft"


async def test_a_silent_meter_still_owes_the_standing_charge(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    assert float(hass.states.get(PREFIX + "energy_cost").state) == 0.0  # type: ignore[union-attr]
    assert hass.states.get(PREFIX + "total_payable").state == "1836"  # type: ignore[union-attr]


async def test_a_whole_settlement_through_the_integration(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """A whole settlement end to end: quantities in, itemised bill out.

    The engine is checked against this invoice directly elsewhere. This checks
    that the integration feeds it the right things and publishes the result.
    """

    coordinator = entry.runtime_data
    # The invoice's prices, and its 1 August price-period boundary.
    hass.config_entries.async_update_entry(
        entry,
        options={
            **entry.options,
            CONF_PRICES: [
                price_entry(date(2024, 1, 1), 36.386, 70.104, 5.11),
                price_entry(date(2025, 8, 1), 36.386, 70.104, 5.11),
            ],
        },
    )
    # 7 000 kWh withdrawn, 7 500 fed in, recorded against the price period
    # each happened in.
    coordinator.state = PeriodState(
        start=date(2024, 9, 9),
        buckets={
            "2024-01-01": Bucket(imported=6300.0, exported=6750.0),
            "2025-08-01": Bucket(imported=700.0, exported=750.0),
        },
        last_import=23000.0,
        last_export=26500.0,
    )
    coordinator.async_set_updated_data(coordinator.build_bill())
    await hass.async_block_till_done()

    bill = coordinator.data
    assert bill.readings.imported_kwh == 7000.0
    assert bill.readings.exported_kwh == 7500.0
    assert bill.billed_kwh == 0
    assert bill.surplus_kwh == 500.0
    assert bill.gross_total == 1836
    assert bill.surplus_net == 2556

    assert hass.states.get(PREFIX + "total_payable").state == "1836"  # type: ignore[union-attr]
    assert hass.states.get(PREFIX + "surplus_owed").state == "2556"  # type: ignore[union-attr]
    assert hass.states.get(PREFIX + "net_position").state == "-720"  # type: ignore[union-attr]


async def test_the_payable_line_carries_the_period_it_covers(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    attributes = hass.states.get(PREFIX + "total_payable").attributes  # type: ignore[union-attr]

    assert "period_start" in attributes
    assert "days_elapsed" in attributes
    assert "imported_kwh" in attributes


async def test_the_feed_in_price_is_the_rate_in_force_per_kwh(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """A price for the energy dashboard's return-to-grid option, not a bill."""

    state = hass.states.get(PREFIX + "current_feed_in_price")

    assert state is not None
    assert float(state.state) == 6.0
    assert state.attributes["unit_of_measurement"] == "Ft/kWh"


async def test_the_feed_in_price_follows_a_price_change(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    prices = [*entry.options[CONF_PRICES]]
    prices[-1] = {**prices[-1], "feed_in": 7.5}
    hass.config_entries.async_update_entry(entry, options={**entry.options, CONF_PRICES: prices})
    await hass.async_block_till_done()

    assert float(hass.states.get(PREFIX + "current_feed_in_price").state) == 7.5  # type: ignore[union-attr]


async def move(hass: HomeAssistant, entity: str, value: float) -> None:
    hass.states.async_set(entity, str(value))
    await hass.async_block_till_done()


async def test_the_running_totals_speak_the_dashboards_currency(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """The energy dashboard labels costs in Home Assistant's currency, not the contract's."""

    for key in ("grid_cost_so_far", "export_compensation_so_far"):
        state = hass.states.get(PREFIX + key)
        assert state is not None, key
        assert state.attributes["unit_of_measurement"] == hass.config.currency
        assert state.attributes["device_class"] == "monetary"
        assert state.attributes["state_class"] == "total"
        assert state.attributes["last_reset"] == dt_util.start_of_local_day(
            entry.runtime_data.state.start
        ).isoformat()


async def test_the_grid_cost_is_the_energy_charge_with_vat(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await move(hass, IMPORT_ENTITY, 1500.0)

    # 500 kWh at the subsidized rate of 40, with 27% VAT on it.
    assert float(hass.states.get(PREFIX + "grid_cost_so_far").state) == 25400.0  # type: ignore[union-attr]
    assert hass.states.get(PREFIX + "export_compensation_so_far").state == "0"  # type: ignore[union-attr]


async def test_export_that_cancels_import_takes_the_cost_back_down(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """An hour of export under szaldó is a negative cost, not a compensation."""

    await move(hass, IMPORT_ENTITY, 1500.0)
    await move(hass, EXPORT_ENTITY, 2800.0)

    assert float(hass.states.get(PREFIX + "grid_cost_so_far").state) == 0.0  # type: ignore[union-attr]
    # 300 kWh of surplus at the feed-in rate of 6.
    assert hass.states.get(PREFIX + "export_compensation_so_far").state == "1800"  # type: ignore[union-attr]


async def test_closing_the_settlement_resets_the_running_totals(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    reading_date = dt_util.now().date()
    entry.runtime_data.seed(reading_date - timedelta(days=30), imported=500.0, exported=0.0)
    entry.runtime_data.refresh_settlement()
    await hass.async_block_till_done()
    before = hass.states.get(PREFIX + "grid_cost_so_far")
    assert before is not None
    assert float(before.state) > 0
    assert before.attributes["last_reset"] == dt_util.start_of_local_day(
        reading_date - timedelta(days=30)
    ).isoformat()

    await hass.services.async_call(
        DOMAIN, SERVICE_CLOSE_SETTLEMENT, {ATTR_READING_DATE: reading_date}, blocking=True
    )

    state = hass.states.get(PREFIX + "grid_cost_so_far")
    assert state is not None
    assert float(state.state) == 0.0
    assert state.attributes["last_reset"] == dt_util.start_of_local_day(reading_date).isoformat()
