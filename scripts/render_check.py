"""Render every generated template against a real Home Assistant.

``hass --script check_config`` validates the shape of a package and compiles
its templates, but never renders one. A template that compiles can still fail
on the first state it reads, so this executes all of them against a Home
Assistant instance holding plausible states.

Run with Home Assistant importable, pointed at a generated output directory:

    uv run --python 3.13 --with homeassistant --no-project \\
        python scripts/render_check.py examples/packages

Unlike check_config, this exits non-zero when something fails.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import sys
from collections.abc import Iterator
from typing import Any

import yaml
from homeassistant.core import HomeAssistant
from homeassistant.helpers.template import Template

MANIFEST_NAME = ".hass-energy-manifest.json"

#: Keys whose values Home Assistant renders as templates.
TEMPLATE_KEYS = frozenset({"state", "availability", "value_template", "option"})

#: Stand-in reading for every source sensor. The value only has to be numeric
#: and plausible; this checks that templates run, not what they conclude.
SOURCE_READING = "1234.5"


def templates_in(node: Any, path: str = "") -> Iterator[tuple[str, str]]:
    """Yield every template string in a package, with where it was found."""

    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{path}.{key}"
            if key == "attributes" and isinstance(value, dict):
                for attribute, text in value.items():
                    if isinstance(text, str):
                        yield f"{here}.{attribute}", text
            elif key in TEMPLATE_KEYS and isinstance(value, str):
                yield here, value
            else:
                yield from templates_in(value, here)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from templates_in(value, f"{path}[{index}]")


def source_entities(packages: pathlib.Path) -> set[str]:
    """Entities the packages read but do not create."""

    sources: set[str] = set()
    for path in sorted(packages.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for meter in (data.get("utility_meter") or {}).values():
            sources.add(meter["source"])
    return sources


def initial_state(entity_id: str) -> str:
    if entity_id.startswith("select."):
        return "subsidized"
    if entity_id.startswith("binary_sensor."):
        return "off"
    return "100.0"


async def check(packages: pathlib.Path) -> int:
    manifest = packages / MANIFEST_NAME
    if not manifest.exists():
        print(f"error: no {MANIFEST_NAME} in {packages}; generate the packages first")
        return 1

    hass = HomeAssistant(str(packages.parent))
    await hass.async_start()

    for entity_id in source_entities(packages):
        hass.states.async_set(entity_id, SOURCE_READING)
    for entity_id in json.loads(manifest.read_text(encoding="utf-8"))["entities"]:
        hass.states.async_set(entity_id, initial_state(entity_id))

    rendered = 0
    failures = 0
    for path in sorted(packages.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        for where, text in templates_in(data, path.name):
            if "{{" not in text and "{%" not in text:
                continue
            rendered += 1
            try:
                Template(text, hass).async_render(parse_result=False)
            except Exception as error:
                failures += 1
                print(f"FAIL {where}\n  {type(error).__name__}: {error}\n  {text}\n")

    print(f"rendered {rendered} templates, {failures} failed")
    await hass.async_stop()
    return 1 if failures else 0


if __name__ == "__main__":
    directory = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "examples/packages")
    sys.exit(asyncio.run(check(directory)))
