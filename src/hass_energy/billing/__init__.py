"""Settlement accounting, independent of Home Assistant.

The generator answers what the house used. This answers what the supplier will
charge for it, which turned out to be a different question: a settlement period
whose boundary is a meter reading rather than a date, prices that change inside
it, a standing charge owed however little energy is bought, and feed-in that is
bought back at a fraction of what the same kWh costs.

Nothing here imports Home Assistant, so it can be checked against a real
invoice with an ordinary test.
"""

from __future__ import annotations

from .bill import Bill, Line, MeterReadings, SettlementPeriod, SurplusLine, forint
from .engine import calculate
from .prices import Prices, PriceSchedule, Segment
from .terms import AllowanceBasis, SettlementMode, TariffTerms

__all__ = [
    "AllowanceBasis",
    "Bill",
    "Line",
    "MeterReadings",
    "PriceSchedule",
    "Prices",
    "Segment",
    "SettlementMode",
    "SettlementPeriod",
    "SurplusLine",
    "TariffTerms",
    "calculate",
    "forint",
]
