"""Checking a configuration against a running Home Assistant.

A typo in a source entity id produces a meter that reads nothing, forever, and
no amount of offline validation can catch it. This asks the instance itself.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from typing import Any

from .config import ProjectConfig

#: Injectable so the checking logic can be tested without a Home Assistant.
Fetch = Callable[[str, str], Sequence[dict[str, Any]]]

TIMEOUT_SECONDS = 10


class VerificationError(RuntimeError):
    """Raised when a running Home Assistant cannot be reached or queried."""


def source_entities(config: ProjectConfig) -> tuple[str, ...]:
    """Entities the configuration expects to already exist."""

    grid = config.grid
    candidates = [grid.import_entity, grid.export_entity, grid.production_entity]
    candidates += [device.entity for device in config.devices]
    return tuple(sorted({entity for entity in candidates if entity}))


def fetch_states(base_url: str, token: str) -> Sequence[dict[str, Any]]:
    """Read every entity state from a Home Assistant REST API."""

    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/states",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            states: Sequence[dict[str, Any]] = json.load(response)
    except urllib.error.HTTPError as error:
        detail = "check the access token" if error.code in (401, 403) else str(error)
        raise VerificationError(f"Home Assistant returned {error.code}: {detail}") from error
    except (urllib.error.URLError, TimeoutError, ValueError) as error:
        raise VerificationError(f"Could not reach Home Assistant at {base_url}: {error}") from error
    return states


def missing_sources(
    config: ProjectConfig, base_url: str, token: str, fetch: Fetch = fetch_states
) -> tuple[str, ...]:
    """Source entities the configuration names that the instance does not have."""

    existing = {state["entity_id"] for state in fetch(base_url, token)}
    return tuple(entity for entity in source_entities(config) if entity not in existing)
