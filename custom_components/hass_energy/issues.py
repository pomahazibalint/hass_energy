"""Problems worth interrupting someone about.

Home Assistant has a place for these, so they are raised as repair issues
rather than as binary sensors nobody has put on a dashboard yet.
"""

from __future__ import annotations

from datetime import date, datetime

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util

from .const import DOMAIN

#: A settlement running this far past a nominal year suggests the meter reading
#: happened and nobody told the integration. The reference invoices ran 359 and
#: 368 days, and the supplier announces the reading as a two-week window.
OVERDUE_AFTER_DAYS = 400


def _issue_id(entry_id: str, kind: str) -> str:
    return f"{kind}_{entry_id}"


def _set(
    hass: HomeAssistant,
    entry_id: str,
    kind: str,
    active: bool,
    severity: ir.IssueSeverity = ir.IssueSeverity.WARNING,
    placeholders: dict[str, str] | None = None,
) -> None:
    issue_id = _issue_id(entry_id, kind)
    if not active:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        return
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=severity,
        translation_key=kind,
        translation_placeholders=placeholders or {},
    )


def price_coverage(hass: HomeAssistant, entry_id: str, covered: bool, start: date) -> None:
    """The schedule has to reach back to the start of the settlement period.

    Without it there is no price for the energy already recorded, and every
    derived figure is unanswerable rather than merely wrong.
    """

    _set(
        hass,
        entry_id,
        "price_coverage",
        active=not covered,
        severity=ir.IssueSeverity.ERROR,
        placeholders={"period_start": start.isoformat()},
    )


def settlement_overdue(hass: HomeAssistant, entry_id: str, days: int) -> None:
    """A period that has run far past a year has probably already been read."""

    _set(
        hass,
        entry_id,
        "settlement_overdue",
        active=days > OVERDUE_AFTER_DAYS,
        placeholders={"days": str(days)},
    )


def source_stale(
    hass: HomeAssistant, entry_id: str, stale: dict[str, datetime | None], days: int
) -> None:
    """A source the recorder has had nothing from for days stops the accounting silently.

    Judged by the statistics rather than the live state, because an inverter
    is unavailable every night and the settlement reads the recorder, not
    the sensor. The live-state check this replaces is withdrawn with it.
    """

    _set(hass, entry_id, "source_missing", active=False)
    _set(
        hass,
        entry_id,
        "source_stale",
        active=bool(stale),
        placeholders={
            # Words belong to the translation; the placeholder carries data.
            "entities": ", ".join(
                f"{source} ({dt_util.as_local(last).isoformat(timespec='minutes')})"
                if last
                else source
                for source, last in stale.items()
            ),
            "days": str(days),
        },
    )


def source_unrecorded(hass: HomeAssistant, entry_id: str, unrecorded: list[str]) -> None:
    """A source the recorder has no statistics for contributes nothing.

    The settlement is read from long-term statistics, so a source that is
    excluded from the recorder, or has no total state class, is invisible.
    """

    _set(
        hass,
        entry_id,
        "source_unrecorded",
        active=bool(unrecorded),
        severity=ir.IssueSeverity.ERROR,
        placeholders={"entities": ", ".join(unrecorded)},
    )


def sources_disagree(
    hass: HomeAssistant, entry_id: str, hours: int, lost_kwh: float, worst: datetime | None
) -> None:
    """Energy left the house in hours it never entered it.

    That cannot happen, so a source is reporting in the wrong hour: an
    inverter that lags the grid meter, or a production meter that counts what
    charged the battery. The native dashboard reads the same rows and
    overstates consumption by the same amount, so the user is told rather
    than the figure smoothed.
    """

    _set(
        hass,
        entry_id,
        "sources_disagree",
        active=hours > 0,
        placeholders={
            "hours": str(hours),
            "lost_kwh": f"{lost_kwh:.1f}",
            # The dashboard the text sends the user to shows local hours.
            "worst": dt_util.as_local(worst).isoformat(timespec="minutes") if worst else "",
        },
    )


def source_glitches(
    hass: HomeAssistant,
    entry_id: str,
    glitches: dict[str, dict[datetime, float]],
    ceiling_kwh: float,
) -> None:
    """A source claimed more energy in an hour than a meter can count.

    An inverter that reads zero for a moment and then its lifetime total
    again: the recorder takes the zero for a meter reset and books the total
    that follows as new energy. The hour is read as nothing here, but the
    recorder's own row still carries it, the energy dashboard draws it, and
    only a repair on the Statistics page removes it.
    """

    _set(
        hass,
        entry_id,
        "source_glitches",
        active=bool(glitches),
        placeholders={
            # Words belong to the translation; the placeholder carries data.
            "sources": "; ".join(
                f"{source} ({len(hours)} h, {sum(hours.values()):.1f} kWh, "
                f"{dt_util.as_local(max(hours)).isoformat(timespec='minutes')})"
                for source, hours in glitches.items()
            ),
            "ceiling": f"{ceiling_kwh:.0f}",
        },
    )


def device_bursts(hass: HomeAssistant, entry_id: str, bursts: dict[str, tuple[int, float]]) -> None:
    """A device meter claimed more in an hour than the whole house used.

    A session's energy booked in the hour it ended, or a reading that stood
    still through a connection gap and caught up in one step. Its cost for
    such an hour is capped at the house's, and the hours it really ran in
    are the rest of the house. Worth knowing, not worth alarm.
    """

    _set(
        hass,
        entry_id,
        "device_bursts",
        active=bool(bursts),
        placeholders={
            # Words belong to the translation; the placeholder carries data.
            "devices": "; ".join(
                f"{name} ({hours} h, {excess:.1f} kWh)" for name, (hours, excess) in bursts.items()
            ),
        },
    )


def running_totals_retired(hass: HomeAssistant, entry_id: str) -> None:
    """Withdraw the notice that announced the running-total sensors' retirement.

    It named the statistics that replaced them for one release; the sensors
    are gone now, and a repair for an entity that no longer exists would only
    puzzle whoever reads it.
    """

    _set(hass, entry_id, "running_totals_retired", active=False)
