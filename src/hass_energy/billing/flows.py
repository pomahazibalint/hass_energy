"""What every meter did in one hour, and what the house did with it.

The settlement needs only the grid meters. The other sources a household
records, production and a battery, say nothing about the bill but everything
about what the household did: what it used, how much of its own generation it
kept, and what the panels were worth, which is the bill without them.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .series import Hour, HourCost


@dataclass(frozen=True)
class Flows(Hour):
    """Every flow through the house in one hour, in kWh."""

    produced_kwh: float = 0.0
    charged_kwh: float = 0.0
    discharged_kwh: float = 0.0

    def __post_init__(self) -> None:
        super().__post_init__()
        if min(self.produced_kwh, self.charged_kwh, self.discharged_kwh) < 0:
            raise ValueError("Meter quantities cannot be negative.")

    @property
    def balance_kwh(self) -> float:
        """What entered the house less what left it.

        Import, production and battery discharge come in; export and battery
        charge go out. The difference is what the house used, when the meters
        agree about the hour.
        """

        return (
            self.imported_kwh
            + self.produced_kwh
            + self.discharged_kwh
            - self.exported_kwh
            - self.charged_kwh
        )

    @property
    def consumption_kwh(self) -> float:
        return max(self.balance_kwh, 0.0)

    @property
    def shortfall_kwh(self) -> float:
        """Energy that left the house without having entered it.

        That cannot happen, so a shortfall is a source reporting in the wrong
        hour: an inverter that lags the grid meter, or a production meter that
        counts what charged the battery. It is reported, never smoothed over,
        because the same rows feed every other viewer of them.
        """

        return max(-self.balance_kwh, 0.0)

    @property
    def solar_kept_kwh(self) -> float:
        """Production that stayed behind the meter.

        Consumed as it was made, or stored and consumed later; either way it
        is what the household did not buy because of the panels.
        """

        return max(self.produced_kwh - self.exported_kwh, 0.0)

    def without_solar(self) -> Hour:
        """The grid flows this hour would have had with no panels.

        What the panels supplied comes from the grid instead, and only export
        the panels could not have supplied remains, which is what a battery
        sent out. The counterfactual is the same whatever the settlement mode;
        the mode decides what the difference is worth.
        """

        return Hour(
            self.start,
            imported_kwh=self.imported_kwh + self.solar_kept_kwh,
            exported_kwh=max(self.exported_kwh - self.produced_kwh, 0.0),
        )


    def without_consumption(self) -> Hour:
        """The grid flows this hour would have had with nothing consumed.

        What the house drew from the grid is not imported, and what it took
        of its own production or battery goes out to the grid instead. The
        grid's share is what import could cover; the rest came from behind
        the meter. The difference in the bill is what the hour's consumption
        cost, and one rule covers both settlement modes: under szaldó a kWh
        not consumed nets whichever way it goes, and under gross settlement
        a grid kWh saves the band price while a solar kWh earns the feed-in
        price, which is the time-of-day effect of a tariff that buys back
        cheaply.
        """

        grid = min(self.imported_kwh, self.consumption_kwh)
        return Hour(
            self.start,
            imported_kwh=self.imported_kwh - grid,
            exported_kwh=self.exported_kwh + self.consumption_kwh - grid,
        )


def device_share(device_kwh: float, consumption_kwh: float) -> tuple[float, float]:
    """A device's share of an hour's consumption, and what it claims beyond it.

    A device cannot have used more than the house did, so a device meter
    that says so is reporting in the wrong hour, like an inverter that lags
    the grid meter. Its share is capped at the whole hour and the excess is
    returned to be reported, never smoothed over.
    """

    if device_kwh < 0 or consumption_kwh < 0:
        raise ValueError("Meter quantities cannot be negative.")
    excess = max(device_kwh - consumption_kwh, 0.0)
    if not consumption_kwh:
        return 0.0, excess
    return (device_kwh - excess) / consumption_kwh, excess


def solar_value(actual: Sequence[HourCost], without: Sequence[HourCost]) -> list[float]:
    """What the panels were worth in each hour.

    The movement of the net position without the panels less its movement
    with them: the extra grid cost the household would have borne, plus the
    compensation it would not have earned. Positive when the panels helped,
    which they can fail to do in an hour where the real export only netted
    against import that the counterfactual has to buy at the same price.
    """

    if len(actual) != len(without):
        raise ValueError("The two allocations must cover the same hours.")
    return [
        (cf.grid_cost - real.grid_cost) + (real.compensation - cf.compensation)
        for real, cf in zip(actual, without, strict=True)
    ]
