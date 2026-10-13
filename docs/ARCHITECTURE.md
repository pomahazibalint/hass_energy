# Architecture

The repository holds two deliverables that share a domain.

`src/hass_energy` is the generator, which writes Home Assistant YAML packages,
plus `src/hass_energy/billing`, a settlement engine that imports nothing from
Home Assistant and is checked against real invoices.

`custom_components/hass_energy` is a Home Assistant integration that records
meter quantities and derives the settlement from them. It exists because two
things the invoices showed cannot be expressed in generated YAML: prices that
change inside a settlement period, and a period boundary set by a meter reading
rather than a date. Both need somewhere to keep state.

The engine has one consumer, the integration, and the integration has to be
self-contained: Home Assistant installs a custom component by copying a single
directory, and anything declared in `manifest.json` requirements is
pip-installed when the entry sets up — a network round-trip at startup and a
way for the integration to fail to load entirely.

So the engine is vendored into `custom_components/hass_energy/billing`, and
that copy is an artifact in exactly the sense the generated packages are:
source of truth in `src`, copy committed so it ships, and a check that the two
have not drifted. `scripts/vendor_billing.py` writes it, `--check` fails when
it is stale, and both the test suite and the workflow run that check. Each
copied file says it is one.

Keeping the source in `src` is what lets the engine be tested in about a
second, against two dependencies, on every supported Python. Moving it into the
component would have made its tests require a Home Assistant install — a poor
trade for the code that most needs a fast feedback loop.

## The generator

This half generates Home Assistant YAML packages for household energy
accounting.

Goals:
- Single device inventory
- Generated utility_meter, template and dashboard YAML
- Hungarian A1 tariff support
- Extensible tariff engine

## Shape of the code

| Module | Responsibility |
| --- | --- |
| `config.py` | The configuration as a user writes it. The source of truth. |
| `loader.py` | Reads YAML into a `ProjectConfig`, reporting every failure as `ConfigurationError`. |
| `naming.py` | Builds every generated object id and entity id. |
| `generator/` | Turns a `ProjectConfig` into rendered package files. |
| `output.py` | Writes packages to disk and reports drift. |
| `cli.py` | `generate` and `validate`. |

Generation is a pure function of the configuration: `generate(config)` returns
rendered files and touches nothing. Everything that reaches the filesystem does
so through `output.py`, which keeps the generators trivially testable.

## Adding a package

A generator subclasses `Generator`, declares a `filename` and a `description`,
and implements `build()` returning plain Python data. Rendering, the generated
file header and file naming are handled by the base class, so every generated
file looks the same. Register it in `GENERATORS`.

Packages are built as data and serialised by PyYAML rather than rendered from
text templates. The structure of the YAML is then guaranteed by the serialiser,
and Home Assistant's own Jinja templates — which are string *values* inside that
structure — never meet a second templating layer. `generator/templates.py`
composes those expressions from helpers so each recurring one has one spelling.

## Entity wiring

Generators read each other's output: device costs need the price sensor, house
totals need the device meters. `generator/entities.py` derives every generated
entity id from the configuration, so no generator spells another's entity id by
hand and a rename lands in one place.

Every id is prefixed with the slugified `project_name`, which keeps a generated
package from colliding with anything else in a Home Assistant instance.

The two integrations pin entity ids differently, and both are pinned on
purpose. A `utility_meter` takes its entity id from the object key it is
configured under, so its `name` is free to be readable. A template sensor
instead slugifies its `name`, which no other generated package could predict,
so every generated template sensor sets `default_entity_id` to
`sensor.<unique_id>`. `tests/test_generator.py` asserts that every entity a
generated template reads is either a configured source sensor or an entity the
generator itself creates.

## Determinism

Identical configuration produces byte-identical files. Nothing carries a
timestamp, a hostname or a random value, and ordering follows the configuration
rather than set iteration. `generate --check` compares the output directory
against a fresh render and fails on drift, which is what CI runs.

`output.py` leaves unchanged files untouched so their timestamps keep reflecting
the last real change, and removes files it previously generated that the
configuration no longer produces. Files without the generated header are never
touched.

## Settlement period

Home Assistant's `utility_meter` yearly cycle always resets on 1 January, and
its `offset` is capped well below a month, so a settlement period starting on
any other date cannot be expressed as a cycle. The settlement meters are
therefore generated without a cycle and calibrated back to zero by the
automation in `settlement.yaml`, which fires on the billing anniversary.

## Pricing model

Within a settlement period, consumption up to the subsidized allowance is billed
at the subsidized price and the remainder at the market price. Under annual net
metering, exported energy offsets imported energy before the bands are applied.

`sensor.<prefix>_price_band` is the only place the allowance is compared against
consumption. The marginal price sensor reads it, and the automation in
`settlement.yaml` mirrors it into the meter tariffs, so nothing can disagree
about which band is active.

Each device's settlement meter is configured with the bands as `utility_meter`
tariffs, so energy accumulates into whichever band was active when it was used
and the settlement cost is exact — no retroactive change when the allowance runs
out. Shorter cycles are not split: the band changes at most once a settlement
period, so splitting every cycle would multiply entities to record a distinction
that is almost always empty. Their cost uses the price in force, which differs
from the billed amount only across the single day the allowance runs out.

House consumption is grid import less export plus local production, so it
reflects what the house used rather than what it bought. Whatever the monitored
devices do not account for is reported as unmonitored. Over a settlement period
the billed total is known exactly, so unmonitored cost is the remainder rather
than an estimate; over a shorter cycle there is no billed figure to divide up
and the remainder is priced at the current rate.

## Entity lifecycle

Entity ids are the join between a generated package and the history Home
Assistant has recorded against it. Renaming the project or a device changes
them, and the old entities keep their history with nothing writing to it.

Each run records the entity ids it produced in `.hass-energy-manifest.json` in
the output directory — hidden and not YAML, so the package include ignores it.
The next run diffs against it and reports anything that disappeared, along with
how to migrate. A manifest that cannot be read is treated as absent: it exists
to report renames and must never block a regeneration.

## Diagnostics and projections

Everything else in this project answers what the household used and what it
cost. Two packages answer different questions.

`diagnostics.yaml` asks whether the accounting is still true. A source sensor
that vanishes, one that holds a plausible value but stopped updating, a tariff
select left behind by a missed automation, or consumption no device accounts
for all leave the cost sensors reporting confident, wrong numbers. Each is a
`problem` binary sensor, so Home Assistant surfaces them without a dashboard.

`projections.yaml` extrapolates the settlement period from the rate so far: the
energy and cost it lands on, and the date the allowance runs out. The value of
a banded tariff is knowing before the year ends whether the allowance will
hold. It is a straight-line estimate, so it is least reliable early in the
period and across a change of season. The exhaustion date reports unknown
rather than a fabricated date when consumption is not on course to reach the
limit at all.

Both are prerequisites for the dashboards: an executive view needs the
projection, and a diagnostics view needs the problem entities.

## The integration

Nothing about energy is stored. The settlement period is a start date over the
recorder's long-term statistics for the import and export meters: the recorder
compiles an hourly sum for every energy sensor with a total state class,
applies its own reset and dip detection, keeps the rows indefinitely and lets a
user repair an outlier from the Statistics page. Reading those rows gives
per-hour energy for the whole period, including hours before the integration
was installed, as long as the sensors were recorded. Every figure with a
currency on it is derived from them on demand.

That is what makes the contract editable. A corrected price, a switched
allowance basis or a changed standing charge re-values the same hours instead
of contradicting them, and a price backdated into the period applies to the
hours after its date, because the hours are known. Storing energy would have
made the first a migration and the second a guess.

Prices are edited as "these are the prices in force from this day". Leaving the
date at today is a change; setting it back is a correction noticed late. The
same form covers both, and submitting a day that already has prices replaces
them rather than adding a second row.

The settlement period runs to a nominal year until a meter reading ends it,
because the allowance is annual: prorating it to the days elapsed would report
a household as over its allowance a week into a period it will finish
comfortably inside. A period that has run past the year stretches to cover
today, so every hour recorded has a price period to fall in. `close_settlement`
takes the reading date and starts the next period there; the hours since the
reading are in the recorder whenever the reading is entered, so nothing is
carried over by hand and nothing is lost.

A settlement period that is already under way when the integration is installed
is adopted with the `seed_period` action, from the last invoice and the current
meter. Whatever the recorder already holds for the period is not seeded twice:
only the part above the statistics is kept, as the unobserved remainder, and
laid over the hours before the recorder's history begins, because the shape of
energy nobody observed is unknowable. If the sources were recorded all along,
there is nothing to keep and the period is simply read from history. The
remainder and the period start are the whole of what is stored.

Past invoices go in through `import_invoice`, which writes them to the recorder
as external statistics. Home Assistant never saw those years, so nothing else
can supply them, and without it a fresh install has no history at all.

Problems are repair issues rather than binary sensors: a price schedule that no
longer reaches the start of the period, a settlement running far past a year
with no reading recorded, a source the recorder has had nothing from for
days, a source the recorder has no statistics for. The checks run on every
refresh, which follows the recorder's hourly compile, so they cannot describe
a state the integration has already left. A schedule that cannot price the
period makes the entities unavailable rather than reporting zero — unvaluable
is not the same number as nothing. A source is judged by its statistics and
never by its live state: an inverter's sensors are unavailable every night,
and the settlement reads the recorder, which has the inverter's day.

The entities lag the meter by up to an hour, the lag the dashboard beside them
already has. The figures they answer for — how much allowance is left, what the
supplier will owe — do not turn on the last hour.

Home Assistant's own energy dashboard values each hour's energy at a price and
sums the hours. Under szaldó no price can make that come out right: a kWh's
worth depends on what the meters do months later, so any per-kWh valuation is
order-dependent and does not reconcile with the invoice. `unit_price` and
`feed_in_price` exist for the dashboard's price option anyway, and are honest
under gross settlement.

What to point the dashboard at instead are two external statistics,
`hass_energy:<entry>_grid_cost` and `hass_energy:<entry>_export_compensation`,
through its "entity tracking the total costs" option. The bill is allocated
to hours chronologically: an hour's cost is the bill after it less the bill
before it, so the hours sum to the invoice by construction, and an hour in
which export cancels earlier import is a negative cost, which is the truth of
netting. A row written for an hour that already has one replaces it, so a
backdated price or a repaired reading rewrites history rather than appearing
as a spike in the hour of the correction. Only hours the recorder saw are
published: the seeded remainder is in the bill, and in the netting position
every later hour is costed against, but a flat smear of cost over months
nobody watched would read as something that happened. The statistics carry
Home Assistant's configured currency, which is what the dashboard labels
costs in, and the standing charge is left out: it is owed however the meters
move. The running-total sensors that preceded them are gone: an install
upgrading from the release that retired them has their registry entries and
the repair that named their successors removed at setup.

The household's other sources come from the energy dashboard's own
preferences, the document in which the user names a statistic for each flow,
so a solar or battery source is named once, in the native settings, and
never asked for again. They belong to the metering point whose import meter
the dashboard's grid source names, so a second entry for a heat pump on its
own tariff is not credited with panels that never fed it. They are read only
where the grid record exists, and the house's figures run from the first
hour every one of them covers: before that the house's flows are
unknowable, not zero, and the house's sensors are unavailable.
They do not touch the bill. They say what the house
used, import plus production plus battery discharge less export less charge,
and how much of its own generation it kept, both published as statistics the
dashboard's cards can draw. An hour in which more energy left the house than
entered it cannot have happened, so it is a source reporting in the wrong
hour; the figure is published as zero and a repair names the hours and what
they lost, because the native dashboard reads the same rows and overstates
consumption by the same amount without saying so. What the panels were worth
is the bill there would have been without them: the same hours with the
kept production bought from the grid instead, settled by the same engine,
which is the only way to value them under szaldó. A figure whose sources
the household lacks is unavailable, and the statistics it would have had
are removed when the source is dropped.

What consuming cost is a different question from what the bill was, and the
two are kept apart. The cost statistics reconcile to the invoice; the
consumption cost is marginal, what each hour would have saved had nothing
been consumed in it, with the grid's share of the hour not imported and the
rest exported instead, and every earlier hour as it was. One rule serves
both settlement modes: under szaldó a kWh not consumed nets whichever way
it goes, and under gross settlement a grid kWh saves the band price while a
solar kWh earns only the feed-in price, which is the time-of-day effect of
a tariff that buys back cheaply. The engine answers it with a second walk
of the ledger the allocation uses, pricing each hour against an alternative
for that hour alone. The dashboard's devices, read from the same
preferences, are each costed at their share of the hour's consumption at
that price, so a device that runs at noon on the panels and one that runs
at night on the grid are told apart. Their statistics and sensors come and
go with the preferences, and a device that claims more than the whole house
used is capped there and reported through a repair of its own, naming the
device, because a meter that books a session in the hour it ends is a
different finding from a house whose sources disagree.

The period is projected along last year's shape rather than a straight
line, because a straight line is least reliable across a change of season,
which is when knowing whether the allowance will hold matters most. The
remaining days are the same calendar days a year earlier, read from the
recorder's daily statistics, scaled per meter by this period's complete days
against theirs; a day last year knows nothing about is the straight line of
this period, so a first year gets what the generator's projection gives and
nothing worse. The projected days settle through the same engine as the
hours, which is what gives the projected bill and the date the allowance is
gone for good, unknown when it holds. The battery what-if is the one
counterfactual that adds nothing to the reader: an optional capacity and
efficiency turn the real hours into the hours a battery would have left, and
both are priced under gross settlement whatever the entry's mode, because
under szaldó annual netting is a free battery and the question is what the
switch will cost.

The dashboard is the integration's own, and it is a strategy: a JavaScript
module that builds the dashboard's configuration in the browser when it is
opened, from the integration's entries, their entities and the statistics
they wrote, so nothing about the dashboard is stored and a second metering
point is a second set of views. The user creates it from Home Assistant's
new-dashboard dialog, which lists the strategy, and owns it like any other;
the integration creates no dashboard and touches no Lovelace internals. The
modules live in `www`, are served through the HTTP component's static paths
under a URL that carries the version, and are loaded through the frontend's
extra module hook, which works in both resource modes without an entry in
the resources list. They are plain modules without a framework or a build
step, for as long as the cards stay thin: the figures they show are tested
in the backend, and the workflow checks that each module parses.

Testing needs Home Assistant, so those tests live in `tests/integration` and run
in the workflow job that installs it. They put hours into the recorder directly
and run on a frozen clock. The engine's own tests need nothing and run
everywhere. The frontend package is installed there too, because the
integration depends on the frontend component for the dashboard it serves.
That job must run on the Python the newest Home Assistant needs and nothing
older: pinning an older Python there silently pins the last Home Assistant
that supported it, which is how a change to the energy preferences' shape
went unnoticed for months while the build stayed green. The household's
other sources are read inside a guard for the same reason; a document the
integration does not understand costs the house's figures, not the bill.

## Releasing

Three places carry the version, and HACS reads two of them for different
purposes: `manifest.json` is what it treats as installed, the release tag is
what it treats as available. Tag a release without bumping the manifest and
HACS offers an update forever — it downloads, finds the old version still
there, and offers it again. `scripts/check_version.py` fails when they part
company, in the test suite on every run and in the workflow on every tag.

The check alone would only find that out afterwards, though, because HACS reads
GitHub releases and continuous integration runs after a tag is pushed. So the
release is not made by hand: the workflow creates it, and only once every job
has passed. A tag on its own is invisible to HACS, so a tag pushed with a
failing build offers nobody anything and can simply be deleted.

Releasing is therefore: bump `manifest.json` and `pyproject.toml` together,
commit, tag `vX.Y.Z`, push the tag, and let the workflow publish it. Creating a
release through the GitHub interface bypasses all of this, so don't.

## Verifying against a running instance

Nothing offline can tell whether `sensor.grid_import_energy` is a real entity or
a typo. `hass-energy validate --home-assistant URL` asks the instance, reading
its states over the REST API and reporting configured sources it does not have.
The token comes from `--token` or `$HASS_TOKEN`.

Continuous integration goes the other way and validates the generated YAML
against Home Assistant's own schemas with `hass --script check_config`. Note
that command exits 0 even when it rejects a configuration, so the workflow
inspects its output rather than its status.

A disagreement finding is judged against the recorder's own rows, and
`scripts/inspect_hours.py` prints them for the sources the energy dashboard
names, hour by hour around a given hour, over the websocket API with a
long-lived access token: the change, sum and state of each source, the hours
a source has no row for, and the balance that went negative. It reads the
same rows the integration reads, so it shows what the integration saw.

`check_config` compiles templates but never renders one, and a template that
compiles can still fail on the first state it reads. `scripts/render_check.py`
executes every generated template against a Home Assistant instance holding
plausible states, and unlike `check_config` it exits non-zero on failure.
