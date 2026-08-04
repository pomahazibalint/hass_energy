from typing import Any

import yaml

from hass_energy.config import DiagnosticsConfig, GridConfig, MeterConfig, ProjectConfig
from hass_energy.generator import generate


def package(config: ProjectConfig) -> dict[str, Any]:
    content = next(f.content for f in generate(config) if f.filename == "diagnostics.yaml")
    parsed: dict[str, Any] = yaml.safe_load(content)
    return parsed


def entity(config: ProjectConfig, unique_id: str, domain: str = "binary_sensor") -> dict[str, Any]:
    block = package(config)["template"][0]
    found: dict[str, Any] = next(e for e in block[domain] if e["unique_id"] == unique_id)
    return found


def test_unavailability_covers_every_source(config: ProjectConfig) -> None:
    check = entity(config, "hass_energy_sources_unavailable")

    for source in ("sensor.grid_import", "sensor.grid_export", "sensor.solar_production"):
        assert source in check["state"]
    for source in ("sensor.heat_pump_energy", "sensor.server_energy"):
        assert source in check["state"]
    assert check["device_class"] == "problem"


def test_unavailability_names_the_missing_sources(config: ProjectConfig) -> None:
    check = entity(config, "hass_energy_sources_unavailable")

    assert "reject('has_value')" in check["attributes"]["missing"]


def test_staleness_uses_the_configured_threshold(config: ProjectConfig) -> None:
    config = config.model_copy(update={"diagnostics": DiagnosticsConfig(stale_after_hours=2)})

    check = entity(config, "hass_energy_sources_stale")

    assert "timedelta(hours=2.0)" in check["state"]
    assert "last_updated" in check["state"]


def test_band_desync_compares_selects_against_the_band(config: ProjectConfig) -> None:
    check = entity(config, "hass_energy_band_desync")

    assert "select.hass_energy_device_server_settlement" in check["state"]
    assert "states('sensor.hass_energy_price_band')" in check["state"]


def test_no_device_checks_without_devices() -> None:
    config = ProjectConfig(grid=GridConfig(import_entity="sensor.grid_import"))
    ids = [e["unique_id"] for e in package(config)["template"][0]["binary_sensor"]]

    assert "hass_energy_band_desync" not in ids
    assert "hass_energy_attribution_poor" not in ids
    # Source availability still matters without devices.
    assert "hass_energy_sources_unavailable" in ids


def test_a_project_with_only_a_settlement_cycle_is_generated(config: ProjectConfig) -> None:
    config = config.model_copy(update={"meters": MeterConfig(cycles=())})

    check = entity(config, "hass_energy_attribution_poor")

    assert "sensor.hass_energy_unmonitored_share_settlement" in check["state"]


def test_unmonitored_share_is_generated_per_cycle(config: ProjectConfig) -> None:
    ids = [e["unique_id"] for e in package(config)["template"][0]["sensor"]]

    assert ids == [
        "hass_energy_unmonitored_share_daily",
        "hass_energy_unmonitored_share_monthly",
        "hass_energy_unmonitored_share_settlement",
    ]


def test_unmonitored_share_survives_a_zero_denominator(config: ProjectConfig) -> None:
    share = entity(config, "hass_energy_unmonitored_share_daily", domain="sensor")

    assert "if used > 0 else 0" in share["state"]
    assert share["unit_of_measurement"] == "%"


def test_attribution_threshold_is_configurable(config: ProjectConfig) -> None:
    config = config.model_copy(
        update={"diagnostics": DiagnosticsConfig(unmonitored_warning_percent=25)}
    )

    check = entity(config, "hass_energy_attribution_poor")

    assert "share > 25.0" in check["state"]
