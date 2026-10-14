"""What the house did, from the sources the energy dashboard names."""

from datetime import date, timedelta
from functools import partial

import pytest
from custom_components.hass_energy.const import (
    ATTR_READING_DATE,
    CONF_IMPORT_ENTITY,
    CONF_PRICES,
    DOMAIN,
    SERVICE_CLOSE_SETTLEMENT,
)
from custom_components.hass_energy.costs import (
    HOUSE_CONSUMPTION,
    SELF_CONSUMED_SOLAR,
    SOLAR_VALUE,
    statistic_id,
)
from custom_components.hass_energy.diagnostics import async_get_config_entry_diagnostics
from custom_components.hass_energy.preferences import FOLLOWERS
from custom_components.hass_energy.settings import price_entry
from homeassistant.components.recorder.statistics import get_metadata
from homeassistant.components.recorder.util import get_instance
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from .conftest import (
    BATTERY_CHARGE_ENTITY,
    BATTERY_DISCHARGE_ENTITY,
    DAY_START,
    EXPORT_ENTITY,
    IMPORT_ENTITY,
    PRODUCTION_ENTITY,
    TODAY,
    coordinator,
    local_midnight,
    name_sources,
    record,
    refresh,
)
from .test_costs import rows, states
from .test_sensor import state_of


async def known(hass: HomeAssistant, entry: MockConfigEntry, kind: str) -> bool:
    """Whether the recorder has a statistic of this kind for the entry."""

    await async_wait_recording_done(hass)
    stat_id = statistic_id(entry.entry_id, kind)
    metadata = await get_instance(hass).async_add_executor_job(
        partial(get_metadata, hass, statistic_ids={stat_id})
    )
    return stat_id in metadata


async def test_consumption_is_what_entered_the_house_less_what_left(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    await name_sources(hass, solar=[PRODUCTION_ENTITY])
    await record(hass, IMPORT_ENTITY, DAY_START, [1.0, 0.5])
    await record(hass, EXPORT_ENTITY, DAY_START, [2.0, 0.0])
    await record(hass, PRODUCTION_ENTITY, DAY_START, [4.0, 1.0])
    await refresh(hass, entry)

    assert states(await rows(hass, entry, HOUSE_CONSUMPTION))[:2] == [3.0, 1.5]
    assert states(await rows(hass, entry, SELF_CONSUMED_SOLAR))[:2] == [2.0, 1.0]
    assert state_of(hass, "house_consumption") == "4.5"
    assert state_of(hass, "self_consumed_solar") == "3.0"


async def test_a_battery_moves_energy_between_hours(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    await name_sources(
        hass, solar=[PRODUCTION_ENTITY], battery=(BATTERY_CHARGE_ENTITY, BATTERY_DISCHARGE_ENTITY)
    )
    await record(hass, IMPORT_ENTITY, DAY_START, [0.0, 0.0])
    await record(hass, PRODUCTION_ENTITY, DAY_START, [3.0, 0.0])
    await record(hass, BATTERY_CHARGE_ENTITY, DAY_START, [2.0, 0.0])
    await record(hass, BATTERY_DISCHARGE_ENTITY, DAY_START, [0.0, 2.0])
    await refresh(hass, entry)

    assert states(await rows(hass, entry, HOUSE_CONSUMPTION))[:2] == [1.0, 2.0]


async def test_two_inverters_are_summed(entry: MockConfigEntry, hass: HomeAssistant) -> None:
    second = "sensor.second_inverter_energy"
    await name_sources(hass, solar=[PRODUCTION_ENTITY, second])
    await record(hass, IMPORT_ENTITY, DAY_START, [0.0])
    await record(hass, PRODUCTION_ENTITY, DAY_START, [1.0])
    await record(hass, second, DAY_START, [2.0])
    await refresh(hass, entry)

    assert states(await rows(hass, entry, HOUSE_CONSUMPTION))[:1] == [3.0]


async def test_without_a_solar_source_the_solar_figures_are_unavailable(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    await record(hass, IMPORT_ENTITY, DAY_START, [5.0])
    await refresh(hass, entry)

    assert state_of(hass, "self_consumed_solar") == STATE_UNAVAILABLE
    assert state_of(hass, "solar_value") == STATE_UNAVAILABLE
    assert states(await rows(hass, entry, HOUSE_CONSUMPTION))[:1] == [5.0]
    assert not await known(hass, entry, SELF_CONSUMED_SOLAR)
    assert not await known(hass, entry, SOLAR_VALUE)


async def test_the_panels_are_worth_the_bill_there_would_be_without_them(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    await name_sources(hass, solar=[PRODUCTION_ENTITY])
    await record(hass, IMPORT_ENTITY, DAY_START, [10.0, 0.0])
    await record(hass, EXPORT_ENTITY, DAY_START, [0.0, 4.0])
    await record(hass, PRODUCTION_ENTITY, DAY_START, [2.0, 7.0])
    await refresh(hass, entry)

    # The panels kept 2 kWh in the first hour and 3 in the second, the rest
    # was exported. Without them the household imports 15 kWh and exports
    # nothing; with them it nets 6. Nine kWh at the subsidized rate of 40,
    # with VAT, is what they were worth.
    bill = coordinator(entry).data
    without = coordinator(entry).bill_without_solar
    assert without is not None
    assert without.readings.imported_kwh == pytest.approx(15.0)
    assert without.readings.exported_kwh == 0.0
    assert float(state_of(hass, "solar_value")) == without.net_position - bill.net_position
    assert float(state_of(hass, "solar_value")) == pytest.approx(9 * 40, abs=1)
    assert sum(states(await rows(hass, entry, SOLAR_VALUE))) == pytest.approx(
        9 * 40, abs=0.01
    )


async def test_naming_a_source_in_the_dashboard_refreshes_the_figures(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    await record(hass, IMPORT_ENTITY, DAY_START, [0.0])
    await record(hass, PRODUCTION_ENTITY, DAY_START, [3.0])
    assert state_of(hass, "self_consumed_solar") == STATE_UNAVAILABLE

    await name_sources(hass, solar=[PRODUCTION_ENTITY])

    assert state_of(hass, "self_consumed_solar") == "3.0"


async def test_dropping_the_solar_source_removes_its_statistics(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    await name_sources(hass, solar=[PRODUCTION_ENTITY])
    await record(hass, IMPORT_ENTITY, DAY_START, [0.0])
    await record(hass, PRODUCTION_ENTITY, DAY_START, [3.0])
    await refresh(hass, entry)
    assert await known(hass, entry, SELF_CONSUMED_SOLAR)
    assert await known(hass, entry, SOLAR_VALUE)

    await name_sources(hass)
    await refresh(hass, entry)

    assert not await known(hass, entry, SELF_CONSUMED_SOLAR)
    assert not await known(hass, entry, SOLAR_VALUE)
    assert await known(hass, entry, HOUSE_CONSUMPTION)


async def test_sources_that_disagree_are_a_repair_not_a_smoothed_figure(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    """An inverter reporting an hour late exports energy that never entered."""

    await name_sources(hass, solar=[PRODUCTION_ENTITY])
    await record(hass, IMPORT_ENTITY, DAY_START, [0.5, 0.5, 0.5])
    await record(hass, EXPORT_ENTITY, DAY_START, [2.0, 0.0, 3.0])
    await record(hass, PRODUCTION_ENTITY, DAY_START, [0.0, 2.0, 0.0])
    await refresh(hass, entry)

    assert states(await rows(hass, entry, HOUSE_CONSUMPTION))[:3] == [0.0, 2.5, 0.0]
    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"sources_disagree_{entry.entry_id}")
    assert issue is not None
    assert issue.translation_placeholders == {
        "hours": "2",
        "lost_kwh": "4.0",
        "worst": dt_util.as_local(DAY_START + timedelta(hours=2)).isoformat(timespec="minutes"),
    }

    report = await async_get_config_entry_diagnostics(hass, entry)
    worst = report["disagreement"]["worst_hours"]
    assert [hour["lost_kwh"] for hour in worst] == pytest.approx([2.5, 1.5])
    assert worst[0]["start"] == dt_util.as_local(DAY_START + timedelta(hours=2)).isoformat(
        timespec="minutes"
    )
    assert worst[0]["exported_kwh"] == 3.0
    assert worst[0]["produced_kwh"] == 0.0
    assert worst[0]["no_row"] == []

    await record(hass, PRODUCTION_ENTITY, DAY_START, [2.0, 0.0, 3.0])
    await refresh(hass, entry)

    assert ir.async_get(hass).async_get_issue(DOMAIN, f"sources_disagree_{entry.entry_id}") is None
    report = await async_get_config_entry_diagnostics(hass, entry)
    assert report["disagreement"]["worst_hours"] == []


async def test_an_inverter_that_dropped_out_for_an_hour_is_named(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    """Export the grid meter counted in an hour the inverter has no row for."""

    await name_sources(hass, solar=[PRODUCTION_ENTITY])
    await record(hass, IMPORT_ENTITY, DAY_START, [0.0, 0.0, 0.0])
    await record(hass, EXPORT_ENTITY, DAY_START, [1.0, 4.0, 1.0])
    await record(hass, PRODUCTION_ENTITY, DAY_START, [2.0])
    await record(hass, PRODUCTION_ENTITY, DAY_START + timedelta(hours=2), [2.0])
    await refresh(hass, entry)

    report = await async_get_config_entry_diagnostics(hass, entry)
    worst = report["disagreement"]["worst_hours"]
    assert len(worst) == 1
    assert worst[0]["lost_kwh"] == pytest.approx(4.0)
    assert worst[0]["no_row"] == [PRODUCTION_ENTITY]


async def test_a_solar_source_the_recorder_never_compiled_is_raised(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    await name_sources(hass, solar=["sensor.nothing_recorded"])
    await refresh(hass, entry)

    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"source_unrecorded_{entry.entry_id}")
    assert issue is not None
    assert "sensor.nothing_recorded" in issue.translation_placeholders["entities"]  # type: ignore[index]


async def test_diagnostics_report_the_household(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    await name_sources(hass, solar=[PRODUCTION_ENTITY])
    await record(hass, IMPORT_ENTITY, DAY_START, [1.0])
    await record(hass, PRODUCTION_ENTITY, DAY_START + timedelta(hours=1), [2.0])
    await refresh(hass, entry)

    report = await async_get_config_entry_diagnostics(hass, entry)

    assert report["sources"]["production"] == [PRODUCTION_ENTITY]
    assert report["observed"]["first_of"][PRODUCTION_ENTITY] == (
        DAY_START + timedelta(hours=1)
    ).isoformat()
    # The house is known from the inverter's first hour; the import before
    # it belongs to the bill, not to the house's figures.
    assert report["household"]["since"] == (DAY_START + timedelta(hours=1)).isoformat()
    assert report["household"]["consumption_kwh"] == pytest.approx(2.0)
    assert report["household"]["consumption_kwh"] == float(state_of(hass, "house_consumption"))
    assert report["disagreement"]["hours"] == 0
    assert report["household"]["solar_value"] == pytest.approx(2 * 40, abs=1)


async def test_export_above_import_with_no_production_source_is_not_a_disagreement(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    """A house that feeds in without a named inverter has unrecorded panels, not a fault."""

    await record(hass, IMPORT_ENTITY, DAY_START, [1.0, 0.0])
    await record(hass, EXPORT_ENTITY, DAY_START, [0.0, 3.0])
    await refresh(hass, entry)

    assert ir.async_get(hass).async_get_issue(DOMAIN, f"sources_disagree_{entry.entry_id}") is None


async def test_the_house_is_known_only_from_the_hour_its_sources_cover(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    """An inverter recorded from hour three says nothing about hours one and two."""

    await name_sources(hass, solar=[PRODUCTION_ENTITY])
    await record(hass, IMPORT_ENTITY, DAY_START, [1.0, 0.0, 0.5])
    await record(hass, EXPORT_ENTITY, DAY_START, [0.0, 3.0, 0.0])
    await record(hass, PRODUCTION_ENTITY, DAY_START + timedelta(hours=2), [2.0])
    await refresh(hass, entry)

    assert ir.async_get(hass).async_get_issue(DOMAIN, f"sources_disagree_{entry.entry_id}") is None
    consumption = await rows(hass, entry, HOUSE_CONSUMPTION)
    assert consumption[0]["start"] == (DAY_START + timedelta(hours=2)).timestamp()
    assert states(consumption)[:1] == [2.5]
    assert state_of(hass, "house_consumption") == "2.5"
    # The bill's own figures still run from the first hour of the grid record.
    assert (await rows(hass, entry, "grid_cost"))[0]["start"] == DAY_START.timestamp()


async def test_production_before_the_grid_record_is_not_the_houses(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    """An inverter recorded before the grid meters, and a seeded period.

    The remainder is spread over the hours before the grid record and none
    of them is published, as without an inverter; and the inverter's early
    hours are not credited as consumption or value, since nothing is known
    of the grid then.
    """

    start = TODAY - timedelta(days=2)
    await name_sources(hass, solar=[PRODUCTION_ENTITY])
    await record(hass, PRODUCTION_ENTITY, local_midnight(start), [2.0] * 48)
    await record(hass, IMPORT_ENTITY, DAY_START, [1.0])
    await coordinator(entry).async_seed(start, imported=100.0, exported=0.0)
    await hass.async_block_till_done()

    for kind in (SOLAR_VALUE, HOUSE_CONSUMPTION, "grid_cost"):
        hourly = await rows(hass, entry, kind)
        assert hourly[0]["start"] == DAY_START.timestamp(), kind
    assert coordinator(entry).state.unobserved_imported == pytest.approx(99.0)
    assert coordinator(entry).solar_value_total() == 0
    assert state_of(hass, "self_consumed_solar") == "0.0"


async def test_the_panels_belong_to_the_metering_point_the_dashboard_names(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    """A heat pump on its own meter is a second entry the panels never fed."""

    heat_pump = "sensor.heat_pump_import_energy"
    hass.states.async_set(heat_pump, "500.0")
    second = MockConfigEntry(
        domain=DOMAIN,
        title="Heat pump",
        data={CONF_IMPORT_ENTITY: heat_pump},
        options={CONF_PRICES: [price_entry(date(2024, 1, 1), 36.386, 70.104, 5.11)]},
    )
    second.add_to_hass(hass)
    await hass.config_entries.async_setup(second.entry_id)
    await name_sources(hass, grid=IMPORT_ENTITY, solar=[PRODUCTION_ENTITY])
    await record(hass, IMPORT_ENTITY, DAY_START, [0.0])
    await record(hass, PRODUCTION_ENTITY, DAY_START, [3.0])
    await record(hass, heat_pump, DAY_START, [1.0])
    await refresh(hass, entry)
    await refresh(hass, second)

    assert state_of(hass, "self_consumed_solar") == "3.0"
    assert coordinator(second).sources.production == ()
    heat_pump_solar = hass.states.get("sensor.heat_pump_self_consumed_solar")
    assert heat_pump_solar is not None and heat_pump_solar.state == STATE_UNAVAILABLE
    assert states(await rows(hass, second, HOUSE_CONSUMPTION))[:1] == [1.0]


async def test_a_grid_source_stored_in_the_old_format_still_names_the_meter(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    """Before 2026.10 the grid source carried lists of flows; a stored one still may."""

    await name_sources(hass, grid=IMPORT_ENTITY, solar=[PRODUCTION_ENTITY], legacy_grid=True)
    await record(hass, IMPORT_ENTITY, DAY_START, [0.0])
    await record(hass, PRODUCTION_ENTITY, DAY_START, [3.0])
    await refresh(hass, entry)

    assert coordinator(entry).sources.production == (PRODUCTION_ENTITY,)
    assert state_of(hass, "self_consumed_solar") == "3.0"


async def test_closing_the_settlement_keeps_the_houses_figures(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    await name_sources(hass, solar=[PRODUCTION_ENTITY])
    await record(hass, IMPORT_ENTITY, DAY_START, [0.0])
    await record(hass, PRODUCTION_ENTITY, DAY_START, [2.0])
    await refresh(hass, entry)

    await hass.services.async_call(
        DOMAIN, SERVICE_CLOSE_SETTLEMENT, {ATTR_READING_DATE: TODAY}, blocking=True
    )
    await hass.async_block_till_done()

    assert state_of(hass, "self_consumed_solar") == "2.0"


async def test_the_house_is_known_only_once_every_source_has_begun(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    """A second inverter recorded from hour three is unknown, not zero, before it."""

    second = "sensor.second_inverter_energy"
    await name_sources(hass, solar=[PRODUCTION_ENTITY, second])
    await record(hass, IMPORT_ENTITY, DAY_START, [0.0, 0.0, 0.0])
    await record(hass, EXPORT_ENTITY, DAY_START, [3.0, 3.0, 0.0])
    await record(hass, PRODUCTION_ENTITY, DAY_START, [1.0, 1.0, 1.0])
    await record(hass, second, DAY_START + timedelta(hours=2), [2.0])
    await refresh(hass, entry)

    assert ir.async_get(hass).async_get_issue(DOMAIN, f"sources_disagree_{entry.entry_id}") is None
    consumption = await rows(hass, entry, HOUSE_CONSUMPTION)
    assert consumption[0]["start"] == (DAY_START + timedelta(hours=2)).timestamp()
    assert states(consumption)[:1] == [3.0]
    assert state_of(hass, "house_consumption") == "3.0"


async def test_a_named_source_with_no_rows_leaves_the_house_unknown(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    await record(hass, IMPORT_ENTITY, DAY_START, [10.0])
    await refresh(hass, entry)
    assert state_of(hass, "house_consumption") == "10.0"

    await name_sources(hass, solar=["sensor.inverter_not_yet_recorded"])

    assert state_of(hass, "house_consumption") == STATE_UNAVAILABLE
    assert state_of(hass, "self_consumed_solar") == STATE_UNAVAILABLE
    assert state_of(hass, "solar_value") == STATE_UNAVAILABLE
    assert await rows(hass, entry, HOUSE_CONSUMPTION) == (
        await rows(hass, entry, HOUSE_CONSUMPTION)
    )


async def test_an_hour_carrying_the_seeded_remainder_is_not_published(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    """A record that begins on the period's first hour has nowhere earlier for the seed.

    It lands on that hour for the bill, and that hour is left out of every
    statistic, so the dashboard and the sensors agree on what was seen.
    """

    await name_sources(hass, solar=[PRODUCTION_ENTITY])
    await record(hass, IMPORT_ENTITY, DAY_START, [1.0, 1.0])
    await record(hass, PRODUCTION_ENTITY, DAY_START, [5.0, 0.0])
    await coordinator(entry).async_seed(TODAY, imported=100.0, exported=50.0)
    await hass.async_block_till_done()

    for kind in (HOUSE_CONSUMPTION, SELF_CONSUMED_SOLAR, SOLAR_VALUE, "grid_cost"):
        hourly = await rows(hass, entry, kind)
        assert hourly[0]["start"] == (DAY_START + timedelta(hours=1)).timestamp(), kind
    assert state_of(hass, "house_consumption") == "7.0"
    assert state_of(hass, "self_consumed_solar") == "5.0"
    assert coordinator(entry).data.readings.imported_kwh == pytest.approx(100.0)


async def test_reloading_the_entry_does_not_leave_a_listener_behind(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    assert len(hass.data[FOLLOWERS]) == 1

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert len(hass.data[FOLLOWERS]) == 1
    await name_sources(hass, solar=[PRODUCTION_ENTITY])
    assert coordinator(entry).sources.production == (PRODUCTION_ENTITY,)
