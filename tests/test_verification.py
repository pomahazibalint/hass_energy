from collections.abc import Sequence
from typing import Any

import pytest

from hass_energy.config import ProjectConfig
from hass_energy.verification import (
    VerificationError,
    fetch_states,
    missing_sources,
    source_entities,
)


def states(*entity_ids: str) -> Sequence[dict[str, Any]]:
    return [{"entity_id": entity_id, "state": "1.0"} for entity_id in entity_ids]


def test_source_entities_are_deduplicated_and_sorted(config: ProjectConfig) -> None:
    assert source_entities(config) == (
        "sensor.grid_export",
        "sensor.grid_import",
        "sensor.heat_pump_energy",
        "sensor.server_energy",
        "sensor.solar_production",
    )


def test_nothing_is_missing_when_every_entity_exists(config: ProjectConfig) -> None:
    def fetch(url: str, token: str) -> Sequence[dict[str, Any]]:
        return states(*source_entities(config))

    assert missing_sources(config, "http://ha.local:8123", "token", fetch) == ()


def test_missing_entities_are_reported(config: ProjectConfig) -> None:
    def fetch(url: str, token: str) -> Sequence[dict[str, Any]]:
        return states("sensor.grid_import", "sensor.unrelated")

    missing = missing_sources(config, "http://ha.local:8123", "token", fetch)

    assert missing == (
        "sensor.grid_export",
        "sensor.heat_pump_energy",
        "sensor.server_energy",
        "sensor.solar_production",
    )


def test_the_url_and_token_reach_the_fetcher(config: ProjectConfig) -> None:
    seen: dict[str, str] = {}

    def fetch(url: str, token: str) -> Sequence[dict[str, Any]]:
        seen["url"] = url
        seen["token"] = token
        return states(*source_entities(config))

    missing_sources(config, "http://ha.local:8123", "secret", fetch)

    assert seen == {"url": "http://ha.local:8123", "token": "secret"}


def test_an_unreachable_instance_is_reported_clearly() -> None:
    # Port 1 on localhost refuses connections, so this exercises the real
    # urllib path without depending on a network.
    with pytest.raises(VerificationError, match="Could not reach Home Assistant"):
        fetch_states("http://127.0.0.1:1", "token")
