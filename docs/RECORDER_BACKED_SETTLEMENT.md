# Recorder-backed settlement

A plan to rebuild the integration's record of energy on Home Assistant's own
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

The live entities keep their meaning but change their source. The bill they
publish is the hourly model plus the current hour's tail, taken from the
source sensors' state since the last compiled hour, so Total payable still
moves as the meter does. The two running-total sensors added for the
dashboard become redundant and are retired; see the migration.

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

Switching the source. The live entities are derived from the hourly model with
the current hour's tail. On the first start of this version, the stored
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

## Open questions

Whether the dashboard's cost selector lists external statistics in every
Home Assistant version the integration supports. Tibber's cost statistics are
selected that way, and the dashboard's validation accepts any statistic id it
has metadata for, but this should be confirmed on a live instance before the
running-total sensors are retired.

Whether to keep a live tail at all. It costs a second code path for a figure
that is at most an hour ahead of the statistics. The argument for it is that a
household watching the allowance run out wants the number now; the argument
against is that the dashboard it stands beside is an hour behind anyway.

Whether the generator's packages should follow. They read utility meters, which
are the same kind of record with the same weaknesses. Reading device energy
from statistics instead would make the per-device attribution correctable the
same way, but it is a separate piece of work with its own plan.
