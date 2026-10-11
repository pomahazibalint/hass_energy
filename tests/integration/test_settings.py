"""Turning options into domain objects."""

from datetime import date

from custom_components.hass_energy.settings import schedule_from_options
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util


async def test_the_fallback_schedule_starts_on_home_assistants_today(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The host's date and Home Assistant's can differ by a day around midnight."""

    # The test instance runs on US/Pacific: 03:00 UTC is still the day before.
    freezer.move_to("2030-05-05T03:00:00+00:00")
    assert date.today() == date(2030, 5, 5)
    assert dt_util.now().date() == date(2030, 5, 4)

    schedule = schedule_from_options({})

    assert schedule.entries[0].valid_from == date(2030, 5, 4)
