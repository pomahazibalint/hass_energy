"""Energy settlement accounting for Home Assistant."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from . import issues
from .const import DOMAIN, RETIRED_OPTIONS, RETIRED_SENSORS
from .coordinator import SettlementCoordinator
from .costs import async_remove as remove_statistics
from .services import register as register_services

PLATFORMS = [Platform.SENSOR]

type SettlementEntry = ConfigEntry[SettlementCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: SettlementEntry) -> bool:
    """Set up one metering point."""

    _forget_retired_sensors(hass, entry)
    coordinator = SettlementCoordinator(hass, entry)
    await coordinator.async_load()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_options_updated))
    register_services(hass)
    return True


@callback
def _forget_retired_sensors(hass: HomeAssistant, entry: SettlementEntry) -> None:
    """Leave nothing of the running-total sensors behind.

    An entity the platform stops providing stays in the entity registry as
    unavailable, with a warning that its integration no longer provides it,
    and the repair that announced its retirement would otherwise outlive it.
    """

    registry = er.async_get(hass)
    for key in RETIRED_SENSORS:
        entity_id = registry.async_get_entity_id(
            Platform.SENSOR, DOMAIN, f"{entry.entry_id}_{key}"
        )
        if entity_id is not None:
            registry.async_remove(entity_id)
    issues.running_totals_retired(hass, entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, entry: SettlementEntry) -> bool:
    """Bring an entry's options up to date.

    Version 2 dropped the step limit: it guarded a record of energy the
    integration no longer keeps.
    """

    if entry.version == 1:
        options = {k: v for k, v in entry.options.items() if k not in RETIRED_OPTIONS}
        hass.config_entries.async_update_entry(entry, options=options, version=2)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SettlementEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: SettlementEntry) -> None:
    """A deleted metering point leaves no statistics the dashboard still offers."""

    await remove_statistics(hass, entry.entry_id)


async def _options_updated(hass: HomeAssistant, entry: SettlementEntry) -> None:
    """Re-derive the settlement when the contract changes.

    Nothing recorded moves; a corrected price simply makes the same quantities
    worth something else.
    """

    await entry.runtime_data.async_refresh()
