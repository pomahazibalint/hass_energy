# Recorder-backed settlement

Implemented in 0.4.0 and 0.5.0. The first collapsed the first three releases
of the migration below into one: the record was retired in the same release
that introduced its replacement, with the running-total sensors kept behind a
repair issue as planned. The second removed the sensors and the repair, and
forgets the entity registry entries they leave behind, which the plan had not
anticipated. One departure from the plan: cost statistics are
written only for hours the recorder observed. The seeded remainder stays in
the bill and in the netting position, but a flat smear of cost over months
nobody watched would have read in the dashboard as something that happened.

This was a plan to rebuild the integration's record of energy on Home Assistant's own
long-term statistics, and to deliver cost to the energy dashboard as hourly
statistics rather than as live sensors.

## Why

Every defect fixed in the integration so far traces back to one decision: the
coordinator keeps its own record of kWh, fed by state-change deltas and
bucketed by price period. That record needs its own reset detection, its own
glitch handling, its own step limit, its own carry-over when a settlement
closes, and its own correction action, because nothing in Home Assistant can
reach it. It also cannot answer which day a kWh fell on, so a price backdated
into the current period is applied to the wrong energy.

Home Assistant already holds the information the record approximates. The
recorder compiles an hourly sum for every energy sensor with a total state
class, applies its own reset and dip detection, keeps the rows indefinitely,
and lets a user repair an outlier from the Statistics page. For the import and
export meters this gives per-hour energy over the whole settlement period, and
over any period before the integration was installed for which the sensors
were recorded.

The energy dashboard, for its part, is a statistics viewer. It accepts a
statistic id for the cost of a source and draws the hourly change in its sum.
Live sensors are a detour: the recorder compiles them into statistics, the
dashboard reads those, and in between the sensor cannot rewrite an hour it has
already published. External statistics written by an integration have no such
limit: a row written for an hour that already has one replaces it. Tibber
delivers its hourly cost this way, and it appears in the dashboard's cost
selector like any other.

## The model

A settlement period is a start date and, until a meter reading ends it, a
nominal year. Nothing about it is stored except the start date.

Energy for the period is the hourly change of the import and export sensors'
long-term statistics from the period start to now, read with
`statistics_during_period` for the two source entities, in kWh, requesting the
`change` column. An hour the source did not report is zero. This replaces the
bucket store: a price period is a range of hours, so the energy recorded under
each set of prices is the sum of the hours it spans, exactly, and a backdated
price simply moves hours from one range to another.

The settlement engine stays as it is. It already takes a per-segment shape,
and the hourly series gives it the real per-segment quantities instead of a
shape, so `consumption_by_segment` and `feed_in_by_segment` become exact.

Cost is allocated to hours chronologically: the cost of an hour is the bill
after that hour less the bill before it. Hours sum to the invoice by
construction. Under szaldó an hour in which export cancels earlier import is a
negative cost, which is the truth of netting and the dashboard renders it as
such. The alternative, spreading the period's final charge over hours in
proportion to energy, also reconciles but rewrites the entire year on every
refresh and says nothing about when a cost arose. The allocation is pure
arithmetic over a series and belongs in `src/hass_energy/billing`, where it is
tested without Home Assistant and vendored like the rest of the engine.

Two external statistics carry the result, named by the entry like the
invoice-import statistics already are: `hass_energy:<entry>_grid_cost` and
`hass_energy:<entry>_export_compensation`. Each row is an hour's cost added to
a running sum, in Home Assistant's configured currency, because that is what
the dashboard labels costs in. The sum may fall; the dashboard reads changes.
The user points the grid consumption and return sources at these through the
dashboard's "entity tracking the total costs" option.

Recomputation runs on the recorder's hourly-statistics event, on an options
change, on seeding, and on closing a settlement. Each run reads the period's
hourly energy, derives the per-hour cost for the whole period, compares it
with the rows already written, and writes only the rows that differ. In normal
operation that is the latest hour; after a price edit it is every hour from
the edited date; after a repair on the Statistics page it is every hour from
the repaired one. A year of hourly rows for two sensors is around eighteen
thousand rows, read in one executor job, which is cheap once an hour.

The live entities keep their meaning but change their source: the bill they
publish is the hourly model, so Total payable lags the meter by up to an hour.
That is the lag the dashboard beside it already has, and the figures these
entities answer for — how much allowance is left, what the supplier will owe —
do not turn on the last hour. Should the lag ever matter, the current hour can
be filled from the recorder's five-minute statistics through the same query
with a different period; it must not be filled from the source sensors'
states, which would bring back a second record with its own rules. The two
running-total sensors added for the dashboard become redundant and are
retired; see the migration.

Closing a settlement becomes a date. The new period's energy is the hours from
the reading date onward, which the recorder already has, so nothing is carried
over and nothing is lost between the reading and the day it is entered. The
cost statistics continue under the same ids; the period boundary is visible as
the running bill starting again from the standing-charge-free zero.

Seeding shrinks to its real job. If the sources were recorded at the period
start, there is nothing to seed: the period is read from history. If the
recorder's history begins after the period start, the seeded totals less the
observed totals is the energy nobody watched, and it is spread by day across
the unobserved hours, as seeding spreads it today. Only that remainder and the
period start are stored, in a storage version 2 that the migration writes.

What goes away: the bucket store, the movement rules, the step-limit option,
the adjust action, the carry-over at close. Reset and dip detection are the
recorder's, and an outlier is corrected where Home Assistant already offers to
correct it. The source-missing repair stays; a source that is not recorded at
all becomes a new repair, since the integration can no longer see it.

## Edge cases

Hours and days. Statistics rows start on UTC hours; price periods start on
local midnights. Hungary's offset is a whole number of hours in both summer
and winter time, so every local midnight is a row boundary and a price period
is an exact set of rows. Daylight-saving transitions keep hour alignment; the
days around them are 23 or 25 rows long, which the day-based allowance does
not notice because it counts days, not hours.

Units. The statistics API converts to the requested unit, so a source in Wh or
MWh is read in kWh without the integration knowing.

Gaps. An hour without a row is an hour the source did not report. It costs
nothing and is not an error; the source-missing repair already covers a source
that has gone quiet.

Rounding. Hourly costs are kept unrounded. The invoice rounds totals and the
surplus per price period, and the live entities keep doing that; rounding
every hour would drift from both.

Sum semantics. External statistics need a sum per row, which is the cumulative
cost since the first row ever written. Negative hours make it fall. The energy
dashboard draws the hourly change and is indifferent to the sum's direction;
Tibber's profit statistic behaves the same way.

Retention. Long-term statistics are not purged, so the period can be read for
as long as the sources have existed. A source renamed in the entity registry
keeps its statistics under the new id; a source replaced by a different entity
is a configuration change, as it is today.

Entry removal. `clear_statistics` removes the two cost statistics when the
entry is removed, so a deleted metering point does not leave orphaned rows the
dashboard still offers.

## Migration

The change is made in four releases, each leaving the previous one's entities
working, so a user can move the dashboard across at their own pace.

Reading beside recording. The hourly reader and the cost writer are added
alongside the bucket store. Both models run; the diagnostics report both
totals, so any divergence between the recorded and the observed period is
visible before anything depends on it. The two external statistics appear in
the dashboard's selector at once. The running-total sensors keep working.

Switching the source. The live entities are derived from the hourly model. On
the first start of this version, the stored
buckets are reconciled against the recorder: observed energy since the period
start is read from statistics, and whatever the store holds above that is kept
as the unobserved remainder, spread by day across the hours before the
recorder's history begins. The store is rewritten in version 2 holding only
the period start and that remainder. The step-limit option and the adjust
action remain but no longer affect the bill; the adjust action corrects the
remainder only, and its description says so.

Retiring the record. The bucket store, the movement rules, the step-limit
option and the adjust action are removed. The option is dropped from existing
entries by the entry migration. The running-total sensors are kept one more
release with a repair issue naming the two statistics to switch the dashboard
to, because an entity that silently disappears from a dashboard source is
worse than one that asks to be replaced.

Removing the sensors. The running-total sensors go, and the repair with them.

Each release carries its tests. The engine's allocation over a series is
tested in `tests/` without Home Assistant. The reader and writer are tested in
`tests/integration` against the recorder fixture, which compiles real
statistics from states set in the test, with the hourly event fired by hand.
The migration is tested by setting up an entry with a version 1 store and a
recorder holding part of the period, and checking the remainder that comes
out.

## Settled questions

Whether the dashboard's cost selector lists external statistics. It does. In
the frontend's `dialog-energy-grid-settings.ts`, the "entity tracking the
total costs" option for both consumption and return is an `ha-statistic-picker`
with no filter at all, bound to `stat_cost` and `stat_compensation`. That
picker fills itself from `recorder/list_statistic_ids`, which returns every
statistic the recorder knows regardless of source, and shows an id with a
colon and no period as an external statistic labelled with its domain. The
energy component's validation accepts any cost statistic it has metadata for
and only inspects state class and unit when the id is an entity. Tibber has
documented its `tibber:energy_totalcost_*` and `tibber:energy_profit_*`
statistics as dashboard cost sources for years, which covers the Home
Assistant versions this integration supports. Checked against the frontend's
development branch on 11 October 2026.

Whether to keep a live tail from the source sensors' states. No. The only
place the figure is read beside anything else is the dashboard, which is an
hour behind in any case, and a state-driven tail is a second record of energy
with its own reset and glitch rules, which is the thing this plan removes. If
the lag is ever felt, the five-minute statistics fill the current hour through
the same code path.

Whether the generator's packages should follow. Not as part of this. The
dashboard's individual-devices section reads each device's own energy
statistics and shows no cost per device, so there is nothing for per-device
cost statistics to feed. What the generator adds — cost per device, split by
price band — is only visible in its own entities, and the utility meters
behind them are corrected with `utility_meter.calibrate`, which Home Assistant
already provides. The meters' weaknesses are real but have a remedy; the
integration's record had none.
