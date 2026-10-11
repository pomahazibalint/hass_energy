"""Energy settlement accounting for Home Assistant."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from . import issues
from .const import RETIRED_OPTIONS
from .coordinator import SettlementCoordinator
from .costs import COST_KINDS, statistic_id
from .costs import async_remove as remove_statistics
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
    issues.running_totals_retired(
        hass, entry.entry_id, {kind: statistic_id(entry.entry_id, kind) for kind in COST_KINDS}
    )
    return True


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
