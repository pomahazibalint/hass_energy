# Vendored copy. Do not edit: edits are lost the next time the engine is
# copied. The original is src/hass_energy/billing/bill.py, and
# scripts/vendor_billing.py keeps this in step with it.
"""What a settlement is made of."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal


def forint(value: float) -> int:
    """Round money the way an invoice does.

    Hungarian invoices carry whole forints and round half away from zero, which
    is not what Python's round() does.
    """

    return int(Decimal(str(value)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class SettlementPeriod:
    """The stretch of time one settlement covers.

    The boundary is a meter reading, not a date in the calendar: the two bills
    behind this model span 359 and 368 days, and the supplier announces the
    next reading as a two-week window. Nothing here assumes a year.
    """

    start: date
    end: date

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise ValueError("A settlement period must end after it starts.")

    @property
    def days(self) -> int:
        return (self.end - self.start).days


@dataclass(frozen=True)
class MeterReadings:
    """Withdrawal and feed-in over a settlement period, in kWh."""

    imported_kwh: float
    exported_kwh: float = 0.0

    def __post_init__(self) -> None:
        if self.imported_kwh < 0 or self.exported_kwh < 0:
            raise ValueError("Meter quantities cannot be negative.")


@dataclass(frozen=True)
class Line:
    """One priced quantity over one price period, as an invoice states it."""

    start: date
    end: date
    kwh: float
    unit_price: float

    @property
    def net(self) -> float:
        return self.kwh * self.unit_price


@dataclass(frozen=True)
class SurplusLine(Line):
    """Feed-in the supplier buys, for one price period.

    Rounded per line because the settlement statement rounds per line: the two
    bills state 2 800 Ft and 337 Ft, not one rounded total.
    """

    @property
    def rounded(self) -> int:
        return forint(self.net)


@dataclass(frozen=True)
class Bill:
    """An itemised settlement.

    Energy owed and feed-in bought are kept apart because the invoice keeps
    them apart: the surplus is claimed on a separate declaration, sits outside
    VAT, and does not reduce the amount payable.
    """

    period: SettlementPeriod
    readings: MeterReadings
    billed_kwh: float
    allowance_kwh: float
    subsidized: tuple[Line, ...] = field(default_factory=tuple)
    market: tuple[Line, ...] = field(default_factory=tuple)
    standing_charge_months: int = 0
    standing_charge_net: float = 0.0
    vat_percent: float = 0.0
    surplus_kwh: float = 0.0
    surplus: tuple[SurplusLine, ...] = field(default_factory=tuple)

    @property
    def subsidized_kwh(self) -> float:
        return sum(line.kwh for line in self.subsidized)

    @property
    def market_kwh(self) -> float:
        return sum(line.kwh for line in self.market)

    @property
    def energy_net(self) -> float:
        return sum(line.net for line in (*self.subsidized, *self.market))

    @property
    def net_total(self) -> float:
        return self.energy_net + self.standing_charge_net

    @property
    def vat(self) -> int:
        return forint(self.net_total * self.vat_percent / 100)

    @property
    def gross_total(self) -> int:
        """What the invoice asks for."""

        return forint(self.net_total) + self.vat

    @property
    def surplus_net(self) -> int:
        """What the supplier owes for feed-in that netting could not absorb."""

        return sum(line.rounded for line in self.surplus)

    @property
    def net_position(self) -> int:
        """Payable less the surplus owed: the household's actual position."""

        return self.gross_total - self.surplus_net
