"""Health of the accounting itself, rather than of the household."""

from __future__ import annotations

from typing import Any

from ..config import ProjectConfig
from . import templates as t
from .base import GenerationError, Generator
from .entities import Entities
from .house_totals import HOUSE_ENERGY, UNMONITORED_ENERGY
from .pricing import PRICE_BAND
from .utility_meters import GRID_FLOWS, cycle_label

#: Names of the diagnostic entities.
UNMONITORED_SHARE = "unmonitored_share"
SOURCES_UNAVAILABLE = "sources_unavailable"
SOURCES_STALE = "sources_stale"
BAND_DESYNC = "band_desync"
ATTRIBUTION_POOR = "attribution_poor"


def entity_list(name: str, entities: tuple[str, ...]) -> str:
    """A template statement binding a list of entity ids."""

    listing = ",\n  ".join(f"'{entity}'" for entity in entities)
    return t.template("{% set " + name + " = [", f"  {listing},", "] %}")


class DiagnosticsGenerator(Generator):
    """Reports the ways this accounting can quietly stop being true.

    A source sensor that disappears, a meter nothing feeds, or a tariff select
    left behind by a missed automation all leave the cost sensors reporting
    confident, wrong numbers. Each becomes a problem entity here.
    """

    filename = "diagnostics.yaml"
    description = (
        "Health of the accounting: source sensors that are missing or have "
        "stopped updating, how much consumption no device accounts for, and "
        "whether the meter tariffs still follow the active price band. These "
        "detect an accounting that has quietly stopped being true."
    )

    def _source_entities(self, config: ProjectConfig) -> tuple[str, ...]:
        sources = [
            getattr(config.grid, flow.field)
            for flow in GRID_FLOWS
            if getattr(config.grid, flow.field) is not None
        ]
        sources += [device.entity for device in config.devices]
        return tuple(sources)

    def _stale_list(self, sources: tuple[str, ...], hours: str) -> str:
        """Template statements binding ``stale`` to the sources that went quiet.

        Built with a loop because the age of a state lives on the state object,
        which the ``states`` filter does not return.
        """

        return t.template(
            entity_list("sources", sources),
            "{% set cutoff = now() - timedelta(hours=" + hours + ") %}",
            "{% set ns = namespace(stale=[]) %}",
            "{% for entity in sources if has_value(entity) %}",
            "  {% if states[entity].last_updated < cutoff %}",
            "    {% set ns.stale = ns.stale + [entity] %}",
            "  {% endif %}",
            "{% endfor %}",
            "{% set stale = ns.stale %}",
        )

    def _availability_sensors(self, entities: Entities, sources: tuple[str, ...]
                              ) -> list[dict[str, Any]]:
        diagnostics = entities.config.diagnostics
        hours = t.number(diagnostics.stale_after_hours)

        return [
            t.binary_sensor(
                name="Energy source sensors unavailable",
                unique_id=entities.problem_id(SOURCES_UNAVAILABLE),
                state=t.template(
                    entity_list("sources", sources),
                    t.expression("sources | reject('has_value') | list | count > 0"),
                ),
                device_class="problem",
                attributes={
                    "missing": t.template(
                        entity_list("sources", sources),
                        t.expression("sources | reject('has_value') | list | join(', ')"),
                    )
                },
            ),
            t.binary_sensor(
                name="Energy source sensors not updating",
                unique_id=entities.problem_id(SOURCES_STALE),
                # A sensor holding a plausible value that stopped reporting
                # looks healthy to every other check in this project.
                state=t.template(
                    self._stale_list(sources, hours), t.expression("stale | count > 0")
                ),
                device_class="problem",
                attributes={
                    "stale": t.template(
                        self._stale_list(sources, hours), t.expression("stale | join(', ')")
                    ),
                    "stale_after_hours": hours,
                },
            ),
        ]

    def build(self, config: ProjectConfig) -> dict[str, Any]:
        if config.grid.import_entity is None:
            raise GenerationError(
                "grid.import_entity is required: there is nothing to diagnose without it."
            )

        entities = Entities(config)
        sources = self._source_entities(config)
        sensors: list[dict[str, Any]] = []
        binary_sensors = self._availability_sensors(entities, sources)

        for cycle in config.all_cycles:
            label = cycle_label(cycle)
            house = entities.total(HOUSE_ENERGY, cycle)
            unmonitored = entities.total(UNMONITORED_ENERGY, cycle)
            sensors.append(
                t.sensor(
                    name=f"Unmonitored share {label}",
                    unique_id=entities.total_id(UNMONITORED_SHARE, cycle),
                    state=t.template(
                        t.assign("used", t.numeric_state(house)),
                        t.assign("rest", t.numeric_state(unmonitored)),
                        t.expression("(rest / used * 100) | round(1) if used > 0 else 0"),
                    ),
                    unit="%",
                    state_class="measurement",
                    available_from=(house, unmonitored),
                )
            )

        if config.devices:
            share = entities.total(UNMONITORED_SHARE, config.primary_cycle)
            threshold = t.number(config.diagnostics.unmonitored_warning_percent)
            binary_sensors.append(
                t.binary_sensor(
                    name="Too much consumption unaccounted for",
                    unique_id=entities.problem_id(ATTRIBUTION_POOR),
                    state=t.template(
                        t.assign("share", t.numeric_state(share)),
                        t.expression(f"share > {threshold}"),
                    ),
                    device_class="problem",
                    available_from=(share,),
                    attributes={"threshold_percent": threshold},
                )
            )
            band = entities.pricing(PRICE_BAND)
            binary_sensors.append(
                t.binary_sensor(
                    name="Meter tariffs do not match the price band",
                    unique_id=entities.problem_id(BAND_DESYNC),
                    # If this sticks, energy is accruing against the wrong band
                    # and the settlement cost silently stops being exact.
                    state=t.template(
                        entity_list("selects", entities.band_selects()),
                        t.assign("band", f"states('{band}')"),
                        t.expression(
                            "selects | map('states') | reject('eq', band) | list | count > 0"
                        ),
                    ),
                    device_class="problem",
                    available_from=(band,),
                )
            )

        return t.package(sensors, binary_sensors)
