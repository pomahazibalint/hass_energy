# hass_energy

Generator-driven Home Assistant energy accounting for households billed on an
annual settlement, with Hungarian A1 tariff support.

You describe the household once — the grid sensors, the devices worth watching,
the tariff — and the generator writes the Home Assistant packages: utility
meters, banded pricing, per-device cost, house totals, and the automation that
rolls the settlement period over.

## Two halves

**The integration** (`custom_components/hass_energy`) records what the meters
did and works out what the supplier will charge for it: netting, price bands,
the standing charge, VAT, and feed-in bought back at a fraction of what the
same kWh costs. It exists because a settlement period is bounded by a meter
reading rather than a date, and prices change inside one — neither of which a
template sensor can hold.

**The generator** (`src/hass_energy`) writes Home Assistant YAML packages for
per-device metering and attribution: utility meters, device costs, house
totals, diagnostics and projections.

They share a settlement engine and can be used separately.

## Installing the integration

Requires Home Assistant 2026.5 or newer.

Via HACS, as a custom repository: add this repository's URL with category
**Integration**, download it, and restart Home Assistant. Or by hand, copy
`custom_components/hass_energy` into your Home Assistant `config` directory and
restart. Either way, add it from **Settings > Devices & services > Add
integration > Energy Settlement**.

It needs nothing installed at runtime: the settlement engine ships inside the
component.

The settlement is read from Home Assistant's long-term statistics for the
import and export meters, so the sources must be recorded with a total state
class. Installed part-way through a settlement period, run the **Seed the
settlement period** action with the figures from your last invoice; only what
the recorder does not already hold is kept. Past invoices can be brought in
with **Import a settled invoice**, which records them as long-term statistics.
A wrong meter reading is repaired where Home Assistant repairs any statistic,
on the Developer tools Statistics page, and the settlement follows.

For Home Assistant's energy dashboard, set the grid consumption and return
sources to **use an entity tracking the total costs** and pick the
**grid cost** and **export compensation** statistics the integration writes.
They follow the bill exactly, hour by hour, so the hours add up to the invoice
and a correction rewrites history rather than spiking; under szaldó an hour of
export that cancels earlier import shows as a negative cost. **Current unit
price** and **Current feed-in price** serve the dashboard's price option
instead, which is only a true figure under gross settlement.

The solar and battery sources named in the dashboard's settings are read from
there. From them the integration publishes **house consumption** and
**self-consumed solar** statistics, and a **Solar value** sensor and
statistic: what the bill would have been without the panels, less what it is.
A repair issue reports hours in which more energy left the house than entered
it, which is a source reporting in the wrong hour; the native dashboard reads
the same rows and overstates consumption by the same amount without saying
so.

What consuming cost is published too, as a **consumption cost** statistic
and sensor: what each hour would have saved had nothing been consumed in it,
which is the band price while a kWh would have netted and the feed-in price
beyond that, and under gross settlement depends on whether the grid or the
panels supplied it. It is a marginal figure and does not add up to the
invoice; the grid cost statistic does that. The devices named in the
dashboard's settings each get a **cost** statistic and sensor, their share
of each hour's consumption at that hour's cost, named as the dashboard names
them. A device meter that claims more than the whole house used is capped
there and reported through the same repair.

The integration brings its own dashboard. Create it from **Settings >
Dashboards > Add dashboard**, where **Energy settlement** is listed among
the custom dashboards; it builds itself from your metering points and needs
no configuration. It has three views. **Settlement** is the invoice beside
the outlook: the projections, and the solar and battery figures. **Usage**
is the native energy cards for the selected range, the usage graph, the
distribution or sankey, the solar graph, the gauges, the sources table and
the device graphs, beside the integration's own figures and a table of
energy and cost per device over the settlement period with the rest of the
house. **History** is each grid meter and the house by calendar month, this
year over the two before it, and past settlements. The integration and the
dashboard are in English and Hungarian, following your Home Assistant
language.

Where the period is heading is projected along last year's shape: the
remaining days follow the same days a year earlier, scaled by how this
period compares to them, and fall back to the straight line of this period
where last year is silent. **Projected total payable**, **Projected billed
energy** and **Allowance runs out** come from settling those days through
the same engine; the date is unknown when the allowance holds. A **Battery
what-if** in the options, a capacity and a round-trip efficiency, gives a
**Battery saving under gross settlement** sensor: what a battery the house
does not have would have saved, priced under gross terms whatever the
settlement mode, since under szaldó annual netting already is a free
battery.

## Quick start

```sh
uv sync --extra dev
uv run hass-energy generate --config examples/config.yaml --output examples/packages
```

Point it at your own configuration and write straight into Home Assistant:

```sh
uv run hass-energy generate --config config.yaml --output /config/packages
```

Then load the packages, once, in `configuration.yaml`, and restart:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

The generated YAML uses `default_entity_id` on template sensors and the current
automation syntax (`triggers:`/`conditions:`/`actions:`), so a recent Home
Assistant is required. An older instance rejects the packages at startup with a
configuration error rather than loading them incorrectly.

## Commands

| Command | Purpose |
| --- | --- |
| `hass-energy generate --config C --output D` | Write the packages into `D` |
| `hass-energy generate ... --check` | Fail if `D` is out of date; changes nothing |
| `hass-energy validate --config C` | Check that a configuration loads and can generate |
| `hass-energy validate ... --home-assistant URL` | Also confirm the source entities exist |

The instance check reads entity states over the REST API and needs a long-lived
access token, from `--token` or `$HASS_TOKEN`:

```sh
HASS_TOKEN=... uv run hass-energy validate --config config.yaml \
  --home-assistant http://homeassistant.local:8123
```

`--check` exists for continuous integration: generated packages are committed to
the repository, so a generator change without a regeneration has to fail.

## Configuration

See [`examples/config.yaml`](examples/config.yaml) for a complete, commented
example. The shape is:

```yaml
project_name: hass_energy   # prefixes every generated entity id

billing:
  settlement_month: 3       # the settlement period runs from this date
  settlement_day: 15
  pricing:
    subsidized_limit_kwh: 2523
    subsidized_price: 36.386
    unsubsidized_price: 70.104
    currency: Ft

solar:
  annual_net_metering: true # export offsets import before the bands apply

grid:
  import_entity: sensor.grid_import_energy      # required
  export_entity: sensor.grid_export_energy      # optional
  production_entity: sensor.solar_production_energy  # optional

meters:
  cycles: [daily, monthly]  # a settlement meter is always generated too
  net_consumption: false    # utility_meter options, applied to every meter
  delta_values: false
  always_available: false

diagnostics:
  stale_after_hours: 6            # a source quiet this long counts as stopped
  unmonitored_warning_percent: 40 # unattributed share worth looking at

devices:
  - id: heat_pump
    entity: sensor.heat_pump_energy
    name: Heat pump
    room: Utility room
    category: heating
  - id: server
    entity: sensor.server_energy
    cycles: [monthly]       # overrides the project cycles for this device
```

Source sensors must be **cumulative energy in kWh** (`state_class:
total_increasing`), not power. Every meter starts at zero on first run — Home
Assistant does not backfill history — so seed the settlement meters with
`utility_meter.calibrate` if you install mid-period.

## What gets generated

| File | Contents |
| --- | --- |
| `utility_meters.yaml` | A meter per grid flow and per device, for every cycle |
| `pricing.yaml` | Billed energy split into price bands, unit prices, settlement cost |
| `device_costs.yaml` | Per-device cost, exact per band over the settlement period |
| `house_totals.yaml` | House consumption, monitored vs unmonitored energy and cost |
| `settlement.yaml` | Automations resetting the settlement meters and following the price band |
| `diagnostics.yaml` | Whether the accounting is still telling the truth |
| `projections.yaml` | Where the settlement period lands at the current rate |

Generated files carry a header saying so. They are artifacts: edit the
configuration or the generator, never the output.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for how generation works and
[docs/PLAN.md](docs/PLAN.md) for where the project is going.
