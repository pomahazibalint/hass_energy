import pytest

from hass_energy.config import DeviceConfig, GridConfig, ProjectConfig


@pytest.fixture
def config() -> ProjectConfig:
    """A configuration exercising grid, solar and devices."""

    return ProjectConfig(
        grid=GridConfig(
            import_entity="sensor.grid_import",
            export_entity="sensor.grid_export",
            production_entity="sensor.solar_production",
        ),
        devices=(
            DeviceConfig(id="heat_pump", entity="sensor.heat_pump_energy", name="Heat pump"),
            DeviceConfig(id="server", entity="sensor.server_energy"),
        ),
    )
