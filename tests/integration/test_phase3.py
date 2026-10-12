"""Seeding, repairs, diagnostics, storage migration and statistics import."""

from datetime import date, timedelta

import pytest
from custom_components.hass_energy.const import (
    ATTR_EXPORTED_KWH,
    ATTR_IMPORTED_KWH,
    ATTR_PERIOD_END,
    ATTR_PERIOD_START,
    CONF_EXPORT_ENTITY,
    CONF_IMPORT_ENTITY,
    CONF_PRICES,
    DOMAIN,
    RETIRED_SENSORS,
    SERVICE_IMPORT_INVOICE,
    SERVICE_SEED_PERIOD,
    STORAGE_KEY,
)
from custom_components.hass_energy.costs import statistic_id
from custom_components.hass_energy.diagnostics import async_get_config_entry_diagnostics
from custom_components.hass_energy.issues import OVERDUE_AFTER_DAYS
from custom_components.hass_energy.settings import price_entry
from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.recorder import Recorder
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .conftest import (
    DAY_START,
    EXPORT_ENTITY,
    IMPORT_ENTITY,
    TODAY,
    coordinator,
    local_midnight,
    record,
    refresh,
)


async def seed(hass: HomeAssistant, start: date, imported: float, exported: float = 0.0) -> None:
    await hass.services.async_call(
        DOMAIN,
        SERVICE_SEED_PERIOD,
        {ATTR_PERIOD_START: start, ATTR_IMPORTED_KWH: imported, ATTR_EXPORTED_KWH: exported},
        blocking=True,
    )
    await hass.async_block_till_done()


async def test_seeding_adopts_a_period_already_under_way(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    """Installed mid-period, the integration must not account from zero."""

    await seed(hass, date(2025, 9, 13), 1847.2, 2103.5)

    state = coordinator(entry).state
    assert state.start == date(2025, 9, 13)
    assert state.unobserved_imported == pytest.approx(1847.2)
    assert state.unobserved_exported == pytest.approx(2103.5)
    bill = coordinator(entry).data
    assert bill.readings.imported_kwh == pytest.approx(1847.2)
    assert bill.readings.exported_kwh == pytest.approx(2103.5)


async def test_seeded_energy_is_spread_across_the_prices_it_spanned(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    """Unobserved history has no shape, so it is spread over the hours nobody saw."""

    await seed(hass, date(2025, 1, 1), 1000.0)

    lines = coordinator(entry).data.subsidized
    assert [round(line.unit_price, 3) for line in lines] == [36.386, 40.0]
    assert sum(line.kwh for line in lines) == pytest.approx(1000.0)
    # Spread over the days from 1 January 2025 to today, 212 of which fell
    # before the price changed on 1 August.
    seeded_days = (TODAY - date(2025, 1, 1)).days
    assert lines[0].kwh / 1000.0 == pytest.approx(212 / seeded_days, abs=0.005)


async def test_seeding_keeps_only_what_the_recorder_does_not_have(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    """The invoice's total is not added on top of hours already recorded."""

    await record(hass, IMPORT_ENTITY, local_midnight(TODAY - timedelta(days=1)), [200.0])

    await seed(hass, TODAY - timedelta(days=1), 500.0)

    assert coordinator(entry).state.unobserved_imported == pytest.approx(300.0)
    assert coordinator(entry).data.readings.imported_kwh == pytest.approx(500.0)


async def test_hours_recorded_after_seeding_add_to_it(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    await seed(hass, TODAY - timedelta(days=1), 500.0)
    await record(hass, IMPORT_ENTITY, DAY_START, [200.0])
    await refresh(hass, entry)

    assert coordinator(entry).data.readings.imported_kwh == pytest.approx(700.0)


async def test_a_fully_recorded_period_needs_no_seed(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    await record(hass, IMPORT_ENTITY, local_midnight(TODAY - timedelta(days=1)), [500.0])

    await seed(hass, TODAY - timedelta(days=1), 500.0)

    assert coordinator(entry).state.unobserved_imported == 0.0
    assert coordinator(entry).data.readings.imported_kwh == 500.0


async def test_a_gap_in_the_price_schedule_is_a_repair_not_a_guess(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    """Unvaluable is not zero, so the entities go unavailable and say why."""

    await seed(hass, date(2020, 1, 1), 100.0)

    registry = ir.async_get(hass)
    assert registry.async_get_issue(DOMAIN, f"price_coverage_{entry.entry_id}")
    assert coordinator(entry).last_update_success is False


async def test_the_repair_clears_once_the_prices_reach_back(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    await seed(hass, date(2020, 1, 1), 100.0)

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
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    """A period well past a year means the reading happened without us."""

    await seed(hass, TODAY - timedelta(days=OVERDUE_AFTER_DAYS + 10), 100.0)

    registry = ir.async_get(hass)
    assert registry.async_get_issue(DOMAIN, f"settlement_overdue_{entry.entry_id}")
    # Every hour recorded still has a price period to fall in.
    assert coordinator(entry).data.period.end > TODAY


async def test_a_source_that_stops_reporting_is_raised(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    hass.states.async_set(IMPORT_ENTITY, "unavailable")
    await hass.async_block_till_done()
    await refresh(hass, entry)

    registry = ir.async_get(hass)
    issue = registry.async_get_issue(DOMAIN, f"source_missing_{entry.entry_id}")
    assert issue is not None
    assert IMPORT_ENTITY in issue.translation_placeholders["entities"]  # type: ignore[index]


async def test_a_source_the_recorder_never_compiled_is_raised(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    """A source without statistics is invisible to the settlement, and says so."""

    registry = ir.async_get(hass)
    issue = registry.async_get_issue(DOMAIN, f"source_unrecorded_{entry.entry_id}")
    assert issue is not None
    assert EXPORT_ENTITY in issue.translation_placeholders["entities"]  # type: ignore[index]

    await record(hass, IMPORT_ENTITY, DAY_START, [1.0])
    await record(hass, EXPORT_ENTITY, DAY_START, [1.0])
    await refresh(hass, entry)

    assert registry.async_get_issue(DOMAIN, f"source_unrecorded_{entry.entry_id}") is None


async def test_diagnostics_explain_every_published_figure(
    entry: MockConfigEntry, hass: HomeAssistant
) -> None:
    await record(hass, IMPORT_ENTITY, DAY_START, [400.0])
    await refresh(hass, entry)

    report = await async_get_config_entry_diagnostics(hass, entry)

    assert report["period"]["period_start"] == TODAY.isoformat()
    assert report["observed"]["imported_kwh"] == 400.0
    assert report["observed"]["first"] == DAY_START.isoformat()
    assert report["terms"]["allowance_basis"] == "netted"
    assert len(report["prices"]) == 2
    assert report["settlement"]["billed_kwh"] == 400.0
    assert report["prices_cover_period"] is True


async def test_the_old_record_is_reconciled_against_the_recorder(
    recorder_mock: Recorder,
    enable_custom_integrations: None,
    frozen: FrozenDateTimeFactory,
    hass: HomeAssistant,
) -> None:
    """A version 1 store kept its own energy; what the recorder has is not kept twice."""

    start = TODAY - timedelta(days=3)
    await record(hass, IMPORT_ENTITY, local_midnight(TODAY - timedelta(days=2)), [300.0])
    hass.states.async_set(IMPORT_ENTITY, "1000.0")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test settlement",
        data={CONF_IMPORT_ENTITY: IMPORT_ENTITY},
        options={CONF_PRICES: [price_entry(date(2024, 1, 1), 36.386, 70.104, 5.11)]},
    )
    entry.add_to_hass(hass)
    await Store[dict](hass, 1, f"{STORAGE_KEY}.{entry.entry_id}").async_save(
        {
            "period_start": start.isoformat(),
            "last_import": 1000.0,
            "last_export": None,
            "buckets": {
                "2024-01-01": {"imported": 450.0, "exported": 20.0},
                "2025-08-01": {"imported": 50.0, "exported": 0.0},
            },
        }
    )

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = coordinator(entry).state
    assert state.start == start
    assert state.unobserved_imported == pytest.approx(200.0)
    assert state.unobserved_exported == pytest.approx(20.0)
    assert coordinator(entry).data.readings.imported_kwh == pytest.approx(500.0)
    # Written back in the new shape, so the reconciliation happens once.
    stored = await Store[dict](hass, 2, f"{STORAGE_KEY}.{entry.entry_id}").async_load()
    assert stored is not None
    assert "reconcile" not in stored
    assert "buckets" not in stored


async def test_a_past_invoice_becomes_history(
    recorder_mock: Recorder, hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """Home Assistant never saw these years, so nothing else can supply them."""

    from homeassistant.components.recorder.statistics import statistics_during_period
    from homeassistant.components.recorder.util import get_instance
    from homeassistant.util import dt as dt_util

    hass.states.async_set(IMPORT_ENTITY, "1000.0")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test settlement",
        data={CONF_IMPORT_ENTITY: IMPORT_ENTITY, CONF_EXPORT_ENTITY: None},
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

    stat_id = statistic_id(entry.entry_id, "imported_energy")
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
    rows = stats[stat_id]
    assert rows[-1]["state"] == 7000.0
    assert rows[-1]["sum"] == 7000.0

    cost_id = statistic_id(entry.entry_id, "settlement_cost")
    cost = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        dt_util.parse_datetime("2025-09-01T00:00:00+00:00"),
        None,
        {cost_id},
        "day",
        None,
        {"sum", "state"},
    )
    assert cost[cost_id][-1]["state"] == 1836.0


async def test_nothing_of_the_retired_sensors_survives_an_upgrade(
    recorder_mock: Recorder,
    enable_custom_integrations: None,
    frozen: FrozenDateTimeFactory,
    hass: HomeAssistant,
) -> None:
    """The running-total sensors and the repair that announced them are gone."""

    hass.states.async_set(IMPORT_ENTITY, "1000.0")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test settlement",
        data={CONF_IMPORT_ENTITY: IMPORT_ENTITY},
        options={CONF_PRICES: [price_entry(date(2024, 1, 1), 36.386, 70.104, 5.11)]},
    )
    entry.add_to_hass(hass)
    entities = er.async_get(hass)
    retired = [
        entities.async_get_or_create(
            "sensor", DOMAIN, f"{entry.entry_id}_{key}", config_entry=entry
        ).entity_id
        for key in RETIRED_SENSORS
    ]
    ir.async_create_issue(
        hass,
        DOMAIN,
        f"running_totals_retired_{entry.entry_id}",
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="running_totals_retired",
    )

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert all(entities.async_get(entity_id) is None for entity_id in retired)
    issues = ir.async_get(hass)
    assert issues.async_get_issue(DOMAIN, f"running_totals_retired_{entry.entry_id}") is None
