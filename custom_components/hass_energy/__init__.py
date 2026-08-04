"""Energy settlement accounting for Home Assistant."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from .const import ATTR_READING_DATE, DOMAIN, SERVICE_CLOSE_SETTLEMENT
from .coordinator import SettlementCoordinator

PLATFORMS = [Platform.SENSOR]

type SettlementEntry = ConfigEntry[SettlementCoordinator]

CLOSE_SETTLEMENT_SCHEMA = vol.Schema(
    {vol.Optional(ATTR_READING_DATE): cv.date}
)


async def async_setup_entry(hass: HomeAssistant, entry: SettlementEntry) -> bool:
    """Set up one metering point."""

    coordinator = SettlementCoordinator(hass, entry)
    await coordinator.async_load()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_options_updated))
    _register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SettlementEntry) -> bool:
    await entry.runtime_data.async_shutdown()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _options_updated(hass: HomeAssistant, entry: SettlementEntry) -> None:
    """Re-derive the settlement when the contract changes.

    Nothing recorded moves; a corrected price simply makes the same quantities
    worth something else.
    """

    coordinator = entry.runtime_data
    coordinator.async_set_updated_data(coordinator.build_bill())


def _register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_CLOSE_SETTLEMENT):
        return

    async def close_settlement(call: ServiceCall) -> None:
        """Start a new settlement period on the day the meter was read."""

        reading_date = call.data.get(ATTR_READING_DATE) or dt_util.now().date()
        for entry in hass.config_entries.async_loaded_entries(DOMAIN):
            await entry.runtime_data.async_close_settlement(reading_date)

    hass.services.async_register(
        DOMAIN, SERVICE_CLOSE_SETTLEMENT, close_settlement, schema=CLOSE_SETTLEMENT_SCHEMA
    )
