"""Two worked settlements, end to end.

Both are annual szaldó settlements for one metering point, and both are
net-exporting: the energy charge is zero and the whole payable amount is the
distribution standing charge. The shape is taken from real MVM invoices — a
period bounded by a meter reading rather than a date, a price period boundary
inside it, and feed-in bought back at the energy component of the tariff — but
the quantities are made up, so nothing here describes a real household.

The standing charge and VAT are not invented: 120.50 Ft a month and 27% are the
published tariff, which is why both settlements come to a round 1 836 Ft.
"""

from datetime import date

from hass_energy.billing import (
    MeterReadings,
    Prices,
    PriceSchedule,
    SettlementPeriod,
    TariffTerms,
    calculate,
)

#: The energy component of the tariff, which is what feed-in beyond netting is
#: bought at, and roughly a seventh of what the same kWh costs to buy.
FEED_IN = 5.11

#: Prices are revised on 1 August, and a settlement is split there whether or
#: not the numbers moved.
SCHEDULE = PriceSchedule(
    [
        Prices(date(2022, 8, 1), subsidized=36.386, market=70.104, feed_in=FEED_IN),
        Prices(date(2023, 8, 1), subsidized=36.386, market=70.104, feed_in=FEED_IN),
        Prices(date(2024, 8, 1), subsidized=36.386, market=70.104, feed_in=FEED_IN),
    ]
)

TERMS = TariffTerms(
    annual_allowance_kwh=2523.0,
    standing_charge_per_month=120.5,
    vat_percent=27.0,
)


def test_a_net_exporting_settlement() -> None:
    """368 days, 7 000 kWh drawn against 7 500 fed in."""

    period = SettlementPeriod(date(2024, 3, 9), date(2025, 3, 12))
    # Meter: 16 000 -> 23 000 drawn, 19 000 -> 26 500 fed in.
    readings = MeterReadings(imported_kwh=23000 - 16000, exported_kwh=26500 - 19000)

    bill = calculate(
        period,
        readings,
        SCHEDULE,
        TERMS,
        standing_charge_months=12,
        # Split across the 1 August boundary as metered, not by day.
        feed_in_by_segment=[450.0, 50.0],
    )

    assert readings.imported_kwh == 7000
    assert readings.exported_kwh == 7500
    # Netting leaves nothing to bill for.
    assert bill.billed_kwh == 0
    assert bill.surplus_kwh == 500

    assert bill.standing_charge_net == 1446
    assert bill.energy_net == 0
    assert bill.vat == 390
    assert bill.gross_total == 1836

    # Each price period is rounded on its own, as the statement does.
    assert [line.rounded for line in bill.surplus] == [2300, 256]
    assert bill.surplus_net == 2556
    assert [(line.start, line.end) for line in bill.surplus] == [
        (date(2024, 3, 9), date(2024, 8, 1)),
        (date(2024, 8, 1), date(2025, 3, 12)),
    ]

    # Paying 1 836 Ft while being owed 2 556 Ft.
    assert bill.net_position == -720


def test_the_preceding_settlement() -> None:
    """359 days, a different length from the one that follows it."""

    period = SettlementPeriod(date(2023, 3, 15), date(2024, 3, 8))
    readings = MeterReadings(imported_kwh=16000 - 10000, exported_kwh=19000 - 12000)

    bill = calculate(
        period,
        readings,
        SCHEDULE,
        TERMS,
        standing_charge_months=12,
        feed_in_by_segment=[900.0, 100.0],
    )

    assert readings.imported_kwh == 6000
    assert readings.exported_kwh == 7000
    assert bill.billed_kwh == 0
    assert bill.surplus_kwh == 1000

    assert bill.standing_charge_net == 1446
    assert bill.vat == 390
    assert bill.gross_total == 1836

    assert [line.kwh for line in bill.surplus] == [900, 100]
    assert [line.rounded for line in bill.surplus] == [4599, 511]
    assert bill.surplus_net == 5110


def test_the_periods_are_not_a_year_and_not_equal() -> None:
    """The settlement boundary follows the meter reading, not the calendar."""

    first = SettlementPeriod(date(2023, 3, 15), date(2024, 3, 8))
    second = SettlementPeriod(date(2024, 3, 9), date(2025, 3, 12))

    assert first.days == 359
    assert second.days == 368


def test_the_allowance_is_apportioned_by_day() -> None:
    """259/2022 § 9 (1): 1/365 of the allowance per day of the period."""

    assert TERMS.allowance_for(365) == 2523
    assert round(TERMS.allowance_for(359), 1) == 2481.5
    assert round(TERMS.allowance_for(368), 1) == 2543.7
