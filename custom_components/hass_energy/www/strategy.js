// The dashboard strategy: builds the dashboard's configuration in the
// browser when it is opened, from the integration's entries, their entities
// and the statistics they wrote. Nothing is stored; the user creates the
// dashboard from the new-dashboard dialog and owns it like any other.
//
// A strategy is a custom element named ll-strategy-dashboard-<name> with a
// static generate(); the entry in window.customStrategies is what makes the
// new-dashboard dialog offer it.
//
// Three views per metering point, in the sections grid so a wide screen is
// used across: the settlement, with the invoice beside the outlook; usage,
// the native energy cards for the selected range beside the integration's
// own figures and the devices; and history, the long view by month.

import { t } from "./strings.js";

const DOMAIN = "hass_energy";

class HassEnergyDashboardStrategy {
  static noEditor = true;

  static getCreateSuggestions(hass) {
    return { title: t(hass, "suggestion_title"), icon: "mdi:receipt-text-outline" };
  }

  static async generate(config, hass) {
    const [entries, registry, statistics, prefs] = await Promise.all([
      hass.callWS({ type: "config_entries/get", domain: DOMAIN }),
      hass.callWS({ type: "config/entity_registry/list" }),
      hass.callWS({ type: "recorder/list_statistic_ids" }),
      hass.callWS({ type: "energy/get_prefs" }).catch(() => null),
    ]);
    const loaded = entries.filter((entry) => entry.state === "loaded");
    const views = [];
    loaded.forEach((entry, index) => {
      views.push(...viewsFor(entry, registry, statistics, prefs, hass, index, loaded.length > 1));
    });
    if (!views.length) {
      views.push({
        title: t(hass, "suggestion_title"),
        cards: [{ type: "markdown", content: t(hass, "no_entry") }],
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

// The statistics the entry wrote, by kind; the ids are the recorder's, so
// the strategy never reproduces the backend's naming. An entry id is an
// upper-case ULID and a statistic id is its slug, which is lower case.
function statisticsOf(entry, statistics) {
  const slug = entry.entry_id.toLowerCase();
  const own = statistics.filter(
    (one) => one.source === DOMAIN && one.statistic_id.startsWith(`${DOMAIN}:`) && one.statistic_id.includes(slug)
  );
  const ofKind = (kind) => own.find((one) => one.statistic_id.endsWith(`_${kind}`))?.statistic_id;
  const devices = own
    .filter((one) => one.statistic_id.includes(`${slug}_device_`) && one.statistic_id.endsWith("_cost"))
    .map((one) => one.statistic_id);
  return { ofKind, devices };
}

// What the energy dashboard names: the grid meters, in either format, and
// whether there is solar, a battery and devices to show cards for.
function preferencesOf(prefs) {
  const imported = [];
  const exported = [];
  let solar = false;
  let battery = false;
  for (const source of prefs?.energy_sources || []) {
    if (source.type === "grid") {
      imported.push(...(source.flow_from || []).map((flow) => flow.stat_energy_from));
      exported.push(...(source.flow_to || []).map((flow) => flow.stat_energy_to));
      if (source.stat_energy_from) imported.push(source.stat_energy_from);
      if (source.stat_energy_to) exported.push(source.stat_energy_to);
    } else if (source.type === "solar") {
      solar = true;
    } else if (source.type === "battery") {
      battery = true;
    }
  }
  const devices = (prefs?.device_consumption || []).length > 0;
  return { imported, exported, solar, battery, devices };
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

// A section spanning n columns is a grid of 12 n card columns, and a card
// takes 12 unless told otherwise, so a stack of full-width cards has to
// say so; "full" is the section's whole width whatever it spans.
const section = (cards, span) => (span ? { type: "grid", column_span: span, cards } : { type: "grid", cards });
const full = (card) => ({ ...card, grid_options: { columns: "full", ...(card.grid_options || {}) } });
const statisticsGraph = (title, entities, extra = {}) => ({
  type: "statistics-graph",
  title,
  entities,
  stat_types: ["change"],
  chart_type: "bar",
  period: "day",
  energy_date_selection: true,
  ...extra,
});

function viewsFor(entry, registry, statistics, prefs, hass, index, several) {
  const { byLine, devices } = entitiesOf(entry, registry);
  const own = statisticsOf(entry, statistics);
  const named = preferencesOf(prefs);
  const suffix = index ? `-${index + 1}` : "";
  const prefix = several ? `${entry.title}: ` : "";
  const present = (lines) => lines.map((line) => byLine[line]).filter(Boolean);
  const entities = (title, lines) => {
    const ids = present(lines);
    return ids.length ? [{ type: "entities", title, entities: ids }] : [];
  };
  const graph = (title, kinds) => {
    const ids = kinds.map((kind) => own.ofKind(kind)).filter(Boolean);
    return ids.length ? [statisticsGraph(title, ids)] : [];
  };

  const settlement = {
    title: `${prefix}${t(hass, "view_settlement")}`,
    path: `settlement${suffix}`,
    icon: "mdi:receipt-text-outline",
    // Three single columns: a card each, nothing to leave a gap.
    type: "sections",
    max_columns: 3,
    sections: [
      section([
        {
          type: "custom:hass-energy-bill-card",
          title: entry.title,
          entities: Object.fromEntries(Object.entries(byLine).filter(([line]) => BILL_LINES.includes(line))),
        },
      ]),
      ...entities(t(hass, "outlook"), [
        "projected_total_payable",
        "projected_billed_energy",
        "allowance_runs_out",
        "allowance_remaining",
        "period_days",
      ]).map((card) => section([card])),
      ...entities(t(hass, "solar_battery"), [
        "solar_value",
        "self_consumed_solar",
        "house_consumption",
        "consumption_cost",
        "battery_saving",
      ]).map((card) => section([card])),
    ],
  };

  // The native cards share the energy date picker; so do the statistics
  // graphs over the integration's own figures, through its date selection.
  // Two stacked columns rather than a section per card: sections in a row
  // align to the tallest, and a stack has no rows to leave gaps between.
  const gauges = [
    ...(named.solar ? [{ type: "energy-solar-consumed-gauge", grid_options: { columns: 12 } }] : []),
    ...(named.exported.length ? [{ type: "energy-grid-neutrality-gauge", grid_options: { columns: 12 } }] : []),
  ];
  const flows = [
    { type: "energy-date-selection" },
    { type: "energy-usage-graph" },
    ...(named.solar ? [{ type: "energy-solar-graph" }] : []),
    ...graph(t(hass, "house_consumption"), ["house_consumption", "self_consumed_solar"]),
    ...graph(t(hass, "cost_and_value"), ["consumption_cost", "solar_value"]),
    { type: "energy-sources-table" },
  ];
  const shares = [
    ...(named.devices ? [] : [{ type: "energy-distribution" }]),
    ...gauges,
    ...(named.devices ? [{ type: "energy-devices-graph" }, { type: "energy-devices-detail-graph" }] : []),
    {
      type: "custom:hass-energy-devices-card",
      title: t(hass, "devices_period"),
      devices,
      entities: Object.fromEntries(
        Object.entries(byLine).filter(([line]) => ["consumption_cost", "house_consumption"].includes(line))
      ),
    },
    ...(own.devices.length ? [statisticsGraph(t(hass, "devices_range"), own.devices)] : []),
  ];
  const usage = {
    title: `${prefix}${t(hass, "view_usage")}`,
    path: `usage${suffix}`,
    icon: "mdi:chart-bar",
    type: "sections",
    max_columns: 4,
    sections: [
      section(flows.map(full), 2),
      section(shares.map((card) => (card.type.endsWith("-gauge") ? card : full(card))), 2),
      // The sankey wants the whole width; it turns vertical when it has less.
      ...(named.devices ? [section([full({ type: "energy-sankey" })], 4)] : []),
    ],
  };

  const monthly = (title, statistic) =>
    statistic ? [{ type: "custom:hass-energy-history-card", title, statistic, years: 3 }] : [];
  const settled = ["settlement_cost", "imported_energy"].map((kind) => own.ofKind(kind)).filter(Boolean);
  const history = {
    title: `${prefix}${t(hass, "view_history")}`,
    path: `history${suffix}`,
    icon: "mdi:history",
    type: "sections",
    max_columns: 4,
    sections: [
      section(
        [
          ...monthly(t(hass, "grid_import"), named.imported[0]),
          ...monthly(t(hass, "house_by_month"), own.ofKind("house_consumption")),
        ].map(full),
        2
      ),
      section(
        [
          ...monthly(t(hass, "grid_export"), named.exported[0]),
          ...(settled.length
            ? [
                {
                  type: "statistics-graph",
                  title: t(hass, "past_settlements"),
                  entities: settled,
                  stat_types: ["change"],
                  chart_type: "bar",
                  period: "month",
                  days_to_show: 1500,
                },
              ]
            : []),
        ].map(full),
        2
      ),
    ],
  };

  return [settlement, usage, history];
}

customElements.define("ll-strategy-dashboard-hass-energy", HassEnergyDashboardStrategy);
window.customStrategies = window.customStrategies || [];
window.customStrategies.push({
  type: "hass-energy",
  name: t(null, "listing_name"),
  description: t(null, "listing_description"),
  documentationURL: "https://github.com/pomahazibalint/hass_energy",
  strategyType: "dashboard",
});
