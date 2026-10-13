"""Show what the recorder holds for the energy sources around an hour.

For judging a disagreement finding: the integration reads the recorder's
hourly statistics, and this prints the same rows, source by source, so an
hour in which export exceeds import and production can be traced to the
row that caused it, whether a spike, a gap or a lag.

Read-only, over the websocket API with a long-lived access token:

    uv run --with websockets python scripts/inspect_hours.py \\
        --url https://home.example --token-file ~/.hass-token \\
        --around 2026-06-26T19:00 --hours 3

The sources are taken from the energy dashboard's preferences, so they are
the ones the integration reads. Pass --sources to look at others.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

try:
    import websockets
except ImportError:  # pragma: no cover
    sys.exit("This needs the websockets package: run it with uv run --with websockets.")


class HomeAssistant:
    """The few websocket calls this needs."""

    def __init__(self, url: str, token: str) -> None:
        scheme = "wss" if url.startswith("https") else "ws"
        self._url = scheme + "://" + url.split("://", 1)[1].rstrip("/") + "/api/websocket"
        self._token = token
        self._next = 1

    async def __aenter__(self) -> HomeAssistant:
        self._socket = await websockets.connect(self._url, max_size=None)
        hello = json.loads(await self._socket.recv())
        if hello.get("type") != "auth_required":
            raise RuntimeError(f"Unexpected greeting: {hello}")
        await self._socket.send(json.dumps({"type": "auth", "access_token": self._token}))
        answer = json.loads(await self._socket.recv())
        if answer.get("type") != "auth_ok":
            raise RuntimeError(f"Authentication failed: {answer}")
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._socket.close()

    async def call(self, **message: Any) -> Any:
        message["id"] = self._next
        self._next += 1
        await self._socket.send(json.dumps(message))
        while True:
            reply = json.loads(await self._socket.recv())
            if reply.get("id") != message["id"]:
                continue
            if not reply.get("success", False):
                raise RuntimeError(f"{message['type']} failed: {reply.get('error')}")
            return reply["result"]


def sources_of(prefs: dict[str, Any] | None) -> dict[str, str]:
    """Statistic id to role, from the energy preferences, in either grid format."""

    found: dict[str, str] = {}
    for source in (prefs or {}).get("energy_sources", []):
        kind = source.get("type")
        if kind == "grid":
            for flow in source.get("flow_from", []):
                found[flow["stat_energy_from"]] = "import"
            for flow in source.get("flow_to", []):
                found[flow["stat_energy_to"]] = "export"
            if source.get("stat_energy_from"):
                found[source["stat_energy_from"]] = "import"
            if source.get("stat_energy_to"):
                found[source["stat_energy_to"]] = "export"
        elif kind == "solar":
            found[source["stat_energy_from"]] = "solar"
        elif kind == "battery":
            found[source["stat_energy_from"]] = "discharge"
            found[source["stat_energy_to"]] = "charge"
    for device in (prefs or {}).get("device_consumption", []):
        found[device["stat_consumption"]] = "device"
    return found


def fmt(value: Any) -> str:
    return "      -" if value is None else f"{value:7.3f}"


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--url", required=True, help="e.g. http://homeassistant.local:8123")
    parser.add_argument(
        "--token-file", type=Path, help="File holding a long-lived access token; else $HASS_TOKEN"
    )
    parser.add_argument("--around", required=True, help="Local hour, e.g. 2026-06-26T19:00")
    parser.add_argument("--hours", type=int, default=3, help="Hours either side to show")
    parser.add_argument("--sources", nargs="*", help="Statistic ids instead of the dashboard's")
    args = parser.parse_args()

    token = os.environ.get("HASS_TOKEN", "")
    if args.token_file:
        token = args.token_file.read_text().strip()
    if not token:
        sys.exit("No token: pass --token-file or set HASS_TOKEN.")
    middle = datetime.fromisoformat(args.around)
    if middle.tzinfo is None:
        middle = middle.astimezone()
    start = middle - timedelta(hours=args.hours)
    end = middle + timedelta(hours=args.hours + 1)

    async with HomeAssistant(args.url, token) as hass:
        roles = sources_of(await hass.call(type="energy/get_prefs")) if not args.sources else {}
        ids = args.sources or list(roles)
        if not ids:
            sys.exit("The energy dashboard names no sources; pass --sources.")
        # The listing takes no id filter; it is the whole recorder's.
        metadata = {
            one["statistic_id"]: one
            for one in await hass.call(type="recorder/list_statistic_ids")
            if one["statistic_id"] in ids
        }
        rows = await hass.call(
            type="recorder/statistics_during_period",
            start_time=start.isoformat(),
            end_time=end.isoformat(),
            statistic_ids=ids,
            period="hour",
            types=["change", "sum", "state"],
        )

    print(f"Hours {start:%Y-%m-%d %H:%M} to {end:%Y-%m-%d %H:%M} ({start.tzname()}), as recorded")
    for statistic in ids:
        meta = metadata.get(statistic, {})
        role = roles.get(statistic, "")
        unit = meta.get("statistics_unit_of_measurement", "?")
        print()
        print(f"{statistic}  [{role}]  unit {unit}  source {meta.get('source', '?')}")
        print("  hour (local)          change      sum    state")
        by_start = {row["start"]: row for row in rows.get(statistic, [])}
        cursor = start.replace(minute=0, second=0, microsecond=0)
        while cursor < end:
            row = by_start.get(cursor.timestamp() * 1000) or by_start.get(cursor.timestamp())
            marker = "" if row else "   <- no row: the source did not report this hour"
            figures = "  ".join(fmt(row and row.get(key)) for key in ("change", "sum", "state"))
            print(f"  {cursor:%Y-%m-%d %H:%M}  {figures}{marker}")
            cursor += timedelta(hours=1)

    print()
    print("Balance per hour: import + solar + discharge - export - charge; negative disagrees,")
    print("and so does a device that used more than the balance.")
    cursor = start.replace(minute=0, second=0, microsecond=0)
    signs = {"import": 1, "solar": 1, "discharge": 1, "export": -1, "charge": -1}

    def change_of(statistic: str, at: datetime) -> float:
        by_start = {row["start"]: row for row in rows.get(statistic, [])}
        row = by_start.get(at.timestamp() * 1000) or by_start.get(at.timestamp())
        return max((row or {}).get("change") or 0.0, 0.0)

    while cursor < end:
        total = sum(
            signs[role] * change_of(statistic, cursor)
            for statistic, role in roles.items()
            if role in signs
        )
        flags = ["energy left that never entered"] if total < -1e-6 else []
        for statistic, role in roles.items():
            used = change_of(statistic, cursor) if role == "device" else 0.0
            house = max(total, 0.0)
            if used > house + 1e-6:
                flags.append(f"{statistic} used {used:.3f}, {used - house:.3f} above the house")
        marker = ("   <- " + "; ".join(flags)) if flags else ""
        print(f"  {cursor:%Y-%m-%d %H:%M}  {total:8.3f}{marker}")
        cursor += timedelta(hours=1)


if __name__ == "__main__":
    asyncio.run(main())
