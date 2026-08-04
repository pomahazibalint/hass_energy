"""Automations that drive the settlement period and the active price band."""

from __future__ import annotations

import calendar
from typing import Any

from ..config import TARIFF_BANDS, ProjectConfig
from . import templates as t
from .base import GenerationError, Generator
from .entities import Entities
from .pricing import PRICE_BAND


class SettlementGenerator(Generator):
    """Rolls the settlement period over and keeps the meter tariffs in step.

    Home Assistant's yearly cycle always resets on 1 January, and its offset is
    capped well below a month, so a settlement period starting on any other date
    cannot be expressed as a cycle. The settlement meters therefore never reset
    on their own and are calibrated back to zero here.
    """

    filename = "settlement.yaml"
    description = (
        "Resets every settlement meter on the billing anniversary, and keeps "
        "each device's meter recording into whichever price band is currently "
        "active. Without these the settlement period never restarts and all "
        "energy lands in the subsidized band."
    )

    def _reset_automation(self, config: ProjectConfig, entities: Entities) -> dict[str, Any]:
        billing = config.billing
        day = billing.settlement_day
        month_name = calendar.month_name[billing.settlement_month]

        return {
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
                        f"now().month == {billing.settlement_month} and now().day == {day}"
                    ),
                }
            ],
            "actions": [
                {
                    "action": "utility_meter.calibrate",
                    "target": {"entity_id": list(entities.settlement_meters())},
                    "data": {"value": "0"},
                }
            ],
        }

    def _band_automation(self, entities: Entities) -> dict[str, Any]:
        band_sensor = entities.pricing(PRICE_BAND)
        options = ", ".join(f"'{band}'" for band in TARIFF_BANDS)

        return {
            "id": f"{entities.prefix}_price_band",
            "alias": "Follow the active energy price band",
            "description": (
                "Points every device settlement meter at the band its energy "
                "should be recorded against. Also runs at startup, so a band "
                "change missed while Home Assistant was down is corrected."
            ),
            "mode": "single",
            "triggers": [
                {"trigger": "state", "entity_id": band_sensor},
                {"trigger": "homeassistant", "event": "start"},
            ],
            "conditions": [
                {
                    "condition": "template",
                    "value_template": t.expression(f"states('{band_sensor}') in [{options}]"),
                }
            ],
            "actions": [
                {
                    "action": "select.select_option",
                    "target": {"entity_id": list(entities.band_selects())},
                    "data": {"option": t.expression(f"states('{band_sensor}')")},
                }
            ],
        }

    def build(self, config: ProjectConfig) -> dict[str, Any]:
        if config.grid.import_entity is None:
            raise GenerationError(
                "grid.import_entity is required: there is no settlement meter to reset."
            )

        entities = Entities(config)
        automations = [self._reset_automation(config, entities)]
        if config.devices:
            automations.append(self._band_automation(entities))

        return {"automation": automations}
