"""Fixtures for the Home Assistant integration tests.

These need Home Assistant installed, which the pure billing and generator tests
do not. They live apart so the rest of the suite stays fast and runnable on any
supported Python.
"""

from collections.abc import Generator
from datetime import date
from typing import Any

import pytest
from custom_components.hass_energy.const import (
    CONF_EXPORT_ENTITY,
    CONF_IMPORT_ENTITY,
    CONF_MAX_STEP_KWH,
    CONF_PRICES,
    DOMAIN,
)
from custom_components.hass_energy.settings import price_entry
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

IMPORT_ENTITY = "sensor.grid_import_energy"
EXPORT_ENTITY = "sensor.grid_export_energy"


@pytest.fixture
def prices() -> list[dict[str, Any]]:
    """A schedule with one change inside the period under test."""

    return [
        price_entry(date(2024, 1, 1), subsidized=36.386, market=70.104, feed_in=5.11),
        price_entry(date(2025, 8, 1), subsidized=40.0, market=80.0, feed_in=6.0),
    ]


@pytest.fixture
async def entry(
    enable_custom_integrations: None,
    hass: HomeAssistant,
    prices: list[dict[str, Any]],
) -> Generator[MockConfigEntry, None, None]:
    """A configured metering point with both meters present."""

    hass.states.async_set(IMPORT_ENTITY, "1000.0")
    hass.states.async_set(EXPORT_ENTITY, "2000.0")
    await async_setup_component(hass, "homeassistant", {})

    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test settlement",
        data={CONF_IMPORT_ENTITY: IMPORT_ENTITY, CONF_EXPORT_ENTITY: EXPORT_ENTITY},
        # The tests move a meter by a whole invoice in one step, which the
        # glitch guard would otherwise hold back. Its own tests set the limit.
        options={CONF_PRICES: prices, CONF_MAX_STEP_KWH: 100000.0},
    )
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    yield config_entry
