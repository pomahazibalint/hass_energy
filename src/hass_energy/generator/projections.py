"""Where the settlement period is heading, at the current rate."""

from __future__ import annotations

from typing import Any

from ..config import ProjectConfig
from . import templates as t
from .base import GenerationError, Generator
from .entities import Entities
from .pricing import ENERGY_UNIT, SETTLEMENT_ENERGY

#: Names of the projection entities.
DAYS_ELAPSED = "settlement_days_elapsed"
DAYS_REMAINING = "settlement_days_remaining"
DAILY_RATE = "settlement_daily_rate"
PROJECTED_ENERGY = "projected_settlement_energy"
PROJECTED_COST = "projected_settlement_cost"
ALLOWANCE_RUNS_OUT = "allowance_runs_out"
ALLOWANCE_EXCEEDED = "allowance_projected_exceeded"


def settlement_start(month: int, day: int) -> str:
    """Template statements binding ``start`` to this period's first moment.

    The settlement date has either happened already this calendar year or is
    still ahead of it, which decides the year the current period began in.
    """

    return t.template(
        f"{{% set month = {month} %}}{{% set day = {day} %}}",
        "{% set started_this_year = now().month > month or "
        "(now().month == month and now().day >= day) %}",
        "{% set year = now().year if started_this_year else now().year - 1 %}",
        "{% set start = now().replace(year=year, month=month, day=day, "
        "hour=0, minute=0, second=0, microsecond=0) %}",
    )


class ProjectionsGenerator(Generator):
    """Extrapolates the settlement period from the rate so far.

    The value of a banded tariff is knowing before the year ends whether the
    allowance will hold. These sensors answer that while there is still time to
    change something.
    """

    filename = "projections.yaml"
    description = (
        "Where this settlement period is heading if consumption continues at "
        "the rate so far: the projected energy and cost at settlement, and the "
        "date the subsidized allowance runs out. A straight-line estimate, so "
        "it is least reliable early in the period and across a change of season."
    )

    def build(self, config: ProjectConfig) -> dict[str, Any]:
        if config.grid.import_entity is None:
            raise GenerationError(
                "grid.import_entity is required: there is nothing to project without it."
            )

        entities = Entities(config)
        billing = config.billing
        pricing = billing.pricing
        limit = t.number(pricing.subsidized_limit_kwh)
        period = settlement_start(billing.settlement_month, billing.settlement_day)

        billed = entities.pricing(SETTLEMENT_ENERGY)
        elapsed = entities.pricing(DAYS_ELAPSED)
        remaining = entities.pricing(DAYS_REMAINING)
        rate = entities.pricing(DAILY_RATE)
        projected = entities.pricing(PROJECTED_ENERGY)

        sensors = [
            t.sensor(
                name="Days into the settlement period",
                unique_id=entities.pricing_id(DAYS_ELAPSED),
                state=t.template(
                    period,
                    t.expression("((now() - start).total_seconds() / 86400) | round(2)"),
                ),
                unit="d",
                state_class="measurement",
            ),
            t.sensor(
                name="Days left in the settlement period",
                unique_id=entities.pricing_id(DAYS_REMAINING),
                # Derived from the next start rather than a fixed 365, so a leap
                # year does not shift the estimate by a day.
                state=t.template(
                    period,
                    "{% set next_start = start.replace(year=start.year + 1) %}",
                    t.expression("((next_start - now()).total_seconds() / 86400) | round(2)"),
                ),
                unit="d",
                state_class="measurement",
            ),
            t.sensor(
                name="Average daily consumption this settlement period",
                unique_id=entities.pricing_id(DAILY_RATE),
                state=t.template(
                    t.assign("used", t.numeric_state(billed)),
                    t.assign("days", t.numeric_state(elapsed)),
                    t.expression("(used / days) | round(3) if days > 0 else 0"),
                ),
                unit="kWh/d",
                state_class="measurement",
                available_from=(billed, elapsed),
            ),
            t.sensor(
                name="Projected energy at settlement",
                unique_id=entities.pricing_id(PROJECTED_ENERGY),
                state=t.template(
                    t.assign("used", t.numeric_state(billed)),
                    t.assign("daily", t.numeric_state(rate)),
                    t.assign("left", t.numeric_state(remaining)),
                    t.expression("(used + daily * left) | round(1)"),
                ),
                unit=ENERGY_UNIT,
                device_class="energy",
                state_class="measurement",
                available_from=(billed, rate, remaining),
            ),
            t.sensor(
                name="Projected cost at settlement",
                unique_id=entities.pricing_id(PROJECTED_COST),
                # Banded exactly as the real bill will be, rather than at one
                # average price, so crossing the allowance shows up in full.
                state=t.template(
                    t.assign("total", t.numeric_state(projected)),
                    t.assign("cheap", f"[total, {limit}] | min"),
                    t.assign("dear", f"[total - {limit}, 0] | max"),
                    t.expression(
                        f"(cheap * {t.number(pricing.subsidized_price)} + "
                        f"dear * {t.number(pricing.unsubsidized_price)}) | round(0)"
                    ),
                ),
                unit=pricing.currency,
                state_class="measurement",
                available_from=(projected,),
            ),
            t.sensor(
                name="Date the subsidized allowance runs out",
                unique_id=entities.pricing_id(ALLOWANCE_RUNS_OUT),
                # Unknown rather than a fabricated date when the allowance is
                # not on course to run out at all.
                state=t.template(
                    t.assign("used", t.numeric_state(billed)),
                    t.assign("daily", t.numeric_state(rate)),
                    t.assign("left", t.numeric_state(remaining)),
                    f"{{% set headroom = {limit} - used %}}",
                    "{% set days = headroom / daily if daily > 0 else -1 %}",
                    t.expression(
                        "(now() + timedelta(days=days)).date() "
                        "if 0 <= days <= left else 'unknown'"
                    ),
                ),
                available_from=(billed, rate, remaining),
            ),
        ]

        binary_sensors = [
            t.binary_sensor(
                name="Subsidized allowance projected to run out",
                unique_id=entities.problem_id(ALLOWANCE_EXCEEDED),
                state=t.template(
                    t.assign("total", t.numeric_state(projected)),
                    t.expression(f"total > {limit}"),
                ),
                available_from=(projected,),
            )
        ]

        return t.package(sensors, binary_sensors)
