from datetime import date

import pytest

from hass_energy.billing import (
    AllowanceBasis,
    Bill,
    MeterReadings,
    Prices,
    PriceSchedule,
    SettlementMode,
    SettlementPeriod,
    TariffTerms,
    calculate,
    forint,
)

FLAT = PriceSchedule([Prices(date(2020, 1, 1), subsidized=36.386, market=70.104, feed_in=5.11)])
YEAR = SettlementPeriod(date(2024, 1, 1), date(2024, 12, 31))
TERMS = TariffTerms()


def settle(
    imported: float,
    exported: float = 0.0,
    terms: TariffTerms = TERMS,
    months: int = 12,
) -> Bill:
    return calculate(
        YEAR,
        MeterReadings(imported, exported),
        FLAT,
        terms,
        standing_charge_months=months,
    )


def test_forint_rounds_half_away_from_zero() -> None:
    # Python's round() would give 2 here.
    assert forint(2.5) == 3
    assert forint(390.42) == 390
    assert forint(2800.28) == 2800


def test_netting_bills_only_the_difference() -> None:
    bill = settle(imported=5000, exported=3000)

    assert bill.billed_kwh == 2000
    assert bill.surplus_kwh == 0


def test_netting_never_bills_a_negative_quantity() -> None:
    bill = settle(imported=3000, exported=5000)

    assert bill.billed_kwh == 0
    assert bill.surplus_kwh == 2000


def test_consumption_within_the_allowance_is_all_subsidized() -> None:
    bill = settle(imported=2000)

    assert bill.subsidized_kwh == 2000
    assert bill.market_kwh == 0
    assert bill.energy_net == pytest.approx(2000 * 36.386)


def test_consumption_above_the_allowance_splits_into_bands() -> None:
    bill = settle(imported=3500)

    # 365 days of a 366-day period earns slightly less than the full allowance.
    assert bill.allowance_kwh == pytest.approx(2523 * 365 / 365)
    assert bill.subsidized_kwh == pytest.approx(2523)
    assert bill.market_kwh == pytest.approx(977)
    assert bill.energy_net == pytest.approx(2523 * 36.386 + 977 * 70.104)


def test_the_gross_basis_leaves_nothing_for_netted_consumption() -> None:
    """A heavy user's allowance is spent on withdrawal before netting applies."""

    terms = TariffTerms(allowance_basis=AllowanceBasis.GROSS)

    bill = settle(imported=6000, exported=5500, terms=terms)

    assert bill.billed_kwh == 500
    assert bill.subsidized_kwh == 0
    assert bill.market_kwh == 500
    assert bill.energy_net == pytest.approx(500 * 70.104)
    # Nothing left, although no subsidized line was ever written.
    assert bill.allowance_remaining_kwh == 0


def test_the_netted_basis_subsidizes_the_same_consumption() -> None:
    bill = settle(imported=6000, exported=5500)

    assert bill.billed_kwh == 500
    assert bill.subsidized_kwh == 500
    assert bill.market_kwh == 0
    assert bill.allowance_remaining_kwh == pytest.approx(2523 - 500)


def test_the_gross_basis_spends_the_allowance_before_the_billed_energy() -> None:
    """Withdrawal within the allowance leaves the rest of it for netted consumption."""

    terms = TariffTerms(allowance_basis=AllowanceBasis.GROSS)

    bill = settle(imported=2000, exported=1500, terms=terms)

    assert bill.billed_kwh == 500
    assert bill.subsidized_kwh == 500
    assert bill.allowance_remaining_kwh == pytest.approx(2523 - 2000)


def test_gross_settlement_bills_everything_and_buys_everything() -> None:
    terms = TariffTerms(mode=SettlementMode.BRUTTO)

    bill = settle(imported=5000, exported=3000, terms=terms)

    assert bill.billed_kwh == 5000
    assert bill.surplus_kwh == 3000
    assert bill.surplus_net == forint(3000 * 5.11)


def test_the_standing_charge_is_owed_on_a_silent_meter() -> None:
    bill = settle(imported=0, exported=0)

    assert bill.energy_net == 0
    assert bill.gross_total == 1836


def test_vat_is_applied_to_energy_and_standing_charge_together() -> None:
    bill = settle(imported=1000)

    net = 1000 * 36.386 + 1446
    assert bill.net_total == pytest.approx(net)
    assert bill.vat == forint(net * 0.27)


def test_the_surplus_is_not_deducted_from_the_amount_payable() -> None:
    bill = settle(imported=0, exported=1000)

    assert bill.gross_total == 1836
    assert bill.surplus_net == forint(1000 * 5.11)
    assert bill.net_position == 1836 - forint(1000 * 5.11)


def test_a_price_change_splits_the_period() -> None:
    schedule = PriceSchedule(
        [
            Prices(date(2024, 1, 1), subsidized=36.386, market=70.104, feed_in=5.11),
            Prices(date(2024, 7, 1), subsidized=40.0, market=80.0, feed_in=6.0),
        ]
    )

    bill = calculate(
        YEAR,
        MeterReadings(imported_kwh=0, exported_kwh=1000),
        schedule,
        TERMS,
        standing_charge_months=12,
        feed_in_by_segment=[400, 600],
    )

    assert [line.unit_price for line in bill.surplus] == [5.11, 6.0]
    assert bill.surplus_net == forint(400 * 5.11) + forint(600 * 6.0)


def test_energy_is_priced_at_the_rate_in_force_in_each_segment() -> None:
    schedule = PriceSchedule(
        [
            Prices(date(2024, 1, 1), subsidized=30.0, market=60.0, feed_in=5.0),
            Prices(date(2024, 7, 1), subsidized=40.0, market=80.0, feed_in=6.0),
        ]
    )

    bill = calculate(
        YEAR,
        MeterReadings(imported_kwh=1000),
        schedule,
        TERMS,
        standing_charge_months=12,
        consumption_by_segment=[600, 400],
    )

    # All within the allowance, so both lines are subsidized, at each rate.
    assert [round(line.kwh, 6) for line in bill.subsidized] == [600, 400]
    assert bill.energy_net == pytest.approx(600 * 30.0 + 400 * 40.0)


def test_quantities_fall_back_to_a_day_split() -> None:
    schedule = PriceSchedule(
        [
            Prices(date(2024, 1, 1), subsidized=30.0, market=60.0, feed_in=5.0),
            Prices(date(2024, 7, 1), subsidized=40.0, market=80.0, feed_in=6.0),
        ]
    )

    bill = calculate(
        YEAR, MeterReadings(0, 365), schedule, TERMS, standing_charge_months=12
    )

    first, second = bill.surplus
    assert first.kwh + second.kwh == pytest.approx(365)
    assert first.kwh == pytest.approx(365 * 182 / 365)


def test_segment_quantities_are_a_shape_scaled_to_the_settled_total() -> None:
    """Netting fixes the totals; the per-segment figures only say where they fell."""

    schedule = PriceSchedule(
        [
            Prices(date(2024, 1, 1), subsidized=30.0, market=60.0, feed_in=5.0),
            Prices(date(2024, 7, 1), subsidized=40.0, market=80.0, feed_in=6.0),
        ]
    )
    # 4 000 withdrawn against 1 000 fed in: 3 000 billed, in the 3:1 shape of
    # the withdrawal, not the 3 000 and 1 000 the meters recorded.
    bill = calculate(
        YEAR,
        MeterReadings(imported_kwh=4000, exported_kwh=1000),
        schedule,
        TERMS,
        standing_charge_months=12,
        consumption_by_segment=[3000, 1000],
        feed_in_by_segment=[200, 800],
    )

    assert bill.billed_kwh == 3000
    assert [round(line.kwh, 6) for line in bill.subsidized] == [1892.25, 630.75]
    assert bill.subsidized_kwh + bill.market_kwh == pytest.approx(3000)
    assert bill.surplus == ()


def test_gross_settlement_lines_add_up_to_the_gross_quantities() -> None:
    """Under brutto the recorded shape and the settled totals always differ."""

    schedule = PriceSchedule(
        [
            Prices(date(2024, 1, 1), subsidized=30.0, market=60.0, feed_in=5.0),
            Prices(date(2024, 7, 1), subsidized=40.0, market=80.0, feed_in=6.0),
        ]
    )
    terms = TariffTerms(mode=SettlementMode.BRUTTO)

    bill = calculate(
        YEAR,
        MeterReadings(imported_kwh=4000, exported_kwh=5000),
        schedule,
        terms,
        standing_charge_months=12,
        consumption_by_segment=[3000, 1000],
        feed_in_by_segment=[2000, 3000],
    )

    assert [round(line.kwh, 6) for line in (*bill.subsidized, *bill.market)] == [
        1892.25,
        630.75,
        1107.75,
        369.25,
    ]
    assert bill.subsidized_kwh + bill.market_kwh == pytest.approx(4000)
    assert [line.kwh for line in bill.surplus] == [2000, 3000]
    assert bill.surplus_net == forint(2000 * 5.0) + forint(3000 * 6.0)


def test_an_empty_shape_falls_back_to_a_day_split() -> None:
    schedule = PriceSchedule(
        [
            Prices(date(2024, 1, 1), subsidized=30.0, market=60.0, feed_in=5.0),
            Prices(date(2024, 7, 1), subsidized=40.0, market=80.0, feed_in=6.0),
        ]
    )

    bill = calculate(
        YEAR,
        MeterReadings(0, 365),
        schedule,
        TERMS,
        standing_charge_months=12,
        feed_in_by_segment=[0, 0],
    )

    first, second = bill.surplus
    assert first.kwh == pytest.approx(365 * 182 / 365)
    assert first.kwh + second.kwh == pytest.approx(365)


def test_a_wrong_number_of_segment_quantities_is_rejected() -> None:
    with pytest.raises(ValueError, match="Expected 1 per-segment quantities"):
        calculate(
            YEAR,
            MeterReadings(1000),
            FLAT,
            TERMS,
            standing_charge_months=12,
            consumption_by_segment=[500, 500],
        )


def test_a_period_must_end_after_it_starts() -> None:
    with pytest.raises(ValueError, match="must end after it starts"):
        SettlementPeriod(date(2024, 5, 1), date(2024, 5, 1))


def test_prices_before_the_schedule_begins_are_an_error() -> None:
    with pytest.raises(ValueError, match="No prices are known"):
        FLAT.at(date(2019, 1, 1))


def test_two_prices_cannot_start_on_the_same_day() -> None:
    with pytest.raises(ValueError, match="same day"):
        PriceSchedule(
            [
                Prices(date(2024, 1, 1), subsidized=1, market=2, feed_in=3),
                Prices(date(2024, 1, 1), subsidized=4, market=5, feed_in=6),
            ]
        )
