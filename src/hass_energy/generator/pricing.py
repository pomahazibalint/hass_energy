"""Settlement-period pricing: banded energy, unit price and cost."""

from __future__ import annotations

from typing import Any

from ..config import SETTLEMENT_CYCLE, ProjectConfig
from ..config import TARIFF_BANDS as BANDS
from . import templates as t
from .base import GenerationError, Generator
from .entities import Entities

ENERGY_UNIT = "kWh"

#: Names of the pricing sensors other packages read.
SETTLEMENT_ENERGY = "settlement_energy"
SUBSIDIZED_ENERGY = "subsidized_energy"
UNSUBSIDIZED_ENERGY = "unsubsidized_energy"
SUBSIDIZED_REMAINING = "subsidized_remaining"
PRICE_BAND = "price_band"
MARGINAL_PRICE = "marginal_price"
SETTLEMENT_COST = "settlement_cost"
AVERAGE_PRICE = "average_price"


class PricingGenerator(Generator):
    """Splits settlement consumption into price bands and costs it."""

    filename = "pricing.yaml"
    description = (
        "Billed energy for the current settlement period, split into the "
        "subsidized and unsubsidized bands, with the resulting unit prices and "
        "cost. Every other cost sensor is priced from these."
    )

    def build(self, config: ProjectConfig) -> dict[str, Any]:
        if config.grid.import_entity is None:
            raise GenerationError(
                "grid.import_entity is required: pricing cannot be derived without grid import."
            )

        entities = Entities(config)
        pricing = config.billing.pricing
        limit = t.number(pricing.subsidized_limit_kwh)
        subsidized_price = t.number(pricing.subsidized_price)
        unsubsidized_price = t.number(pricing.unsubsidized_price)

        imported = entities.grid_meter("import", SETTLEMENT_CYCLE)
        billed = entities.pricing(SETTLEMENT_ENERGY)
        sources: tuple[str, ...] = (imported,)

        # Under annual net metering, exported solar offsets imported energy
        # before the price bands are applied, so netting happens first.
        nets_export = config.solar.annual_net_metering and config.grid.export_entity is not None
        if nets_export:
            exported = entities.grid_meter("export", SETTLEMENT_CYCLE)
            sources = (imported, exported)
            billed_state = t.template(
                t.assign("imported", t.numeric_state(imported)),
                t.assign("exported", t.numeric_state(exported)),
                t.expression("[imported - exported, 0] | max | round(3)"),
            )
        else:
            billed_state = t.expression(f"{t.numeric_state(imported)} | round(3)")

        sensors = [
            t.sensor(
                name="Billed energy this settlement period",
                unique_id=entities.pricing_id(SETTLEMENT_ENERGY),
                state=billed_state,
                unit=ENERGY_UNIT,
                device_class="energy",
                state_class="total",
                available_from=sources,
            ),
            t.sensor(
                name="Subsidized energy used",
                unique_id=entities.pricing_id(SUBSIDIZED_ENERGY),
                state=t.template(
                    t.assign("billed", t.numeric_state(billed)),
                    t.expression(f"[billed, {limit}] | min | round(3)"),
                ),
                unit=ENERGY_UNIT,
                device_class="energy",
                state_class="total",
                available_from=(billed,),
            ),
            t.sensor(
                name="Subsidized energy remaining",
                unique_id=entities.pricing_id(SUBSIDIZED_REMAINING),
                state=t.template(
                    t.assign("billed", t.numeric_state(billed)),
                    t.expression(f"[{limit} - billed, 0] | max | round(3)"),
                ),
                unit=ENERGY_UNIT,
                device_class="energy",
                state_class="measurement",
                available_from=(billed,),
            ),
            t.sensor(
                name="Unsubsidized energy used",
                unique_id=entities.pricing_id(UNSUBSIDIZED_ENERGY),
                state=t.template(
                    t.assign("billed", t.numeric_state(billed)),
                    t.expression(f"[billed - {limit}, 0] | max | round(3)"),
                ),
                unit=ENERGY_UNIT,
                device_class="energy",
                state_class="total",
                available_from=(billed,),
            ),
            # The one place the allowance is compared against consumption. The
            # price sensor and the meter tariffs both follow this sensor, so
            # they cannot disagree about which band is active.
            t.sensor(
                name="Active price band",
                unique_id=entities.pricing_id(PRICE_BAND),
                state=t.template(
                    t.assign("billed", t.numeric_state(billed)),
                    t.expression(f"'{BANDS[0]}' if billed < {limit} else '{BANDS[1]}'"),
                ),
                available_from=(billed,),
                attributes={"tariff": config.billing.tariff},
            ),
            t.sensor(
                name="Marginal energy price",
                unique_id=entities.pricing_id(MARGINAL_PRICE),
                state=t.template(
                    t.assign("band", f"states('{entities.pricing(PRICE_BAND)}')"),
                    t.expression(
                        f"{subsidized_price} if band == '{BANDS[0]}' else {unsubsidized_price}"
                    ),
                ),
                unit=pricing.price_unit,
                state_class="measurement",
                available_from=(entities.pricing(PRICE_BAND),),
            ),
            t.sensor(
                name="Settlement period cost",
                unique_id=entities.pricing_id(SETTLEMENT_COST),
                state=t.template(
                    t.assign(
                        "subsidized", t.numeric_state(entities.pricing(SUBSIDIZED_ENERGY))
                    ),
                    t.assign(
                        "unsubsidized", t.numeric_state(entities.pricing(UNSUBSIDIZED_ENERGY))
                    ),
                    t.expression(
                        f"(subsidized * {subsidized_price} + "
                        f"unsubsidized * {unsubsidized_price}) | round(2)"
                    ),
                ),
                unit=pricing.currency,
                state_class=t.COST_STATE_CLASS,
                available_from=(
                    entities.pricing(SUBSIDIZED_ENERGY),
                    entities.pricing(UNSUBSIDIZED_ENERGY),
                ),
            ),
            t.sensor(
                name="Average energy price this settlement period",
                unique_id=entities.pricing_id(AVERAGE_PRICE),
                state=t.template(
                    t.assign("billed", t.numeric_state(billed)),
                    t.assign("cost", t.numeric_state(entities.pricing(SETTLEMENT_COST))),
                    t.expression(
                        f"(cost / billed) | round(3) if billed > 0 else {subsidized_price}"
                    ),
                ),
                unit=pricing.price_unit,
                state_class="measurement",
                available_from=(billed, entities.pricing(SETTLEMENT_COST)),
            ),
        ]

        return t.package(sensors)
