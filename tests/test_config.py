from pathlib import Path

import pytest

from hass_energy.config import BillingConfig, DeviceConfig, MeterConfig, ProjectConfig
from hass_energy.loader import ConfigurationError, load_config


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_load_config_requires_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="not found"):
        load_config(tmp_path / "missing.yaml")


def test_load_config_rejects_empty_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="empty"):
        load_config(write(tmp_path, ""))


def test_load_config_rejects_non_mapping(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="mapping"):
        load_config(write(tmp_path, "- one\n- two\n"))


def test_load_config_rejects_malformed_yaml(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="not valid YAML"):
        load_config(write(tmp_path, "devices: [\n"))


def test_load_config_reports_validation_errors(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="Invalid configuration"):
        load_config(write(tmp_path, "billing:\n  settlement_month: 13\n"))


def test_load_config_reads_a_full_configuration(tmp_path: Path) -> None:
    config = load_config(
        write(
            tmp_path,
            """
project_name: home
billing:
  settlement_month: 3
  settlement_day: 15
  pricing:
    subsidized_limit_kwh: 2523
grid:
  import_entity: sensor.grid_import
  export_entity: sensor.grid_export
meters:
  cycles: [daily, monthly, yearly]
devices:
  - id: server
    entity: sensor.server_energy
    room: Office
""",
        )
    )

    assert config.project_name == "home"
    assert config.billing.settlement_day == 18
    assert config.grid.import_entity == "sensor.grid_import"
    assert config.meters.cycles == ("daily", "monthly", "yearly")
    assert config.devices[0].display_name == "Server"


def test_project_defaults() -> None:
    config = ProjectConfig()

    assert config.billing.country == "HU"
    assert config.billing.tariff == "A1"
    assert config.billing.pricing.price_unit == "Ft/kWh"
    assert config.solar.annual_net_metering is True
    assert config.devices == ()
    assert config.all_cycles == ("daily", "monthly", "settlement")


def test_settlement_date_must_exist_in_every_year() -> None:
    with pytest.raises(ValueError, match="does not exist"):
        BillingConfig(settlement_month=2, settlement_day=29)


def test_meter_cycles_are_validated() -> None:
    with pytest.raises(ValueError, match="Unsupported meter cycles"):
        MeterConfig(cycles=("daily", "fortnightly"))

    with pytest.raises(ValueError, match="unique"):
        MeterConfig(cycles=("daily", "daily"))


def test_duplicate_device_ids_are_rejected() -> None:
    with pytest.raises(ValueError, match="Duplicate device ids: server"):
        ProjectConfig(
            devices=(
                DeviceConfig(id="server", entity="sensor.a"),
                DeviceConfig(id="server", entity="sensor.b"),
            )
        )


def test_device_display_name_prefers_configured_name() -> None:
    device = DeviceConfig(id="heat_pump", entity="sensor.heat_pump_energy", name="Heat pump")

    assert device.display_name == "Heat pump"
    assert DeviceConfig(id="heat_pump", entity="sensor.x").display_name == "Heat pump"
