# Settlement dashboard

A plan to give the integration the figures Home Assistant's energy dashboard
cannot produce, and a dashboard of its own that shows them beside the parts of
the native one worth keeping. It follows the recorder-backed settlement in
[RECORDER_BACKED_SETTLEMENT.md](RECORDER_BACKED_SETTLEMENT.md) and assumes it:
every figure here is derived from the recorder's long-term statistics on
demand, and nothing about energy is stored.

## Why

The native energy dashboard is a statistics viewer configured by one document,
the energy preferences, in which the user names a statistic for each flow:
grid import and export, solar production, battery charge and discharge, and
the consumption of individual devices. The frontend reads those statistics
and draws them. That design is why any recorded sensor works as a source, and
it is kept here: the integration reads the same preferences, so the user
names each source once, in the native settings, and nothing in this plan asks
for them again.

What the dashboard then does with the sources is fixed, and four things it
does are not good enough for a household on an annual settlement.

It knows one cost per flow. The sources table shows what import cost, what
export earned, and the difference. It has no idea what self-consumed solar
avoided, no standing charge, no VAT, no bill. The integration has every one of
those except the solar figure.

Its consumption is only as good as the hour alignment of its sources. The
frontend works each statistics bucket on its own: every input is clamped at
zero, consumption is import plus production plus discharge less export less
charge, a negative result is clamped to zero, and solar consumed is whatever
production is left after the bucket's battery charge and export, up to that
consumption. The totals, the distribution diagram and the solar gauge are
sums of those per-bucket results. So an inverter that reports late or
coarsely puts production in a different bucket from the export it caused:
the first bucket counts all of it as consumed, the second goes negative and
is clamped away, and the day overstates what the house used by the amount
that was really exported. A production sensor that includes energy sent to a
battery does the same. Nothing tells the user which it is.

It shows no cost per device. Device energy is shown, and the cost of a device
depends on when it ran: under gross settlement a kWh served by the panels at
noon costs the feed-in price it forwent, while one drawn from the grid at
night costs the retail price. Under szaldó neither matters, because every kWh
consumed reduces netting by one. Only the settlement engine can say which
rule applies.

It has no long view. Day, week, month, year and a comparison with the
previous period, over statistics that are never purged. The same period last
year, a seasonal profile across years, and a projection that follows last
year's shape instead of a straight line are all available from the rows it
already reads.

Three of these are computations and one is an input-quality problem. None is
a rendering problem. So the backend grows first, and the dashboard is mostly
an arrangement of built-in cards and statistics graphs around a few thin
custom cards for the figures no built-in card can show.

## The model

### Sources

The integration's own two meters stay in its config entry: they decide the
bill, and changing one is re-creating the entry, as it is today. Everything
else comes from the energy preferences, read through the energy component's
manager. A solar source gives the production statistic, a battery source the
charge and discharge statistics, and the device list gives each device's
consumption statistic and its display name. The manager publishes updates, so
a source added in the native settings is picked up on the next refresh.

A feature whose sources are absent is absent: no solar source, no solar
value, no self-consumption. Absence is not an error and raises nothing. A
source that is named but has no statistics is the existing unrecorded
repair, extended to cover these sources. The preferences are the
household's and an entry is a metering point, so the sources go to the entry
whose import meter the dashboard's grid source names; a second metering
point gets none of them.

The grid meters are the record. The other sources are read only where it
exists, and the house's figures run from the first hour every one of them
covers as well: an inverter recorded before the grid meters says nothing
about hours the grid did not report, one recorded after them says nothing
about the hours before it, and a second inverter that began later leaves
the hours before it unknown. Before that hour the house's flows are
unknowable, which is not zero, so the house's sensors are unavailable,
nothing of the house is published for those hours and the disagreement
finding does not look at them. An hour that carries the seeded remainder,
which happens only when the record begins on the period's first hour, is
left out of every statistic: what it holds is the invoice's, not the hour's.

Everything is read as the two meters are read, by statistic id through
`statistics_during_period`, requesting the hourly change in kWh. External
statistics other integrations wrote are as good as sensors.

### House consumption

What the house used in an hour is import less export plus production, plus
battery discharge less battery charge. The hourly reader grows from two
series to as many as the preferences supply, and the result is published as
two statistics the native dashboard cannot otherwise show, in the same form
as the cost statistics: `hass_energy:<entry>_house_consumption` and
`hass_energy:<entry>_self_consumed_solar`, each row an hour's kWh added to a
running sum.

An hour whose identity fails, where export exceeds production and discharge
so that consumption comes out negative, is published as zero, because a
negative consumption means nothing to any viewer. It is not hidden. The
refresh counts such hours and sums what they lose, and a repair issue reports
the count, the loss and the worst hour, so a misaligned inverter or a
production sensor that counts battery charging is found rather than smoothed
over. The diagnostics carry the same figures. The repair clears when the
window the refresh reads has no such hour.

### Solar value

What the panels earned is a counterfactual: the bill the period would have
produced had there been no panels, less the bill it did produce. The
counterfactual lays each hour's self-consumed solar onto its import and sets
its export to zero, then runs the same engine. Under szaldó the difference
includes what export netted away; under gross settlement it is what
self-consumption avoided plus what surplus earned. Nothing per kWh can get
this right under szaldó, which is the reason the integration exists.

The figure is a sensor for the period and a statistic by the hour:
`hass_energy:<entry>_solar_value`, each hour's row being the counterfactual
bill's movement over that hour less the actual bill's. Both come from the
allocation already made for the cost statistics, run a second time over the
counterfactual hours. A year is a second pass of a few thousand bills over a
handful of price periods, in the same executor job.

### Battery what-if

The settlement needs nothing for a battery; the grid meters already reflect
what it did. The useful question is what a battery would have saved, and
under szaldó the answer is close to nothing, because annual netting is a free
battery. The question matters for the switch to gross settlement, which every
szaldó household reaches ten years after commissioning, so the simulation
prices under gross terms whatever the entry's mode is, and says so.

The simulation is an optional capacity and round-trip efficiency in the
options. Each hour's export charges the battery up to its capacity, each
hour's import discharges it, and the resulting hours are priced under gross
settlement with the entry's prices. The saving is the gross bill of the real
hours less the gross bill of the simulated ones, a sensor for the period that
is unavailable when no capacity is configured. It builds on the counterfactual
machinery of the solar value and adds nothing to the reader.

### Consumption cost and devices

The cost of an hour's consumption is what the household would have saved had
nothing been consumed in that hour: the bill after the hour, less the bill
after an hour in which the grid share was not imported and the self-consumed
solar was exported instead. One rule covers both modes. Under szaldó a kWh
not consumed would have netted, so it is worth the band price, or the feed-in
price once the period is in surplus. Under gross settlement a grid kWh saves
the band price and a solar kWh saves the feed-in price, which is the
time-of-day effect the user is asking for. The rule is chronological, using
only the hours up to the one being costed, so a past hour does not move when
later hours arrive, the property the cost statistics already have.

This is a marginal measure and it does not sum to the invoice. The invoice is
reconciled by the cost statistics; this figure answers a different question,
what each thing that ran was worth not running. The solar value is its
complement.

A device's cost in an hour is its share of the hour's consumption at that
hour's consumption cost. Devices come from the preferences, with their names,
and a device that includes another's consumption in its total carries that
cost too, as the dashboard's own device graph does. Each device gets a
statistic, `hass_energy:<entry>_device_<slug>_cost`, and a sensor for the
period. A device whose share exceeds the hour's consumption, which a
misaligned device meter can produce, is capped at the hour's cost and
counted into the same repair as the consumption identity.

### Projections by season

The period is projected by taking the remaining days from the same calendar
days a year earlier, read from the recorder's daily statistics for the two
meters, and scaling them by the ratio of this period so far to the same days
last year. Where last year has nothing for a day, that day falls back to the
straight-line rate of this period, so a household in its first year gets the
projection the generator makes today and nothing worse. The projected hours
run through the engine like any other, which gives the projected bill, the
projected billed energy and the date the allowance runs out, each as a sensor
and each unknown when the projection does not reach the limit at all. The
generator's projections package is unchanged; this is the integration route.

The same daily reads give the long view: the same period last year and the
monthly profile across years are the native statistics, read for a longer
window, and need nothing new from the backend beyond what the cards ask for.

## The dashboard

A dashboard strategy is a JavaScript module that builds the dashboard's
configuration in the browser when it is opened, from the live registries and
the energy preferences; Home Assistant's own energy and map dashboards are
strategies. Since Home Assistant 2026.5 a strategy can register itself in
`window.customStrategies`, after which it is offered in the new-dashboard
dialog under community dashboards, with a suggested title and icon from the
strategy's `getCreateSuggestions`. The user creates the dashboard from that
dialog, in one step, and owns it like any other: the integration creates no
dashboard and touches no Lovelace internals. That is the minimum Home
Assistant version in `hacs.json`.

The module is served from the integration's own directory through the
HTTP component's static paths and registered with the frontend's extra
module hook, which loads it in both resource modes without an entry in the
resources list. The URL carries the integration's version, so a browser does
not keep a stale module across an upgrade. Core's marketplace, the HACS
successor on its development branch, recognises a resource loaded that way
and leaves it alone.

The strategy arranges five views.

Bill: the settlement as an invoice. Grid cost, what solar avoided, surplus
compensation, standing charge, VAT, total payable, net position, allowance
remaining and the days elapsed. One custom card, reading the integration's
sensors.

Usage: the native date selector, usage graph and distribution, sharing one
collection key, with the integration's cost statistics as the costs and the
house consumption statistic beside them. No custom code.

Devices: energy and cost per device for the selected range. One custom card,
reading the device cost statistics.

History: the same period last year overlaid on this one, and the monthly
profile across years, from the native statistics. One custom card for the
overlay; the native statistics graph for the rest.

Outlook: the projected bill, energy and allowance date, and the battery and
solar figures. Native cards over sensors.

The native settings dialogs stay the only place sources are configured, and
the Bill view links to them. The native cards keep their look; the
dashboard's own look lives in its layout and its three cards.

The cards are written as plain modules, without a framework or a build step,
for as long as they stay thin. The rule for adding a toolchain is that a card
needs a chart library or a second contributor needs type checking, and not
before, because a build pipeline is a second codebase to maintain in a Python
repository. The workflow checks that each module parses, and the cards'
behaviour is covered by the backend tests of the figures they display.

## Edge cases

Alignment. Every derived hour is only as true as the sources' hour alignment,
and no computation here fixes a misaligned source. What the plan adds is the
finding: the consumption repair names the hours, and a user who sees it can
re-point the production source at the inverter's own energy statistic or
exclude battery charging. The native dashboard will show the same error
until the source is fixed, because it reads the same rows.

Units. The recorder converts, so a device metered in Wh is read in kWh.

Partial coverage. A production source recorded from a later date than the
period start gives self-consumption for the hours it covers and nothing for
the rest, and the solar value is of the covered hours only. The seeded
remainder has no production counterpart and takes none; it stays in the bill
as it does today. The diagnostics report the first hour each source has.

Nesting. A device that includes another's consumption is costed on its own
total, so its cost includes the child's, and the Devices view shows the
hierarchy rather than summing siblings and parents together.

Rounding. Hourly figures stay unrounded, like the cost statistics. Period
sensors round as the invoice does.

Removal. The entry's removal clears every statistic it wrote, which now
includes consumption, solar value and one per device. A device dropped from
the preferences has its statistic cleared on the next refresh, so the
dashboard's picker does not keep offering it.

Several metering points. The strategy finds every entry of the integration
in the device registry and builds the five views per entry, so a second
metering point is a second set of views and no configuration. The strategy
declares that it needs no editor.

The marketplace. HACS is moving into core as the marketplace component,
merged on the development branch in October 2026 and not yet released. It
adopts an existing HACS install and keeps reading `hacs.json`, so the
install route is unchanged. It also has a category for dashboard resources,
which would let the strategy be a repository of its own; it is not, because
one install is simpler than two and the module is small.

## Releases

Each release leaves the previous one's entities and statistics working.

House consumption and solar value. The reader grows to the preferences'
sources, the two consumption statistics and the solar value statistic and
sensor appear, and the alignment repair with them. Nothing in the frontend;
the figures show in the native dashboard's own cards and statistics graphs,
which is the first test of whether they are the right figures.

Consumption cost and devices. The engine gains the hourly consumption cost,
the integration the per-device statistics and sensors, and the diagnostics
the device shares.

Projections. The daily reader, the seasonal projection and its sensors, and
the battery what-if with its options.

The dashboard. The strategy module, its registration, the Bill card and
the Usage and Outlook views. The Devices and History cards follow in the
release after, once the first card has shown what a plain module costs to
maintain.

The engine's new rules, the counterfactual, the hourly consumption cost and
the seasonal projection, are tested in `tests/` without Home Assistant. The
reader, the statistics and the repair are tested in `tests/integration`
against the recorder fixture with the preferences set in the test. The
resource's registration is tested there too; the cards are not, beyond
parsing.

## Settled questions

Whether the native usage graph clamps per bucket. It does, in
`computeConsumptionSingle` in the frontend's `src/data/energy.ts`, as
described above, and the distribution card and the solar gauge sum the same
per-bucket results. The sources table does not use it. Checked against the
frontend's development branch on 12 October 2026.

Whether an integration should create the dashboard. No. Home Assistant 2026.5
added `window.customStrategies`, so a registered strategy is offered in the
new-dashboard dialog and the user creates it there. The dashboards
collection the map dashboard is created through is not needed and not used.
Dwains Dashboard, the best-known integration-shipped dashboard, predates
this and registers a YAML-mode dashboard through Lovelace's data directly,
which is the dependency on internals this plan avoids.

How the module is loaded. Through the frontend's extra module hook, after
registering the integration directory as a static path, as Dwains does. The
alternative, an entry in the Lovelace resources collection, is what the
marketplace writes for the resources it installs, but it exists only in
storage mode, and the marketplace itself skips it for a module loaded
through the hook.

Whether device cost should be marginal or average. Marginal: an hour's
consumption cost is what not consuming it would have saved, which answers
the question asked and is chronological. The average, each device's share of
the bill, reconciles to the invoice but says that a device which ran only at
noon on the panels cost the same per kWh as one that ran at night, which is
the complaint. This is a choice, not a finding, and the solar value card is
where the invoice is reconciled.

Whether the battery what-if should also be priced under the entry's own
mode. Not at first. Under szaldó the figure is near zero by construction,
and two figures on one card invite the wrong one to be read. The sensor's
description says which mode it is priced under.
