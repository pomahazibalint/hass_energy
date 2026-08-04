"""Core data models for hass_energy."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class DeviceModel(BaseModel):
    """A single monitored device."""

    model_config = ConfigDict(frozen=True)

    id: str
    entity: str
    room: str | None = None
    category: str | None = None
    name: str | None = None


class BillingModel(BaseModel):
    """Billing-related project settings."""

    model_config = ConfigDict(frozen=True)

    country: str = Field(default="HU")
    tariff: str = Field(default="A1")
    settlement_month: int = Field(default=1, ge=1, le=12)
    settlement_day: int = Field(default=1, ge=1, le=31)
    subsidized_limit_kwh: float = Field(default=2523.0, ge=0)
    cheap_price_ft_per_kwh: float = Field(default=36.386, ge=0)
    expensive_price_ft_per_kwh: float = Field(default=70.104, ge=0)


class SolarModel(BaseModel):
    """Solar settlement settings."""

    model_config = ConfigDict(frozen=True)

    annual_net_metering: bool = True


class ProjectModel(BaseModel):
    """Top-level project model."""

    model_config = ConfigDict(frozen=True)

    project_name: str = Field(default="hass_energy")
    billing: BillingModel = Field(default_factory=BillingModel)
    solar: SolarModel = Field(default_factory=SolarModel)
    devices: list[DeviceModel] = Field(default_factory=list)
