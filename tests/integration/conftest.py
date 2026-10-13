"""Fixtures for the Home Assistant integration tests.

These need Home Assistant installed, which the pure billing and generator tests
do not. They live apart so the rest of the suite stays fast and runnable on any
supported Python.

The settlement is read from the recorder's long-term statistics, so the tests
put hours into the recorder directly rather than moving sensor states, and run
on a frozen clock so that "today" and the hours before it are known.
"""

from collections.abc import AsyncGenerator, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from custom_components.hass_energy.const import (
    CONF_EXPORT_ENTITY,
    CONF_IMPORT_ENTITY,
    CONF_PRICES,
    DOMAIN,
)
from custom_components.hass_energy.coordinator import SettlementCoordinator
from custom_components.hass_energy.settings import price_entry
from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.energy.data import async_get_manager
from homeassistant.components.recorder import Recorder
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.models.statistics import StatisticMeanType
from homeassistant.components.recorder.statistics import async_import_statistics
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

IMPORT_ENTITY = "sensor.grid_import_energy"
EXPORT_ENTITY = "sensor.grid_export_energy"
PRODUCTION_ENTITY = "sensor.solar_production_energy"
BATTERY_CHARGE_ENTITY = "sensor.battery_charge_energy"
BATTERY_DISCHARGE_ENTITY = "sensor.battery_discharge_energy"

#: The test instance runs on US/Pacific. 20:00 UTC is 13:00 local, so the
#: local day began at 07:00 UTC and thirteen complete hours of it exist.
NOW = datetime(2026, 10, 11, 20, 0, tzinfo=UTC)
TODAY = date(2026, 10, 11)
DAY_START = datetime(2026, 10, 11, 7, 0, tzinfo=UTC)


def local_midnight(day: date) -> datetime:
    """The UTC instant a local day began, on the test instance's clock."""

    return DAY_START + timedelta(days=(day - TODAY).days)


@pytest.fixture
def prices() -> list[dict[str, Any]]:
    """A schedule with one change inside the period under test."""

    return [
        price_entry(date(2024, 1, 1), subsidized=36.386, market=70.104, feed_in=5.11),
        price_entry(date(2025, 8, 1), subsidized=40.0, market=80.0, feed_in=6.0),
    ]


@pytest.fixture
def frozen(freezer: FrozenDateTimeFactory) -> FrozenDateTimeFactory:
    freezer.move_to(NOW)
    return freezer


@pytest.fixture
async def entry(
    recorder_mock: Recorder,
    enable_custom_integrations: None,
    frozen: FrozenDateTimeFactory,
    hass: HomeAssistant,
    prices: list[dict[str, Any]],
) -> AsyncGenerator[MockConfigEntry]:
    """A configured metering point with both meters present and a recorder."""

    hass.states.async_set(IMPORT_ENTITY, "1000.0")
    hass.states.async_set(EXPORT_ENTITY, "2000.0")
    await async_setup_component(hass, "homeassistant", {})

    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test settlement",
        data={CONF_IMPORT_ENTITY: IMPORT_ENTITY, CONF_EXPORT_ENTITY: EXPORT_ENTITY},
        options={CONF_PRICES: prices},
    )
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    yield config_entry


def coordinator(entry: MockConfigEntry) -> SettlementCoordinator:
    data: SettlementCoordinator = entry.runtime_data
    return data


async def record(
    hass: HomeAssistant, entity_id: str, start: datetime, kwh_per_hour: Sequence[float]
) -> None:
    """Put hourly energy for a source into the recorder's long-term statistics.

    ``start`` is the first hour's UTC start; each quantity is one hour's kWh.
    The recorder derives an hour's change from consecutive sums, so every call
    rewrites the source's whole series with the sums recomputed in time order,
    which lets a test record hours in any order.
    """

    recorded: dict[str, dict[datetime, float]] = hass.data.setdefault("_test_recorded", {})
    series = recorded.setdefault(entity_id, {})
    for i, kwh in enumerate(kwh_per_hour):
        series[start + timedelta(hours=i)] = kwh

    metadata = StatisticMetaData(
        mean_type=StatisticMeanType.NONE,
        has_sum=True,
        name=None,
        source="recorder",
        statistic_id=entity_id,
        unit_class="energy",
        unit_of_measurement="kWh",
    )
    running = 0.0
    rows: list[StatisticData] = []
    for hour in sorted(series):
        running += series[hour]
        rows.append(StatisticData(start=hour, state=running, sum=running))
    async_import_statistics(hass, metadata, rows)
    await async_wait_recording_done(hass)


async def refresh(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Re-derive the settlement, as the recorder's hourly compile would."""

    await coordinator(entry).async_refresh()
    await hass.async_block_till_done()


async def name_sources(
    hass: HomeAssistant,
    *,
    solar: Sequence[str] = (),
    battery: tuple[str, str] | None = None,
    grid: str | None = None,
    devices: Sequence[dict[str, Any]] = (),
    legacy_grid: bool = False,
) -> None:
    """Name the household's sources as the energy dashboard's settings would.

    ``battery`` is the charge and discharge statistics, in that order,
    ``grid`` the import meter the dashboard's grid source names, and
    ``devices`` the device consumption rows as the preferences hold them.
    Saving the preferences is what the dashboard does, so the integration
    hears about it the same way. ``legacy_grid`` writes the grid source as
    Home Assistant did before 2026.10, with lists of flows, which a stored
    document keeps until it is next saved.
    """

    sources: list[Any] = [
        {"type": "solar", "stat_energy_from": source, "config_entry_solar_forecast": None}
        for source in solar
    ]
    if grid and legacy_grid:
        sources.insert(
            0,
            {
                "type": "grid",
                "flow_from": [
                    {
                        "stat_energy_from": grid,
                        "stat_cost": None,
                        "entity_energy_price": None,
                        "number_energy_price": None,
                    }
                ],
                "flow_to": [],
                "cost_adjustment_day": 0,
            },
        )
    elif grid:
        sources.insert(
            0,
            {
                "type": "grid",
                "stat_energy_from": grid,
                "stat_energy_to": None,
                "stat_cost": None,
                "entity_energy_price": None,
                "number_energy_price": None,
                "stat_compensation": None,
                "entity_energy_price_export": None,
                "number_energy_price_export": None,
                "cost_adjustment_day": 0,
            },
        )
    if battery:
        charge, discharge = battery
        sources.append(
            {"type": "battery", "stat_energy_from": discharge, "stat_energy_to": charge}
        )
    manager = await async_get_manager(hass)
    await manager.async_update({"energy_sources": sources, "device_consumption": list(devices)})
    await hass.async_block_till_done()
