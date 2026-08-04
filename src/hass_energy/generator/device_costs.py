"""Per-device running cost."""

from __future__ import annotations

from typing import Any

from ..config import ProjectConfig
from . import templates as t
from .base import Generator
from .entities import Entities
from .pricing import MARGINAL_PRICE
from .utility_meters import cycle_label


class DeviceCostGenerator(Generator):
    """Prices each device's energy at the current marginal band."""

    filename = "device_costs.yaml"
    description = (
        "Cost of each monitored device per cycle, priced at the marginal rate: "
        "what the device costs to run right now. While the household is still "
        "inside the subsidized band these figures rise once the band is "
        "exhausted, and they are exact only at settlement."
    )

    def applies_to(self, config: ProjectConfig) -> bool:
        return bool(config.devices)

    def build(self, config: ProjectConfig) -> dict[str, Any]:
        entities = Entities(config)
        price = entities.pricing(MARGINAL_PRICE)
        currency = config.billing.pricing.currency
        sensors = []

        for device in config.devices:
            for cycle in config.all_cycles:
                energy = entities.device_meter(device.id, cycle)
                sensors.append(
                    t.sensor(
                        name=f"{device.display_name} cost {cycle_label(cycle)}",
                        unique_id=entities.device_cost_id(device.id, cycle),
                        state=t.template(
                            t.assign("energy", t.numeric_state(energy)),
                            t.assign("price", t.numeric_state(price)),
                            t.expression("(energy * price) | round(2)"),
                        ),
                        unit=currency,
                        state_class=t.COST_STATE_CLASS,
                        available_from=(energy, price),
                        attributes={"room": device.room or "", "category": device.category or ""},
                    )
                )

        return t.package(sensors)
