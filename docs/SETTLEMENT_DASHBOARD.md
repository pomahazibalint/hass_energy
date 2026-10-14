# Settlement dashboard

Status, 13 October 2026: everything below is implemented and released,
the four releases and the Devices and History cards the fourth deferred.
The plan is complete; what follows it is use. Things the
implementation settled that the plan had left open are recorded where they
belong: the house's figures begin only where the grid record and every named
household source exist, an hour that carries the seeded remainder is left
out of every statistic, a device's figures begin at its own first hour
without gating the house's, the house's consumption cost is a statistic and
a sensor of its own, the allowance's exhaustion date is when it is gone for
good, the battery charges before it discharges within an hour, and a
strategy is a custom element with a listing in `window.customStrategies`
rather than a registration there, the Devices card shows the settlement
period and leaves the selected range to a native graph, and the History
card is hand-drawn SVG; see "Sources", "Consumption cost and devices",
"Projections by season", "Battery what-if", "The dashboard" and "Edge
cases".

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
options, a step of their own in the options menu, where a capacity of zero
is no battery. Each hour's export charges the battery up to its capacity,
each hour's import discharges it with the round-trip loss taken on the way
out, and an hour with both is charged first, since the order within the hour
is unknown and a battery is there to catch what would have left. The
resulting hours are priced under gross settlement with the entry's prices.
The saving is the gross bill of the real hours less the gross bill of the
simulated ones, a sensor for the period that is unavailable when no capacity
is configured, and whose name says it is priced under gross settlement. It
builds on the counterfactual machinery of the solar value and adds nothing
to the reader.

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

The house's figure is published like the others: a statistic,
`hass_energy:<entry>_consumption_cost`, each row an hour's cost, and a
sensor for the period, from the same first hour as the house's consumption.
It is the figure the Devices view divides up, so the part no device accounts
for can be shown as the rest of the house.

What the panels saved on that consumption is the same walk over the house
without them: the no-panels hours `without_solar` already gives, each costed
against nothing consumed in it, which is what the hour's consumption would
have cost bought from the grid. A house without panels has nothing to net
or to sell, so the figure is the same in either settlement mode: the band
price with VAT while the allowance would have lasted, the market price
after. The saving is that less the consumption cost, for the house and for
each device's share, and the device cost sensors and the consumption cost
sensor carry it as attributes, split into what would have been bought at
the subsidized price and at the market price, in money and in kWh: the
hour's purchase cost over its consumption is a price between the two bands
in force that day, and says how the hour fell between them. The Devices
card shows these as money columns that sum in two directions: across a
row, subsidized plus market is the no-panels cost, and the no-panels cost
less the bill is the saving; down a column, the devices and the rest of the
house are the house. They replaced the per-price kWh columns and the
average, which said the same thing less directly. Below the width the
columns fit at, the share and the two bands give way, by a container query
on the card's own width, since the dashboard's grid sets it and not the
screen. A household without panels has none of these figures, and none of
the columns. The contract what-if, what the period would cost under gross
settlement, is a house-wide question that one line of the invoice answers.
Two caveats, in the card's note: the actual cost is marginal and the
savings do not sum to the solar value line, which compares two whole bills;
and the no-panels house eats its allowance sooner, so a late hour's saving
can be priced at the market rate where the real hour was not. When that
house's allowance would run out is projected the way the real one is, from
the no-panels hours and last year's no-panels days, and is a sensor beside
the real date.

The allowance is applied per allowance year. The year begins on 1 August,
the supplier splits a period there by a dictated or estimated reading, and
what one year leaves unused does not carry into the next. So a period that
straddles 1 August has one allowance for each side, that side's days'
worth, against the energy billed on that side, and the price schedule
splits its segments there whether or not a price moved, as the invoice
does. The two rules agree for a household under the allowance on both
sides or over it on both; they differ for a heavy winter on slack from the
spring, which the per-side rule bills at the market price while one total
would not. MVM states the no-carry-over and the split for the allowance in
general and nothing for a szaldó settlement in particular, so the per-side
rule is the safe reading rather than a confirmed one. The bill carries its
sides, the allowance remaining counts a side that has ended as spent, the
next kWh is priced on today's side, and the run-out date is asked of the
first side still open: a side gone is not the allowance gone when the next
side's is still to come.

The net position under gross settlement is the same hours settled gross,
one more line of the invoice for a szaldó household asking what the switch
would mean; under gross settlement it would repeat the net position, so the
line is unavailable rather than said twice. The battery what-if had already
settled the hours gross, and the two share the one walk.

A device's cost in an hour is its share of the hour's consumption at that
hour's consumption cost. Devices come from the preferences, with their names,
and a device that includes another's consumption in its total carries that
cost too, as the dashboard's own device graph does. Each device gets a
statistic, `hass_energy:<entry>_device_<slug>_cost`, and a sensor for the
period, named as the dashboard names the device and following a rename. The
slug is of the device's statistic id, not its name, so a rename does not
start a second series. A device's figures run from its own first hour as
well as the house's: a meter that began recording last month used something
unknown before that, not nothing. A device gates nothing of the house, since
it says nothing about the house's flows. A device whose share exceeds the
hour's consumption, which a meter that books a session's energy in the hour
the session ends produces, as does one whose reading stood still through a
connection gap and caught up in one step, is capped at the hour's cost and reported
through a repair of its own that names the device, from the hour the house
is known. It is not the house's disagreement: the meter is right about the
total and wrong about the hours, and the hours it really ran in are the
rest of the house.

The sensors for devices follow the preferences rather than the entry's
setup: a device named in the dashboard gets its sensor on the next refresh,
and one dropped has its sensor removed from the registry and its statistic
cleared. Removing the entry clears whatever the recorder holds under the
entry's name, which is how statistics named after devices the integration
no longer knows about are found.

### Projections by season

The period is projected by taking the remaining days from the same calendar
days a year earlier, read from the recorder's daily statistics for the two
meters, and scaling them by the ratio of this period so far to the same days
last year. Where last year has nothing for a day, that day falls back to the
straight-line rate of this period, so a household in its first year gets the
projection the generator makes today and nothing worse. The projected hours
run through the engine like any other, which gives the projected bill, the
projected billed energy and the date the allowance runs out, each as a sensor
and the date unknown when the projection does not reach the limit at all.
The generator's projections package is unchanged; this is the integration
route.

What the implementation settled. The ratio is per meter, over this period's
complete days that the recorder saw against the same days last year, so a
household whose panels are new scales its import from last year and takes
its export from the straight line. Today counts for the fraction of it still
to come. The straight-line rate is the bill's readings over the days elapsed,
so a seeded remainder counts in it; the shape is only what the recorder saw.
A projected day settles as one hour at the day's start, since the allocation
assigns an hour to a price period by its local day and a day's shape within
itself is not projected. The allowance runs out when it is gone for good:
under szaldó export can restore allowance that earlier import used, so the
date is the hour after the last one with any left, not the first that
reaches zero. The three sensors are measurements rather than totals, because
a projection is re-estimated, not accumulated.

The same daily reads give the long view: the same period last year and the
monthly profile across years are the native statistics, read for a longer
window, and need nothing new from the backend beyond what the cards ask for.

## The dashboard

A dashboard strategy is a JavaScript module that builds the dashboard's
configuration in the browser when it is opened, from the live registries and
the energy preferences; Home Assistant's own energy and map dashboards are
strategies. A strategy is a custom element named
`ll-strategy-dashboard-<name>` with a static `generate`, and since Home
Assistant 2026.5 a listing pushed to `window.customStrategies` makes the
new-dashboard dialog offer it under custom dashboards, with a suggested
title and icon from the strategy's `getCreateSuggestions`. The user creates
the dashboard from that dialog, in one step, and owns it like any other: the
integration creates no dashboard and touches no Lovelace internals. That is
the version the dashboard needs at least. The strategy declares
`noEditor`, since it takes no configuration.

The strategy reads three things over the websocket: the integration's
config entries, the entity registry, from which it takes each entry's
entities by the line of the settlement each is, and the recorder's list of
statistic ids, from which it takes the statistics the entry wrote. Reading
the statistics rather than spelling their ids means the strategy never
reproduces the backend's naming. A view's cards include only the entities
and statistics the entry has, so a household without panels sees no solar
lines and no empty graphs.

The module is served from the integration's own directory through the
HTTP component's static paths and registered with the frontend's extra
module hook, which loads it in both resource modes without an entry in the
resources list. The URL carries the integration's version, so a browser does
not keep a stale module across an upgrade. Core's marketplace, the HACS
successor on its development branch, recognises a resource loaded that way
and leaves it alone.

The strategy arranged five views at first, one per question, each a single
column of cards, then three in the sections grid. Use showed what it was
becoming: the native energy dashboard with two tabs added. So that is what
it is. The native dashboard's own tabs, Summary, Electricity, Gas, Water
and Now, are chosen as the native dashboard chooses them from the
preferences and titled with its own words. All but Now are views that
delegate to Home Assistant's view strategies, over the collection the
native dashboard keys its date-picked tabs by; nothing of them is copied.
Now is laid out by the strategy itself from the native power cards and
badges, over the native dashboard's own collection for it, because the
native power view is one section of the sections grid that the energy
panel widens to the view with a style of its own, and in a dashboard it
would be one column wide. Their titles, and the native cards', are in the
energy panel's translation fragment, which a dashboard does not load, so
the strategy loads it before it builds them. After them come the
integration's two per metering point: Costs, the invoice and the outlook
in the sidebar beside the costs for the selected range, the house's
consumption and the devices; and History, the long view. The two are
built in the native view's own shape, a sidebar of small cards
shown when the view has two or more columns and the same cards inline when
it has one, a main section three columns wide in which a card asks for all
36 card columns, and the date picker as a floating footer card that takes
no room from the cards. The five below are the questions; the three views
are how they are laid out. Two things about the sections grid that the
first layouts got wrong: a section spanning n columns is a grid of 12 n
card columns in which a card takes 12 unless told otherwise, and sections
in a row align to the tallest, so a section per card leaves gaps. The
History card draws itself at the card's real width, because a scaled
viewBox scales its text with it. The sidebar and footer of a view exist
from Home Assistant 2026.10, which is the minimum version in `hacs.json`.

Bill: the settlement as an invoice. Grid cost, what solar avoided, surplus
compensation, standing charge, VAT, total payable, net position, allowance
remaining and the days elapsed. One custom card, reading the integration's
sensors.

Usage: the native date selector, usage graph and distribution, sharing one
collection key, with the integration's cost statistics as the costs and the
house consumption statistic beside them. No custom code.

Devices: energy and cost per device. One custom card for the settlement
period, reading the device cost sensors, which carry the device's name, its
energy and the device it is included in, so the card shows the hierarchy
rather than summing a parent and its child together, and the part no device
accounts for as the rest of the house. The selected range is the native
statistics graph's, over the device cost statistics and following the
energy date picker: a custom card could follow the picker only through the
frontend's internal energy collection, which this plan does not touch, and
the settlement period is the question the integration answers.

History: the same calendar months this year over the years before it, from
the native statistics, read over the websocket by month and drawn as
grouped bars. One custom card per statistic, for the grid meters the
dashboard names and the house consumption; the native statistics graph for
past settlements, from the statistics the invoice import writes. The bars
are plain SVG: the rule for adding a chart library is that a card needs
one, and grouped bars do not.

Outlook: the projected bill, energy and allowance date, and the battery and
solar figures. Native cards over sensors.

The native settings dialogs stay the only place sources are configured, and
the Bill card links to them. The native cards keep their look; the
dashboard's own look lives in its layout and its three cards. The Usage
view takes every native energy card the household has sources for: the
usage graph, the distribution or, with devices named, the sankey, the solar
graph, the self-consumption and grid-neutrality gauges, the sources table,
and the device graphs. They share the energy date picker, and the
statistics graphs over the integration's own figures follow it through the
card's own date-selection option.

The dashboard speaks the user's language. What Home Assistant renders,
entity names and repairs, is translated in the integration's translations
directory, English and Hungarian; what the strategy and the cards write
themselves, view and card titles, the invoice's lines, the devices table,
is translated in the module `strings.js` from the language in `hass`, with
month names from the browser's own locale data. A repair's placeholders
carry data and never words, so a translation can phrase the sentence.

The cards are written as plain modules, without a framework or a build step,
for as long as they stay thin. The rule for adding a toolchain is that a card
needs a chart library or a second contributor needs type checking, and not
before, because a build pipeline is a second codebase to maintain in a Python
repository. The workflow checks that each module parses, and the cards'
behaviour is covered by the backend tests of the figures they display.

## How a figure came to be

A figure the user cannot follow is a figure the user does not trust, and a
device's cost, its share of each hour at what not consuming in that hour
would have saved, is the hardest to follow. The answer is the same for
every money line and it is not prose from the backend: every money sensor
carries the figures it was made of as attributes, numbers and never words,
and the cards phrase them in the user's language when a line is tapped.
The attributes show in Home Assistant's own more-info dialog too.

For the costs priced hour by hour, the house's and each device's, the
figures are how much energy was worth which price. The engine names the
rate of each hour by comparing the hour's cost per kWh with the prices in
force that day: the subsidized price with VAT while the allowance lasts and
a kWh would net, the market price with VAT once it has run out, the feed-in
price once the period is in surplus or, under gross settlement, for what the
panels supplied, and mixed for an hour that straddled two. A device's share
of each hour goes into the same buckets. The Devices card shows them as
columns rather than a sentence: each device's energy, its share of the
house, its energy in the hours worth each price with the price in the
column head, the average per kWh and the cost, with the rest of the house
and the house in the same columns, so the table spells out how the totals
come about without a tap. A column nobody has a figure in is left out. The
invoice's lines are simpler and carry what they
always were: energy as subsidized and market kWh with their lines, the
standing charge as months times the monthly charge, VAT as the rate on the
net total, the total as its three parts, the net position as the total
less the surplus owed, the solar value as the two net positions, the
allowance as used over earned, and the period as its dates.

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

House consumption and solar value. Done. The reader grows to the
preferences' sources, the two consumption statistics and the solar value
statistic and sensor appear, and the alignment repair with them. Nothing in
the frontend; the figures show in the native dashboard's own cards and
statistics graphs, which is the first test of whether they are the right
figures.

Consumption cost and devices. Done. The engine gained the hourly consumption
cost, the integration the consumption cost and per-device statistics and
sensors, and the diagnostics the device shares. The engine's part is a
second walk of the same ledger `allocate` uses, `marginal`, which prices any
hour against any alternative for that hour alone, and the no-consumption
alternative is a method on the hour's flows beside the no-solar one.

Projections. Done. The daily reader, the seasonal projection and its
sensors, and the battery what-if with its options. The engine gained a
projection module, the allowance left after each hour on the allocation's
hourly figures, a one-shot settlement for callers that want only the end,
and the battery beside the other counterfactuals on the hour's flows.

The dashboard. Done. The strategy module, its registration, the Bill card
and the Usage and Outlook views. The module is served from the
integration's `www` directory under a URL carrying the version, the
`frontend` and `http` components became dependencies, and the workflow
parses each module with node, since that is the only check a plain module
without a build step can have.

The Devices and History cards. Done, in the release after, as planned. The
Bill card had shown that a plain module is a hundred lines to own and
nothing to build, and the two cards followed the same shape. The device
cost sensors gained the device's name as an attribute so the Devices card
needs no registry lookup.

Savings. Done. What the panels saved on each device and on the house, and
the period under gross settlement on the invoice; then, in the release
after, the purchase split into its bands as the table's money columns, the
allowance per side of 1 August, and when the allowance would run out
without panels. In the savings release the
prices were found to have been taken as net when the published figures,
36.386 and 70.104 Ft/kWh, carry the VAT already, so every energy line had
been 27% high; the options now say the prices are entered as published and
the settings bring them to net for the engine, which was right to bill net
and add the VAT as the invoice does. The feed-in price is outside VAT and
was never touched.

After the plan: the five views became three in the sections grid, the
native energy cards came in, the History card gained the hover tooltip the
native charts have, the dashboard and the integration gained Hungarian, and
every money line can say how it came to be; see "How a figure came to be".

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
added `window.customStrategies`, so a listed strategy is offered in the
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
