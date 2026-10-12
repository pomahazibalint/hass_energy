"""Publishing hourly figures as statistics the energy dashboard reads.

The dashboard is a statistics viewer: it draws the hourly change in a
statistic's sum. A live sensor reaches it only through the recorder's own
compile, and cannot rewrite an hour it has already published. Statistics
written here can: a row written for an hour that already has one replaces it,
so a backdated price or a repaired meter reading rewrites history rather than
appearing as a spike in the hour the correction was made.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from typing import Final

from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.models.statistics import StatisticMeanType
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_metadata,
    statistics_during_period,
)

# Home Assistant does not re-export this, but it is the documented way to
# reach the recorder's executor.
from homeassistant.components.recorder.util import get_instance  # type: ignore[attr-defined]
from homeassistant.core import HomeAssistant
from homeassistant.util import slugify

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

GRID_COST: Final = "grid_cost"
EXPORT_COMPENSATION: Final = "export_compensation"
HOUSE_CONSUMPTION: Final = "house_consumption"
SELF_CONSUMED_SOLAR: Final = "self_consumed_solar"
SOLAR_VALUE: Final = "solar_value"
#: The statistics the dashboard is pointed at.
COST_KINDS: Final = (GRID_COST, EXPORT_COMPENSATION)
#: What the household did, for the dashboard's own cards to draw.
HOUSEHOLD_KINDS: Final = (HOUSE_CONSUMPTION, SELF_CONSUMED_SOLAR, SOLAR_VALUE)
#: Written by the invoice import, kept here so removal can find them.
INVOICE_KINDS: Final = ("imported_energy", "exported_energy", "settlement_cost", "surplus_value")

KWH: Final = "kWh"

#: Far enough back to precede any period, for reading a statistic's history.
EPOCH: Final = datetime(2000, 1, 1, tzinfo=UTC)

#: Two figures closer than this are the same figure, so a row is left alone.
TOLERANCE: Final = 1e-6


@dataclass(frozen=True)
class Series:
    """One statistic's hourly figures for the period.

    ``rows`` is None for a figure whose sources the household lacks, which
    removes whatever the statistic held rather than leaving a stale series
    for the dashboard to keep offering.
    """

    kind: str
    unit: str
    rows: Sequence[tuple[datetime, float]] | None

    @property
    def unit_class(self) -> str | None:
        """Energy is declared so the dashboard can convert it; money is not."""

        return "energy" if self.unit == KWH else None


def statistic_id(entry_id: str, kind: str) -> str:
    """Statistic ids are slugs, and an entry id is not one."""

    return f"{DOMAIN}:{slugify(entry_id)}_{kind}"


def _metadata(entry_id: str, title: str, series: Series) -> StatisticMetaData:
    return StatisticMetaData(
        mean_type=StatisticMeanType.NONE,
        has_sum=True,
        unit_class=series.unit_class,
        name=f"{title} {series.kind.replace('_', ' ')}",
        source=DOMAIN,
        statistic_id=statistic_id(entry_id, series.kind),
        unit_of_measurement=series.unit,
    )


async def async_publish(
    hass: HomeAssistant,
    entry_id: str,
    title: str,
    period_start: datetime,
    series: Sequence[Series],
) -> None:
    """Write each series' hours, replacing only the rows that changed.

    The sum continues from wherever the statistic stood before the period
    began, so a closed settlement does not break the series. In ordinary
    operation only the latest hour is new; after a price edit or a repaired
    reading, every hour from that point on is rewritten.
    """

    ids = {one.kind: statistic_id(entry_id, one.kind) for one in series}
    instance = get_instance(hass)
    known = await instance.async_add_executor_job(
        partial(get_metadata, hass, statistic_ids=set(ids.values()))
    )
    absent = [ids[one.kind] for one in series if one.rows is None and ids[one.kind] in known]
    if absent:
        instance.async_clear_statistics(absent)
        _LOGGER.debug("Removed %s for %s: their sources are gone", absent, entry_id)

    present = [one for one in series if one.rows is not None]
    if not present:
        return
    wanted = {ids[one.kind] for one in present}
    before = await instance.async_add_executor_job(
        statistics_during_period, hass, EPOCH, period_start, wanted, "hour", None, {"sum"}
    )
    existing = await instance.async_add_executor_job(
        statistics_during_period,
        hass,
        period_start,
        None,
        wanted,
        "hour",
        None,
        {"state", "sum"},
    )

    for one in present:
        stat_id = ids[one.kind]
        earlier = before.get(stat_id) or []
        running = float(earlier[-1]["sum"] or 0.0) if earlier else 0.0
        written = {
            row["start"]: (row.get("state"), row.get("sum")) for row in existing.get(stat_id, [])
        }
        changed: list[StatisticData] = []
        for start, value in one.rows or ():
            running += value
            have = written.get(start.timestamp())
            if (
                have is None
                or have[0] is None
                or have[1] is None
                or abs(have[0] - value) > TOLERANCE
                or abs(have[1] - running) > TOLERANCE
            ):
                changed.append(StatisticData(start=start, state=value, sum=running))
        if changed:
            async_add_external_statistics(hass, _metadata(entry_id, title, one), changed)
            _LOGGER.debug("Wrote %d hours of %s for %s", len(changed), one.kind, entry_id)


async def async_remove(hass: HomeAssistant, entry_id: str) -> None:
    """Drop every statistic a metering point wrote, so none is left to offer."""

    ids = [
        statistic_id(entry_id, kind)
        for kind in (*COST_KINDS, *HOUSEHOLD_KINDS, *INVOICE_KINDS)
    ]
    get_instance(hass).async_clear_statistics(ids)
