"""Home Assistant package generation.

The generators are the source of truth for everything under the output
directory. Given the same configuration they produce byte-identical files, so
regenerating is always safe and drift is visible in a diff.
"""

from __future__ import annotations

from .. import naming
from ..config import ProjectConfig
from .base import GeneratedFile, GenerationError, Generator
from .device_costs import DeviceCostGenerator
from .diagnostics import DiagnosticsGenerator
from .house_totals import HouseTotalsGenerator
from .pricing import PricingGenerator
from .projections import ProjectionsGenerator
from .settlement import SettlementGenerator
from .utility_meters import UtilityMeterGenerator

#: Registered generators. Order decides the order files are reported in, not
#: the order Home Assistant loads them.
GENERATORS: tuple[Generator, ...] = (
    UtilityMeterGenerator(),
    PricingGenerator(),
    DeviceCostGenerator(),
    HouseTotalsGenerator(),
    SettlementGenerator(),
    DiagnosticsGenerator(),
    ProjectionsGenerator(),
)

__all__ = [
    "GENERATORS",
    "GeneratedFile",
    "GenerationError",
    "Generator",
    "generate",
    "inventory",
]


def generate(config: ProjectConfig) -> tuple[GeneratedFile, ...]:
    """Render every package that applies to this configuration."""

    return tuple(
        generator.generate(config) for generator in GENERATORS if generator.applies_to(config)
    )


def inventory(config: ProjectConfig) -> tuple[str, ...]:
    """Every entity id Home Assistant will create from these packages.

    Read back out of the built packages rather than derived a second time, so
    it cannot drift from what the generators actually emit.
    """

    entities: list[str] = []
    for generator in GENERATORS:
        if not generator.applies_to(config):
            continue
        data = generator.build(config)
        for object_id, meter in data.get("utility_meter", {}).items():
            bands = meter.get("tariffs", ())
            if bands:
                # A tariffed meter has no combined sensor; it has one sensor per
                # band and a select choosing between them.
                entities += [naming.band_sensor(object_id, band) for band in bands]
                entities.append(naming.tariff_select(object_id))
            else:
                entities.append(naming.sensor(object_id))
        for block in data.get("template", []):
            for domain in ("sensor", "binary_sensor"):
                entities += [entry["default_entity_id"] for entry in block.get(domain, [])]
    return tuple(entities)
