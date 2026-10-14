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
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, tzinfo
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_RECORDER_HOURLY_STATISTICS_GENERATED
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from . import issues
from .billing import (
    Bill,
    Day,
    Flows,
    Hour,
    HourCost,
    Prices,
    PriceSchedule,
    Rate,
    SettlementMode,
    SettlementPeriod,
    TariffTerms,
    a_year_before,
    allocate,
    allowance_runs_out,
    device_share,
    forint,
    hours_of,
    marginal,
    project,
    rates,
    settle,
    solar_value,
    with_battery,
)
from .const import (
    CONF_EXPORT_ENTITY,
    CONF_IMPORT_ENTITY,
    DOMAIN,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .costs import (
    CONSUMPTION_COST,
    EXPORT_COMPENSATION,
    GRID_COST,
    HOUSE_CONSUMPTION,
    KWH,
    SELF_CONSUMED_SOLAR,
    SOLAR_VALUE,
    Series,
    async_publish,
    device_kind,
)
from .history import Observed, async_observe, async_observe_days
from .preferences import Sources, async_follow, async_sources
from .settings import (
    Battery,
    battery_from_options,
    schedule_from_options,
    standing_charge_months,
    terms_from_options,
)

_LOGGER = logging.getLogger(__name__)

#: A source the recorder has had no row from for this long has stopped being
#: recorded. An inverter is off every night and its sensors unavailable with
#: it, which is not a fault; two days is longer than any night.
STALE_AFTER = timedelta(days=2)

#: Assumed length of a settlement period until a meter reading ends it. The two
#: reference invoices ran 359 and 368 days, so this is a placeholder for the
#: allowance to be earned against, never a prediction of the boundary.
NOMINAL_PERIOD_DAYS = 365


@dataclass(frozen=True)
class Disagreement:
    """Hours in which energy left the house without having entered it.

    That cannot happen, so a source is reporting in the wrong hour, and the
    finding is reported rather than smoothed over. A device that claims
    more than the house used is a different finding, with its own repair:
    a meter that reports in bursts.
    """

    hours: int = 0
    lost_kwh: float = 0.0
    worst: datetime | None = None

    @classmethod
    def over(cls, losses: Mapping[datetime, float]) -> Disagreement:
        """The finding over the energy each hour lost to the disagreement."""

        failing = {start: lost for start, lost in losses.items() if lost > 0}
        if not failing:
            return cls()
        return cls(
            hours=len(failing),
            lost_kwh=sum(failing.values()),
            worst=max(failing, key=lambda start: failing[start]),
        )


@dataclass(frozen=True)
class Contract:
    """The terms every settlement in a refresh is run under."""

    period: SettlementPeriod
    schedule: PriceSchedule
    terms: TariffTerms
    standing_charge_months: int
    tz: tzinfo

    def allocate(self, hours: Sequence[Hour]) -> tuple[Bill, list[HourCost]]:
        return allocate(
            self.period,
            hours,
            self.schedule,
            self.terms,
            standing_charge_months=self.standing_charge_months,
            tz=self.tz,
        )

    def marginal(self, hours: Sequence[Hour], instead: Sequence[Hour]) -> list[float]:
        return marginal(
            self.period,
            hours,
            instead,
            self.schedule,
            self.terms,
            standing_charge_months=self.standing_charge_months,
            tz=self.tz,
        )

    def settle(self, hours: Sequence[Hour], terms: TariffTerms | None = None) -> Bill:
        return settle(
            self.period,
            hours,
            self.schedule,
            terms or self.terms,
            standing_charge_months=self.standing_charge_months,
            tz=self.tz,
        )


@dataclass(frozen=True)
class Outlook:
    """Where the period is heading, following last year's shape."""

    #: The bill the period lands on.
    bill: Bill
    #: When the allowance is gone for good, or None when it holds.
    allowance_runs_out: datetime | None
    #: Days still to come, and how many of them last year's shape covers;
    #: the rest are the straight line.
    days_remaining: int
    days_from_last_year: int

    @property
    def runs_out_on(self) -> date | None:
        if self.allowance_runs_out is None:
            return None
        return dt_util.as_local(self.allowance_runs_out).date()


def _outlook(
    contract: Contract,
    hours: Sequence[Hour],
    projected: Sequence[Day],
    days_from_last_year: int,
) -> Outlook:
    """Settle the hours so far and the days still to come as one period."""

    bill, costs = contract.allocate([*hours, *hours_of(projected, contract.tz)])
    return Outlook(bill, allowance_runs_out(costs), len(projected), days_from_last_year)


def _under_gross(
    contract: Contract, hours: Sequence[Hour], battery: Battery | None
) -> tuple[Bill, int | None]:
    """The period under gross settlement, and what a battery would have saved in it.

    Both whatever the entry's mode: under szaldó a battery's saving is near
    zero by construction, and the question matters for the switch, which
    is also what the bill under gross settlement answers.
    """

    gross = replace(contract.terms, mode=SettlementMode.BRUTTO)
    real = contract.settle(hours, gross)
    if battery is None:
        return real, None
    simulated = contract.settle(
        with_battery(hours, battery.capacity_kwh, battery.round_trip_efficiency), gross
    )
    return real, real.net_position - simulated.net_position


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
        #: What each hour's consumption cost, and each device's part of it,
        #: alongside the observed hours; and what each device claimed above
        #: the whole house, which is the device's part of the disagreement.
        self.consumption_costs: list[float] = []
        self.device_costs: dict[str, list[float]] = {}
        self.rates: list[Rate] = []
        #: What each hour's consumption would have cost bought from the grid,
        #: with no panels, and each device's part of that: what the panels
        #: saved is the difference. Empty without a production source, when
        #: there is nothing to have saved.
        self.purchase_costs: list[float] = []
        self.device_purchases: dict[str, list[float]] = {}
        self.device_excess: dict[str, list[float]] = {}
        #: Hours carrying the seeded remainder, which are the invoice's
        #: hours rather than the recorder's and count in no figure of the
        #: house.
        self.seeded: set[datetime] = set()
        self.disagreement = Disagreement()
        #: Where the period is heading, and what a battery would have saved.
        self.outlook: Outlook | None = None
        self.battery_saving: int | None = None
        #: The same hours settled under gross settlement, for a szaldó
        #: household asking what the switch would mean; None under gross
        #: settlement, where it is the bill itself.
        self.bill_under_gross: Bill | None = None

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

        # The household's other sources are the dashboard's, and a shape of
        # that document this does not know must not take the bill down with
        # it: the bill needs only the grid meters.
        try:
            self.sources = await async_sources(self.hass, self.import_entity)
        except Exception:
            _LOGGER.exception("Could not read the energy dashboard's sources; using none")
            self.sources = Sources()
        observed = await self._observe()
        self.observed = observed
        issues.source_unrecorded(self.hass, self.entry.entry_id, observed.unrecorded)
        issues.source_stale(self.hass, self.entry.entry_id, self.stale_sources(), STALE_AFTER.days)
        self.device_excess = self._device_excess(observed)
        self.disagreement = Disagreement.over(self._losses(observed))
        issues.sources_disagree(
            self.hass,
            self.entry.entry_id,
            self.disagreement.hours,
            self.disagreement.lost_kwh,
            self.disagreement.worst,
        )
        issues.device_bursts(self.hass, self.entry.entry_id, self.device_bursts())

        if not covered:
            # Every derived figure is unanswerable, which is not the same as
            # zero, so the entities go unavailable rather than report a guess.
            raise UpdateFailed(
                f"No prices are known for {self.state.start}, when the settlement period began."
            )

        contract = Contract(
            SettlementPeriod(self.state.start, self.period_end()),
            schedule_from_options(self.entry.options),
            terms_from_options(self.entry.options),
            standing_charge_months(self.entry.options),
            dt_util.get_default_time_zone(),
        )
        hours, self.seeded = self._with_unobserved(observed)
        bill, self.costs = await self.hass.async_add_executor_job(contract.allocate, hours)

        # What each hour's consumption cost: what not consuming in that hour
        # would have saved, with every earlier hour as it was. A device's
        # cost is its share of the hour at that price. With nothing observed
        # yet, the one hour settled is the seed's rather than the recorder's,
        # and no figure of the house is built on it.
        costs = await self.hass.async_add_executor_job(
            contract.marginal, hours, [hour.without_consumption() for hour in hours]
        )
        self.consumption_costs = costs if observed.hours else []
        self.device_costs = self._device_costs(observed, self.consumption_costs)
        # What the same consumption would have cost bought from the grid:
        # the no-panels hours costed against nothing consumed in them. Only
        # with panels; without them it is the consumption cost itself.
        if self.sources.production and observed.hours:
            self.purchase_costs = await self.hass.async_add_executor_job(
                contract.marginal,
                [hour.without_solar() for hour in hours],
                [hour.without_solar_or_consumption() for hour in hours],
            )
        else:
            self.purchase_costs = []
        self.device_purchases = self._device_costs(observed, self.purchase_costs)
        # What price each hour's consumption was worth: the ingredient a
        # figure explains itself with, so many kWh at this price.
        self.rates = (
            rates(
                observed.hours,
                self.consumption_costs,
                contract.schedule,
                contract.terms,
                contract.tz,
            )
            if observed.hours
            else []
        )

        self.outlook = await self._project(contract, hours, bill, observed)
        battery = battery_from_options(self.entry.options)
        under_gross, self.battery_saving = await self.hass.async_add_executor_job(
            _under_gross, contract, hours, battery
        )
        self.bill_under_gross = (
            under_gross if contract.terms.mode is SettlementMode.SZALDO else None
        )

        # The panels' worth is the bill there would have been without them.
        # Without a production source there is no counterfactual to run.
        if self.sources.production:
            self.bill_without_solar, without = await self.hass.async_add_executor_job(
                contract.allocate, [hour.without_solar() for hour in hours]
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
                self.hass, self.entry.entry_id, self._period_start(), self._series(observed)
            )
        except Exception:
            _LOGGER.exception("Could not publish the hourly statistics for %s", self.entry.title)
        return bill

    def _series(self, observed: Observed) -> list[Series]:
        """Everything the dashboard can draw, over the hours the recorder saw.

        The bill's figures run from the first hour of the grid record. The
        house's figures run from the first hour the household's other sources
        cover as well, when any is named: before that the house's flows are
        unknowable, and a figure built on them would be a guess. A household
        with no source beyond the grid has no production to miss, and its
        consumption is the grid record itself. A device's figures run from
        its own first hour as well. An hour carrying the seeded remainder is
        left out whatever the figure: what it holds is the invoice's, not the
        hour's.
        """

        hours = observed.hours
        seeded = self.seeded

        def seen(figures: list[float], since: datetime | None) -> list[tuple[datetime, float]]:
            return [
                (hour.start, figure)
                for hour, figure in zip(hours, figures, strict=True)
                if since is not None and hour.start >= since and hour.start not in seeded
            ]

        house_since = self.house_since()
        with_solar = bool(self.sources.production)
        currency = self.hass.config.currency
        devices = [
            Series(
                device_kind(device.slug),
                currency,
                seen(self.device_costs[device.statistic], self.device_since(device.statistic)),
                name=f"{device.name} cost",
            )
            for device in self.sources.devices
        ]
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
            Series(CONSUMPTION_COST, currency, seen(self.consumption_costs, house_since)),
            *devices,
        ]

    def _period_start(self) -> datetime:
        """The UTC instant the period began, on the local calendar."""

        return dt_util.as_utc(dt_util.start_of_local_day(self.state.start))

    async def _observe(self) -> Observed:
        """The period's hours so far, as the recorder has them."""

        end = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
        roles = {
            **self._grid_roles(),
            "produced": self.sources.production,
            "charged": self.sources.charge,
            "discharged": self.sources.discharge,
        }
        return await async_observe(
            self.hass,
            roles,
            self._period_start(),
            end,
            devices=[device.statistic for device in self.sources.devices],
        )

    async def _project(
        self, contract: Contract, hours: Sequence[Hour], bill: Bill, observed: Observed
    ) -> Outlook:
        """Where the period is heading.

        The days still to come follow the same days a year earlier, scaled
        by this period's complete days against theirs, and the straight
        line of this period wherever last year is silent. The rate is the
        bill's readings over the days elapsed, so a seeded remainder counts
        in it; the shape is only what the recorder saw.
        """

        now = dt_util.now()
        today = now.date()
        period = contract.period
        last_year = await async_observe_days(
            self.hass, self._grid_roles(), a_year_before(period.start), a_year_before(period.end)
        )

        so_far: dict[date, Day] = {}
        for hour in observed.hours:
            if observed.first is None or hour.start < observed.first:
                continue
            day = dt_util.as_local(hour.start).date()
            if day >= today:
                break
            before = so_far.get(day, Day(day))
            so_far[day] = Day(
                day,
                before.imported_kwh + hour.imported_kwh,
                before.exported_kwh + hour.exported_kwh,
            )

        elapsed = max(self.days_elapsed(today), 1)
        readings = bill.readings
        rate = Day(today, readings.imported_kwh / elapsed, readings.exported_kwh / elapsed)
        remaining: list[tuple[date, float]] = [(today, (24 - now.hour) / 24)]
        remaining += [
            (today + timedelta(days=offset), 1.0)
            for offset in range(1, (period.end - today).days)
        ]
        projected = project(remaining, so_far, last_year, rate)
        from_last_year = sum(a_year_before(day) in last_year for day, _ in remaining)
        return await self.hass.async_add_executor_job(
            _outlook, contract, hours, projected, from_last_year
        )

    def _grid_roles(self) -> dict[str, tuple[str, ...]]:
        return {
            "imported": (self.import_entity,),
            "exported": (self.export_entity,) if self.export_entity else (),
        }

    def _device_excess(self, observed: Observed) -> dict[str, list[float]]:
        """What each device claimed above the whole house, hour by hour.

        Only from the hour the house is known: before it the house's
        consumption is not a figure a device can be held against.
        """

        since = self.house_since()
        return {
            statistic: [
                device_share(used, hour.consumption_kwh)[1]
                if since is not None and hour.start >= since
                else 0.0
                for hour, used in zip(observed.hours, kwh, strict=True)
            ]
            for statistic, kwh in observed.devices.items()
        }

    def _device_costs(
        self, observed: Observed, costs: Sequence[float]
    ) -> dict[str, list[float]]:
        """Each device's share of each hour's consumption, at that hour's cost.

        Empty when the costs are, which is a figure nobody has.
        """

        if not costs:
            return {}
        return {
            statistic: [
                device_share(used, hour.consumption_kwh)[0] * cost
                for hour, used, cost in zip(observed.hours, kwh, costs, strict=True)
            ]
            for statistic, kwh in observed.devices.items()
        }

    def disagreement_detail(self, limit: int = 24) -> list[dict[str, Any]]:
        """The worst hours of the disagreement, with what every source had.

        What a user needs to judge the finding: the flows the hour was read
        with, what each device claimed, and which sources had no row at all
        for it, since an inverter that dropped out for an hour reads as zero
        production against export the grid meter did record.
        """

        observed = self.observed
        if observed is None:
            return []
        losses = self._losses(observed)
        by_start = {hour.start: hour for hour in observed.hours}
        index = {hour.start: i for i, hour in enumerate(observed.hours)}
        worst = sorted(losses, key=lambda start: losses[start], reverse=True)[:limit]
        return [
            {
                "start": dt_util.as_local(start).isoformat(timespec="minutes"),
                "lost_kwh": losses[start],
                "imported_kwh": by_start[start].imported_kwh,
                "exported_kwh": by_start[start].exported_kwh,
                "produced_kwh": by_start[start].produced_kwh,
                "charged_kwh": by_start[start].charged_kwh,
                "discharged_kwh": by_start[start].discharged_kwh,
                "devices_kwh": {
                    statistic: kwh[index[start]] for statistic, kwh in observed.devices.items()
                },
                "no_row": observed.silent_in(start),
            }
            for start in worst
        ]

    def _losses(self, observed: Observed) -> dict[datetime, float]:
        """The energy each hour lost to sources that cannot all be right.

        Export above import is a shortfall only once the household's other
        sources are known: before the first hour they cover it is production
        nobody recorded, and with none named at all there is nothing to
        disagree.
        """

        losses: defaultdict[datetime, float] = defaultdict(float)
        since = observed.household_first
        if since is not None:
            for hour in observed.hours:
                if hour.start >= since and hour.shortfall_kwh > 0:
                    losses[hour.start] += hour.shortfall_kwh
        return dict(losses)

    def device_bursts(self) -> dict[str, tuple[int, float]]:
        """Devices that claimed more than the house used, by name.

        Each with the hours it did so in and the energy above the house in
        all. A meter that reports a session's energy when the session ends
        puts it all into one hour; its cost for that hour is capped at the
        house's, and what it used in the hours before is the rest of the
        house. The meter is right about the total and wrong about the hours.
        """

        bursts: dict[str, tuple[int, float]] = {}
        for statistic, excess in self.device_excess.items():
            hours = sum(1 for lost in excess if lost > 0)
            if not hours:
                continue
            device = self.sources.device(statistic)
            name = device.name if device else statistic
            bursts[name] = (hours, sum(excess))
        return bursts

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

    def house_since(self) -> datetime | None:
        """The first hour the house's figures can be built on, if any.

        The grid record's first hour, or when the household's other sources
        are named, the first hour every one of them covers as well; see
        ``_series``. None while nothing is known of the house.
        """

        if self.observed is None:
            return None
        return self.observed.household_first if self.sources.ids else self.observed.first

    def device_since(self, statistic: str) -> datetime | None:
        """The first hour a device's figures can be built on, if any.

        The house's first hour, or the device's own first row when that is
        later: a device that began recording last month used something
        unknown before that, not nothing.
        """

        since = self.house_since()
        if self.observed is None or since is None or statistic not in self.observed.first_of:
            return None
        return max(since, self.observed.first_of[statistic])

    def _household_hours(self) -> list[Flows]:
        since = self.house_since()
        if self.observed is None or since is None:
            return []
        return [hour for hour in self.observed.hours if hour.start >= since]

    def _seen(self, figures: Sequence[float], since: datetime | None) -> float:
        """A figure summed over the hours the house is known and the recorder saw."""

        if self.observed is None or since is None:
            return 0.0
        return sum(
            figure
            for hour, figure in zip(self.observed.hours, figures, strict=True)
            if hour.start >= since and hour.start not in self.seeded
        )

    def household_consumption_kwh(self) -> float:
        return sum(hour.consumption_kwh for hour in self._household_hours())

    def household_solar_kept_kwh(self) -> float:
        return sum(hour.solar_kept_kwh for hour in self._household_hours())

    def consumption_cost_total(self) -> int | None:
        """What consuming cost over the period, as the invoice would round it.

        A marginal figure: what each hour would have saved had nothing been
        consumed in it. It does not sum to the invoice, which the cost
        statistics reconcile; it says what the things that ran were worth
        not running.
        """

        if self.house_since() is None or not self.consumption_costs:
            return None
        return forint(self._seen(self.consumption_costs, self.house_since()))

    def breakdown(self, kwh_per_hour: Sequence[float], since: datetime | None) -> dict[str, float]:
        """How much energy was worth which price, over the hours the house is known.

        The figures a cost explains itself with: so many kWh at the
        subsidized price, so many at the market price, so many at the
        feed-in price, so many in hours that straddled two, and the average
        per kWh that came out of it. For the house the energy is each
        hour's consumption; for a device, its share of it.
        """

        by_rate = dict.fromkeys(Rate, 0.0)
        if self.observed is not None and since is not None:
            for hour, kwh, rate in zip(self.observed.hours, kwh_per_hour, self.rates, strict=True):
                if hour.start >= since and hour.start not in self.seeded:
                    by_rate[rate] += kwh
        return {
            "kwh_at_subsidized": round(by_rate[Rate.SUBSIDIZED], 3),
            "kwh_at_market": round(by_rate[Rate.MARKET], 3),
            "kwh_at_feed_in": round(by_rate[Rate.FEED_IN], 3),
            "kwh_mixed": round(by_rate[Rate.MIXED], 3),
        }

    def prices_with_vat(self) -> dict[str, float]:
        """Today's prices as a consumer meets them, for an explanation to quote."""

        prices = self._prices_today()
        vat = 1 + terms_from_options(self.entry.options).vat_percent / 100
        return {
            "subsidized_price_with_vat": round(prices.subsidized * vat, 2),
            "market_price_with_vat": round(prices.market * vat, 2),
            "feed_in_price": prices.feed_in,
        }

    def consumption_breakdown(self) -> dict[str, float]:
        since = self.house_since()
        if self.observed is None or since is None:
            return {}
        used = self._seen([hour.consumption_kwh for hour in self.observed.hours], since)
        cost = self._seen(self.consumption_costs, since)
        return {
            **self.breakdown([hour.consumption_kwh for hour in self.observed.hours], since),
            "average_per_kwh": round(cost / used, 2) if used else 0.0,
            **self.saved_by_panels(self.purchase_costs, self.consumption_costs, since),
            **self.prices_with_vat(),
        }

    def saved_by_panels(
        self, purchases: Sequence[float], costs: Sequence[float], since: datetime | None
    ) -> dict[str, int]:
        """What the panels saved on a cost: what it would have been bought from
        the grid, less what it was. Nothing without panels, when there is no
        figure rather than a zero."""

        if not purchases:
            return {}
        bought = forint(self._seen(purchases, since))
        return {
            "cost_without_panels": bought,
            "saved_by_panels": bought - forint(self._seen(costs, since)),
        }

    def device_breakdown(self, statistic: str) -> dict[str, float | int]:
        """A device's share of each hour, by the price the hour was worth."""

        since = self.device_since(statistic)
        if self.observed is None or since is None or statistic not in self.observed.devices:
            return {}
        used = self.observed.devices[statistic]
        capped = [
            min(kwh, hour.consumption_kwh)
            for hour, kwh in zip(self.observed.hours, used, strict=True)
        ]
        energy = self._seen(capped, since)
        cost = self._seen(self.device_costs.get(statistic, []), since)
        house = self.household_consumption_kwh()
        excess = self.device_excess.get(statistic, [])
        return {
            **self.breakdown(capped, since),
            "average_per_kwh": round(cost / energy, 2) if energy else 0.0,
            "share_of_house": round(energy / house, 4) if house else 0.0,
            "capped_hours": sum(1 for lost in excess if lost > 0),
            "excess_kwh": round(sum(excess), 3),
            **self.saved_by_panels(
                self.device_purchases.get(statistic, []),
                self.device_costs.get(statistic, []),
                since,
            ),
            **self.prices_with_vat(),
        }

    def device_kwh_total(self, statistic: str) -> float:
        if self.observed is None or statistic not in self.observed.devices:
            return 0.0
        return self._seen(self.observed.devices[statistic], self.device_since(statistic))

    def device_cost_total(self, statistic: str) -> int | None:
        """What one device's consumption cost over the period."""

        since = self.device_since(statistic)
        if since is None or statistic not in self.device_costs:
            return None
        return forint(self._seen(self.device_costs[statistic], since))

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

    def stale_sources(self) -> dict[str, datetime | None]:
        """Recorded sources the recorder has had nothing from for too long.

        By the statistics, not the live state: the settlement reads the
        recorder, and a sensor that is unavailable overnight has rows by day.
        Each is mapped to the start of its last hour in the window, None for
        none at all. Nothing is said until the window read is long enough
        to tell.
        """

        observed = self.observed
        if observed is None or observed.end - observed.start < STALE_AFTER:
            return {}
        return {
            source: observed.last_of.get(source)
            for source in observed.sources
            if source not in observed.unrecorded
            and (
                source not in observed.last_of
                or observed.end - observed.last_of[source] > STALE_AFTER
            )
        }

    def prices_cover_period(self) -> bool:
        """Whether the schedule reaches back to the start of the period."""

        schedule = schedule_from_options(self.entry.options)
        return schedule.entries[0].valid_from <= self.state.start

    def current_unit_price(self, today: date | None = None) -> float:
        """What the next kWh costs, at the band in force, with VAT.

        The figure to point Home Assistant's energy dashboard at, since that
        wants a price rather than a bill: what the household pays, which is
        the published figure.
        """

        prices = self._prices_today(today)
        with_vat = 1 + terms_from_options(self.entry.options).vat_percent / 100
        bill = self.data
        if bill is not None and bill.allowance_remaining_kwh <= 0:
            return round(prices.market * with_vat, 3)
        return round(prices.subsidized * with_vat, 3)

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
