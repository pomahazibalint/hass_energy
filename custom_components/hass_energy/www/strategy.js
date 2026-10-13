// The dashboard strategy: builds the dashboard's configuration in the
// browser when it is opened, from the integration's entries, their entities
// and the statistics they wrote. Nothing is stored; the user creates the
// dashboard from the new-dashboard dialog and owns it like any other.
//
// A strategy is a custom element named ll-strategy-dashboard-<name> with a
// static generate(); the entry in window.customStrategies is what makes the
// new-dashboard dialog offer it.

const DOMAIN = "hass_energy";

class HassEnergyDashboardStrategy {
  static noEditor = true;

  static getCreateSuggestions() {
    return { title: "Energy settlement", icon: "mdi:receipt-text-outline" };
  }

  static async generate(config, hass) {
    const [entries, registry, statistics] = await Promise.all([
      hass.callWS({ type: "config_entries/get", domain: DOMAIN }),
      hass.callWS({ type: "config/entity_registry/list" }),
      hass.callWS({ type: "recorder/list_statistic_ids" }),
    ]);
    const loaded = entries.filter((entry) => entry.state === "loaded");
    const views = [];
    loaded.forEach((entry, index) => {
      views.push(...viewsFor(entry, registry, statistics, index, loaded.length > 1));
    });
    if (!views.length) {
      views.push({
        title: "Energy settlement",
        cards: [
          {
            type: "markdown",
            content:
              "No Energy Settlement metering point is set up. Add one under " +
              "Settings > Devices & services, and this dashboard fills itself.",
          },
        ],
      });
    }
    return { views };
  }
}

// One metering point's entities, by the line of the settlement each is.
function entitiesOf(entry, registry) {
  const byLine = {};
  const devices = [];
  for (const entity of registry) {
    if (entity.platform !== DOMAIN || entity.config_entry_id !== entry.entry_id) continue;
    if (entity.disabled_by) continue;
    if (entity.translation_key === "device_cost") {
      devices.push(entity.entity_id);
    } else if (entity.translation_key) {
      byLine[entity.translation_key] = entity.entity_id;
    }
  }
  return { byLine, devices };
}

// The statistic of one kind the entry wrote, if it has.
function statisticOf(entry, statistics, kind) {
  const suffix = `_${kind}`;
  const match = statistics.find(
    (one) =>
      one.source === DOMAIN &&
      one.statistic_id.startsWith(`${DOMAIN}:`) &&
      one.statistic_id.includes(entry.entry_id) &&
      one.statistic_id.endsWith(suffix)
  );
  return match?.statistic_id;
}

function viewsFor(entry, registry, statistics, index, several) {
  const { byLine } = entitiesOf(entry, registry);
  const suffix = index ? `-${index + 1}` : "";
  const prefix = several ? `${entry.title}: ` : "";
  const present = (lines) => lines.map((line) => byLine[line]).filter(Boolean);
  const graph = (title, kinds) => {
    const ids = kinds.map((kind) => statisticOf(entry, statistics, kind)).filter(Boolean);
    return ids.length
      ? [
          {
            type: "statistics-graph",
            title,
            entities: ids,
            stat_types: ["change"],
            chart_type: "bar",
            period: "day",
            energy_date_selection: true,
          },
        ]
      : [];
  };

  const bill = {
    title: `${prefix}Bill`,
    path: `bill${suffix}`,
    icon: "mdi:receipt-text-outline",
    cards: [
      {
        type: "custom:hass-energy-bill-card",
        title: entry.title,
        entities: Object.fromEntries(
          Object.entries(byLine).filter(([line]) => BILL_LINES.includes(line))
        ),
      },
    ],
  };

  const usage = {
    title: `${prefix}Usage`,
    path: `usage${suffix}`,
    icon: "mdi:chart-bar",
    cards: [
      { type: "energy-date-selection" },
      { type: "energy-usage-graph" },
      { type: "energy-distribution" },
      ...graph("House consumption", ["house_consumption", "self_consumed_solar"]),
      ...graph("Consumption cost and solar value", ["consumption_cost", "solar_value"]),
    ],
  };

  const outlook = {
    title: `${prefix}Outlook`,
    path: `outlook${suffix}`,
    icon: "mdi:chart-timeline-variant",
    cards: [
      {
        type: "entities",
        title: "Where the period is heading",
        entities: present([
          "projected_total_payable",
          "projected_billed_energy",
          "allowance_runs_out",
          "allowance_remaining",
          "period_days",
        ]),
      },
      {
        type: "entities",
        title: "Solar and battery",
        entities: present([
          "solar_value",
          "self_consumed_solar",
          "house_consumption",
          "consumption_cost",
          "battery_saving",
        ]),
      },
    ].filter((card) => card.entities.length),
  };

  return [bill, usage, outlook];
}

const BILL_LINES = [
  "energy_cost",
  "solar_value",
  "surplus_value",
  "standing_charge",
  "vat",
  "total_payable",
  "net_position",
  "allowance_remaining",
  "period_days",
];

customElements.define("ll-strategy-dashboard-hass-energy", HassEnergyDashboardStrategy);
window.customStrategies = window.customStrategies || [];
window.customStrategies.push({
  type: "hass-energy",
  name: "Energy settlement",
  description: "The settlement as an invoice, what the house used, and where the period is heading.",
  documentationURL: "https://github.com/pomahazibalint/hass_energy",
  strategyType: "dashboard",
});
