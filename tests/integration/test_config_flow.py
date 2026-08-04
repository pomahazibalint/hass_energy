from datetime import date
from typing import Any

from custom_components.hass_energy.const import (
    CONF_ALLOWANCE_BASIS,
    CONF_EXPORT_ENTITY,
    CONF_FEED_IN,
    CONF_IMPORT_ENTITY,
    CONF_MARKET,
    CONF_PRICES,
    CONF_SUBSIDIZED,
    CONF_VALID_FROM,
    DOMAIN,
)
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .conftest import EXPORT_ENTITY, IMPORT_ENTITY


async def test_setup_only_asks_for_the_meters(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    assert result["type"] is FlowResultType.FORM
    assert set(result["data_schema"].schema) == {
        CONF_NAME,
        CONF_IMPORT_ENTITY,
        CONF_EXPORT_ENTITY,
    }

    created = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Main meter",
            CONF_IMPORT_ENTITY: IMPORT_ENTITY,
            CONF_EXPORT_ENTITY: EXPORT_ENTITY,
        },
    )

    assert created["type"] is FlowResultType.CREATE_ENTRY
    assert created["title"] == "Main meter"
    assert created["data"][CONF_IMPORT_ENTITY] == IMPORT_ENTITY
    # A starting price schedule so the entry can value energy immediately.
    assert len(created["options"][CONF_PRICES]) == 1


async def test_export_is_optional(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    created = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NAME: "No solar", CONF_IMPORT_ENTITY: IMPORT_ENTITY}
    )

    assert created["data"][CONF_EXPORT_ENTITY] is None


async def options(hass: HomeAssistant, entry: MockConfigEntry, step: str) -> Any:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    return await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": step}
    )


async def test_a_price_change_is_recorded_from_the_chosen_day(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    form = await options(hass, entry, "prices")

    result = await hass.config_entries.options.async_configure(
        form["flow_id"],
        {
            CONF_VALID_FROM: "2026-01-01",
            CONF_SUBSIDIZED: 41.0,
            CONF_MARKET: 82.0,
            CONF_FEED_IN: 6.5,
        },
    )

    rows = result["data"][CONF_PRICES]
    assert [row[CONF_VALID_FROM] for row in rows] == ["2024-01-01", "2025-08-01", "2026-01-01"]
    assert rows[-1][CONF_SUBSIDIZED] == 41.0


async def test_backdating_a_price_is_the_same_form(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """A correction noticed late is a date, not a separate mechanism."""

    form = await options(hass, entry, "prices")

    result = await hass.config_entries.options.async_configure(
        form["flow_id"],
        {
            CONF_VALID_FROM: "2024-06-01",
            CONF_SUBSIDIZED: 30.0,
            CONF_MARKET: 60.0,
            CONF_FEED_IN: 4.0,
        },
    )

    rows = result["data"][CONF_PRICES]
    assert [row[CONF_VALID_FROM] for row in rows] == ["2024-01-01", "2024-06-01", "2025-08-01"]


async def test_submitting_the_same_day_twice_replaces_it(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    form = await options(hass, entry, "prices")
    await hass.config_entries.options.async_configure(
        form["flow_id"],
        {
            CONF_VALID_FROM: "2025-08-01",
            CONF_SUBSIDIZED: 44.0,
            CONF_MARKET: 88.0,
            CONF_FEED_IN: 7.0,
        },
    )

    rows = entry.options[CONF_PRICES]
    assert [row[CONF_VALID_FROM] for row in rows] == ["2024-01-01", "2025-08-01"]
    assert rows[-1][CONF_SUBSIDIZED] == 44.0


async def test_the_price_form_is_prefilled_with_what_is_in_force(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    form = await options(hass, entry, "prices")

    defaults = {str(key): key.default() for key in form["data_schema"].schema}

    assert defaults[CONF_SUBSIDIZED] == 40.0
    assert defaults[CONF_MARKET] == 80.0
    assert defaults[CONF_VALID_FROM] == date.today().isoformat()


async def test_a_price_change_can_be_removed(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    form = await options(hass, entry, "remove_price")

    result = await hass.config_entries.options.async_configure(
        form["flow_id"], {CONF_VALID_FROM: "2025-08-01"}
    )

    assert [row[CONF_VALID_FROM] for row in result["data"][CONF_PRICES]] == ["2024-01-01"]


async def test_removal_is_hidden_with_a_single_price(hass: HomeAssistant) -> None:
    """A schedule with nothing in it cannot value anything."""

    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_IMPORT_ENTITY: IMPORT_ENTITY},
        options={
            CONF_PRICES: [
                {"valid_from": "2024-01-01", "subsidized": 1, "market": 2, "feed_in": 3}
            ]
        },
    )
    config_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(config_entry.entry_id)

    assert "remove_price" not in result["menu_options"]


async def test_the_allowance_basis_is_switchable(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """The question the invoices could not settle is a dropdown, not a rebuild."""

    form = await options(hass, entry, "terms")

    result = await hass.config_entries.options.async_configure(
        form["flow_id"],
        {
            "allowance_kwh": 2523.0,
            CONF_ALLOWANCE_BASIS: "gross",
            "mode": "szaldo",
            "standing_charge_per_month": 120.5,
            "standing_charge_months": 12,
            "vat_percent": 27.0,
            "currency": "Ft",
        },
    )

    assert result["data"][CONF_ALLOWANCE_BASIS] == "gross"
