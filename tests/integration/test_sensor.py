from datetime import date

from custom_components.hass_energy.const import CONF_PRICES
from custom_components.hass_energy.coordinator import Bucket, PeriodState
from custom_components.hass_energy.settings import price_entry
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

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


async def test_the_2025_invoice_through_the_integration(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """Invoice settlement end to end: quantities in, settlement out.

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
    # 7 000 kWh withdrawn, 7 500 fed in, recorded against each price period as
    # the invoice splits them.
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
