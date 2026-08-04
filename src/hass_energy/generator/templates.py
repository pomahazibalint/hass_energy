"""Building blocks for Home Assistant template expressions.

Home Assistant templates are Jinja, and so is anything that would render them.
Composing them from these helpers instead keeps the two levels of templating
from meeting, and keeps one spelling of each recurring expression.
"""

from __future__ import annotations

from typing import Any

#: Cost sensors deliberately carry no ``monetary`` device class: that class
#: expects an ISO currency code, while households read prices in local notation.
#: ``state_class`` alone is enough for long-term statistics.
COST_STATE_CLASS = "total"


def number(value: float) -> str:
    """Format a configured number for embedding in a template."""

    return repr(float(value))


def numeric_state(entity: str) -> str:
    """Read an entity's state as a number, treating anything unusable as zero."""

    return f"states('{entity}') | float(0)"


def expression(body: str) -> str:
    """Wrap an expression in template delimiters."""

    return "{{ " + body + " }}"


def assign(name: str, body: str) -> str:
    """A template statement binding a name."""

    return "{% set " + name + " = " + body + " %}"


def template(*lines: str) -> str:
    """Join template lines into one state template."""

    return "\n".join(lines)


def availability(*entities: str) -> str:
    """A template that is true only once every source entity has a value."""

    return expression(" and ".join(f"has_value('{entity}')" for entity in entities))


def sum_of(
    entities: tuple[str, ...] | list[str], name: str = "sources", precision: int = 3
) -> str:
    """Template summing a fixed list of numeric entities."""

    if not entities:
        return expression("0")
    listing = ",\n  ".join(f"'{entity}'" for entity in entities)
    return template(
        "{% set " + name + " = [",
        f"  {listing},",
        "] %}",
        expression(f"{name} | map('states') | map('float', 0) | sum | round({precision})"),
    )


def _entity(
    domain: str,
    name: str,
    unique_id: str,
    state: str,
    available_from: tuple[str, ...],
    attributes: dict[str, str] | None,
    describes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # Home Assistant derives a template entity's id by slugifying its name, so
    # a readable name would produce an id no other generated template could
    # predict. default_entity_id pins the id to the unique id instead, which is
    # what entities.py hands out, and leaves the name free to stay readable.
    entry: dict[str, Any] = {
        "name": name,
        "unique_id": unique_id,
        "default_entity_id": f"{domain}.{unique_id}",
    }
    # Keys describing what the state means read better ahead of the state.
    entry.update(describes or {})
    entry["state"] = state
    if available_from:
        entry["availability"] = availability(*available_from)
    if attributes:
        entry["attributes"] = attributes
    return entry


def sensor(
    *,
    name: str,
    unique_id: str,
    state: str,
    unit: str | None = None,
    state_class: str | None = None,
    device_class: str | None = None,
    available_from: tuple[str, ...] = (),
    attributes: dict[str, str] | None = None,
) -> dict[str, Any]:
    """One entry of a Home Assistant template sensor package."""

    describes: dict[str, Any] = {}
    if device_class is not None:
        describes["device_class"] = device_class
    if state_class is not None:
        describes["state_class"] = state_class
    if unit is not None:
        describes["unit_of_measurement"] = unit
    return _entity("sensor", name, unique_id, state, available_from, attributes, describes)


def binary_sensor(
    *,
    name: str,
    unique_id: str,
    state: str,
    device_class: str | None = None,
    available_from: tuple[str, ...] = (),
    attributes: dict[str, str] | None = None,
) -> dict[str, Any]:
    """One entry of a Home Assistant template binary sensor package."""

    describes = {"device_class": device_class} if device_class is not None else {}
    return _entity(
        "binary_sensor", name, unique_id, state, available_from, attributes, describes
    )


def package(
    sensors: list[dict[str, Any]] | None = None,
    binary_sensors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Wrap template entities in the package structure Home Assistant expects."""

    block: dict[str, Any] = {}
    if sensors:
        block["sensor"] = sensors
    if binary_sensors:
        block["binary_sensor"] = binary_sensors
    return {"template": [block]}
