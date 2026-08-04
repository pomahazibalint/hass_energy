# hass_energy

Generator-driven Home Assistant energy accounting for households billed on an
annual settlement, with Hungarian A1 tariff support.

You describe the household once — the grid sensors, the devices worth watching,
the tariff — and the generator writes the Home Assistant packages: utility
meters, banded pricing, per-device cost, house totals, and the automation that
rolls the settlement period over.

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

devices:
  - id: heat_pump
    entity: sensor.heat_pump_energy
    name: Heat pump
    room: Utility room
    category: heating
```

## What gets generated

| File | Contents |
| --- | --- |
| `utility_meters.yaml` | A meter per grid flow and per device, for every cycle |
| `pricing.yaml` | Billed energy split into price bands, unit prices, settlement cost |
| `device_costs.yaml` | Per-device cost at the marginal rate |
| `house_totals.yaml` | House consumption, monitored vs unmonitored energy and cost |
| `settlement.yaml` | Automation resetting the settlement meters on the billing date |

Generated files carry a header saying so. They are artifacts: edit the
configuration or the generator, never the output.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for how generation works and
[docs/PLAN.md](docs/PLAN.md) for where the project is going.
