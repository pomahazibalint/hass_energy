"""Recording what the meters did, and deriving the settlement from it.

Only quantities are stored. Every figure with a currency on it is computed from
those quantities and the current contract, so correcting a price or switching
the allowance basis re-values history instead of contradicting it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from . import issues
from .billing import Bill, MeterReadings, SettlementPeriod, calculate
from .const import (
    CONF_EXPORT_ENTITY,
    CONF_IMPORT_ENTITY,
    DOMAIN,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .settings import schedule_from_options, standing_charge_months, terms_from_options

_LOGGER = logging.getLogger(__name__)

#: Written back this long after a reading, so a chatty meter does not turn into
#: a chatty disk.
SAVE_DELAY = 30

#: Assumed length of a settlement period until a meter reading ends it. The two
#: reference invoices ran 359 and 368 days, so this is a placeholder for the
#: allowance to be earned against, never a prediction of the boundary.
NOMINAL_PERIOD_DAYS = 365


@dataclass
class Bucket:
    """Energy recorded while one set of prices was in force."""

    imported: float = 0.0
    exported: float = 0.0


@dataclass
class PeriodState:
    """Everything known about the settlement period in progress."""

    start: date
    buckets: dict[str, Bucket] = field(default_factory=dict)
    last_import: float | None = None
    last_export: float | None = None

    @property
    def imported(self) -> float:
        return sum(bucket.imported for bucket in self.buckets.values())

    @property
    def exported(self) -> float:
        return sum(bucket.exported for bucket in self.buckets.values())

    def as_dict(self) -> dict[str, Any]:
        return {
            "period_start": self.start.isoformat(),
            "last_import": self.last_import,
            "last_export": self.last_export,
            "buckets": {
                key: {"imported": bucket.imported, "exported": bucket.exported}
                for key, bucket in self.buckets.items()
            },
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> PeriodState:
        return cls(
            start=date.fromisoformat(raw["period_start"]),
            buckets={
                key: Bucket(float(value["imported"]), float(value["exported"]))
                for key, value in (raw.get("buckets") or {}).items()
            },
            last_import=raw.get("last_import"),
            last_export=raw.get("last_export"),
        )


class SettlementCoordinator(DataUpdateCoordinator[Bill]):
    """Accrues meter deltas and hands entities a freshly derived settlement."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=None)
        self.entry = entry
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{STORAGE_KEY}.{entry.entry_id}"
        )
        self.state = PeriodState(start=dt_util.now().date())

    @property
    def import_entity(self) -> str:
        return str(self.entry.data[CONF_IMPORT_ENTITY])

    @property
    def export_entity(self) -> str | None:
        entity: str | None = self.entry.data.get(CONF_EXPORT_ENTITY)
        return entity

    async def async_load(self) -> None:
        """Restore recorded quantities and start watching the meters."""

        stored = await self._store.async_load()
        if stored:
            self.state = PeriodState.from_dict(stored)

        sources = [self.import_entity]
        if self.export_entity:
            sources.append(self.export_entity)
        self.entry.async_on_unload(
            async_track_state_change_event(self.hass, sources, self._handle_source)
        )
        self._seed_from_current_states()
        self.refresh_settlement()

    def _seed_from_current_states(self) -> None:
        """Take the first reading without counting it as consumption.

        A meter's absolute value says nothing about what happened while Home
        Assistant was not looking, so the first sighting only establishes a
        baseline.
        """

        if self.state.last_import is None:
            self.state.last_import = self._read(self.import_entity)
        if self.export_entity and self.state.last_export is None:
            self.state.last_export = self._read(self.export_entity)

    def _read(self, entity_id: str) -> float | None:
        state = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return None
        try:
            return float(state.state)
        except ValueError:
            _LOGGER.debug("%s is not numeric: %s", entity_id, state.state)
            return None

    @callback
    def _handle_source(self, event: Event[EventStateChangedData]) -> None:
        entity_id = event.data["entity_id"]
        reading = self._read(entity_id)
        if reading is None:
            return

        if entity_id == self.import_entity:
            delta = self._delta(self.state.last_import, reading)
            self.state.last_import = reading
            self._bucket().imported += delta
        else:
            delta = self._delta(self.state.last_export, reading)
            self.state.last_export = reading
            self._bucket().exported += delta

        self._store.async_delay_save(self.state.as_dict, SAVE_DELAY)
        self.refresh_settlement()

    @staticmethod
    def _delta(previous: float | None, reading: float) -> float:
        """How much the meter moved.

        A reading below the last one means the source restarted its total, so
        the new reading is the movement rather than a negative quantity.
        """

        if previous is None:
            return 0.0
        return reading - previous if reading >= previous else reading

    def _bucket(self, today: date | None = None) -> Bucket:
        """The bucket for the prices in force today."""

        day = today or dt_util.now().date()
        schedule = schedule_from_options(self.entry.options)
        key = schedule.at(max(day, schedule.entries[0].valid_from)).valid_from.isoformat()
        return self.state.buckets.setdefault(key, Bucket())

    def days_elapsed(self, today: date | None = None) -> int:
        """How far into the settlement period we are."""

        day = today or dt_util.now().date()
        return max((day - self.state.start).days, 0)

    def period_end(self, today: date | None = None) -> date:
        """Where the period is assumed to run to.

        A nominal year rather than today, because the allowance is annual and
        prorating it to the days elapsed would report a household as over its
        allowance a week into a period it will comfortably finish inside. The
        real end arrives with the meter reading, through close_settlement.
        """

        return self.state.start + timedelta(days=NOMINAL_PERIOD_DAYS)

    def refresh_settlement(self) -> None:
        """Re-derive the settlement and re-check what could be wrong with it.

        The checks run here rather than on a timer so they cannot describe a
        state the integration has already moved on from.
        """

        covered = self.prices_cover_period()
        issues.price_coverage(self.hass, self.entry.entry_id, covered, self.state.start)
        issues.settlement_overdue(self.hass, self.entry.entry_id, self.days_elapsed())
        issues.source_missing(self.hass, self.entry.entry_id, self.missing_sources())

        if not covered:
            # Every derived figure is unanswerable, which is not the same as
            # zero, so the entities go unavailable rather than report a guess.
            self.async_set_update_error(
                UpdateFailed(
                    f"No prices are known for {self.state.start}, "
                    "when the settlement period began."
                )
            )
            return

        self.async_set_updated_data(self.build_bill())

    def missing_sources(self) -> list[str]:
        """Configured meters that are not currently reporting a number."""

        sources = [self.import_entity]
        if self.export_entity:
            sources.append(self.export_entity)
        return [entity for entity in sources if self._read(entity) is None]

    def prices_cover_period(self) -> bool:
        """Whether the schedule reaches back to the start of the period."""

        schedule = schedule_from_options(self.entry.options)
        return schedule.entries[0].valid_from <= self.state.start

    def current_unit_price(self, today: date | None = None) -> float:
        """What the next kWh costs, at the band in force.

        The figure to point Home Assistant's energy dashboard at, since that
        wants a price rather than a bill.
        """

        day = today or dt_util.now().date()
        schedule = schedule_from_options(self.entry.options)
        prices = schedule.at(max(day, schedule.entries[0].valid_from))
        bill = self.data
        if bill is not None and bill.billed_kwh >= bill.allowance_kwh:
            return prices.market
        return prices.subsidized

    def seed(
        self, period_start: date, imported: float, exported: float, today: date | None = None
    ) -> None:
        """Adopt a settlement period already under way.

        Installed in March, the integration would otherwise account from zero
        for a period that began in September. The quantities are spread across
        the price periods elapsed by day, because the shape of energy nobody
        observed is unknowable; everything recorded from here on is exact.
        """

        day = today or dt_util.now().date()
        schedule = schedule_from_options(self.entry.options)
        # Recording what the meter did must not depend on being able to price
        # it. A period starting before the schedule does is normal on a fresh
        # install, where the only price so far is the one dated today; the
        # missing prices are reported as a repair, not by refusing the figures.
        window_start = max(period_start, schedule.entries[0].valid_from)
        end = max(day, window_start + timedelta(days=1))
        segments = schedule.segments(window_start, end)
        days = sum(segment.days for segment in segments) or 1

        # Built whole and adopted at the end, so a period that cannot be
        # divided up leaves the previous one untouched rather than replacing it
        # with nothing.
        buckets = {
            segment.prices.valid_from.isoformat(): Bucket(
                imported=imported * segment.days / days,
                exported=exported * segment.days / days,
            )
            for segment in segments
        }
        self.state = PeriodState(
            start=period_start,
            buckets=buckets,
            last_import=self.state.last_import,
            last_export=self.state.last_export,
        )

    def build_bill(self, today: date | None = None) -> Bill:
        """Derive the settlement from what has been recorded so far."""

        schedule = schedule_from_options(self.entry.options)
        period = SettlementPeriod(self.state.start, self.period_end(today))
        segments = schedule.segments(period.start, period.end)

        imported: list[float] = []
        exported: list[float] = []
        for segment in segments:
            bucket = self.state.buckets.get(segment.prices.valid_from.isoformat(), Bucket())
            imported.append(bucket.imported)
            exported.append(bucket.exported)

        # Totals come from everything recorded, not from the buckets the
        # current schedule happens to reach. Editing prices changes which
        # buckets a segment claims, and energy must not disappear from the bill
        # because a price boundary moved. The per-segment figures are only the
        # shape of the apportionment; the engine nets and scales them, so the
        # settlement mode is its concern and not repeated here.
        readings = MeterReadings(self.state.imported, self.state.exported)

        return calculate(
            period,
            readings,
            schedule,
            terms_from_options(self.entry.options),
            standing_charge_months=standing_charge_months(self.entry.options),
            consumption_by_segment=imported,
            feed_in_by_segment=exported,
        )

    async def async_shutdown(self) -> None:
        """Flush pending quantities.

        A delayed save is lost if the entry reloads before it fires, and losing
        half a minute of accrual to a restart would be a silent error.
        """

        await self._store.async_save(self.state.as_dict())

    async def async_close_settlement(self, reading_date: date) -> None:
        """Start a new settlement period on the day the meter was read."""

        self.state = PeriodState(
            start=reading_date,
            last_import=self.state.last_import,
            last_export=self.state.last_export,
        )
        await self._store.async_save(self.state.as_dict())
        self.refresh_settlement()
