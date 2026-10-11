"""Turning config entry options into billing domain objects.

Options hold the contract as the user typed it. Everything here is derived, so
editing a price or the allowance basis changes what past energy is worth
without touching a single recorded quantity.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

from homeassistant.util import dt as dt_util

from .billing import AllowanceBasis, Prices, PriceSchedule, SettlementMode, TariffTerms
from .const import (
    CONF_ALLOWANCE_BASIS,
    CONF_ALLOWANCE_KWH,
    CONF_CURRENCY,
    CONF_FEED_IN,
    CONF_MARKET,
    CONF_MAX_STEP_KWH,
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
    DEFAULT_MAX_STEP_KWH,
    DEFAULT_STANDING_CHARGE,
    DEFAULT_STANDING_CHARGE_MONTHS,
    DEFAULT_SUBSIDIZED,
    DEFAULT_VAT_PERCENT,
)


def price_entry(valid_from: date, subsidized: float, market: float, feed_in: float
                ) -> dict[str, Any]:
    """One stored price row."""

    return {
        CONF_VALID_FROM: valid_from.isoformat(),
        CONF_SUBSIDIZED: subsidized,
        CONF_MARKET: market,
        CONF_FEED_IN: feed_in,
    }


def default_prices(valid_from: date) -> list[dict[str, Any]]:
    """The Hungarian A1 residential rates, effective from a given day."""

    return [price_entry(valid_from, DEFAULT_SUBSIDIZED, DEFAULT_MARKET, DEFAULT_FEED_IN)]


def terms_from_options(options: Mapping[str, Any]) -> TariffTerms:
    """Read the contract terms out of the entry options."""

    return TariffTerms(
        annual_allowance_kwh=float(options.get(CONF_ALLOWANCE_KWH, DEFAULT_ALLOWANCE_KWH)),
        standing_charge_per_month=float(
            options.get(CONF_STANDING_CHARGE, DEFAULT_STANDING_CHARGE)
        ),
        vat_percent=float(options.get(CONF_VAT_PERCENT, DEFAULT_VAT_PERCENT)),
        mode=SettlementMode(options.get(CONF_MODE, SettlementMode.SZALDO)),
        allowance_basis=AllowanceBasis(
            options.get(CONF_ALLOWANCE_BASIS, AllowanceBasis.NETTED)
        ),
        currency=str(options.get(CONF_CURRENCY, DEFAULT_CURRENCY)),
    )


def standing_charge_months(options: Mapping[str, Any]) -> int:
    return int(options.get(CONF_STANDING_CHARGE_MONTHS, DEFAULT_STANDING_CHARGE_MONTHS))


def max_step_kwh(options: Mapping[str, Any]) -> float:
    """The largest movement a single reading is believed to report."""

    return float(options.get(CONF_MAX_STEP_KWH, DEFAULT_MAX_STEP_KWH))


def schedule_from_options(options: Mapping[str, Any]) -> PriceSchedule:
    """Read the price schedule out of the entry options."""

    # Home Assistant's clock, not the host's: the rest of the integration dates
    # energy by it, and a schedule starting on a different day would not cover
    # the energy recorded against that date.
    rows = options.get(CONF_PRICES) or default_prices(dt_util.now().date())
    return PriceSchedule(
        [
            Prices(
                valid_from=date.fromisoformat(row[CONF_VALID_FROM]),
                subsidized=float(row[CONF_SUBSIDIZED]),
                market=float(row[CONF_MARKET]),
                feed_in=float(row[CONF_FEED_IN]),
            )
            for row in rows
        ]
    )


def upsert_price(
    rows: list[dict[str, Any]],
    valid_from: date,
    subsidized: float,
    market: float,
    feed_in: float,
) -> list[dict[str, Any]]:
    """Add a price change, replacing any already effective on that day.

    Submitting is an assertion about a date rather than an append, so setting
    the same day twice leaves one row and the schedule keeps its rule that two
    prices cannot take effect together.
    """

    kept = [row for row in rows if row[CONF_VALID_FROM] != valid_from.isoformat()]
    kept.append(price_entry(valid_from, subsidized, market, feed_in))
    return sorted(kept, key=lambda row: str(row[CONF_VALID_FROM]))
