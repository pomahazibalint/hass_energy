"""Energy settlement accounting for Home Assistant."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import SettlementCoordinator
from .services import register as register_services

PLATFORMS = [Platform.SENSOR]

type SettlementEntry = ConfigEntry[SettlementCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: SettlementEntry) -> bool:
    """Set up one metering point."""

    coordinator = SettlementCoordinator(hass, entry)
    await coordinator.async_load()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_options_updated))
    register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SettlementEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _options_updated(hass: HomeAssistant, entry: SettlementEntry) -> None:
    """Re-derive the settlement when the contract changes.

    Nothing recorded moves; a corrected price simply makes the same quantities
    worth something else.
    """

    await entry.runtime_data.async_refresh()
