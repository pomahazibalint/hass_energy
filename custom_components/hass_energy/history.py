"""What the meters did, read from the recorder's long-term statistics.

The recorder compiles an hourly sum for every energy sensor with a total state
class, applies its own reset and dip detection, keeps the rows indefinitely and
lets a user repair an outlier from the Statistics page. That is the record the
integration used to keep for itself, kept better, so it is read instead.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import partial

from homeassistant.components.recorder.statistics import (
    get_metadata,
    statistics_during_period,
)

# Home Assistant does not re-export this, but it is the documented way to
# reach the recorder's executor.
from homeassistant.components.recorder.util import get_instance  # type: ignore[attr-defined]
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .billing import Flows

KWH = "kWh"

#: The flows an hour is made of, each fed by any number of statistics. The
#: first two are the grid meters, which are the record; the rest describe
#: what the house did with what the grid record shows.
ROLES = ("imported", "exported", "produced", "charged", "discharged")
GRID_ROLES = ROLES[:2]


@dataclass(frozen=True)
class Observed:
    """The hours between two instants, as the recorder has them."""

    #: One entry per hour from start to end, zero where nothing was recorded.
    hours: list[Flows]
    #: Start of the earliest hour a grid meter has a row for, or None when
    #: the recorder has nothing of the grid for the window. The record begins
    #: here: earlier hours are the seeded remainder's, and nothing in them
    #: is published.
    first: datetime | None
    #: Sources the recorder has never compiled statistics for.
    unrecorded: list[str]
    #: Start of the earliest hour each source has a row for, for the ones
    #: that have any.
    first_of: dict[str, datetime] = field(default_factory=dict)
    #: Start of the earliest hour every one of the household's other sources
    #: covers within the grid record, or None when none is named or one of
    #: them has no rows there. Before it the house's flows are unknowable,
    #: not zero, and the other sources are read as nothing.
    household_first: datetime | None = None

    @property
    def imported_kwh(self) -> float:
        return sum(hour.imported_kwh for hour in self.hours)

    @property
    def exported_kwh(self) -> float:
        return sum(hour.exported_kwh for hour in self.hours)

    @property
    def produced_kwh(self) -> float:
        return sum(hour.produced_kwh for hour in self.hours)

    @property
    def consumption_kwh(self) -> float:
        return sum(hour.consumption_kwh for hour in self.hours)

    @property
    def solar_kept_kwh(self) -> float:
        return sum(hour.solar_kept_kwh for hour in self.hours)

    @property
    def shortfall_kwh(self) -> float:
        return sum(hour.shortfall_kwh for hour in self.hours)


async def async_observe(
    hass: HomeAssistant,
    roles: Mapping[str, Sequence[str]],
    start: datetime,
    end: datetime,
) -> Observed:
    """Read hourly flows between two UTC instants, in kWh.

    ``roles`` names the statistics feeding each flow; a role with several is
    summed. ``start`` must be on an hour. The recorder converts units, so a
    source in Wh or MWh comes back in kWh. An hour without a row is an hour
    the source did not report, which costs nothing and is not an error.

    The household's other sources are taken only where the grid record
    exists and every one of them has begun. An hour the grid meters did not
    report has nothing to attribute production to, and an hour one inverter
    reported and another had not yet begun to is not the house's hour: the
    missing one is unknown, not zero.
    """

    sources = [source for role in ROLES for source in roles.get(role, ())]
    instance = get_instance(hass)
    rows = await instance.async_add_executor_job(
        statistics_during_period,
        hass,
        start,
        end,
        set(sources),
        "hour",
        {"energy": KWH},
        {"change"},
    )
    metadata = await instance.async_add_executor_job(
        partial(get_metadata, hass, statistic_ids=set(sources))
    )

    # A total sensor may fall; the recorder reports that as a negative
    # change, and energy cannot be negative.
    changes = {
        source: {row["start"]: max(row.get("change") or 0.0, 0.0) for row in rows.get(source, [])}
        for source in sources
    }
    first_of = {
        source: dt_util.utc_from_timestamp(min(per_source))
        for source, per_source in changes.items()
        if per_source
    }

    grid = [source for role in GRID_ROLES for source in roles.get(role, ())]
    first = min((first_of[source] for source in grid if source in first_of), default=None)
    household = [source for source in sources if source not in grid]
    household_first: datetime | None = None
    if household and first is not None and all(source in first_of for source in household):
        household_first = max(first, *(first_of[source] for source in household))

    def flow(role: str, at: float, cursor: datetime) -> float:
        if role not in GRID_ROLES and (household_first is None or cursor < household_first):
            return 0.0
        return sum(changes[source].get(at, 0.0) for source in roles.get(role, ()))

    hours: list[Flows] = []
    cursor = start
    while cursor < end:
        at = cursor.timestamp()
        hours.append(Flows(cursor, **{f"{role}_kwh": flow(role, at, cursor) for role in ROLES}))
        cursor += timedelta(hours=1)

    return Observed(
        hours=hours,
        first=first,
        unrecorded=[source for source in sources if source not in metadata],
        first_of=first_of,
        household_first=household_first,
    )
