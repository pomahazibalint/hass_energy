"""Setting the integration up and editing the contract afterwards."""

from __future__ import annotations

from datetime import date
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_NAME
from homeassistant.helpers import selector
from homeassistant.util import dt as dt_util

from .billing import AllowanceBasis, SettlementMode
from .const import (
    CONF_ALLOWANCE_BASIS,
    CONF_ALLOWANCE_KWH,
    CONF_CURRENCY,
    CONF_EXPORT_ENTITY,
    CONF_FEED_IN,
    CONF_IMPORT_ENTITY,
    CONF_MARKET,
    CONF_MODE,
    CONF_PRICES,
    CONF_STANDING_CHARGE,
    CONF_STANDING_CHARGE_MONTHS,
    CONF_SUBSIDIZED,
    CONF_VALID_FROM,
    CONF_VAT_PERCENT,
    DEFAULT_ALLOWANCE_KWH,
    DEFAULT_CURRENCY,
    DEFAULT_FEED_IN,
    DEFAULT_MARKET,
    DEFAULT_STANDING_CHARGE,
    DEFAULT_STANDING_CHARGE_MONTHS,
    DEFAULT_SUBSIDIZED,
    DEFAULT_VAT_PERCENT,
    DOMAIN,
)
from .settings import default_prices, upsert_price

ENERGY_SENSOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="sensor", device_class="energy")
)


def _price_number() -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(min=0, step="any", mode=selector.NumberSelectorMode.BOX)
    )


class HassEnergyConfigFlow(ConfigFlow, domain=DOMAIN):
    """Collects the meters. Everything else has a sensible default."""

    VERSION = 2

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            options: dict[str, Any] = {CONF_PRICES: default_prices(dt_util.now().date())}
            return self.async_create_entry(
                title=user_input[CONF_NAME],
                data={
                    CONF_IMPORT_ENTITY: user_input[CONF_IMPORT_ENTITY],
                    CONF_EXPORT_ENTITY: user_input.get(CONF_EXPORT_ENTITY),
                },
                options=options,
            )

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default="Energy settlement"): str,
                vol.Required(CONF_IMPORT_ENTITY): ENERGY_SENSOR,
                vol.Optional(CONF_EXPORT_ENTITY): ENERGY_SENSOR,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    @staticmethod
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return HassEnergyOptionsFlow()


class HassEnergyOptionsFlow(OptionsFlow):
    """Edits the contract. Nothing here touches a recorded quantity."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        menu = ["terms", "prices"]
        if len(self._prices) > 1:
            menu.append("remove_price")
        return self.async_show_menu(step_id="init", menu_options=menu)

    @property
    def _prices(self) -> list[dict[str, Any]]:
        stored = self.config_entry.options.get(CONF_PRICES) or []
        return [dict(row) for row in stored]

    def _save(self, options: dict[str, Any]) -> ConfigFlowResult:
        return self.async_create_entry(title="", data=options)

    async def async_step_terms(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        options = dict(self.config_entry.options)
        if user_input is not None:
            options.update(user_input)
            return self._save(options)

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_ALLOWANCE_KWH,
                    default=options.get(CONF_ALLOWANCE_KWH, DEFAULT_ALLOWANCE_KWH),
                ): _price_number(),
                vol.Required(
                    CONF_ALLOWANCE_BASIS,
                    default=options.get(CONF_ALLOWANCE_BASIS, AllowanceBasis.NETTED.value),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[basis.value for basis in AllowanceBasis],
                        translation_key=CONF_ALLOWANCE_BASIS,
                    )
                ),
                vol.Required(
                    CONF_MODE, default=options.get(CONF_MODE, SettlementMode.SZALDO.value)
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[mode.value for mode in SettlementMode],
                        translation_key=CONF_MODE,
                    )
                ),
                vol.Required(
                    CONF_STANDING_CHARGE,
                    default=options.get(CONF_STANDING_CHARGE, DEFAULT_STANDING_CHARGE),
                ): _price_number(),
                vol.Required(
                    CONF_STANDING_CHARGE_MONTHS,
                    default=options.get(
                        CONF_STANDING_CHARGE_MONTHS, DEFAULT_STANDING_CHARGE_MONTHS
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=24, step=1, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Required(
                    CONF_VAT_PERCENT,
                    default=options.get(CONF_VAT_PERCENT, DEFAULT_VAT_PERCENT),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=99, step="any", mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Required(
                    CONF_CURRENCY, default=options.get(CONF_CURRENCY, DEFAULT_CURRENCY)
                ): str,
            }
        )
        return self.async_show_form(step_id="terms", data_schema=schema)

    async def async_step_prices(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Set the prices in force from a chosen day.

        The date is what makes this both an edit and a correction: leave it at
        today for a change, set it back for something noticed late. Submitting
        replaces whatever was already effective on that day rather than adding
        a second row for it.
        """

        rows = self._prices
        current = rows[-1] if rows else None

        if user_input is not None:
            valid_from = dt_util.parse_date(str(user_input[CONF_VALID_FROM]))
            if valid_from is None:
                return self.async_show_form(
                    step_id="prices",
                    data_schema=self._prices_schema(current),
                    errors={CONF_VALID_FROM: "invalid_date"},
                )
            options = dict(self.config_entry.options)
            options[CONF_PRICES] = upsert_price(
                rows,
                valid_from,
                float(user_input[CONF_SUBSIDIZED]),
                float(user_input[CONF_MARKET]),
                float(user_input[CONF_FEED_IN]),
            )
            return self._save(options)

        return self.async_show_form(step_id="prices", data_schema=self._prices_schema(current))

    def _prices_schema(self, current: dict[str, Any] | None) -> vol.Schema:
        """Prefilled with what is in force, so a change is one field."""

        return vol.Schema(
            {
                vol.Required(
                    CONF_VALID_FROM, default=dt_util.now().date().isoformat()
                ): selector.DateSelector(),
                vol.Required(
                    CONF_SUBSIDIZED,
                    default=(current or {}).get(CONF_SUBSIDIZED, DEFAULT_SUBSIDIZED),
                ): _price_number(),
                vol.Required(
                    CONF_MARKET, default=(current or {}).get(CONF_MARKET, DEFAULT_MARKET)
                ): _price_number(),
                vol.Required(
                    CONF_FEED_IN, default=(current or {}).get(CONF_FEED_IN, DEFAULT_FEED_IN)
                ): _price_number(),
            }
        )

    async def async_step_remove_price(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Drop a price change added with the wrong date.

        Upsert cannot delete, and without this a mistyped date is permanent.
        The last remaining row is not removable: a schedule with no prices
        cannot value anything.
        """

        rows = self._prices
        if user_input is not None:
            dropped = str(user_input[CONF_VALID_FROM])
            options = dict(self.config_entry.options)
            options[CONF_PRICES] = [
                row for row in rows if str(row[CONF_VALID_FROM]) != dropped
            ]
            return self._save(options)

        schema = vol.Schema(
            {
                vol.Required(CONF_VALID_FROM): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[str(row[CONF_VALID_FROM]) for row in rows]
                    )
                )
            }
        )
        return self.async_show_form(step_id="remove_price", data_schema=schema)


def earliest_price(rows: list[dict[str, Any]]) -> date | None:
    """First day the schedule can value energy for."""

    if not rows:
        return None
    return min(date.fromisoformat(str(row[CONF_VALID_FROM])) for row in rows)
