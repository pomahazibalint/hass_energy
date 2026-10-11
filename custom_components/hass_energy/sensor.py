"""The settlement, as an itemised set of entities.

An invoice is a list of lines, not one number, and the questions a household
actually asks — what is this costing, how much allowance is left, what is the
supplier going to owe me — are different lines of it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import SettlementEntry
from .const import DOMAIN
from .coordinator import SettlementCoordinator
from .settings import terms_from_options

KWH = UnitOfEnergy.KILO_WATT_HOUR


@dataclass(frozen=True, kw_only=True)
class SettlementSensorDescription(SensorEntityDescription):
    """A line of the settlement and how to read it off the bill."""

    value: Callable[[SettlementCoordinator], float | int]
    #: Currency lines take their unit from the contract rather than a constant.
    monetary: bool = False
    #: A price rather than an amount, so the unit carries the kWh.
    per_kwh: bool = False
    #: A running total for the energy dashboard. It reports in Home Assistant's
    #: own currency, which is what the dashboard labels costs in, and resets
    #: with the settlement period rather than dropping to zero.
    running_total: bool = False


SENSORS: tuple[SettlementSensorDescription, ...] = (
    SettlementSensorDescription(
        key="billed_energy",
        translation_key="billed_energy",
        native_unit_of_measurement=KWH,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        value=lambda c: round(c.data.billed_kwh, 3),
    ),
    SettlementSensorDescription(
        key="surplus_energy",
        translation_key="surplus_energy",
        native_unit_of_measurement=KWH,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        value=lambda c: round(c.data.surplus_kwh, 3),
    ),
    SettlementSensorDescription(
        key="subsidized_energy",
        translation_key="subsidized_energy",
        native_unit_of_measurement=KWH,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        value=lambda c: round(c.data.subsidized_kwh, 3),
    ),
    SettlementSensorDescription(
        key="market_energy",
        translation_key="market_energy",
        native_unit_of_measurement=KWH,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        value=lambda c: round(c.data.market_kwh, 3),
    ),
    # No energy device class: this is how much of a budget is left, not a
    # quantity that accumulated, and Home Assistant rejects the combination.
    SettlementSensorDescription(
        key="allowance_remaining",
        translation_key="allowance_remaining",
        native_unit_of_measurement=KWH,
        state_class=SensorStateClass.MEASUREMENT,
        value=lambda c: round(c.data.allowance_remaining_kwh, 3),
    ),
    SettlementSensorDescription(
        key="energy_cost",
        translation_key="energy_cost",
        state_class=SensorStateClass.TOTAL,
        monetary=True,
        value=lambda c: round(c.data.energy_net, 2),
    ),
    SettlementSensorDescription(
        key="standing_charge",
        translation_key="standing_charge",
        state_class=SensorStateClass.TOTAL,
        monetary=True,
        value=lambda c: round(c.data.standing_charge_net, 2),
    ),
    SettlementSensorDescription(
        key="vat",
        translation_key="vat",
        state_class=SensorStateClass.TOTAL,
        monetary=True,
        value=lambda c: c.data.vat,
    ),
    SettlementSensorDescription(
        key="total_payable",
        translation_key="total_payable",
        state_class=SensorStateClass.TOTAL,
        monetary=True,
        value=lambda c: c.data.gross_total,
    ),
    SettlementSensorDescription(
        key="surplus_value",
        translation_key="surplus_value",
        state_class=SensorStateClass.TOTAL,
        monetary=True,
        value=lambda c: c.data.surplus_net,
    ),
    SettlementSensorDescription(
        key="net_position",
        translation_key="net_position",
        state_class=SensorStateClass.TOTAL,
        monetary=True,
        value=lambda c: c.data.net_position,
    ),
    SettlementSensorDescription(
        key="period_days",
        translation_key="period_days",
        native_unit_of_measurement="d",
        state_class=SensorStateClass.MEASUREMENT,
        value=lambda c: c.days_elapsed(),
    ),
    # Home Assistant's own energy dashboard wants a price, not a bill. Point
    # its "use an entity tracking the price" option at this.
    SettlementSensorDescription(
        key="unit_price",
        translation_key="unit_price",
        state_class=SensorStateClass.MEASUREMENT,
        per_kwh=True,
        value=lambda c: c.current_unit_price(),
    ),
    # And its "return to grid" price. Only the surplus beyond netting earns
    # this, so under szaldó the surplus owed sensor is what matches the bill.
    SettlementSensorDescription(
        key="feed_in_price",
        translation_key="feed_in_price",
        state_class=SensorStateClass.MEASUREMENT,
        per_kwh=True,
        value=lambda c: c.current_feed_in_price(),
    ),
    # Prices cannot give the dashboard a true figure under szaldó, where the
    # worth of a kWh depends on what the meters do months later. These can:
    # each hour's cost is the change in the bill that hour, so the hours sum
    # to the invoice by construction. Point the dashboard's "use an entity
    # tracking the total costs" option at them. Hours in which export cancels
    # earlier import show as negative, which is the truth of netting.
    SettlementSensorDescription(
        key="grid_cost",
        translation_key="grid_cost",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        running_total=True,
        value=lambda c: round(c.data.energy_gross, 2),
    ),
    SettlementSensorDescription(
        key="export_compensation",
        translation_key="export_compensation",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        running_total=True,
        value=lambda c: c.data.surplus_net,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: SettlementEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        SettlementSensor(coordinator, entry, description) for description in SENSORS
    )


class SettlementSensor(CoordinatorEntity[SettlementCoordinator], SensorEntity):
    """One line of the settlement."""

    _attr_has_entity_name = True
    entity_description: SettlementSensorDescription

    def __init__(
        self,
        coordinator: SettlementCoordinator,
        entry: SettlementEntry,
        description: SettlementSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        currency = terms_from_options(entry.options).currency
        if description.running_total:
            self._attr_native_unit_of_measurement = coordinator.hass.config.currency
        elif description.monetary:
            self._attr_native_unit_of_measurement = currency
        elif description.per_kwh:
            self._attr_native_unit_of_measurement = f"{currency}/{KWH}"

    @property
    def native_value(self) -> float | int:
        return self.entity_description.value(self.coordinator)

    @property
    def last_reset(self) -> datetime | None:
        """When the running totals last started from zero.

        Closing a settlement moves it, which tells the recorder the drop to
        zero is a new period rather than a negative cost.
        """

        if not self.entity_description.running_total:
            return None
        return dt_util.start_of_local_day(self.coordinator.state.start)

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        if self.entity_description.key != "total_payable":
            return None
        bill = self.coordinator.data
        return {
            "period_start": bill.period.start.isoformat(),
            "period_end": bill.period.end.isoformat(),
            "days_elapsed": str(self.coordinator.days_elapsed()),
            "allowance_kwh": f"{bill.allowance_kwh:.1f}",
            "imported_kwh": f"{bill.readings.imported_kwh:.3f}",
            "exported_kwh": f"{bill.readings.exported_kwh:.3f}",
        }

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.entry.entry_id)},
            name=self.coordinator.entry.title,
            manufacturer="hass-energy",
            entry_type=DeviceEntryType.SERVICE,
        )
