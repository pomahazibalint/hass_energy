"""What price an hour's consumption was worth."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from hass_energy.billing import (
    Flows,
    Prices,
    PriceSchedule,
    Rate,
    SettlementMode,
    SettlementPeriod,
    TariffTerms,
    marginal,
    rate_of,
    rates,
)

BUDAPEST = ZoneInfo("Europe/Budapest")
PERIOD = SettlementPeriod(date(2025, 3, 1), date(2026, 3, 1))
PRICES = Prices(date(2025, 1, 1), subsidized=30.0, market=60.0, feed_in=5.0)
SCHEDULE = PriceSchedule([PRICES])
TERMS = TariffTerms()
START = datetime(2025, 6, 1, 10, tzinfo=BUDAPEST)


def flows(*hours: dict[str, float]) -> list[Flows]:
    return [Flows(START + timedelta(hours=i), **hour) for i, hour in enumerate(hours)]


def rated(series: list[Flows], terms: TariffTerms = TERMS) -> list[Rate]:
    costs = marginal(
        PERIOD,
        series,
        [hour.without_consumption() for hour in series],
        SCHEDULE,
        terms,
        standing_charge_months=12,
        tz=BUDAPEST,
    )
    return rates(series, costs, SCHEDULE, terms, BUDAPEST)


def test_the_rate_is_the_price_the_cost_per_kwh_matches() -> None:
    assert rate_of(2.0, 2 * 30 * 1.27, PRICES, 27.0) is Rate.SUBSIDIZED
    assert rate_of(2.0, 2 * 60 * 1.27, PRICES, 27.0) is Rate.MARKET
    assert rate_of(2.0, 2 * 5.0, PRICES, 27.0) is Rate.FEED_IN
    assert rate_of(2.0, 2 * 20.0, PRICES, 27.0) is Rate.MIXED
    assert rate_of(0.0, 0.0, PRICES, 27.0) is Rate.NONE


def test_under_szaldo_consumption_is_at_the_band_price_then_the_feed_in_price() -> None:
    series = flows(
        {"imported_kwh": 2.0},
        {"exported_kwh": 100.0, "produced_kwh": 103.0},
        {"produced_kwh": 3.0},
    )

    assert rated(series) == [Rate.SUBSIDIZED, Rate.FEED_IN, Rate.FEED_IN]


def test_an_hour_that_straddles_two_prices_is_mixed() -> None:
    """Two kWh imported, then three solar kWh consumed: two net, one is surplus."""

    series = flows({"imported_kwh": 2.0}, {"produced_kwh": 3.0})

    assert rated(series)[1] is Rate.MIXED


def test_the_market_price_once_the_allowance_is_gone() -> None:
    series = flows({"imported_kwh": 2.0})

    assert rated(series, TariffTerms(annual_allowance_kwh=0.0)) == [Rate.MARKET]


def test_under_gross_settlement_solar_consumed_is_at_the_feed_in_price() -> None:
    series = flows({"imported_kwh": 2.0}, {"produced_kwh": 2.0})

    assert rated(series, TariffTerms(mode=SettlementMode.BRUTTO)) == [Rate.SUBSIDIZED, Rate.FEED_IN]
