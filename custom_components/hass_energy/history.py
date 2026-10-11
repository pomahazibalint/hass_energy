"""What the meters did, read from the recorder's long-term statistics.

The recorder compiles an hourly sum for every energy sensor with a total state
class, applies its own reset and dip detection, keeps the rows indefinitely and
lets a user repair an outlier from the Statistics page. That is the record the
integration used to keep for itself, kept better, so it is read instead.
"""

from __future__ import annotations

from dataclasses import dataclass
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

from .billing import Hour

KWH = "kWh"


@dataclass(frozen=True)
class Observed:
    """The hours between two instants, as the recorder has them."""

    #: One entry per hour from start to end, zero where nothing was recorded.
    hours: list[Hour]
    #: Start of the earliest hour any source has a row for, or None when the
    #: recorder has nothing at all for the window.
    first: datetime | None
    #: Sources the recorder has never compiled statistics for.
    unrecorded: list[str]

    @property
    def imported_kwh(self) -> float:
        return sum(hour.imported_kwh for hour in self.hours)

    @property
    def exported_kwh(self) -> float:
        return sum(hour.exported_kwh for hour in self.hours)


async def async_observe(
    hass: HomeAssistant,
    import_entity: str,
    export_entity: str | None,
    start: datetime,
    end: datetime,
) -> Observed:
    """Read hourly import and export between two UTC instants, in kWh.

    ``start`` must be on an hour. The recorder converts units, so a source in
    Wh or MWh comes back in kWh. An hour without a row is an hour the source
    did not report, which costs nothing and is not an error.
    """

    sources = [import_entity] + ([export_entity] if export_entity else [])
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

    changes = {
        source: {row["start"]: row.get("change") or 0.0 for row in rows.get(source, [])}
        for source in sources
    }
    first = min((ts for per_source in changes.values() for ts in per_source), default=None)

    hours: list[Hour] = []
    cursor = start
    while cursor < end:
        at = cursor.timestamp()
        hours.append(
            Hour(
                cursor,
                # A total sensor may fall; the recorder reports that as a
                # negative change, and energy cannot be negative.
                imported_kwh=max(changes[import_entity].get(at, 0.0), 0.0),
                exported_kwh=(
                    max(changes[export_entity].get(at, 0.0), 0.0) if export_entity else 0.0
                ),
            )
        )
        cursor += timedelta(hours=1)

    return Observed(
        hours=hours,
        first=dt_util.utc_from_timestamp(first) if first is not None else None,
        unrecorded=[source for source in sources if source not in metadata],
    )
