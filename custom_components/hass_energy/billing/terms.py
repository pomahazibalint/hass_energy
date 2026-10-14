# Vendored copy. Do not edit: edits are lost the next time the engine is
# copied. The original is src/hass_energy/billing/terms.py, and
# scripts/vendor_billing.py keeps this in step with it.
"""The contractual terms a settlement is calculated under."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

#: The allowance year runs from 1 August to 31 July, and what one year leaves
#: unused does not carry into the next.
ALLOWANCE_YEAR_STARTS = (8, 1)


def allowance_year_starts(start: date, end: date) -> list[date]:
    """Each 1 August strictly inside a stretch of time, in order.

    A settlement period that straddles one has two allowances, one per side,
    each against that side's consumption; the supplier splits the period
    there by a dictated or estimated reading.
    """

    month, day = ALLOWANCE_YEAR_STARTS
    starts = []
    for year in range(start.year, end.year + 1):
        boundary = date(year, month, day)
        if start < boundary < end:
            starts.append(boundary)
    return starts


class SettlementMode(StrEnum):
    """How generation is set against consumption.

    ``SZALDO`` nets feed-in against withdrawal over the settlement period and
    bills the difference. It is closed to new installations since 1 January
    2024 and runs out ten years after commissioning, or after an expansion, so
    every szaldó household has a date on which it becomes ``BRUTTO``.

    ``BRUTTO`` bills all withdrawal and pays for all feed-in separately.
    """

    SZALDO = "szaldo"
    BRUTTO = "brutto"


class AllowanceBasis(StrEnum):
    """Which quantity consumes the subsidized allowance.

    ``NETTED`` charges the allowance against the quantity actually settled,
    which under szaldó is withdrawal less feed-in. ``GROSS`` charges it against
    everything withdrawn, so a household that withdraws far more than the
    allowance has none left for its netted consumption and is billed at the
    market price throughout.

    259/2022 grants the allowance on consumption "up to which the residential
    consumer is entitled to withdraw", and does not say which basis applies to
    a szaldó household. It is configurable because the answer changes the bill
    substantially and only the supplier can settle it.
    """

    NETTED = "netted"
    GROSS = "gross"


@dataclass(frozen=True)
class TariffTerms:
    """Everything about a contract that is not a price or a meter reading."""

    #: Subsidized quantity per year per metering point. 2523 kWh for Hungarian
    #: residential electricity, apportioned across the period by day.
    annual_allowance_kwh: float = 2523.0
    #: Fixed distribution charge, net, per month. Owed whatever the meter says,
    #: and on a net-exporting household it is the whole bill.
    standing_charge_per_month: float = 120.5
    vat_percent: float = 27.0
    mode: SettlementMode = SettlementMode.SZALDO
    allowance_basis: AllowanceBasis = AllowanceBasis.NETTED
    currency: str = "Ft"

    def __post_init__(self) -> None:
        if self.annual_allowance_kwh < 0:
            raise ValueError("The allowance cannot be negative.")
        if self.standing_charge_per_month < 0:
            raise ValueError("The standing charge cannot be negative.")
        if not 0 <= self.vat_percent < 100:
            raise ValueError("VAT must be a percentage below 100.")

    def allowance_for(self, days: int) -> float:
        """The allowance earned over a number of days.

        259/2022 § 9 (1): the supplier applies daily apportionment, billing
        1/365 of the allowance per day of the billing period and everything
        above it at the market price. 365 is fixed by the decree, so a leap
        year earns a fraction more rather than the same amount.
        """

        if days < 0:
            raise ValueError("A settlement period cannot have negative days.")
        return self.annual_allowance_kwh * days / 365
