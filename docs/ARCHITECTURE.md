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

Device and unmonitored costs are priced at the *marginal* rate — what that
energy costs right now — rather than the average. This answers "what does
running this cost me", but it means figures rise once the allowance is
exhausted, and they are only exact at settlement. `pricing.yaml` also publishes
the average price for the period for comparison.

House consumption is grid import less export plus local production, so it
reflects what the house used rather than what it bought. Whatever the monitored
devices do not account for is reported as unmonitored.
