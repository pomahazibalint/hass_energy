# Vendored copy. Do not edit: edits are lost the next time the engine is
# copied. The original is src/hass_energy/billing/__init__.py, and
# scripts/vendor_billing.py keeps this in step with it.
"""Settlement accounting, independent of Home Assistant.

The generator answers what the house used. This answers what the supplier will
charge for it, which turned out to be a different question: a settlement period
whose boundary is a meter reading rather than a date, prices that change inside
it, a standing charge owed however little energy is bought, and feed-in that is
bought back at a fraction of what the same kWh costs. ``allocate`` walks a
period hour by hour so the bill's movement can be shown where it arose.

Nothing here imports Home Assistant, so it can be checked against a real
invoice with an ordinary test.
"""

from __future__ import annotations

from .bill import Bill, Line, MeterReadings, SettlementPeriod, SurplusLine, forint
from .engine import calculate
from .flows import Flows, device_share, solar_value, with_battery
from .prices import Prices, PriceSchedule, Segment
from .projection import Day, a_year_before, allowance_runs_out, hours_of, project
from .rates import Rate, rate_of, rates
from .series import Hour, HourCost, allocate, marginal, settle
from .terms import AllowanceBasis, SettlementMode, TariffTerms

__all__ = [
    "AllowanceBasis",
    "Bill",
    "Day",
    "Flows",
    "Hour",
    "HourCost",
    "Line",
    "MeterReadings",
    "PriceSchedule",
    "Prices",
    "Rate",
    "Segment",
    "SettlementMode",
    "SettlementPeriod",
    "SurplusLine",
    "TariffTerms",
    "a_year_before",
    "allocate",
    "allowance_runs_out",
    "calculate",
    "device_share",
    "forint",
    "hours_of",
    "marginal",
    "project",
    "rate_of",
    "rates",
    "settle",
    "solar_value",
    "with_battery",
]
