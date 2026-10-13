"""Serving the dashboard to the browser.

The dashboard is a strategy and a few cards, plain modules in the
integration's own directory. They are served through the HTTP component's
static paths and loaded through the frontend's extra module hook, which
works in both resource modes without an entry in the resources list, and
which core's marketplace recognises and leaves alone. The URL carries the
integration's version, so a browser does not keep a stale module across an
upgrade.
"""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url

# Defined in the http component's package before 2026.10 and only re-exported
# from it since, which the type check does not accept; the import works on both.
from homeassistant.components.http import StaticPathConfig  # type: ignore[attr-defined]
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration
from homeassistant.util.hass_dict import HassKey

from .const import DOMAIN

#: The module's URL once it is served; the key doubles as the guard, since
#: the paths are registered once however many metering points there are.
SERVED: HassKey[str] = HassKey(f"{DOMAIN}_frontend")

MODULE = "hass-energy.js"
WWW = Path(__file__).parent / "www"


async def async_serve(hass: HomeAssistant) -> str:
    """Serve the dashboard's modules, once, and return the entry module's URL."""

    if (url := hass.data.get(SERVED)) is not None:
        return url
    integration = await async_get_integration(hass, DOMAIN)
    base = f"/{DOMAIN}/{integration.version}"
    await hass.http.async_register_static_paths([StaticPathConfig(base, str(WWW), True)])
    url = f"{base}/{MODULE}"
    add_extra_js_url(hass, url)
    hass.data[SERVED] = url
    return url
