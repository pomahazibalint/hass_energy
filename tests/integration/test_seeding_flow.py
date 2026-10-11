"""The path a real installation takes: set up, backdate a price, seed.

Reproduces what someone actually does after installing part-way through a
settlement period, in the order they would do it.
"""

from datetime import date, timedelta

import pytest
from custom_components.hass_energy.const import (
    ATTR_EXPORTED_KWH,
    ATTR_IMPORTED_KWH,
    ATTR_PERIOD_START,
    CONF_EXPORT_ENTITY,
    CONF_FEED_IN,
    CONF_IMPORT_ENTITY,
    CONF_MARKET,
    CONF_SUBSIDIZED,
    CONF_VALID_FROM,
    DOMAIN,
    SERVICE_SEED_PERIOD,
)
from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.recorder import Recorder
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant

from .conftest import EXPORT_ENTITY, IMPORT_ENTITY, TODAY

PREFIX = "sensor.vag_meter_"
LAST_SEPTEMBER = TODAY.replace(month=9, day=13) - timedelta(days=365)


async def install(hass: HomeAssistant) -> str:
    """Set the integration up the way the UI does."""

    hass.states.async_set(IMPORT_ENTITY, "1000.0")
    hass.states.async_set(EXPORT_ENTITY, "2000.0")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    created = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Vag meter",
            CONF_IMPORT_ENTITY: IMPORT_ENTITY,
            CONF_EXPORT_ENTITY: EXPORT_ENTITY,
        },
    )
    await hass.async_block_till_done()
    return str(created["result"].entry_id)


async def backdate_price(hass: HomeAssistant, entry_id: str, when: date) -> None:
    """Add a price effective from a past date, through the options flow."""

    result = await hass.config_entries.options.async_init(entry_id)
    form = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "prices"}
    )
    await hass.config_entries.options.async_configure(
        form["flow_id"],
        {
            CONF_VALID_FROM: when.isoformat(),
            CONF_SUBSIDIZED: 36.386,
            CONF_MARKET: 70.104,
            CONF_FEED_IN: 5.11,
        },
    )
    await hass.async_block_till_done()


async def seed(hass: HomeAssistant, start: date, imported: float, exported: float) -> None:
    await hass.services.async_call(
        DOMAIN,
        SERVICE_SEED_PERIOD,
        {
            ATTR_PERIOD_START: start,
            ATTR_IMPORTED_KWH: imported,
            ATTR_EXPORTED_KWH: exported,
        },
        blocking=True,
    )
    await hass.async_block_till_done()


async def test_backdate_the_price_then_seed(
    recorder_mock: Recorder,
    enable_custom_integrations: None,
    frozen: FrozenDateTimeFactory,
    hass: HomeAssistant,
) -> None:
    """The order the instructions imply: fix prices first, then seed."""

    entry_id = await install(hass)
    await backdate_price(hass, entry_id, LAST_SEPTEMBER)
    await seed(hass, LAST_SEPTEMBER, imported=4000.0, exported=3500.0)

    coordinator = hass.config_entries.async_get_entry(entry_id).runtime_data  # type: ignore[union-attr]
    assert coordinator.state.start == LAST_SEPTEMBER
    assert coordinator.data.readings.imported_kwh == pytest.approx(4000.0)

    billed = hass.states.get(PREFIX + "billed_energy")
    assert billed is not None
    assert billed.state == "500.0", f"billed energy is {billed.state}"


async def test_seed_first_then_backdate_the_price(
    recorder_mock: Recorder,
    enable_custom_integrations: None,
    frozen: FrozenDateTimeFactory,
    hass: HomeAssistant,
) -> None:
    """The order someone actually does it: seed, discover it is unpriced, fix."""

    entry_id = await install(hass)
    await seed(hass, LAST_SEPTEMBER, imported=4000.0, exported=3500.0)

    unpriced = hass.states.get(PREFIX + "billed_energy")
    assert unpriced is not None
    # No prices reach back to the period start, so nothing can be valued.
    assert unpriced.state == "unavailable"

    await backdate_price(hass, entry_id, LAST_SEPTEMBER)

    billed = hass.states.get(PREFIX + "billed_energy")
    assert billed is not None
    assert billed.state == "500.0", f"billed energy is {billed.state}"


async def test_seeded_energy_survives_the_price_schedule_changing(
    recorder_mock: Recorder,
    enable_custom_integrations: None,
    frozen: FrozenDateTimeFactory,
    hass: HomeAssistant,
) -> None:
    """Editing prices must not lose energy: the hours are what they are."""

    midway = LAST_SEPTEMBER + timedelta(days=120)

    entry_id = await install(hass)
    await backdate_price(hass, entry_id, LAST_SEPTEMBER)
    await backdate_price(hass, entry_id, midway)
    await seed(hass, LAST_SEPTEMBER, imported=4000.0, exported=3500.0)

    entry = hass.config_entries.async_get_entry(entry_id)
    assert entry is not None
    # Three price periods: the two backdated ones and the default dated today.
    assert len(entry.runtime_data.data.subsidized) == 3

    result = await hass.config_entries.options.async_init(entry_id)
    form = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "remove_price"}
    )
    await hass.config_entries.options.async_configure(
        form["flow_id"], {CONF_VALID_FROM: midway.isoformat()}
    )
    await hass.async_block_till_done()

    bill = entry.runtime_data.data
    assert bill.readings.imported_kwh == pytest.approx(4000.0)
    assert bill.readings.exported_kwh == pytest.approx(3500.0)
    assert bill.billed_kwh == pytest.approx(500.0)
    assert len(bill.subsidized) == 2


async def test_the_money_follows_the_seeded_energy(
    recorder_mock: Recorder,
    enable_custom_integrations: None,
    frozen: FrozenDateTimeFactory,
    hass: HomeAssistant,
) -> None:
    entry_id = await install(hass)
    await backdate_price(hass, entry_id, LAST_SEPTEMBER)
    await seed(hass, LAST_SEPTEMBER, imported=4000.0, exported=1000.0)

    cost = hass.states.get(PREFIX + "energy_cost")
    assert cost is not None
    assert float(cost.state) > 0, "3 000 kWh billed should cost something"
