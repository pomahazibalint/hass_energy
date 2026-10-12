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
