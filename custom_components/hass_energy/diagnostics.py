"""What to attach to a bug report.

The recorded quantities and the contract they were valued under, which between
them explain any figure the integration has published.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import SettlementEntry
from .settings import schedule_from_options, terms_from_options


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
            "imported_kwh": coordinator.observed.imported_kwh,
            "exported_kwh": coordinator.observed.exported_kwh,
            "unrecorded": coordinator.observed.unrecorded,
        }

    return {
        # Entity ids are the user's own naming, so they are reported as
        # configured rather than redacted into uselessness.
        "sources": {
            "import": coordinator.import_entity,
            "export": coordinator.export_entity,
            "missing": coordinator.missing_sources(),
        },
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
