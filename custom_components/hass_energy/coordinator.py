"""Deriving the settlement from what the recorder knows the meters did.

Nothing about energy is stored here. The period is a start date over the
recorder's hourly statistics for the import and export meters, so a backdated
price applies to the hours after its date, an outlier is corrected where Home
Assistant already offers to correct it, and closing a settlement is a date.
The one thing kept is energy the recorder never saw: what a seed said the
period held above what the statistics hold.

The household's other sources, production and a battery, come from the
energy dashboard's own preferences. They do not touch the bill; they say what
the house used and what the panels were worth, which is the bill without
them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from functools import partial
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    EVENT_RECORDER_HOURLY_STATISTICS_GENERATED,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from . import issues
from .billing import Bill, Flows, HourCost, Prices, SettlementPeriod, allocate, solar_value
from .const import (
    CONF_EXPORT_ENTITY,
    CONF_IMPORT_ENTITY,
    DOMAIN,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .costs import (
    EXPORT_COMPENSATION,
    GRID_COST,
    HOUSE_CONSUMPTION,
    KWH,
    SELF_CONSUMED_SOLAR,
    SOLAR_VALUE,
    Series,
    async_publish,
)
from .history import Observed, async_observe
from .preferences import Sources, async_follow, async_sources
from .settings import schedule_from_options, standing_charge_months, terms_from_options

_LOGGER = logging.getLogger(__name__)

#: Assumed length of a settlement period until a meter reading ends it. The two
#: reference invoices ran 359 and 368 days, so this is a placeholder for the
#: allowance to be earned against, never a prediction of the boundary.
NOMINAL_PERIOD_DAYS = 365


@dataclass(frozen=True)
class Disagreement:
    """Hours in which energy left the house without having entered it."""

    hours: int = 0
    lost_kwh: float = 0.0
    worst: datetime | None = None

    @classmethod
    def over(cls, flows: list[Flows], since: datetime | None) -> Disagreement:
        """The finding over the hours the household's sources cover.

        Before the first hour they cover, export above import is production
        nobody recorded, not a source in the wrong hour; with none named at
        all there is nothing to disagree.
        """

        if since is None:
            return cls()
        failing = [hour for hour in flows if hour.start >= since and hour.shortfall_kwh > 0]
        if not failing:
            return cls()
        return cls(
            hours=len(failing),
            lost_kwh=sum(hour.shortfall_kwh for hour in failing),
            worst=max(failing, key=lambda hour: hour.shortfall_kwh).start,
        )


@dataclass
class PeriodState:
    """Everything the integration has to remember about the period in progress."""

    start: date
    #: Energy the recorder never saw: what a seed said the period held above
    #: what the statistics hold. Spread across the hours before the recorder's
    #: history begins, because the shape of unobserved energy is unknowable.
    unobserved_imported: float = 0.0
    unobserved_exported: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "period_start": self.start.isoformat(),
            "unobserved_imported": self.unobserved_imported,
            "unobserved_exported": self.unobserved_exported,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> PeriodState:
        return cls(
            start=date.fromisoformat(raw["period_start"]),
            unobserved_imported=float(raw.get("unobserved_imported") or 0.0),
            unobserved_exported=float(raw.get("unobserved_exported") or 0.0),
        )


class SettlementStore(Store[dict[str, Any]]):
    """The period state on disk, with the record it replaced migrated away."""

    async def _async_migrate_func(
        self, old_major_version: int, old_minor_version: int, old_data: dict[str, Any]
    ) -> dict[str, Any]:
        if old_major_version == 1:
            # Version 1 kept its own record of energy in buckets. Its totals
            # are reconciled against the recorder on first load: whatever they
            # hold above what the statistics hold is the unobserved remainder.
            buckets = (old_data.get("buckets") or {}).values()
            return {
                "period_start": old_data["period_start"],
                "reconcile": {
                    "imported": sum(float(bucket["imported"]) for bucket in buckets),
                    "exported": sum(float(bucket["exported"]) for bucket in buckets),
                },
            }
        return old_data


class SettlementCoordinator(DataUpdateCoordinator[Bill]):
    """Settles the period from the recorder's hourly statistics."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=None)
        self.entry = entry
        self._store = SettlementStore(hass, STORAGE_VERSION, f"{STORAGE_KEY}.{entry.entry_id}")
        self.state = PeriodState(start=dt_util.now().date())
        #: What the last refresh read and derived, for diagnostics and for
        #: whatever publishes the hourly costs.
        self.observed: Observed | None = None
        self.costs: list[HourCost] = []
        #: The household's sources beyond the grid, as the energy dashboard
        #: has them, and what they add: the bill there would have been with
        #: no panels, and what the panels were worth each hour.
        self.sources = Sources()
        self.bill_without_solar: Bill | None = None
        self.solar_values: list[float] = []
        self.disagreement = Disagreement()

    @property
    def import_entity(self) -> str:
        return str(self.entry.data[CONF_IMPORT_ENTITY])

    @property
    def export_entity(self) -> str | None:
        entity: str | None = self.entry.data.get(CONF_EXPORT_ENTITY)
        return entity

    async def async_load(self) -> None:
        """Restore the period and follow the recorder's hourly compile."""

        stored = await self._store.async_load()
        reconcile = None
        if stored:
            self.state = PeriodState.from_dict(stored)
            reconcile = stored.get("reconcile")

        self.entry.async_on_unload(
            self.hass.bus.async_listen(EVENT_RECORDER_HOURLY_STATISTICS_GENERATED, self._hourly)
        )
        self.entry.async_on_unload(await async_follow(self.hass, self._preferences_saved))

        if reconcile:
            await self.async_seed(
                self.state.start, float(reconcile["imported"]), float(reconcile["exported"])
            )
        else:
            await self.async_refresh()

    @callback
    def _hourly(self, event: Event[Any]) -> None:
        self.hass.async_create_task(self.async_request_refresh())

    async def _preferences_saved(self) -> None:
        """A source named or dropped in the energy dashboard changes the figures."""

        await self.async_request_refresh()

    async def _async_update_data(self) -> Bill:
        """Re-derive the settlement and re-check what could be wrong with it.

        The checks run here rather than on a timer so they cannot describe a
        state the integration has already moved on from.
        """

        covered = self.prices_cover_period()
        issues.price_coverage(self.hass, self.entry.entry_id, covered, self.state.start)
        issues.settlement_overdue(self.hass, self.entry.entry_id, self.days_elapsed())
        issues.source_missing(self.hass, self.entry.entry_id, self.missing_sources())

        self.sources = await async_sources(self.hass, self.import_entity)
        observed = await self._observe()
        self.observed = observed
        issues.source_unrecorded(self.hass, self.entry.entry_id, observed.unrecorded)
        self.disagreement = Disagreement.over(observed.hours, observed.household_first)
        issues.sources_disagree(
            self.hass,
            self.entry.entry_id,
            self.disagreement.hours,
            self.disagreement.lost_kwh,
            self.disagreement.worst,
        )

        if not covered:
            # Every derived figure is unanswerable, which is not the same as
            # zero, so the entities go unavailable rather than report a guess.
            raise UpdateFailed(
                f"No prices are known for {self.state.start}, when the settlement period began."
            )

        period = SettlementPeriod(self.state.start, self.period_end())
        hours, seeded = self._with_unobserved(observed)
        settle = partial(
            allocate,
            period,
            schedule=schedule_from_options(self.entry.options),
            terms=terms_from_options(self.entry.options),
            standing_charge_months=standing_charge_months(self.entry.options),
            tz=dt_util.get_default_time_zone(),
        )
        bill, self.costs = await self.hass.async_add_executor_job(settle, hours)

        # The panels' worth is the bill there would have been without them.
        # Without a production source there is no counterfactual to run.
        if self.sources.production:
            self.bill_without_solar, without = await self.hass.async_add_executor_job(
                settle, [hour.without_solar() for hour in hours]
            )
            self.solar_values = solar_value(self.costs, without)
        else:
            self.bill_without_solar = None
            self.solar_values = []

        # Only hours the recorder saw are published. The seeded remainder is
        # in the bill, and in the netting position every later hour is costed
        # against, but a flat smear of cost over months nobody watched would
        # read in the dashboard as something that happened. The entities must
        # not go unavailable because the statistics could not be written; the
        # two are separate readers of the same bill.
        try:
            await async_publish(
                self.hass,
                self.entry.entry_id,
                self.entry.title,
                self._period_start(),
                self._series(observed, seeded),
            )
        except Exception:
            _LOGGER.exception("Could not publish the hourly statistics for %s", self.entry.title)
        return bill

    def _series(self, observed: Observed, seeded: set[datetime]) -> list[Series]:
        """Everything the dashboard can draw, over the hours the recorder saw.

        The bill's figures run from the first hour of the grid record. The
        house's figures run from the first hour the household's other sources
        cover as well, when any is named: before that the house's flows are
        unknowable, and a figure built on them would be a guess. A household
        with no source beyond the grid has no production to miss, and its
        consumption is the grid record itself. An hour carrying the seeded
        remainder is left out whatever the figure: what it holds is the
        invoice's, not the hour's.
        """

        hours = observed.hours

        def seen(figures: list[float], since: datetime | None) -> list[tuple[datetime, float]]:
            return [
                (hour.start, figure)
                for hour, figure in zip(hours, figures, strict=True)
                if since is not None and hour.start >= since and hour.start not in seeded
            ]

        house_since = self.house_since()
        with_solar = bool(self.sources.production)
        currency = self.hass.config.currency
        return [
            Series(GRID_COST, currency, seen([c.grid_cost for c in self.costs], observed.first)),
            Series(
                EXPORT_COMPENSATION,
                currency,
                seen([float(c.compensation) for c in self.costs], observed.first),
            ),
            Series(
                HOUSE_CONSUMPTION,
                KWH,
                seen([hour.consumption_kwh for hour in hours], house_since),
            ),
            Series(
                SELF_CONSUMED_SOLAR,
                KWH,
                seen([hour.solar_kept_kwh for hour in hours], house_since) if with_solar else None,
            ),
            Series(
                SOLAR_VALUE,
                currency,
                seen(self.solar_values, house_since) if with_solar else None,
            ),
        ]

    def _period_start(self) -> datetime:
        """The UTC instant the period began, on the local calendar."""

        return dt_util.as_utc(dt_util.start_of_local_day(self.state.start))

    async def _observe(self) -> Observed:
        """The period's hours so far, as the recorder has them."""

        end = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
        roles = {
            "imported": (self.import_entity,),
            "exported": (self.export_entity,) if self.export_entity else (),
            "produced": self.sources.production,
            "charged": self.sources.charge,
            "discharged": self.sources.discharge,
        }
        return await async_observe(self.hass, roles, self._period_start(), end)

    def _with_unobserved(self, observed: Observed) -> tuple[list[Flows], set[datetime]]:
        """Lay the unobserved remainder over the hours before the record begins.

        With no hour before it, the remainder goes on the first hour there
        is; with no hours at all, on the period's first hour. Returns the
        hours and the starts of those that carry the remainder, which are
        the invoice's hours rather than the recorder's.
        """

        state = self.state
        if not (state.unobserved_imported or state.unobserved_exported):
            return observed.hours, set()

        hours = list(observed.hours)
        if not hours:
            hours = [Flows(self._period_start())]
        targets = [
            i
            for i, hour in enumerate(hours)
            if observed.first is None or hour.start < observed.first
        ] or [0]
        imported = state.unobserved_imported / len(targets)
        exported = state.unobserved_exported / len(targets)
        for i in targets:
            hours[i] = replace(
                hours[i],
                imported_kwh=hours[i].imported_kwh + imported,
                exported_kwh=hours[i].exported_kwh + exported,
            )
        return hours, {hours[i].start for i in targets}

    def _read(self, entity_id: str) -> float | None:
        state = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return None
        try:
            return float(state.state)
        except ValueError:
            _LOGGER.debug("%s is not numeric: %s", entity_id, state.state)
            return None

    def house_since(self) -> datetime | None:
        """The first hour the house's figures can be built on, if any.

        The grid record's first hour, or when the household's other sources
        are named, the first hour every one of them covers as well; see
        ``_series``. None while nothing is known of the house.
        """

        if self.observed is None:
            return None
        return self.observed.household_first if self.sources.ids else self.observed.first

    def _household_hours(self) -> list[Flows]:
        since = self.house_since()
        if self.observed is None or since is None:
            return []
        return [hour for hour in self.observed.hours if hour.start >= since]

    def household_consumption_kwh(self) -> float:
        return sum(hour.consumption_kwh for hour in self._household_hours())

    def household_solar_kept_kwh(self) -> float:
        return sum(hour.solar_kept_kwh for hour in self._household_hours())

    def solar_value_total(self) -> int | None:
        """What the panels have been worth over the period, as the invoice counts.

        The net position without them less the net position with them, so it
        is what the household would have paid more.
        """

        if self.bill_without_solar is None or self.data is None or self.house_since() is None:
            return None
        return self.bill_without_solar.net_position - self.data.net_position

    def days_elapsed(self, today: date | None = None) -> int:
        """How far into the settlement period we are."""

        day = today or dt_util.now().date()
        return max((day - self.state.start).days, 0)

    def period_end(self, today: date | None = None) -> date:
        """Where the period is assumed to run to.

        A nominal year rather than today, because the allowance is annual and
        prorating it to the days elapsed would report a household as over its
        allowance a week into a period it will comfortably finish inside. A
        period that has run past the year stretches to cover today, so every
        hour recorded has a price period to fall in. The real end arrives with
        the meter reading, through close_settlement.
        """

        day = today or dt_util.now().date()
        return max(self.state.start + timedelta(days=NOMINAL_PERIOD_DAYS), day + timedelta(days=1))

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

        prices = self._prices_today(today)
        bill = self.data
        if bill is not None and bill.allowance_remaining_kwh <= 0:
            return prices.market
        return prices.subsidized

    def current_feed_in_price(self, today: date | None = None) -> float:
        """What the supplier pays for the next kWh fed in beyond netting.

        The counterpart of ``current_unit_price`` for the energy dashboard's
        return-to-grid price. Under szaldó it is the price of surplus only:
        feed-in that netting absorbs is worth the withdrawal it cancels, which
        the dashboard cannot express, so the surplus owed sensor is the figure
        that matches the invoice.
        """

        return self._prices_today(today).feed_in

    def _prices_today(self, today: date | None = None) -> Prices:
        day = today or dt_util.now().date()
        schedule = schedule_from_options(self.entry.options)
        return schedule.at(max(day, schedule.entries[0].valid_from))

    async def async_seed(self, period_start: date, imported: float, exported: float) -> None:
        """Adopt a settlement period already under way.

        The figures are what the invoice and the meter say the period holds.
        Whatever the recorder already has for it is not seeded twice: only the
        part above the statistics is kept, and laid over the hours before the
        recorder's history begins. If the sources were recorded all along,
        there is nothing to keep and the period is simply read from history.
        Recording what the meter did must not depend on being able to price
        it, so missing prices are reported as a repair, not by refusing.
        """

        self.state = PeriodState(start=period_start)
        observed = await self._observe()
        self.state.unobserved_imported = max(imported - observed.imported_kwh, 0.0)
        self.state.unobserved_exported = max(exported - observed.exported_kwh, 0.0)
        await self._store.async_save(self.state.as_dict())
        await self.async_refresh()

    async def async_close_settlement(self, reading_date: date) -> None:
        """Start a new settlement period on the day the meter was read.

        The hours since the reading are in the recorder, whenever the reading
        is entered, so nothing is carried over by hand and nothing is lost.
        """

        self.state = PeriodState(start=reading_date)
        await self._store.async_save(self.state.as_dict())
        await self.async_refresh()
