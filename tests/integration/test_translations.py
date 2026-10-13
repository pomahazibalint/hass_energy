"""Every repair and every sensor the integration raises has words for it.

A repair whose key has no translation shows the key, and nothing else in the
test suite renders a repair, so this checks the files the way Home Assistant
loads them.
"""

import json
from pathlib import Path

from custom_components.hass_energy.sensor import SENSORS
from homeassistant.core import HomeAssistant
from homeassistant.helpers.translation import async_get_translations
from pytest_homeassistant_custom_component.common import MockConfigEntry

ISSUES = Path("custom_components/hass_energy/issues.py").read_text()
STRINGS = json.loads(Path("custom_components/hass_energy/strings.json").read_text())


def issue_kinds() -> set[str]:
    """Every kind issues.py raises, by the literal it passes to the registry."""

    kinds = set()
    for line in ISSUES.splitlines():
        line = line.strip()
        if line.startswith('"') and line.endswith('",') and "_" in line and " " not in line:
            kinds.add(line.strip('",'))
    return kinds - {"running_totals_retired", "source_missing"}


async def test_every_repair_has_a_title_and_description(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    kinds = issue_kinds()
    assert kinds >= {"price_coverage", "sources_disagree", "device_bursts", "source_stale"}
    translations = await async_get_translations(hass, "en", "issues", {"hass_energy"})
    for kind in kinds:
        for part in ("title", "description"):
            assert f"component.hass_energy.issues.{kind}.{part}" in translations, kind


async def test_every_sensor_has_a_name(entry: MockConfigEntry, hass: HomeAssistant) -> None:
    translations = await async_get_translations(hass, "en", "entity", {"hass_energy"})
    for key in [description.translation_key for description in SENSORS] + ["device_cost"]:
        assert f"component.hass_energy.entity.sensor.{key}.name" in translations, key


def keys_of(tree: dict[str, object], prefix: str = "") -> set[str]:
    found: set[str] = set()
    for key, value in tree.items():
        if isinstance(value, dict):
            found |= keys_of(value, f"{prefix}{key}.")
        else:
            found.add(prefix + key)
    return found


def test_the_english_translation_matches_the_strings() -> None:
    """The translations are a copy of strings.json, and a copy can drift."""

    en = json.loads(Path("custom_components/hass_energy/translations/en.json").read_text())
    assert en == STRINGS


def test_every_language_has_every_string() -> None:
    """A language missing a key shows the key, in that language's UI only."""

    for path in Path("custom_components/hass_energy/translations").glob("*.json"):
        translated = json.loads(path.read_text())
        assert keys_of(translated) == keys_of(STRINGS), path.name
