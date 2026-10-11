"""Publishing the hourly costs as statistics the energy dashboard reads.

The dashboard is a statistics viewer: it draws the hourly change in a
statistic's sum. A live sensor reaches it only through the recorder's own
compile, and cannot rewrite an hour it has already published. Statistics
written here can: a row written for an hour that already has one replaces it,
so a backdated price or a repaired meter reading rewrites history rather than
appearing as a spike in the hour the correction was made.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Final

from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.models.statistics import StatisticMeanType
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    statistics_during_period,
)

# Home Assistant does not re-export this, but it is the documented way to
# reach the recorder's executor.
from homeassistant.components.recorder.util import get_instance  # type: ignore[attr-defined]
from homeassistant.core import HomeAssistant
from homeassistant.util import slugify

from .billing import HourCost
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

GRID_COST: Final = "grid_cost"
EXPORT_COMPENSATION: Final = "export_compensation"
#: The statistics the dashboard is pointed at.
COST_KINDS: Final = (GRID_COST, EXPORT_COMPENSATION)
#: Written by the invoice import, kept here so removal can find them.
INVOICE_KINDS: Final = ("imported_energy", "exported_energy", "settlement_cost", "surplus_value")

#: Far enough back to precede any period, for reading a statistic's history.
EPOCH: Final = datetime(2000, 1, 1, tzinfo=UTC)

#: Two figures closer than this are the same figure, so a row is left alone.
TOLERANCE: Final = 1e-6


def statistic_id(entry_id: str, kind: str) -> str:
    """Statistic ids are slugs, and an entry id is not one."""

    return f"{DOMAIN}:{slugify(entry_id)}_{kind}"


def _metadata(entry_id: str, title: str, kind: str, currency: str) -> StatisticMetaData:
    return StatisticMetaData(
        mean_type=StatisticMeanType.NONE,
        has_sum=True,
        unit_class=None,
        name=f"{title} {kind.replace('_', ' ')}",
        source=DOMAIN,
        statistic_id=statistic_id(entry_id, kind),
        unit_of_measurement=currency,
    )


def _value(cost: HourCost, kind: str) -> float:
    return cost.grid_cost if kind == GRID_COST else float(cost.compensation)


async def async_publish(
    hass: HomeAssistant,
    entry_id: str,
    title: str,
    period_start: datetime,
    costs: list[HourCost],
) -> None:
    """Write the period's hourly costs, replacing only the rows that changed.

    The sum continues from wherever the statistic stood before the period
    began, so a closed settlement does not break the series. In ordinary
    operation only the latest hour is new; after a price edit or a repaired
    reading, every hour from that point on is rewritten.
    """

    ids = {kind: statistic_id(entry_id, kind) for kind in COST_KINDS}
    instance = get_instance(hass)
    before = await instance.async_add_executor_job(
        statistics_during_period,
        hass,
        EPOCH,
        period_start,
        set(ids.values()),
        "hour",
        None,
        {"sum"},
    )
    existing = await instance.async_add_executor_job(
        statistics_during_period,
        hass,
        period_start,
        None,
        set(ids.values()),
        "hour",
        None,
        {"state", "sum"},
    )

    for kind, stat_id in ids.items():
        earlier = before.get(stat_id) or []
        running = float(earlier[-1]["sum"] or 0.0) if earlier else 0.0
        written = {
            row["start"]: (row.get("state"), row.get("sum")) for row in existing.get(stat_id, [])
        }
        changed: list[StatisticData] = []
        for cost in costs:
            value = _value(cost, kind)
            running += value
            have = written.get(cost.start.timestamp())
            if (
                have is None
                or have[0] is None
                or have[1] is None
                or abs(have[0] - value) > TOLERANCE
                or abs(have[1] - running) > TOLERANCE
            ):
                changed.append(StatisticData(start=cost.start, state=value, sum=running))
        if changed:
            async_add_external_statistics(
                hass, _metadata(entry_id, title, kind, hass.config.currency), changed
            )
            _LOGGER.debug("Wrote %d hours of %s for %s", len(changed), kind, entry_id)


async def async_remove(hass: HomeAssistant, entry_id: str) -> None:
    """Drop every statistic a metering point wrote, so none is left to offer."""

    ids = [statistic_id(entry_id, kind) for kind in (*COST_KINDS, *INVOICE_KINDS)]
    get_instance(hass).async_clear_statistics(ids)
