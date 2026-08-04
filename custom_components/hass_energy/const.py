"""Constants and the shape of what is stored."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "hass_energy"

#: Config entry data: what the integration reads. Changing a source sensor
#: means re-creating the entry, so these are kept out of the options.
CONF_IMPORT_ENTITY: Final = "import_entity"
CONF_EXPORT_ENTITY: Final = "export_entity"

#: Options: the contract. All editable in the UI, all able to change the value
#: of energy already recorded, which is why money is derived and never stored.
CONF_ALLOWANCE_KWH: Final = "allowance_kwh"
CONF_STANDING_CHARGE: Final = "standing_charge_per_month"
CONF_STANDING_CHARGE_MONTHS: Final = "standing_charge_months"
CONF_VAT_PERCENT: Final = "vat_percent"
CONF_MODE: Final = "mode"
CONF_ALLOWANCE_BASIS: Final = "allowance_basis"
CONF_CURRENCY: Final = "currency"
CONF_PRICES: Final = "prices"

#: One entry of the price schedule.
CONF_VALID_FROM: Final = "valid_from"
CONF_SUBSIDIZED: Final = "subsidized"
CONF_MARKET: Final = "market"
CONF_FEED_IN: Final = "feed_in"

SERVICE_CLOSE_SETTLEMENT: Final = "close_settlement"
SERVICE_SEED_PERIOD: Final = "seed_period"
SERVICE_IMPORT_INVOICE: Final = "import_invoice"

ATTR_READING_DATE: Final = "reading_date"
ATTR_PERIOD_START: Final = "period_start"
ATTR_PERIOD_END: Final = "period_end"
ATTR_IMPORTED_KWH: Final = "imported_kwh"
ATTR_EXPORTED_KWH: Final = "exported_kwh"

STORAGE_VERSION: Final = 1
STORAGE_KEY: Final = DOMAIN

DEFAULT_ALLOWANCE_KWH: Final = 2523.0
DEFAULT_STANDING_CHARGE: Final = 120.5
DEFAULT_STANDING_CHARGE_MONTHS: Final = 12
DEFAULT_VAT_PERCENT: Final = 27.0
DEFAULT_CURRENCY: Final = "Ft"
DEFAULT_SUBSIDIZED: Final = 36.386
DEFAULT_MARKET: Final = 70.104
DEFAULT_FEED_IN: Final = 5.11
