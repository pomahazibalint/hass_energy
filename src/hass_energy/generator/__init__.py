"""Home Assistant package generation.

The generators are the source of truth for everything under the output
directory. Given the same configuration they produce byte-identical files, so
regenerating is always safe and drift is visible in a diff.
"""

from __future__ import annotations

from ..config import ProjectConfig
from .base import GeneratedFile, GenerationError, Generator
from .device_costs import DeviceCostGenerator
from .house_totals import HouseTotalsGenerator
from .pricing import PricingGenerator
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
)

__all__ = [
    "GENERATORS",
    "GeneratedFile",
    "GenerationError",
    "Generator",
    "generate",
]


def generate(config: ProjectConfig) -> tuple[GeneratedFile, ...]:
    """Render every package that applies to this configuration."""

    return tuple(
        generator.generate(config) for generator in GENERATORS if generator.applies_to(config)
    )
