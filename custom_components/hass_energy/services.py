"""Services for the things a settlement cannot infer on its own."""

from __future__ import annotations

from datetime import date, datetime, time

import voluptuous as vol
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.models.statistics import StatisticMeanType
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
)

# Home Assistant does not re-export this, but it is the documented way to
# reach the recorder's executor.
from homeassistant.components.recorder.util import get_instance  # type: ignore[attr-defined]
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from .billing import MeterReadings, SettlementPeriod, calculate
from .const import (
    ATTR_EXPORTED_KWH,
    ATTR_IMPORTED_KWH,
    ATTR_PERIOD_END,
    ATTR_PERIOD_START,
    ATTR_READING_DATE,
    DOMAIN,
    SERVICE_CLOSE_SETTLEMENT,
    SERVICE_IMPORT_INVOICE,
    SERVICE_SEED_PERIOD,
)
from .coordinator import SettlementCoordinator
from .costs import statistic_id
from .settings import schedule_from_options, standing_charge_months, terms_from_options

CLOSE_SETTLEMENT_SCHEMA = vol.Schema({vol.Optional(ATTR_READING_DATE): cv.date})

SEED_PERIOD_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_PERIOD_START): cv.date,
        vol.Required(ATTR_IMPORTED_KWH): vol.Coerce(float),
        vol.Optional(ATTR_EXPORTED_KWH, default=0.0): vol.Coerce(float),
    }
)

IMPORT_INVOICE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_PERIOD_START): cv.date,
        vol.Required(ATTR_PERIOD_END): cv.date,
        vol.Required(ATTR_IMPORTED_KWH): vol.Coerce(float),
        vol.Optional(ATTR_EXPORTED_KWH, default=0.0): vol.Coerce(float),
    }
)


def _coordinators(hass: HomeAssistant) -> list[SettlementCoordinator]:
    return [
        entry.runtime_data for entry in hass.config_entries.async_loaded_entries(DOMAIN)
    ]


async def _last_sum(hass: HomeAssistant, stat_id: str) -> float:
    """Where a previously imported invoice left the running total."""

    stats = await get_instance(hass).async_add_executor_job(
        get_last_statistics, hass, 1, stat_id, True, {"sum"}
    )
    rows = stats.get(stat_id) or []
    return float(rows[0].get("sum") or 0.0) if rows else 0.0


async def _import_invoice(hass: HomeAssistant, call: ServiceCall) -> None:
    """Put a settled invoice into the recorder as external statistics.

    Home Assistant never saw these periods, so nothing else can produce them.
    Importing past invoices is what lets a freshly installed integration show
    a history rather than starting the story today.
    """

    start: date = call.data[ATTR_PERIOD_START]
    end: date = call.data[ATTR_PERIOD_END]
    imported = float(call.data[ATTR_IMPORTED_KWH])
    exported = float(call.data[ATTR_EXPORTED_KWH])

    for coordinator in _coordinators(hass):
        options = coordinator.entry.options
        bill = calculate(
            SettlementPeriod(start, end),
            MeterReadings(imported, exported),
            schedule_from_options(options),
            terms_from_options(options),
            standing_charge_months=standing_charge_months(options),
        )
        currency = terms_from_options(options).currency

        # One point per invoice, stamped at the end of the period it covers.
        when = dt_util.as_utc(
            datetime.combine(end, time.min).replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
        ).replace(minute=0, second=0, microsecond=0)

        for kind, unit, value in (
            ("imported_energy", UnitOfEnergy.KILO_WATT_HOUR, imported),
            ("exported_energy", UnitOfEnergy.KILO_WATT_HOUR, exported),
            ("settlement_cost", currency, float(bill.gross_total)),
            ("surplus_value", currency, float(bill.surplus_net)),
        ):
            stat_id = statistic_id(coordinator.entry.entry_id, kind)
            running = await _last_sum(hass, stat_id)
            metadata = StatisticMetaData(
                mean_type=StatisticMeanType.NONE,
                has_sum=True,
                unit_class=None,
                name=f"{coordinator.entry.title} {kind.replace('_', ' ')}",
                source=DOMAIN,
                statistic_id=stat_id,
                unit_of_measurement=unit,
            )
            async_add_external_statistics(
                hass, metadata, [StatisticData(start=when, sum=running + value, state=value)]
            )


def register(hass: HomeAssistant) -> None:
    """Register the services once, however many metering points exist."""

    if hass.services.has_service(DOMAIN, SERVICE_CLOSE_SETTLEMENT):
        return

    async def close_settlement(call: ServiceCall) -> None:
        reading_date = call.data.get(ATTR_READING_DATE) or dt_util.now().date()
        for coordinator in _coordinators(hass):
            await coordinator.async_close_settlement(reading_date)

    async def seed_period(call: ServiceCall) -> None:
        for coordinator in _coordinators(hass):
            await coordinator.async_seed(
                call.data[ATTR_PERIOD_START],
                float(call.data[ATTR_IMPORTED_KWH]),
                float(call.data[ATTR_EXPORTED_KWH]),
            )

    async def import_invoice(call: ServiceCall) -> None:
        await _import_invoice(hass, call)

    hass.services.async_register(
        DOMAIN, SERVICE_CLOSE_SETTLEMENT, close_settlement, schema=CLOSE_SETTLEMENT_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SEED_PERIOD, seed_period, schema=SEED_PERIOD_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_IMPORT_INVOICE, import_invoice, schema=IMPORT_INVOICE_SCHEMA
    )
