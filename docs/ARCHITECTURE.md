# Architecture

This project generates Home Assistant YAML packages for household energy
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

## Verifying against a running instance

Nothing offline can tell whether `sensor.grid_import_energy` is a real entity or
a typo. `hass-energy validate --home-assistant URL` asks the instance, reading
its states over the REST API and reporting configured sources it does not have.
The token comes from `--token` or `$HASS_TOKEN`.

Continuous integration goes the other way and validates the generated YAML
against Home Assistant's own schemas with `hass --script check_config`. Note
that command exits 0 even when it rejects a configuration, so the workflow
inspects its output rather than its status.
