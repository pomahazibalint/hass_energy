"""The settlement, as an itemised set of entities.

An invoice is a list of lines, not one number, and the questions a household
actually asks — what is this costing, how much allowance is left, what is the
supplier going to owe me — are different lines of it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import Platform, UnitOfEnergy
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import SettlementEntry
from .const import DOMAIN
from .coordinator import SettlementCoordinator
from .costs import device_kind
from .preferences import Device
from .settings import terms_from_options

KWH = UnitOfEnergy.KILO_WATT_HOUR


@dataclass(frozen=True, kw_only=True)
class SettlementSensorDescription(SensorEntityDescription):
    """A line of the settlement and how to read it off the bill."""

    value: Callable[[SettlementCoordinator], float | int | date | None]
    #: Currency lines take their unit from the contract rather than a constant.
    monetary: bool = False
    #: A price rather than an amount, so the unit carries the kWh.
    per_kwh: bool = False
    #: Whether the line can be answered at all. A figure whose sources the
    #: household lacks is unavailable, not zero.
    available: Callable[[SettlementCoordinator], bool] = lambda c: True


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
    # What the house did, from the sources the energy dashboard names. The
    # bill does not need them; these answer what the household used and what
    # its panels were worth, which the dashboard cannot say under szaldó.
    SettlementSensorDescription(
        key="house_consumption",
        translation_key="house_consumption",
        native_unit_of_measurement=KWH,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        available=lambda c: c.house_since() is not None,
        value=lambda c: round(c.household_consumption_kwh(), 3),
    ),
    SettlementSensorDescription(
        key="self_consumed_solar",
        translation_key="self_consumed_solar",
        native_unit_of_measurement=KWH,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        available=lambda c: bool(c.sources.production) and c.house_since() is not None,
        value=lambda c: round(c.household_solar_kept_kwh(), 3),
    ),
    SettlementSensorDescription(
        key="solar_value",
        translation_key="solar_value",
        state_class=SensorStateClass.TOTAL,
        monetary=True,
        available=lambda c: c.solar_value_total() is not None,
        value=lambda c: c.solar_value_total() or 0,
    ),
    # What consuming cost: what each hour would have saved had nothing been
    # consumed in it. Marginal, so it does not sum to the invoice.
    SettlementSensorDescription(
        key="consumption_cost",
        translation_key="consumption_cost",
        state_class=SensorStateClass.TOTAL,
        monetary=True,
        available=lambda c: c.consumption_cost_total() is not None,
        value=lambda c: c.consumption_cost_total() or 0,
    ),
    # Where the period is heading, following last year's shape where it is
    # known and the straight line where it is not. Measurements rather than
    # totals: a projection is re-estimated, not accumulated.
    SettlementSensorDescription(
        key="projected_total_payable",
        translation_key="projected_total_payable",
        state_class=SensorStateClass.MEASUREMENT,
        monetary=True,
        available=lambda c: c.outlook is not None,
        value=lambda c: c.outlook.bill.gross_total if c.outlook else None,
    ),
    SettlementSensorDescription(
        key="projected_billed_energy",
        translation_key="projected_billed_energy",
        native_unit_of_measurement=KWH,
        state_class=SensorStateClass.MEASUREMENT,
        available=lambda c: c.outlook is not None,
        value=lambda c: round(c.outlook.bill.billed_kwh, 3) if c.outlook else None,
    ),
    # Unknown rather than a fabricated date when the allowance holds.
    SettlementSensorDescription(
        key="allowance_runs_out",
        translation_key="allowance_runs_out",
        device_class=SensorDeviceClass.DATE,
        available=lambda c: c.outlook is not None,
        value=lambda c: c.outlook.runs_out_on if c.outlook else None,
    ),
    # What a battery would have saved, under gross settlement whatever the
    # entry's mode: under szaldó annual netting is a free battery.
    SettlementSensorDescription(
        key="battery_saving",
        translation_key="battery_saving",
        state_class=SensorStateClass.MEASUREMENT,
        monetary=True,
        available=lambda c: c.battery_saving is not None,
        value=lambda c: c.battery_saving,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: SettlementEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        SettlementSensor(coordinator, entry, description) for description in SENSORS
    )

    # The devices come from the energy dashboard's preferences and come and
    # go with them, so their sensors follow each refresh rather than setup.
    registry = er.async_get(hass)
    known: set[str] = set()

    @callback
    def follow_devices() -> None:
        wanted = {device.statistic: device for device in coordinator.sources.devices}
        for statistic in known - wanted.keys():
            known.discard(statistic)
            entity_id = registry.async_get_entity_id(
                Platform.SENSOR, DOMAIN, DeviceCostSensor.unique_id_for(entry, statistic)
            )
            if entity_id is not None:
                registry.async_remove(entity_id)
        added = [
            DeviceCostSensor(coordinator, entry, device)
            for statistic, device in wanted.items()
            if statistic not in known
        ]
        known.update(wanted)
        if added:
            async_add_entities(added)

    follow_devices()
    entry.async_on_unload(coordinator.async_add_listener(follow_devices))


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
        if description.monetary:
            self._attr_native_unit_of_measurement = currency
        elif description.per_kwh:
            self._attr_native_unit_of_measurement = f"{currency}/{KWH}"

    @property
    def available(self) -> bool:
        return super().available and self.entity_description.available(self.coordinator)

    @property
    def native_value(self) -> float | int | date | None:
        return self.entity_description.value(self.coordinator)

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


class DeviceCostSensor(CoordinatorEntity[SettlementCoordinator], SensorEntity):
    """What one device's consumption cost over the period.

    Its share of each hour's consumption at that hour's cost, so a device
    that runs at noon on the panels and one that runs at night on the grid
    are told apart, which is what the dashboard's own device graph cannot
    do. Named as the dashboard names the device, and following a rename.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "device_cost"
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(
        self, coordinator: SettlementCoordinator, entry: SettlementEntry, device: Device
    ) -> None:
        super().__init__(coordinator)
        self.statistic = device.statistic
        self._attr_unique_id = self.unique_id_for(entry, device.statistic)
        self._attr_native_unit_of_measurement = terms_from_options(entry.options).currency
        self._attr_translation_placeholders = {"device": device.name}

    @staticmethod
    def unique_id_for(entry: SettlementEntry, statistic: str) -> str:
        return f"{entry.entry_id}_{device_kind(Device(statistic, statistic).slug)}"

    @property
    def device(self) -> Device | None:
        return self.coordinator.sources.device(self.statistic)

    @callback
    def _handle_coordinator_update(self) -> None:
        device = self.device
        if device is not None:
            self._attr_translation_placeholders = {"device": device.name}
        super()._handle_coordinator_update()

    @property
    def available(self) -> bool:
        return (
            super().available
            and self.device is not None
            and self.coordinator.device_cost_total(self.statistic) is not None
        )

    @property
    def native_value(self) -> int:
        return self.coordinator.device_cost_total(self.statistic) or 0

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """What a card needs to list the device: its name, its energy, its place."""

        device = self.device
        return {
            "device": device.name if device else self.statistic,
            "statistic": self.statistic,
            "included_in": (device.included_in if device else None) or "",
            "energy_kwh": f"{self.coordinator.device_kwh_total(self.statistic):.3f}",
        }

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.entry.entry_id)},
            name=self.coordinator.entry.title,
            manufacturer="hass-energy",
            entry_type=DeviceEntryType.SERVICE,
        )
