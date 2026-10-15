"""What consuming cost, and each device's part of it."""

from datetime import timedelta
from typing import Any

import pytest
from custom_components.hass_energy.const import CONF_ALLOWANCE_KWH, CONF_MODE, DOMAIN
from custom_components.hass_energy.costs import CONSUMPTION_COST, device_kind, statistic_id
from custom_components.hass_energy.diagnostics import async_get_config_entry_diagnostics
from custom_components.hass_energy.preferences import Device
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .conftest import (
    DAY_START,
    EXPORT_ENTITY,
    IMPORT_ENTITY,
    PRODUCTION_ENTITY,
    TODAY,
    coordinator,
    name_sources,
    record,
    record_rebook,
    refresh,
)
from .test_costs import rows, states
from .test_household import known
from .test_sensor import PREFIX, state_of

WASHER = "sensor.washer_energy"
HEAT_PUMP = "sensor.heat_pump_energy"
#: The subsidized and market prices in force on the test's day, from the fixture schedule.
BAND = 40.0
MARKET = 80.0
FEED_IN = 6.0


def device(statistic: str, **extra: Any) -> dict[str, Any]:
    return {"stat_consumption": statistic, **extra}


def device_rows(entry: MockConfigEntry, statistic: str) -> str:
    return device_kind(Device(statistic, statistic).slug)


async def test_what_the_house_consumed_cost_the_band_price(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    """Under szaldó a kWh not consumed would have netted, whatever supplied it."""

    await name_sources(hass, solar=[PRODUCTION_ENTITY])
    await record(hass, IMPORT_ENTITY, DAY_START, [3.0, 0.0])
    await record(hass, PRODUCTION_ENTITY, DAY_START, [0.0, 3.0])
    await refresh(hass, entry)

    assert states(await rows(hass, entry, CONSUMPTION_COST))[:2] == pytest.approx(
        [3 * BAND, 3 * BAND], abs=1e-4
    )
    assert state_of(hass, "consumption_cost") == str(round(6 * BAND))


async def test_consumption_beyond_what_would_net_is_worth_the_feed_in_price(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    """With 2 kWh imported, only 2 of 3 solar kWh consumed would have netted."""

    await name_sources(hass, solar=[PRODUCTION_ENTITY])
    await record(hass, IMPORT_ENTITY, DAY_START, [2.0, 0.0])
    await record(hass, PRODUCTION_ENTITY, DAY_START, [0.0, 3.0])
    await refresh(hass, entry)

    assert states(await rows(hass, entry, CONSUMPTION_COST))[1] == pytest.approx(
        2 * BAND + 1 * FEED_IN, abs=1e-4
    )


async def test_under_gross_settlement_solar_consumed_is_worth_the_feed_in_price(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_MODE: "brutto"}
    )
    await hass.async_block_till_done()
    await name_sources(hass, solar=[PRODUCTION_ENTITY])
    await record(hass, IMPORT_ENTITY, DAY_START, [2.0, 0.0])
    await record(hass, PRODUCTION_ENTITY, DAY_START, [0.0, 3.0])
    await refresh(hass, entry)

    assert states(await rows(hass, entry, CONSUMPTION_COST))[:2] == pytest.approx(
        [2 * BAND, 3 * FEED_IN], abs=1e-4
    )


async def test_a_device_costs_its_share_of_the_hour(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    await name_sources(hass, devices=[device(WASHER, name="Washer")])
    await record(hass, IMPORT_ENTITY, DAY_START, [4.0, 2.0])
    await record(hass, WASHER, DAY_START, [1.0, 2.0])
    await refresh(hass, entry)

    hourly = states(await rows(hass, entry, device_rows(entry, WASHER)))
    assert hourly[:2] == pytest.approx([1 * BAND, 2 * BAND], abs=1e-4)
    assert state_of(hass, "washer_cost") == str(round(3 * BAND))
    washer = hass.states.get(PREFIX + "washer_cost")
    assert washer is not None
    assert washer.attributes["unit_of_measurement"] == "Ft"
    assert washer.attributes["energy_kwh"] == "3.000"
    assert washer.attributes["statistic"] == WASHER


async def test_a_device_that_runs_on_the_panels_is_cheaper_under_gross_settlement(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    """The time-of-day effect the native dashboard cannot show."""

    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_MODE: "brutto"}
    )
    await hass.async_block_till_done()
    await name_sources(
        hass,
        solar=[PRODUCTION_ENTITY],
        devices=[device(WASHER, name="Washer"), device(HEAT_PUMP, name="Heat pump")],
    )
    await record(hass, IMPORT_ENTITY, DAY_START, [0.0, 2.0])
    await record(hass, PRODUCTION_ENTITY, DAY_START, [2.0, 0.0])
    await record(hass, WASHER, DAY_START, [2.0, 0.0])
    await record(hass, HEAT_PUMP, DAY_START, [0.0, 2.0])
    await refresh(hass, entry)

    assert state_of(hass, "washer_cost") == str(round(2 * FEED_IN))
    assert state_of(hass, "heat_pump_cost") == str(round(2 * BAND))


async def test_a_device_is_named_as_the_dashboard_names_it(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    hass.states.async_set(HEAT_PUMP, "10.0", {"friendly_name": "Heat pump energy"})
    await name_sources(hass, devices=[device(WASHER, name="Washer"), device(HEAT_PUMP)])
    await record(hass, IMPORT_ENTITY, DAY_START, [4.0])
    await record(hass, WASHER, DAY_START, [1.0])
    await record(hass, HEAT_PUMP, DAY_START, [1.0])
    await refresh(hass, entry)

    assert hass.states.get(PREFIX + "washer_cost") is not None
    assert hass.states.get(PREFIX + "heat_pump_energy_cost") is not None
    assert coordinator(entry).sources.devices == (
        Device(WASHER, "Washer"),
        Device(HEAT_PUMP, "Heat pump energy"),
    )


async def test_a_device_above_the_house_is_capped_and_reported(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    """A device meter reporting late claims more than the whole house used."""

    await name_sources(hass, devices=[device(WASHER, name="Washer")])
    await record(hass, IMPORT_ENTITY, DAY_START, [1.0, 1.0])
    await record(hass, WASHER, DAY_START, [3.0, 0.5])
    await refresh(hass, entry)

    hourly = states(await rows(hass, entry, device_rows(entry, WASHER)))
    assert hourly[:2] == pytest.approx([1 * BAND, 0.5 * BAND], abs=1e-4)
    registry = ir.async_get(hass)
    issue = registry.async_get_issue(DOMAIN, f"device_bursts_{entry.entry_id}")
    assert issue is not None
    assert issue.translation_placeholders == {"devices": "Washer (1 h, 2.0 kWh)"}
    # The house's own figures agree with each other; that repair stays quiet.
    assert registry.async_get_issue(DOMAIN, f"sources_disagree_{entry.entry_id}") is None
    report = await async_get_config_entry_diagnostics(hass, entry)
    assert report["device_bursts"] == {"Washer": {"hours": 1, "excess_kwh": pytest.approx(2.0)}}


async def test_a_device_dropped_from_the_dashboard_takes_its_figures_with_it(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    await name_sources(hass, devices=[device(WASHER, name="Washer")])
    await record(hass, IMPORT_ENTITY, DAY_START, [4.0])
    await record(hass, WASHER, DAY_START, [1.0])
    await refresh(hass, entry)
    assert await known(hass, entry, device_rows(entry, WASHER))
    assert hass.states.get(PREFIX + "washer_cost") is not None

    await name_sources(hass)
    await refresh(hass, entry)

    assert not await known(hass, entry, device_rows(entry, WASHER))
    assert hass.states.get(PREFIX + "washer_cost") is None
    unique_id = f"{entry.entry_id}_{device_rows(entry, WASHER)}"
    assert er.async_get(hass).async_get_entity_id("sensor", DOMAIN, unique_id) is None
    assert await known(hass, entry, CONSUMPTION_COST)


async def test_a_device_named_in_the_dashboard_appears_without_a_reload(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    await record(hass, IMPORT_ENTITY, DAY_START, [4.0])
    await record(hass, WASHER, DAY_START, [1.0])
    assert hass.states.get(PREFIX + "washer_cost") is None

    await name_sources(hass, devices=[device(WASHER, name="Washer")])

    assert state_of(hass, "washer_cost") == str(round(1 * BAND))


async def test_a_device_is_known_from_its_own_first_hour(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    await name_sources(hass, devices=[device(WASHER, name="Washer")])
    await record(hass, IMPORT_ENTITY, DAY_START, [4.0, 4.0])
    await record(hass, WASHER, DAY_START + timedelta(hours=1), [1.0])
    await refresh(hass, entry)

    hourly = await rows(hass, entry, device_rows(entry, WASHER))
    assert hourly[0]["start"] == (DAY_START + timedelta(hours=1)).timestamp()
    assert (await rows(hass, entry, CONSUMPTION_COST))[0]["start"] == DAY_START.timestamp()


async def test_a_device_the_recorder_never_compiled_is_raised(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    await name_sources(hass, devices=[device("sensor.nothing_recorded", name="Ghost")])
    await record(hass, IMPORT_ENTITY, DAY_START, [4.0])
    await refresh(hass, entry)

    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"source_unrecorded_{entry.entry_id}")
    assert issue is not None
    assert "sensor.nothing_recorded" in issue.translation_placeholders["entities"]  # type: ignore[index]
    assert state_of(hass, "ghost_cost") == STATE_UNAVAILABLE


async def test_a_device_does_not_gate_the_house(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    """A device added last month says nothing about what the house did before."""

    await name_sources(hass, solar=[PRODUCTION_ENTITY], devices=[device(WASHER, name="Washer")])
    await record(hass, IMPORT_ENTITY, DAY_START, [1.0, 1.0])
    await record(hass, PRODUCTION_ENTITY, DAY_START, [2.0, 2.0])
    await record(hass, WASHER, DAY_START + timedelta(hours=1), [1.0])
    await refresh(hass, entry)

    assert state_of(hass, "house_consumption") == "6.0"
    assert (await rows(hass, entry, "house_consumption"))[0]["start"] == DAY_START.timestamp()


async def test_a_nested_device_carries_its_childs_cost(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    """A device whose total includes another's is costed on its own total."""

    await name_sources(
        hass,
        devices=[
            device(HEAT_PUMP, name="Heat pump"),
            device(WASHER, name="Washer", included_in_stat=HEAT_PUMP),
        ],
    )
    await record(hass, IMPORT_ENTITY, DAY_START, [4.0])
    await record(hass, HEAT_PUMP, DAY_START, [3.0])
    await record(hass, WASHER, DAY_START, [1.0])
    await refresh(hass, entry)

    assert state_of(hass, "heat_pump_cost") == str(round(3 * BAND))
    assert state_of(hass, "washer_cost") == str(round(1 * BAND))
    washer = hass.states.get(PREFIX + "washer_cost")
    assert washer is not None
    assert washer.attributes["included_in"] == HEAT_PUMP


async def test_the_cost_of_consuming_is_unavailable_while_the_house_is_unknown(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    await name_sources(hass, solar=["sensor.inverter_not_yet_recorded"])
    await record(hass, IMPORT_ENTITY, DAY_START, [4.0])
    await refresh(hass, entry)

    assert state_of(hass, "consumption_cost") == STATE_UNAVAILABLE


async def test_removing_the_entry_removes_the_device_statistics(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    await name_sources(hass, devices=[device(WASHER, name="Washer")])
    await record(hass, IMPORT_ENTITY, DAY_START, [4.0])
    await record(hass, WASHER, DAY_START, [1.0])
    await refresh(hass, entry)
    assert await known(hass, entry, device_rows(entry, WASHER))

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    assert not await known(hass, entry, device_rows(entry, WASHER))
    assert not await known(hass, entry, CONSUMPTION_COST)


async def test_diagnostics_report_the_devices(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    await name_sources(hass, devices=[device(WASHER, name="Washer")])
    await record(hass, IMPORT_ENTITY, DAY_START, [4.0])
    await record(hass, WASHER, DAY_START, [1.0])
    await refresh(hass, entry)

    report = await async_get_config_entry_diagnostics(hass, entry)

    assert report["household"]["consumption_cost"] == round(4 * BAND)
    assert report["devices"] == [
        {
            "statistic": WASHER,
            "name": "Washer",
            "included_in": None,
            "since": DAY_START.isoformat(),
            "kwh": pytest.approx(1.0),
            "share": pytest.approx(0.25),
            "cost": round(1 * BAND),
            "excess_kwh": 0.0,
        }
    ]
    assert statistic_id(entry.entry_id, device_rows(entry, WASHER)).endswith(
        "_device_sensor_washer_energy_cost"
    )


async def test_a_devices_cost_carries_the_figures_it_was_made_of(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    """Two kWh at the band price, one kWh of solar in surplus at the feed-in price."""

    await name_sources(hass, solar=[PRODUCTION_ENTITY], devices=[device(WASHER, name="Washer")])
    await record(hass, IMPORT_ENTITY, DAY_START, [4.0, 0.0, 0.0])
    await record(hass, EXPORT_ENTITY, DAY_START, [0.0, 100.0, 0.0])
    await record(hass, PRODUCTION_ENTITY, DAY_START, [0.0, 100.0, 2.0])
    await record(hass, WASHER, DAY_START, [2.0, 0.0, 1.0])
    await refresh(hass, entry)

    washer = hass.states.get(PREFIX + "washer_cost")
    assert washer is not None
    attributes = washer.attributes
    assert attributes["kwh_at_subsidized"] == pytest.approx(2.0)
    assert attributes["kwh_at_feed_in"] == pytest.approx(1.0)
    assert attributes["kwh_at_market"] == 0.0
    assert attributes["kwh_mixed"] == 0.0
    assert attributes["share_of_house"] == pytest.approx(3 / 6)
    assert attributes["capped_hours"] == 0
    assert attributes["subsidized_price_with_vat"] == pytest.approx(BAND)
    assert attributes["feed_in_price"] == FEED_IN
    assert attributes["average_per_kwh"] == pytest.approx((2 * BAND + FEED_IN) / 3, abs=0.01)

    house = hass.states.get(PREFIX + "consumption_cost")
    assert house is not None
    assert house.attributes["energy_kwh"] == pytest.approx(6.0)
    assert house.attributes["kwh_at_subsidized"] == pytest.approx(4.0)
    assert house.attributes["kwh_at_feed_in"] == pytest.approx(2.0)

    # Bought from the grid, every kWh would have cost the band price: the
    # panels saved the difference, on the device and on the house, and all
    # of it within the allowance.
    assert attributes["cost_without_panels"] == round(3 * BAND)
    assert attributes["saved_by_panels"] == round(3 * BAND) - round(2 * BAND + FEED_IN)
    assert attributes["bought_at_subsidized"] == round(3 * BAND)
    assert attributes["bought_at_market"] == 0
    assert attributes["kwh_bought_at_subsidized"] == pytest.approx(3.0)
    assert attributes["kwh_bought_at_market"] == 0.0
    assert house.attributes["cost_without_panels"] == round(6 * BAND)
    assert house.attributes["saved_by_panels"] == round(6 * BAND) - round(4 * BAND + 2 * FEED_IN)
    assert house.attributes["bought_at_subsidized"] == round(6 * BAND)
    assert house.attributes["kwh_bought_at_subsidized"] == pytest.approx(6.0)


async def test_bought_from_the_grid_the_market_band_follows_the_allowance(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    """With no allowance, every kWh bought would be at the market price, and
    the no-panels allowance is gone from the first hour."""

    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_ALLOWANCE_KWH: 0.0}
    )
    await hass.async_block_till_done()
    await name_sources(hass, solar=[PRODUCTION_ENTITY], devices=[device(WASHER, name="Washer")])
    await record(hass, IMPORT_ENTITY, DAY_START, [4.0, 0.0])
    await record(hass, PRODUCTION_ENTITY, DAY_START, [0.0, 2.0])
    await record(hass, WASHER, DAY_START, [2.0, 1.0])
    await refresh(hass, entry)

    washer = hass.states.get(PREFIX + "washer_cost")
    assert washer is not None
    assert washer.attributes["kwh_bought_at_market"] == pytest.approx(3.0)
    assert washer.attributes["kwh_bought_at_subsidized"] == 0.0
    assert washer.attributes["bought_at_market"] == round(3 * MARKET)
    assert washer.attributes["bought_at_subsidized"] == 0
    assert washer.attributes["cost_without_panels"] == round(3 * MARKET)
    assert state_of(hass, "allowance_runs_out_without_panels") == TODAY.isoformat()


async def test_without_panels_the_allowance_runs_out_without_them_is_unavailable(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    await record(hass, IMPORT_ENTITY, DAY_START, [4.0])
    await refresh(hass, entry)

    assert state_of(hass, "allowance_runs_out_without_panels") == STATE_UNAVAILABLE


async def test_without_panels_there_is_no_saving_to_report(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    """A household without panels has no figure, rather than a zero."""

    await name_sources(hass, devices=[device(WASHER, name="Washer")])
    await record(hass, IMPORT_ENTITY, DAY_START, [4.0])
    await record(hass, WASHER, DAY_START, [2.0])
    await refresh(hass, entry)

    washer = hass.states.get(PREFIX + "washer_cost")
    assert washer is not None
    assert "saved_by_panels" not in washer.attributes
    house = hass.states.get(PREFIX + "consumption_cost")
    assert house is not None
    assert "saved_by_panels" not in house.attributes



async def test_a_device_meter_that_reports_its_lifetime_total_is_set_aside(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    """A plug that leaps by its own reading is a glitch, not a burst."""

    await name_sources(hass, devices=[device(WASHER, name="Washer")])
    await record(hass, IMPORT_ENTITY, DAY_START, [1.0, 1.0])
    await record(hass, WASHER, DAY_START, [0.5, 0.5])
    booked = await record_rebook(hass, WASHER, DAY_START + timedelta(hours=1))
    await refresh(hass, entry)

    hourly = states(await rows(hass, entry, device_rows(entry, WASHER)))
    assert hourly[:2] == pytest.approx([0.5 * BAND, 0.0], abs=1e-4)
    registry = ir.async_get(hass)
    assert registry.async_get_issue(DOMAIN, f"device_bursts_{entry.entry_id}") is None
    issue = registry.async_get_issue(DOMAIN, f"source_glitches_{entry.entry_id}")
    assert issue is not None
    placeholders = issue.translation_placeholders or {}
    assert placeholders["sources"].startswith(f"{WASHER} (1 h, {booked:.1f} kWh, ")
    report = await async_get_config_entry_diagnostics(hass, entry)
    assert report["devices"][0]["kwh"] == pytest.approx(0.5)
