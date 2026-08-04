from hass_energy.models import BillingModel, DeviceModel, ProjectModel, SolarModel


def test_project_model_defaults():
    project = ProjectModel()

    assert project.project_name == "hass_energy"
    assert project.billing.country == "HU"
    assert project.billing.tariff == "A1"
    assert project.solar.annual_net_metering is True
    assert project.devices == []


def test_device_model_fields():
    device = DeviceModel(id="server", entity="sensor.server_energy", room="Office")

    assert device.id == "server"
    assert device.entity == "sensor.server_energy"
    assert device.room == "Office"
    assert device.category is None
    assert device.name is None


def test_billing_and_solar_models():
    billing = BillingModel(country="HU", tariff="A1", settlement_month=3, settlement_day=15)
    solar = SolarModel(annual_net_metering=False)

    assert billing.country == "HU"
    assert billing.tariff == "A1"
    assert billing.settlement_month == 9
    assert billing.settlement_day == 18
    assert solar.annual_net_metering is False
