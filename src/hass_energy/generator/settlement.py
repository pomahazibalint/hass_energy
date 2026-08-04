"""Automation that rolls the settlement period over."""

from __future__ import annotations

import calendar
from typing import Any

from ..config import SETTLEMENT_CYCLE, ProjectConfig
from . import templates as t
from .base import GenerationError, Generator
from .entities import Entities
from .utility_meters import GRID_FLOWS


class SettlementGenerator(Generator):
    """Resets the settlement meters on the billing anniversary.

    Home Assistant's yearly cycle always resets on 1 January, and its offset is
    capped well below a month, so a settlement period starting on any other date
    cannot be expressed as a cycle. The settlement meters therefore never reset
    on their own and are calibrated back to zero here.
    """

    filename = "settlement.yaml"
    description = (
        "Resets every settlement meter on the billing anniversary. The meters "
        "carry no cycle of their own, so this automation is what starts a new "
        "settlement period."
    )

    def build(self, config: ProjectConfig) -> dict[str, Any]:
        if config.grid.import_entity is None:
            raise GenerationError(
                "grid.import_entity is required: there is no settlement meter to reset."
            )

        entities = Entities(config)
        billing = config.billing
        meters = [
            entities.grid_meter(flow.key, SETTLEMENT_CYCLE)
            for flow in GRID_FLOWS
            if getattr(config.grid, flow.field) is not None
        ]
        meters += [entities.device_meter(device.id, SETTLEMENT_CYCLE) for device in config.devices]

        day = billing.settlement_day
        month_name = calendar.month_name[billing.settlement_month]

        return {
            "automation": [
                {
                    "id": f"{entities.prefix}_settlement_reset",
                    "alias": f"Reset settlement meters on {day} {month_name}",
                    "description": (
                        "Starts a new billing settlement period by calibrating every "
                        "settlement meter back to zero."
                    ),
                    "mode": "single",
                    "triggers": [{"trigger": "time", "at": "00:00:00"}],
                    "conditions": [
                        {
                            "condition": "template",
                            "value_template": t.expression(
                                f"now().month == {billing.settlement_month} "
                                f"and now().day == {day}"
                            ),
                        }
                    ],
                    "actions": [
                        {
                            "action": "utility_meter.calibrate",
                            "target": {"entity_id": meters},
                            "data": {"value": "0"},
                        }
                    ],
                }
            ]
        }
