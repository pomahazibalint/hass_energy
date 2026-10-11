"""Seeding, repairs, diagnostics and statistics import."""

from datetime import date

import pytest
from custom_components.hass_energy.const import (
    ATTR_DAY,
    ATTR_EXPORTED_KWH,
    ATTR_IMPORTED_KWH,
    ATTR_PERIOD_END,
    ATTR_PERIOD_START,
    CONF_PRICES,
    DOMAIN,
    SERVICE_ADJUST_ENERGY,
    SERVICE_IMPORT_INVOICE,
    SERVICE_SEED_PERIOD,
)
from custom_components.hass_energy.coordinator import SettlementCoordinator
from custom_components.hass_energy.diagnostics import async_get_config_entry_diagnostics
from custom_components.hass_energy.issues import OVERDUE_AFTER_DAYS
from custom_components.hass_energy.services import statistic_id
from custom_components.hass_energy.settings import price_entry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .conftest import IMPORT_ENTITY


def coordinator(entry: MockConfigEntry) -> SettlementCoordinator:
    data: SettlementCoordinator = entry.runtime_data
    return data


async def test_seeding_adopts_a_period_already_under_way(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """Installed mid-period, the integration must not account from zero."""

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SEED_PERIOD,
        {
            ATTR_PERIOD_START: date(2025, 9, 13),
            ATTR_IMPORTED_KWH: 1847.2,
            ATTR_EXPORTED_KWH: 2103.5,
        },
        blocking=True,
    )

    state = coordinator(entry).state
    assert state.start == date(2025, 9, 13)
    assert state.imported == pytest.approx(1847.2)
    assert state.exported == pytest.approx(2103.5)


async def test_seeded_energy_is_spread_across_the_prices_it_spanned(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """Unobserved history has no shape, so it is split by day and said so."""

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SEED_PERIOD,
        {ATTR_PERIOD_START: date(2025, 1, 1), ATTR_IMPORTED_KWH: 1000.0},
        blocking=True,
    )

    buckets = coordinator(entry).state.buckets
    assert set(buckets) == {"2024-01-01", "2025-08-01"}
    assert sum(b.imported for b in buckets.values()) == pytest.approx(1000.0)


async def test_accrual_after_seeding_adds_to_it(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await hass.services.async_call(
        DOMAIN,
        SERVICE_SEED_PERIOD,
        {ATTR_PERIOD_START: date(2026, 1, 1), ATTR_IMPORTED_KWH: 500.0},
        blocking=True,
    )
    hass.states.async_set(IMPORT_ENTITY, "1200.0")
    await hass.async_block_till_done()

    assert coordinator(entry).state.imported == pytest.approx(700.0)


async def test_a_gap_in_the_price_schedule_is_a_repair_not_a_guess(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """Unvaluable is not zero, so the entities go unavailable and say why."""

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SEED_PERIOD,
        {ATTR_PERIOD_START: date(2020, 1, 1), ATTR_IMPORTED_KWH: 100.0},
        blocking=True,
    )

    registry = ir.async_get(hass)
    assert registry.async_get_issue(DOMAIN, f"price_coverage_{entry.entry_id}")
    assert coordinator(entry).last_update_success is False


async def test_the_repair_clears_once_the_prices_reach_back(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await hass.services.async_call(
        DOMAIN,
        SERVICE_SEED_PERIOD,
        {ATTR_PERIOD_START: date(2020, 1, 1), ATTR_IMPORTED_KWH: 100.0},
        blocking=True,
    )

    hass.config_entries.async_update_entry(
        entry,
        options={
            **entry.options,
            CONF_PRICES: [
                price_entry(date(2019, 1, 1), 30.0, 60.0, 5.0),
                *entry.options[CONF_PRICES],
            ],
        },
    )
    await hass.async_block_till_done()

    registry = ir.async_get(hass)
    assert registry.async_get_issue(DOMAIN, f"price_coverage_{entry.entry_id}") is None
    assert coordinator(entry).last_update_success is True


async def test_an_overdue_settlement_is_raised(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """A period well past a year means the reading happened without us."""

    long_ago = date.today().toordinal() - (OVERDUE_AFTER_DAYS + 10)
    await hass.services.async_call(
        DOMAIN,
        SERVICE_SEED_PERIOD,
        {
            ATTR_PERIOD_START: date.fromordinal(long_ago),
            ATTR_IMPORTED_KWH: 100.0,
        },
        blocking=True,
    )

    registry = ir.async_get(hass)
    assert registry.async_get_issue(DOMAIN, f"settlement_overdue_{entry.entry_id}")


async def test_a_source_that_stops_reporting_is_raised(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    hass.states.async_set(IMPORT_ENTITY, "unavailable")
    await hass.async_block_till_done()
    coordinator(entry).refresh_settlement()

    registry = ir.async_get(hass)
    issue = registry.async_get_issue(DOMAIN, f"source_missing_{entry.entry_id}")
    assert issue is not None
    assert IMPORT_ENTITY in issue.translation_placeholders["entities"]  # type: ignore[index]


async def test_diagnostics_explain_every_published_figure(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    hass.states.async_set(IMPORT_ENTITY, "1400.0")
    await hass.async_block_till_done()

    report = await async_get_config_entry_diagnostics(hass, entry)

    assert report["recorded"]["buckets"]
    assert report["terms"]["allowance_basis"] == "netted"
    assert len(report["prices"]) == 2
    assert report["settlement"]["billed_kwh"] == 400.0
    assert report["prices_cover_period"] is True


async def test_a_past_invoice_becomes_history(
    recorder_mock: None, hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """Home Assistant never saw these years, so nothing else can supply them.

    Builds its own entry because the recorder has to exist before Home
    Assistant starts, and the shared fixture starts it.
    """

    from custom_components.hass_energy.const import CONF_IMPORT_ENTITY
    from homeassistant.components.recorder.statistics import statistics_during_period
    from homeassistant.components.recorder.util import get_instance
    from homeassistant.util import dt as dt_util

    hass.states.async_set(IMPORT_ENTITY, "1000.0")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test settlement",
        data={CONF_IMPORT_ENTITY: IMPORT_ENTITY},
        options={CONF_PRICES: [price_entry(date(2024, 1, 1), 36.386, 70.104, 5.11)]},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call(
        DOMAIN,
        SERVICE_IMPORT_INVOICE,
        {
            ATTR_PERIOD_START: date(2024, 9, 9),
            ATTR_PERIOD_END: date(2025, 9, 12),
            ATTR_IMPORTED_KWH: 7000.0,
            ATTR_EXPORTED_KWH: 7500.0,
        },
        blocking=True,
    )
    await hass.async_block_till_done()
    await get_instance(hass).async_block_till_done()

    stat_id = statistic_id(coordinator(entry), "imported_energy")
    stats = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        dt_util.parse_datetime("2025-09-01T00:00:00+00:00"),
        None,
        {stat_id},
        "day",
        None,
        {"sum", "state"},
    )

    assert stats[stat_id]
    assert stats[stat_id][0]["state"] == 7000.0


async def test_a_glitch_that_slipped_through_can_be_taken_out(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """Developer tools cannot reach the integration's record; this can."""

    hass.states.async_set(IMPORT_ENTITY, "24000.0")
    await hass.async_block_till_done()
    assert coordinator(entry).state.imported == 23000.0

    await hass.services.async_call(
        DOMAIN, SERVICE_ADJUST_ENERGY, {ATTR_IMPORTED_KWH: -22990.0}, blocking=True
    )

    assert coordinator(entry).state.imported == 10.0
    assert coordinator(entry).data.readings.imported_kwh == 10.0


async def test_an_adjustment_lands_in_the_price_period_of_its_day(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await hass.services.async_call(
        DOMAIN,
        SERVICE_ADJUST_ENERGY,
        {ATTR_DAY: date(2025, 3, 1), ATTR_EXPORTED_KWH: 12.5},
        blocking=True,
    )

    buckets = coordinator(entry).state.buckets
    assert buckets["2024-01-01"].exported == 12.5
    assert buckets["2024-01-01"].imported == 0.0


async def test_an_adjustment_cannot_take_out_more_than_was_recorded(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    with pytest.raises(ServiceValidationError, match="cannot go below zero"):
        await hass.services.async_call(
            DOMAIN, SERVICE_ADJUST_ENERGY, {ATTR_IMPORTED_KWH: -1.0}, blocking=True
        )

    assert coordinator(entry).state.imported == 0.0
