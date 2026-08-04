"""House-wide energy and cost, split into monitored and unmonitored."""

from __future__ import annotations

from typing import Any

from ..config import ProjectConfig
from . import templates as t
from .base import GenerationError, Generator
from .entities import Entities
from .pricing import ENERGY_UNIT, MARGINAL_PRICE
from .utility_meters import cycle_label

HOUSE_ENERGY = "house_energy"
MONITORED_ENERGY = "monitored_energy"
UNMONITORED_ENERGY = "unmonitored_energy"
MONITORED_COST = "monitored_cost"
UNMONITORED_COST = "unmonitored_cost"
TOTAL_COST = "total_cost"
SELF_CONSUMPTION = "self_consumption"


class HouseTotalsGenerator(Generator):
    """Totals that answer what the house used and what it cost."""

    filename = "house_totals.yaml"
    description = (
        "House-wide consumption and cost per cycle. Consumption is grid import "
        "less export plus local production, so it reflects what the house used "
        "rather than what it bought. Whatever the monitored devices do not "
        "account for is reported as unmonitored."
    )

    def build(self, config: ProjectConfig) -> dict[str, Any]:
        if config.grid.import_entity is None:
            raise GenerationError(
                "grid.import_entity is required: house totals need a grid import sensor."
            )

        entities = Entities(config)
        currency = config.billing.pricing.currency
        price = entities.pricing(MARGINAL_PRICE)
        has_export = config.grid.export_entity is not None
        has_production = config.grid.production_entity is not None
        sensors: list[dict[str, Any]] = []

        for cycle in config.all_cycles:
            label = cycle_label(cycle)
            imported = entities.grid_meter("import", cycle)
            house = entities.total(HOUSE_ENERGY, cycle)
            monitored = entities.total(MONITORED_ENERGY, cycle)
            unmonitored = entities.total(UNMONITORED_ENERGY, cycle)
            monitored_cost = entities.total(MONITORED_COST, cycle)
            unmonitored_cost = entities.total(UNMONITORED_COST, cycle)

            house_terms = [t.assign("used", t.numeric_state(imported))]
            house_sources = [imported]
            if has_export:
                exported = entities.grid_meter("export", cycle)
                house_terms.append(t.assign("used", f"used - ({t.numeric_state(exported)})"))
                house_sources.append(exported)
            if has_production:
                produced = entities.grid_meter("production", cycle)
                house_terms.append(t.assign("used", f"used + ({t.numeric_state(produced)})"))
                house_sources.append(produced)

            sensors.append(
                t.sensor(
                    name=f"House consumption {label}",
                    unique_id=entities.total_id(HOUSE_ENERGY, cycle),
                    state=t.template(*house_terms, t.expression("[used, 0] | max | round(3)")),
                    unit=ENERGY_UNIT,
                    device_class="energy",
                    state_class="total",
                    available_from=tuple(house_sources),
                )
            )
            sensors.append(
                t.sensor(
                    name=f"Monitored consumption {label}",
                    unique_id=entities.total_id(MONITORED_ENERGY, cycle),
                    state=t.sum_of(entities.device_meters(cycle), name="meters"),
                    unit=ENERGY_UNIT,
                    device_class="energy",
                    state_class="total",
                )
            )
            sensors.append(
                t.sensor(
                    name=f"Unmonitored consumption {label}",
                    unique_id=entities.total_id(UNMONITORED_ENERGY, cycle),
                    state=t.template(
                        t.assign("used", t.numeric_state(house)),
                        t.assign("measured", t.numeric_state(monitored)),
                        t.expression("[used - measured, 0] | max | round(3)"),
                    ),
                    unit=ENERGY_UNIT,
                    device_class="energy",
                    state_class="total",
                    available_from=(house, monitored),
                )
            )
            sensors.append(
                t.sensor(
                    name=f"Monitored cost {label}",
                    unique_id=entities.total_id(MONITORED_COST, cycle),
                    state=t.sum_of(entities.device_costs(cycle), name="costs", precision=2),
                    unit=currency,
                    state_class=t.COST_STATE_CLASS,
                )
            )
            sensors.append(
                t.sensor(
                    name=f"Unmonitored cost {label}",
                    unique_id=entities.total_id(UNMONITORED_COST, cycle),
                    state=t.template(
                        t.assign("energy", t.numeric_state(unmonitored)),
                        t.assign("price", t.numeric_state(price)),
                        t.expression("(energy * price) | round(2)"),
                    ),
                    unit=currency,
                    state_class=t.COST_STATE_CLASS,
                    available_from=(unmonitored, price),
                )
            )
            sensors.append(
                t.sensor(
                    name=f"Total cost {label}",
                    unique_id=entities.total_id(TOTAL_COST, cycle),
                    state=t.template(
                        t.assign("measured", t.numeric_state(monitored_cost)),
                        t.assign("rest", t.numeric_state(unmonitored_cost)),
                        t.expression("(measured + rest) | round(2)"),
                    ),
                    unit=currency,
                    state_class=t.COST_STATE_CLASS,
                    available_from=(monitored_cost, unmonitored_cost),
                )
            )

            if has_production:
                produced = entities.grid_meter("production", cycle)
                self_terms = [t.assign("produced", t.numeric_state(produced))]
                self_sources = [produced]
                if has_export:
                    exported = entities.grid_meter("export", cycle)
                    self_terms.append(
                        t.assign("produced", f"produced - ({t.numeric_state(exported)})")
                    )
                    self_sources.append(exported)
                sensors.append(
                    t.sensor(
                        name=f"Solar self-consumption {label}",
                        unique_id=entities.total_id(SELF_CONSUMPTION, cycle),
                        state=t.template(
                            *self_terms, t.expression("[produced, 0] | max | round(3)")
                        ),
                        unit=ENERGY_UNIT,
                        device_class="energy",
                        state_class="total",
                        available_from=tuple(self_sources),
                    )
                )

        return t.package(sensors)
