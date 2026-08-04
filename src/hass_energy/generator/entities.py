"""The entity ids one configuration produces.

Generators reference each other's output — device costs need the price sensor,
house totals need the device meters — so the wiring lives in one place and no
generator spells another's entity id by hand.

Two integrations name entities differently, and both are accounted for here. A
utility_meter takes its entity id from the object key it is configured under. A
template sensor slugifies its name, so every generated template sensor pins
``default_entity_id`` to ``sensor.<unique_id>`` instead.
"""

from __future__ import annotations

from dataclasses import dataclass

from .. import naming
from ..config import SETTLEMENT_CYCLE, TARIFF_BANDS, DeviceConfig, ProjectConfig


@dataclass(frozen=True)
class Entities:
    """Derives generated object ids and entity ids from a configuration."""

    config: ProjectConfig

    @property
    def prefix(self) -> str:
        """Object id prefix shared by everything this project generates."""

        return naming.slugify(self.config.project_name)

    def grid_meter_id(self, flow: str, cycle: str) -> str:
        return naming.grid_meter(self.prefix, flow, cycle)

    def grid_meter(self, flow: str, cycle: str) -> str:
        return naming.sensor(self.grid_meter_id(flow, cycle))

    def device_meter_id(self, device_id: str, cycle: str) -> str:
        return naming.device_meter(self.prefix, device_id, cycle)

    def device_meter(self, device_id: str, cycle: str) -> str:
        """Entity id of a device's meter for a cycle that has no tariffs."""

        return naming.sensor(self.device_meter_id(device_id, cycle))

    def device_band_meter(self, device_id: str, band: str) -> str:
        """Entity id of one price band of a device's settlement meter."""

        return naming.band_sensor(self.device_meter_id(device_id, SETTLEMENT_CYCLE), band)

    def device_band_select(self, device_id: str) -> str:
        """Entity id of the select choosing a device's active price band."""

        return naming.tariff_select(self.device_meter_id(device_id, SETTLEMENT_CYCLE))

    def device_cost_id(self, device_id: str, cycle: str) -> str:
        return naming.device_cost(self.prefix, device_id, cycle)

    def device_cost(self, device_id: str, cycle: str) -> str:
        return naming.sensor(self.device_cost_id(device_id, cycle))

    def total_id(self, name: str, cycle: str) -> str:
        return naming.total(self.prefix, name, cycle)

    def total(self, name: str, cycle: str) -> str:
        return naming.sensor(self.total_id(name, cycle))

    def pricing_id(self, name: str) -> str:
        return naming.prefixed(self.prefix, name)

    def pricing(self, name: str) -> str:
        return naming.sensor(self.pricing_id(name))

    def problem_id(self, name: str) -> str:
        return naming.prefixed(self.prefix, name)

    def problem(self, name: str) -> str:
        """Entity id of a diagnostic binary sensor."""

        return naming.binary_sensor(self.problem_id(name))

    def device_energy(self, device: DeviceConfig, cycle: str) -> tuple[str, ...]:
        """Meters holding a device's energy for one cycle.

        The settlement meter is split across price bands, so it answers with one
        entity per band and every other cycle with a single meter.
        """

        if cycle == SETTLEMENT_CYCLE:
            return tuple(self.device_band_meter(device.id, band) for band in TARIFF_BANDS)
        return (self.device_meter(device.id, cycle),)

    def device_meters(self, cycle: str) -> tuple[str, ...]:
        """Every device energy meter for one cycle, in configuration order."""

        return tuple(
            entity
            for device in self.config.devices_with_cycle(cycle)
            for entity in self.device_energy(device, cycle)
        )

    def device_costs(self, cycle: str) -> tuple[str, ...]:
        """Every device cost sensor for one cycle, in configuration order."""

        return tuple(
            self.device_cost(device.id, cycle)
            for device in self.config.devices_with_cycle(cycle)
        )

    def band_selects(self) -> tuple[str, ...]:
        """Every select that has to follow the active price band."""

        return tuple(self.device_band_select(device.id) for device in self.config.devices)

    def settlement_meters(self) -> tuple[str, ...]:
        """Every meter a settlement rollover has to reset."""

        meters = [
            self.grid_meter(flow, SETTLEMENT_CYCLE)
            for flow in ("import", "export", "production")
            if getattr(self.config.grid, f"{flow}_entity") is not None
        ]
        meters += [
            entity
            for device in self.config.devices
            for entity in self.device_energy(device, SETTLEMENT_CYCLE)
        ]
        return tuple(meters)
