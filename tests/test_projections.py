from typing import Any

import yaml

from hass_energy.config import BillingConfig, ProjectConfig
from hass_energy.generator import generate


def package(config: ProjectConfig) -> dict[str, Any]:
    content = next(f.content for f in generate(config) if f.filename == "projections.yaml")
    parsed: dict[str, Any] = yaml.safe_load(content)
    return parsed


def entity(config: ProjectConfig, unique_id: str, domain: str = "sensor") -> dict[str, Any]:
    block = package(config)["template"][0]
    found: dict[str, Any] = next(e for e in block[domain] if e["unique_id"] == unique_id)
    return found


def test_the_period_start_follows_the_billing_date(config: ProjectConfig) -> None:
    billing = BillingConfig(settlement_month=3, settlement_day=15)
    config = config.model_copy(update={"billing": billing})

    elapsed = entity(config, "hass_energy_settlement_days_elapsed")

    assert "{% set month = 3 %}{% set day = 15 %}" in elapsed["state"]
    assert "now().year - 1" in elapsed["state"]


def test_days_remaining_uses_the_next_start_not_a_fixed_year(config: ProjectConfig) -> None:
    remaining = entity(config, "hass_energy_settlement_days_remaining")

    assert "start.replace(year=start.year + 1)" in remaining["state"]
    assert "365" not in remaining["state"]


def test_the_daily_rate_survives_the_first_day(config: ProjectConfig) -> None:
    rate = entity(config, "hass_energy_settlement_daily_rate")

    assert "if days > 0 else 0" in rate["state"]


def test_the_projection_extrapolates_the_rate(config: ProjectConfig) -> None:
    projected = entity(config, "hass_energy_projected_settlement_energy")

    assert "sensor.hass_energy_settlement_energy" in projected["state"]
    assert "sensor.hass_energy_settlement_daily_rate" in projected["state"]
    assert "used + daily * left" in projected["state"]


def test_the_projected_cost_is_banded(config: ProjectConfig) -> None:
    cost = entity(config, "hass_energy_projected_settlement_cost")

    assert "[total, 2523.0] | min" in cost["state"]
    assert "[total - 2523.0, 0] | max" in cost["state"]
    assert "cheap * 36.386 + dear * 70.104" in cost["state"]


def test_the_exhaustion_date_is_unknown_when_not_on_course(config: ProjectConfig) -> None:
    runs_out = entity(config, "hass_energy_allowance_runs_out")

    assert "if 0 <= days <= left else 'unknown'" in runs_out["state"]
    # A rate of zero would divide by zero rather than mean "never".
    assert "if daily > 0 else -1" in runs_out["state"]


def test_the_exceeded_flag_compares_against_the_allowance(config: ProjectConfig) -> None:
    exceeded = entity(config, "hass_energy_allowance_projected_exceeded", domain="binary_sensor")

    assert "total > 2523.0" in exceeded["state"]
    assert "sensor.hass_energy_projected_settlement_energy" in exceeded["state"]
