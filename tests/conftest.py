from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from hass_energy.config import ProjectConfig


@pytest.fixture
def config() -> "ProjectConfig":
    """A configuration exercising grid, solar and devices.

    The generator is imported inside the fixture because this file is also a
    parent conftest for the integration tests, which run without the generator
    or its dependencies installed.
    """

    from hass_energy.config import DeviceConfig, GridConfig, ProjectConfig

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
