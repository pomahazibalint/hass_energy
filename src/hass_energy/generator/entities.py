"""The entity ids one configuration produces.

Generators reference each other's output — device costs need the price sensor,
house totals need the device meters — so the wiring lives in one place and no
generator spells another's entity id by hand.
"""

from __future__ import annotations

from dataclasses import dataclass

from .. import naming
from ..config import ProjectConfig


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
        return naming.sensor(self.device_meter_id(device_id, cycle))

    def device_cost_id(self, device_id: str, cycle: str) -> str:
        return naming.device_cost(self.prefix, device_id, cycle)

    def device_cost(self, device_id: str, cycle: str) -> str:
        return naming.sensor(self.device_cost_id(device_id, cycle))

    def total_id(self, name: str, cycle: str) -> str:
        return naming.total(self.prefix, name, cycle)

    def total(self, name: str, cycle: str) -> str:
        return naming.sensor(self.total_id(name, cycle))

    def pricing_id(self, name: str) -> str:
        return naming.pricing(self.prefix, name)

    def pricing(self, name: str) -> str:
        return naming.sensor(self.pricing_id(name))

    def device_meters(self, cycle: str) -> tuple[str, ...]:
        """Every device energy meter for one cycle, in configuration order."""

        return tuple(self.device_meter(device.id, cycle) for device in self.config.devices)

    def device_costs(self, cycle: str) -> tuple[str, ...]:
        """Every device cost sensor for one cycle, in configuration order."""

        return tuple(self.device_cost(device.id, cycle) for device in self.config.devices)
