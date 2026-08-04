"""Utility meters for grid flows and monitored devices."""

from __future__ import annotations

from typing import Any, NamedTuple

from ..config import SETTLEMENT_CYCLE, ProjectConfig
from .base import GenerationError, Generator
from .entities import Entities


class GridFlow(NamedTuple):
    """One flow of energy across the property boundary."""

    key: str
    field: str
    label: str


#: Grid flows, each naming the configuration field holding its source sensor.
GRID_FLOWS = (
    GridFlow("import", "import_entity", "Grid import"),
    GridFlow("export", "export_entity", "Grid export"),
    GridFlow("production", "production_entity", "Solar production"),
)


def cycle_label(cycle: str) -> str:
    """Human-readable name of a meter cycle."""

    return "settlement period" if cycle == SETTLEMENT_CYCLE else cycle


def meter(source: str, name: str, object_id: str, cycle: str) -> dict[str, Any]:
    """One utility_meter entry.

    The settlement meter is given no cycle: a settlement period rarely starts on
    1 January, so it is reset by the generated settlement automation instead.
    """

    entry: dict[str, Any] = {"source": source, "name": name, "unique_id": object_id}
    if cycle != SETTLEMENT_CYCLE:
        entry["cycle"] = cycle
    return entry


class UtilityMeterGenerator(Generator):
    """Accumulating meters every other generated package reads from."""

    filename = "utility_meters.yaml"
    description = (
        "Utility meters for each grid flow and each monitored device, one per "
        "configured cycle plus a meter spanning the billing settlement period."
    )

    def build(self, config: ProjectConfig) -> dict[str, Any]:
        if config.grid.import_entity is None:
            raise GenerationError(
                "grid.import_entity is required: energy accounting needs a grid import sensor."
            )

        entities = Entities(config)
        meters: dict[str, dict[str, Any]] = {}

        for flow in GRID_FLOWS:
            source = getattr(config.grid, flow.field)
            if source is None:
                continue
            for cycle in config.all_cycles:
                object_id = entities.grid_meter_id(flow.key, cycle)
                meters[object_id] = meter(
                    source=source,
                    name=f"{flow.label} {cycle_label(cycle)}",
                    object_id=object_id,
                    cycle=cycle,
                )

        for device in config.devices:
            for cycle in config.all_cycles:
                object_id = entities.device_meter_id(device.id, cycle)
                meters[object_id] = meter(
                    source=device.entity,
                    name=f"{device.display_name} {cycle_label(cycle)}",
                    object_id=object_id,
                    cycle=cycle,
                )

        return {"utility_meter": meters}
