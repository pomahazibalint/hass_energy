"""The dashboard's modules, served to the browser."""

import json
from pathlib import Path

from custom_components.hass_energy.const import CONF_IMPORT_ENTITY, CONF_PRICES, DOMAIN
from custom_components.hass_energy.frontend import SERVED
from custom_components.hass_energy.settings import default_prices
from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from .conftest import TODAY

MANIFEST = Path("custom_components/hass_energy/manifest.json")


async def test_the_dashboard_module_is_loaded_by_the_frontend(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    version = json.loads(MANIFEST.read_text())["version"]
    url = hass.data[SERVED]

    assert url == f"/{DOMAIN}/{version}/hass-energy.js"
    assert url in hass.data[DATA_EXTRA_MODULE_URL].urls


async def test_the_modules_are_served_from_the_integration(
    entry: MockConfigEntry, hass: HomeAssistant, hass_client: ClientSessionGenerator
) -> None:
    client = await hass_client()
    base = hass.data[SERVED].rsplit("/", 1)[0]

    for module, marker in (
        ("hass-energy.js", 'import "./strategy.js"'),
        ("strategy.js", "ll-strategy-dashboard-hass-energy"),
        ("bill-card.js", "hass-energy-bill-card"),
        ("devices-card.js", "hass-energy-devices-card"),
        ("history-card.js", "hass-energy-history-card"),
        ("strings.js", "listing_name"),
    ):
        response = await client.get(f"{base}/{module}")
        assert response.status == 200, module
        assert marker in await response.text()


async def test_a_second_metering_point_does_not_register_twice(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    hass.states.async_set("sensor.heat_pump_import_energy", "1.0")
    second = MockConfigEntry(
        domain=DOMAIN,
        title="Heat pump",
        data={CONF_IMPORT_ENTITY: "sensor.heat_pump_import_energy"},
        options={CONF_PRICES: default_prices(TODAY)},
    )
    second.add_to_hass(hass)
    await hass.config_entries.async_setup(second.entry_id)
    await hass.async_block_till_done()

    urls = [url for url in hass.data[DATA_EXTRA_MODULE_URL].urls if url.startswith(f"/{DOMAIN}/")]
    assert len(urls) == 1
