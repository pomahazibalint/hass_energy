"""The hourly costs, as statistics for the energy dashboard."""

from datetime import timedelta
from functools import partial

import pytest
from custom_components.hass_energy.const import (
    ATTR_READING_DATE,
    CONF_PRICES,
    DOMAIN,
    SERVICE_CLOSE_SETTLEMENT,
)
from custom_components.hass_energy.costs import (
    COST_KINDS,
    EXPORT_COMPENSATION,
    GRID_COST,
    HOUSEHOLD_KINDS,
    statistic_id,
)
from custom_components.hass_energy.settings import price_entry
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_metadata,
    statistics_during_period,
)
from homeassistant.components.recorder.util import get_instance
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from .conftest import (
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

VAT = 1.27


async def rows(hass: HomeAssistant, entry: MockConfigEntry, kind: str) -> list[dict]:
    """Every hour written for one cost statistic, oldest first."""

    await async_wait_recording_done(hass)
    stat_id = statistic_id(entry.entry_id, kind)
    stats = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        local_midnight(TODAY - timedelta(days=30)),
        None,
        {stat_id},
        "hour",
        None,
        {"state", "sum"},
    )
    return list(stats.get(stat_id, []))


def states(hourly: list[dict]) -> list[float]:
    return [round(row["state"], 4) for row in hourly]


async def test_each_hour_carries_the_change_in_the_bill(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    await record(hass, IMPORT_ENTITY, DAY_START, [10.0, 0.0, 5.0])
    await record(hass, EXPORT_ENTITY, DAY_START, [0.0, 4.0, 0.0])
    await refresh(hass, entry)

    cost = await rows(hass, entry, GRID_COST)
    assert [row["start"] for row in cost[:3]] == [
        (DAY_START + timedelta(hours=i)).timestamp() for i in range(3)
    ]
    # Import at 40 with VAT, then export cancelling four of those kWh.
    assert states(cost)[:3] == pytest.approx([10 * 40 * VAT, -4 * 40 * VAT, 5 * 40 * VAT])
    assert cost[2]["sum"] == pytest.approx(11 * 40 * VAT)
    assert sum(row["state"] for row in cost) == pytest.approx(
        coordinator(entry).data.energy_gross
    )


async def test_surplus_is_compensation_not_negative_cost(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    await record(hass, EXPORT_ENTITY, DAY_START, [100.0, 100.0])
    await refresh(hass, entry)

    cost = await rows(hass, entry, GRID_COST)
    compensation = await rows(hass, entry, EXPORT_COMPENSATION)
    assert states(cost)[:2] == [0.0, 0.0]
    assert states(compensation)[:2] == [600.0, 600.0]
    assert compensation[1]["sum"] == 1200.0


async def test_the_statistics_speak_the_dashboards_currency(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    await record(hass, IMPORT_ENTITY, DAY_START, [1.0])
    await refresh(hass, entry)
    await async_wait_recording_done(hass)

    metadata = await get_instance(hass).async_add_executor_job(
        partial(get_metadata, hass, statistic_ids={statistic_id(entry.entry_id, GRID_COST)})
    )
    _, meta = metadata[statistic_id(entry.entry_id, GRID_COST)]
    assert meta["unit_of_measurement"] == hass.config.currency
    assert meta["has_sum"] is True
    assert meta["source"] == DOMAIN
    assert meta["name"] == "Grid cost"


async def test_a_backdated_price_rewrites_the_hours_it_covers(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    """History is corrected in place, not as a spike in the hour of the edit."""

    two_days_ago = TODAY - timedelta(days=2)
    yesterday = TODAY - timedelta(days=1)
    await hass.services.async_call(
        DOMAIN, SERVICE_CLOSE_SETTLEMENT, {ATTR_READING_DATE: two_days_ago}, blocking=True
    )
    await record(hass, IMPORT_ENTITY, local_midnight(two_days_ago), [10.0])
    await record(hass, IMPORT_ENTITY, local_midnight(yesterday), [10.0])
    await refresh(hass, entry)
    before = {row["start"]: row["state"] for row in await rows(hass, entry, GRID_COST)}
    assert before[local_midnight(yesterday).timestamp()] == pytest.approx(10 * 40 * VAT)

    hass.config_entries.async_update_entry(
        entry,
        options={
            **entry.options,
            CONF_PRICES: [*entry.options[CONF_PRICES], price_entry(yesterday, 80.0, 90.0, 7.0)],
        },
    )
    await hass.async_block_till_done()

    after = {row["start"]: row["state"] for row in await rows(hass, entry, GRID_COST)}
    assert after[local_midnight(two_days_ago).timestamp()] == pytest.approx(10 * 40 * VAT)
    assert after[local_midnight(yesterday).timestamp()] == pytest.approx(10 * 80 * VAT)
    assert sum(after.values()) == pytest.approx(coordinator(entry).data.energy_gross)


async def test_the_sum_continues_across_a_closed_settlement(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    yesterday = TODAY - timedelta(days=1)
    await hass.services.async_call(
        DOMAIN, SERVICE_CLOSE_SETTLEMENT, {ATTR_READING_DATE: yesterday}, blocking=True
    )
    await record(hass, IMPORT_ENTITY, local_midnight(yesterday), [10.0])
    await record(hass, IMPORT_ENTITY, DAY_START, [5.0])
    await refresh(hass, entry)
    before = {row["start"]: row for row in await rows(hass, entry, GRID_COST)}
    last_of_old = before[(DAY_START - timedelta(hours=1)).timestamp()]

    await hass.services.async_call(
        DOMAIN, SERVICE_CLOSE_SETTLEMENT, {ATTR_READING_DATE: TODAY}, blocking=True
    )
    await hass.async_block_till_done()

    after = {row["start"]: row for row in await rows(hass, entry, GRID_COST)}
    first_of_new = after[DAY_START.timestamp()]
    assert first_of_new["state"] == pytest.approx(5 * 40 * VAT)
    assert first_of_new["sum"] == pytest.approx(last_of_old["sum"] + 5 * 40 * VAT)
    # The old period's hours are untouched.
    assert after[local_midnight(yesterday).timestamp()]["state"] == pytest.approx(10 * 40 * VAT)


async def test_unchanged_hours_are_not_rewritten(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    await record(hass, IMPORT_ENTITY, DAY_START, [10.0])
    await refresh(hass, entry)
    first = await rows(hass, entry, GRID_COST)

    await refresh(hass, entry)

    assert await rows(hass, entry, GRID_COST) == first


async def test_removing_the_entry_removes_its_statistics(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    await name_sources(hass, solar=[PRODUCTION_ENTITY])
    await record(hass, IMPORT_ENTITY, DAY_START, [10.0])
    await record(hass, PRODUCTION_ENTITY, DAY_START, [2.0])
    await refresh(hass, entry)
    await async_wait_recording_done(hass)
    every = {statistic_id(entry.entry_id, kind) for kind in (*COST_KINDS, *HOUSEHOLD_KINDS)}
    written = await get_instance(hass).async_add_executor_job(
        partial(get_metadata, hass, statistic_ids=every)
    )
    assert set(written) == every

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    await async_wait_recording_done(hass)

    metadata = await get_instance(hass).async_add_executor_job(
        partial(get_metadata, hass, statistic_ids=every)
    )
    assert metadata == {}


async def test_hours_nobody_watched_are_not_published(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    """Seeded energy is in the bill, not smeared over the dashboard's history."""

    await coordinator(entry).async_seed(TODAY - timedelta(days=10), imported=1000.0, exported=0.0)
    await hass.async_block_till_done()
    assert coordinator(entry).data.readings.imported_kwh == pytest.approx(1000.0)
    assert await rows(hass, entry, GRID_COST) == []

    await record(hass, IMPORT_ENTITY, DAY_START, [10.0])
    await refresh(hass, entry)

    cost = await rows(hass, entry, GRID_COST)
    # From the first recorded hour on, nothing earlier.
    assert cost[0]["start"] == DAY_START.timestamp()
    assert cost[0]["state"] == pytest.approx(10 * 40 * VAT)
    assert all(row["state"] == 0 for row in cost[1:])


async def test_statistics_are_named_without_the_entry_title(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    """A legend that repeats the entry's title on every series says nothing."""

    await record(hass, IMPORT_ENTITY, DAY_START, [1.0])
    await refresh(hass, entry)
    await async_wait_recording_done(hass)

    stat_id = statistic_id(entry.entry_id, GRID_COST)
    metadata = await get_instance(hass).async_add_executor_job(
        partial(get_metadata, hass, statistic_ids={stat_id})
    )
    assert metadata[stat_id][1]["name"] == "Grid cost"


async def test_a_statistic_written_under_an_old_name_is_renamed_in_place(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    await record(hass, IMPORT_ENTITY, DAY_START, [1.0])
    await refresh(hass, entry)
    await async_wait_recording_done(hass)
    stat_id = statistic_id(entry.entry_id, GRID_COST)
    old = await get_instance(hass).async_add_executor_job(
        partial(get_metadata, hass, statistic_ids={stat_id})
    )
    renamed = {**old[stat_id][1], "name": "Test settlement grid cost"}
    async_add_external_statistics(hass, renamed, [])
    await async_wait_recording_done(hass)

    # Nothing about the hours changed, so only the name has to.
    await refresh(hass, entry)
    await async_wait_recording_done(hass)

    metadata = await get_instance(hass).async_add_executor_job(
        partial(get_metadata, hass, statistic_ids={stat_id})
    )
    assert metadata[stat_id][1]["name"] == "Grid cost"

