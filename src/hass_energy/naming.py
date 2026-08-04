"""Identifier construction for generated Home Assistant entities.

Every generated object id, entity id and unique id is built here. Centralising
this keeps regeneration stable — an entity id that changes shape orphans the
recorder history behind it — and keeps a rename to a single place.
"""

from __future__ import annotations

import re
import unicodedata

_NON_SLUG = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    """Reduce arbitrary text to a Home Assistant object id fragment.

    Accented letters are folded to their base letter rather than dropped, so
    ``Nyaraló`` becomes ``nyaralo`` and not ``nyaral``.
    """

    decomposed = unicodedata.normalize("NFKD", value.strip().lower())
    folded = "".join(char for char in decomposed if not unicodedata.combining(char))
    return _NON_SLUG.sub("_", folded).strip("_")


def sensor(object_id: str) -> str:
    """Entity id of a sensor with the given object id."""

    return f"sensor.{object_id}"


def band_sensor(object_id: str, band: str) -> str:
    """Entity id of one tariff band of a utility meter.

    Home Assistant appends the tariff to the meter's object id when a meter is
    configured with ``tariffs``.
    """

    return f"sensor.{object_id}_{band}"


def tariff_select(object_id: str) -> str:
    """Entity id of the select a tariffed utility meter creates."""

    return f"select.{object_id}"


def device_meter(prefix: str, device_id: str, cycle: str) -> str:
    """Object id of a device's energy meter for one cycle."""

    return f"{prefix}_device_{device_id}_{cycle}"


def grid_meter(prefix: str, flow: str, cycle: str) -> str:
    """Object id of a grid meter, where ``flow`` is import, export or production."""

    return f"{prefix}_grid_{flow}_{cycle}"


def device_cost(prefix: str, device_id: str, cycle: str) -> str:
    """Object id of a device's cost sensor for one cycle."""

    return f"{prefix}_cost_{device_id}_{cycle}"


def total(prefix: str, name: str, cycle: str) -> str:
    """Object id of a house-wide total for one cycle."""

    return f"{prefix}_{name}_{cycle}"


def prefixed(prefix: str, name: str) -> str:
    """Object id of a project-wide entity that is not per device or per cycle."""

    return f"{prefix}_{name}"


def binary_sensor(object_id: str) -> str:
    """Entity id of a binary sensor with the given object id."""

    return f"binary_sensor.{object_id}"
