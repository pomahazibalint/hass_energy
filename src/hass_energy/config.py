"""Project configuration models.

These models describe the project exactly as a user writes it in YAML. They are
the source of truth for generation: every file under the output directory is
derived from an instance of :class:`ProjectConfig` and nothing else.
"""

from __future__ import annotations

import calendar

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: Reset cycles Home Assistant's utility_meter integration accepts.
SUPPORTED_CYCLES = ("hourly", "daily", "weekly", "monthly", "quarterly", "yearly")

#: Name of the meter spanning a whole billing settlement period. It is not a
#: Home Assistant cycle: a settlement period rarely starts on 1 January, so the
#: meter never resets on its own and is calibrated by a generated automation.
SETTLEMENT_CYCLE = "settlement"


class TariffConfig(BaseModel):
    """Price bands applied within one settlement period.

    Defaults describe the Hungarian A1 residential tariff, where consumption up
    to an annual allowance is subsidized and the remainder is billed at the
    market rate.
    """

    model_config = ConfigDict(frozen=True)

    subsidized_limit_kwh: float = Field(default=2523.0, ge=0)
    subsidized_price: float = Field(default=36.386, ge=0)
    unsubsidized_price: float = Field(default=70.104, ge=0)
    currency: str = Field(default="Ft", min_length=1)

    @property
    def price_unit(self) -> str:
        """Unit of measurement used for price sensors."""

        return f"{self.currency}/kWh"


class BillingConfig(BaseModel):
    """Billing scheme and the date on which the settlement period rolls over."""

    model_config = ConfigDict(frozen=True)

    country: str = Field(default="HU", min_length=2)
    tariff: str = Field(default="A1", min_length=1)
    settlement_month: int = Field(default=1, ge=1, le=12)
    settlement_day: int = Field(default=1, ge=1, le=31)
    pricing: TariffConfig = Field(default_factory=TariffConfig)

    @model_validator(mode="after")
    def _check_settlement_date(self) -> BillingConfig:
        # 2001 is not a leap year, so 29 February is rejected too: a settlement
        # date must exist in every year for the reset automation to fire.
        _, last_day = calendar.monthrange(2001, self.settlement_month)
        if self.settlement_day > last_day:
            raise ValueError(
                f"Settlement day {self.settlement_day} does not exist in month "
                f"{self.settlement_month}."
            )
        return self


class SolarConfig(BaseModel):
    """How exported solar energy is settled against imported energy."""

    model_config = ConfigDict(frozen=True)

    annual_net_metering: bool = True


class GridConfig(BaseModel):
    """Source sensors describing the household's connection to the grid.

    ``import_entity`` is required for any cost accounting. Export and production
    stay optional so that a household without solar generates a smaller package.
    """

    model_config = ConfigDict(frozen=True)

    import_entity: str | None = None
    export_entity: str | None = None
    production_entity: str | None = None


class MeterConfig(BaseModel):
    """Which reset cycles are generated alongside the settlement meter."""

    model_config = ConfigDict(frozen=True)

    cycles: tuple[str, ...] = ("daily", "monthly")

    @model_validator(mode="after")
    def _check_cycles(self) -> MeterConfig:
        unknown = [cycle for cycle in self.cycles if cycle not in SUPPORTED_CYCLES]
        if unknown:
            raise ValueError(
                f"Unsupported meter cycles: {', '.join(unknown)}. "
                f"Supported cycles: {', '.join(SUPPORTED_CYCLES)}."
            )
        if len(set(self.cycles)) != len(self.cycles):
            raise ValueError("Meter cycles must be unique.")
        return self


class DeviceConfig(BaseModel):
    """A single monitored device backed by an energy sensor."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(pattern=r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
    entity: str = Field(pattern=r"^[a-z_]+\.[a-z0-9_]+$")
    room: str | None = None
    category: str | None = None
    name: str | None = None

    @property
    def display_name(self) -> str:
        """Human-readable name, derived from the id when none is configured."""

        return self.name or self.id.replace("_", " ").capitalize()


class ProjectConfig(BaseModel):
    """Top-level project configuration."""

    model_config = ConfigDict(frozen=True)

    project_name: str = Field(default="hass_energy", min_length=1)
    billing: BillingConfig = Field(default_factory=BillingConfig)
    solar: SolarConfig = Field(default_factory=SolarConfig)
    grid: GridConfig = Field(default_factory=GridConfig)
    meters: MeterConfig = Field(default_factory=MeterConfig)
    devices: tuple[DeviceConfig, ...] = ()

    @model_validator(mode="after")
    def _check_unique_device_ids(self) -> ProjectConfig:
        seen: set[str] = set()
        duplicates: set[str] = set()
        for device in self.devices:
            if device.id in seen:
                duplicates.add(device.id)
            seen.add(device.id)
        if duplicates:
            raise ValueError(f"Duplicate device ids: {', '.join(sorted(duplicates))}.")
        return self

    @property
    def all_cycles(self) -> tuple[str, ...]:
        """Every cycle a meter is generated for, settlement period included."""

        return (*self.meters.cycles, SETTLEMENT_CYCLE)
