"""Configuration models for hass_energy."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class BillingConfig(BaseModel):
    """Billing-related configuration."""

    model_config = ConfigDict(frozen=True)

    country: str = Field(default="HU")
    tariff: str = Field(default="A1")
    settlement_month: int = Field(default=1, ge=1, le=12)
    settlement_day: int = Field(default=1, ge=1, le=31)


class SolarConfig(BaseModel):
    """Solar settlement configuration."""

    model_config = ConfigDict(frozen=True)

    annual_net_metering: bool = True


class DeviceConfig(BaseModel):
    """A single monitored device."""

    model_config = ConfigDict(frozen=True)

    id: str
    entity: str
    room: str | None = None
    category: str | None = None
    name: str | None = None


class ProjectConfig(BaseModel):
    """Top-level project configuration."""

    model_config = ConfigDict(frozen=True)

    project_name: str = Field(default="hass_energy")
    billing: BillingConfig = Field(default_factory=BillingConfig)
    solar: SolarConfig = Field(default_factory=SolarConfig)
    devices: list[DeviceConfig] = Field(default_factory=list)


def load_config(path: str | Path) -> ProjectConfig:
    """Load project configuration from YAML later in the build."""

    raise NotImplementedError("Configuration loading is not implemented yet.")
