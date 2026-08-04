"""Per-device running cost."""

from __future__ import annotations

from typing import Any

from ..config import SETTLEMENT_CYCLE, DeviceConfig, ProjectConfig
from ..config import TARIFF_BANDS as BANDS
from . import templates as t
from .base import Generator
from .entities import Entities
from .pricing import MARGINAL_PRICE
from .utility_meters import cycle_label


class DeviceCostGenerator(Generator):
    """Costs each device's energy against the band it was used in."""

    filename = "device_costs.yaml"
    description = (
        "Cost of each monitored device per cycle. The settlement figure is "
        "exact: energy accumulates into a meter per price band, so each band is "
        "costed at its own price. Shorter cycles are costed at the price in "
        "force now, which differs from the billed amount only across the single "
        "day the allowance runs out."
    )

    def applies_to(self, config: ProjectConfig) -> bool:
        return bool(config.devices)

    def _settlement_state(self, entities: Entities, device: DeviceConfig, config: ProjectConfig
                          ) -> str:
        pricing = config.billing.pricing
        return t.template(
            t.assign(
                BANDS[0], t.numeric_state(entities.device_band_meter(device.id, BANDS[0]))
            ),
            t.assign(
                BANDS[1], t.numeric_state(entities.device_band_meter(device.id, BANDS[1]))
            ),
            t.expression(
                f"({BANDS[0]} * {t.number(pricing.subsidized_price)} + "
                f"{BANDS[1]} * {t.number(pricing.unsubsidized_price)}) | round(2)"
            ),
        )

    def build(self, config: ProjectConfig) -> dict[str, Any]:
        entities = Entities(config)
        price = entities.pricing(MARGINAL_PRICE)
        currency = config.billing.pricing.currency
        sensors = []

        for device in config.devices:
            for cycle in config.cycles_for(device):
                if cycle == SETTLEMENT_CYCLE:
                    state = self._settlement_state(entities, device, config)
                    sources = entities.device_energy(device, cycle)
                else:
                    energy = entities.device_meter(device.id, cycle)
                    state = t.template(
                        t.assign("energy", t.numeric_state(energy)),
                        t.assign("price", t.numeric_state(price)),
                        t.expression("(energy * price) | round(2)"),
                    )
                    sources = (energy, price)

                attributes = {}
                if device.room is not None:
                    attributes["room"] = device.room
                if device.category is not None:
                    attributes["category"] = device.category

                sensors.append(
                    t.sensor(
                        name=f"{device.display_name} cost {cycle_label(cycle)}",
                        unique_id=entities.device_cost_id(device.id, cycle),
                        state=state,
                        unit=currency,
                        state_class=t.COST_STATE_CLASS,
                        available_from=sources,
                        attributes=attributes or None,
                    )
                )

        return t.package(sensors)
