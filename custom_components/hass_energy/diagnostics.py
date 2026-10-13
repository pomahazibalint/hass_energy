"""What to attach to a bug report.

The recorded quantities and the contract they were valued under, which between
them explain any figure the integration has published.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import SettlementEntry
from .settings import battery_from_options, schedule_from_options, terms_from_options


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SettlementEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    terms = terms_from_options(entry.options)
    schedule = schedule_from_options(entry.options)
    bill = coordinator.data

    settlement: dict[str, Any] | None = None
    if bill is not None:
        settlement = {
            "period": [bill.period.start.isoformat(), bill.period.end.isoformat()],
            "billed_kwh": bill.billed_kwh,
            "surplus_kwh": bill.surplus_kwh,
            "allowance_kwh": bill.allowance_kwh,
            "subsidized_kwh": bill.subsidized_kwh,
            "market_kwh": bill.market_kwh,
            "energy_net": bill.energy_net,
            "standing_charge_net": bill.standing_charge_net,
            "vat": bill.vat,
            "gross_total": bill.gross_total,
            "surplus_net": bill.surplus_net,
            "net_position": bill.net_position,
        }

    observed: dict[str, Any] | None = None
    if coordinator.observed is not None:
        observed = {
            "hours": len(coordinator.observed.hours),
            "first": (
                coordinator.observed.first.isoformat() if coordinator.observed.first else None
            ),
            "first_of": {
                source: first.isoformat()
                for source, first in coordinator.observed.first_of.items()
            },
            "imported_kwh": coordinator.observed.imported_kwh,
            "exported_kwh": coordinator.observed.exported_kwh,
            "produced_kwh": coordinator.observed.produced_kwh,
            "unrecorded": coordinator.observed.unrecorded,
        }

    since = coordinator.house_since()
    household = {
        "since": since.isoformat() if since else None,
        "consumption_kwh": coordinator.household_consumption_kwh(),
        "solar_kept_kwh": coordinator.household_solar_kept_kwh(),
        "solar_value": coordinator.solar_value_total(),
        "consumption_cost": coordinator.consumption_cost_total(),
    }

    consumption = coordinator.household_consumption_kwh()
    devices = []
    for device in coordinator.sources.devices:
        first = coordinator.device_since(device.statistic)
        used = coordinator.device_kwh_total(device.statistic)
        devices.append(
            {
                "statistic": device.statistic,
                "name": device.name,
                "included_in": device.included_in,
                "since": first.isoformat() if first else None,
                "kwh": used,
                "share": used / consumption if consumption else None,
                "cost": coordinator.device_cost_total(device.statistic),
                "excess_kwh": sum(coordinator.device_excess.get(device.statistic, ())),
            }
        )

    outlook = coordinator.outlook
    battery = battery_from_options(entry.options)

    return {
        "outlook": {
            "days_remaining": outlook.days_remaining,
            "days_from_last_year": outlook.days_from_last_year,
            "billed_kwh": outlook.bill.billed_kwh,
            "gross_total": outlook.bill.gross_total,
            "allowance_runs_out": (
                outlook.runs_out_on.isoformat() if outlook.runs_out_on else None
            ),
        }
        if outlook
        else None,
        "battery": {
            "capacity_kwh": battery.capacity_kwh,
            "round_trip_efficiency": battery.round_trip_efficiency,
            "saving": coordinator.battery_saving,
        }
        if battery
        else None,
        # Entity ids are the user's own naming, so they are reported as
        # configured rather than redacted into uselessness.
        "sources": {
            "import": coordinator.import_entity,
            "export": coordinator.export_entity,
            "production": list(coordinator.sources.production),
            "battery_charge": list(coordinator.sources.charge),
            "battery_discharge": list(coordinator.sources.discharge),
            "stale": {
                source: last.isoformat() if last else None
                for source, last in coordinator.stale_sources().items()
            },
        },
        "disagreement": {
            "hours": coordinator.disagreement.hours,
            "lost_kwh": coordinator.disagreement.lost_kwh,
            "worst": (
                coordinator.disagreement.worst.isoformat()
                if coordinator.disagreement.worst
                else None
            ),
        },
        "household": household,
        "devices": devices,
        "period": coordinator.state.as_dict(),
        "observed": observed,
        "days_elapsed": coordinator.days_elapsed(),
        "prices_cover_period": coordinator.prices_cover_period(),
        "terms": {
            "annual_allowance_kwh": terms.annual_allowance_kwh,
            "standing_charge_per_month": terms.standing_charge_per_month,
            "vat_percent": terms.vat_percent,
            "mode": terms.mode.value,
            "allowance_basis": terms.allowance_basis.value,
            "currency": terms.currency,
        },
        "prices": [
            {
                "valid_from": prices.valid_from.isoformat(),
                "subsidized": prices.subsidized,
                "market": prices.market,
                "feed_in": prices.feed_in,
            }
            for prices in schedule.entries
        ],
        "settlement": settlement,
    }
