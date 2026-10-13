"""The household's other sources, read from where the user already named them.

Home Assistant's energy dashboard is configured by one document, the energy
preferences, in which the user names a statistic for each flow. The grid
meters stay in this integration's config entry because they decide the bill;
everything else is read from that document, so a source is named once, in
the native settings, and never asked for again.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from homeassistant.components.energy.data import async_get_manager
from homeassistant.const import ATTR_FRIENDLY_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import slugify
from homeassistant.util.hass_dict import HassKey

from .const import DOMAIN

Listener = Callable[[], Awaitable[None]]

#: The entries following the preferences. The energy manager keeps a
#: listener for life, so it is given one, and entries come and go behind it.
FOLLOWERS: HassKey[set[Listener]] = HassKey(f"{DOMAIN}_preferences_followers")


@dataclass(frozen=True)
class Device:
    """One device whose consumption the dashboard shows.

    Named as the dashboard names it, so the two agree about what a figure
    is for. A device whose total already includes another's says so, and is
    costed on its own total, child included, as the dashboard's own device
    graph shows it.
    """

    statistic: str
    name: str
    included_in: str | None = None

    @property
    def slug(self) -> str:
        """What the device is called in a statistic id.

        The statistic rather than the name: renaming a device in the
        dashboard must not start a second series.
        """

        return slugify(self.statistic)


@dataclass(frozen=True)
class Sources:
    """Statistic ids for the flows that are not the grid meters.

    Each flow is a tuple because the dashboard allows several of a kind: two
    inverters are two solar sources, and their production is summed. Devices
    are a different thing, each its own figure, and say nothing about the
    house's flows.
    """

    production: tuple[str, ...] = field(default_factory=tuple)
    charge: tuple[str, ...] = field(default_factory=tuple)
    discharge: tuple[str, ...] = field(default_factory=tuple)
    devices: tuple[Device, ...] = field(default_factory=tuple)

    @property
    def ids(self) -> list[str]:
        """The statistics the house's flows are read from."""

        return [*self.production, *self.charge, *self.discharge]

    def device(self, statistic: str) -> Device | None:
        return next((one for one in self.devices if one.statistic == statistic), None)


async def async_sources(hass: HomeAssistant, import_entity: str) -> Sources:
    """What the energy preferences name beyond the grid, for one metering point.

    The preferences are the household's, and a household can have more than
    one metering point: a heat pump on its own tariff is a second entry whose
    meter the panels never fed. The panels, and the devices, belong to the
    metering point whose import meter the dashboard's grid source names. A
    dashboard that names no grid at all has nothing to tie them to, and they
    go to every entry.
    """

    manager = await async_get_manager(hass)
    if manager.data is None:
        return Sources()
    grid: list[str] = []
    production: list[str] = []
    charge: list[str] = []
    discharge: list[str] = []
    for source in manager.data["energy_sources"]:
        if source["type"] == "grid":
            grid.extend(flow["stat_energy_from"] for flow in source["flow_from"])
        elif source["type"] == "solar":
            production.append(source["stat_energy_from"])
        elif source["type"] == "battery":
            discharge.append(source["stat_energy_from"])
            charge.append(source["stat_energy_to"])
    if grid and import_entity not in grid:
        return Sources()
    devices = tuple(
        Device(
            statistic=device["stat_consumption"],
            name=device.get("name") or _display_name(hass, device["stat_consumption"]),
            included_in=device.get("included_in_stat"),
        )
        for device in manager.data["device_consumption"]
    )
    return Sources(tuple(production), tuple(charge), tuple(discharge), devices)


@callback
def _display_name(hass: HomeAssistant, statistic: str) -> str:
    """What the dashboard shows for a device it was not given a name for."""

    state = hass.states.get(statistic)
    if state is not None:
        name: str | None = state.attributes.get(ATTR_FRIENDLY_NAME)
        if name:
            return name
    return statistic


async def async_follow(hass: HomeAssistant, listener: Listener) -> Callable[[], None]:
    """Call back whenever the preferences are saved, until the return is called."""

    followers = hass.data.get(FOLLOWERS)
    if followers is None:
        followers = hass.data[FOLLOWERS] = set()

        async def fan_out() -> None:
            await asyncio.gather(*(follower() for follower in list(followers)))

        manager = await async_get_manager(hass)
        manager.async_listen_updates(fan_out)
    followers.add(listener)

    @callback
    def unfollow() -> None:
        followers.discard(listener)

    return unfollow
