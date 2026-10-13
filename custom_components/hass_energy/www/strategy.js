// The dashboard strategy: builds the dashboard's configuration in the
// browser when it is opened, from the integration's entries, their entities
// and the statistics they wrote. Nothing is stored; the user creates the
// dashboard from the new-dashboard dialog and owns it like any other.
//
// A strategy is a custom element named ll-strategy-dashboard-<name> with a
// static generate(); the entry in window.customStrategies is what makes the
// new-dashboard dialog offer it.
//
// Three views per metering point: Energy, a copy of Home Assistant's own
// energy view; Costs, the invoice and the outlook beside the costs for the
// selected range and the devices; and History, the long view by month.

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

// The shape of Home Assistant's own energy view, copied rather than
// approximated: a sidebar of small cards shown when the view has two or
// more columns, the same cards inline when it has one, a main section
// three columns wide in which a card asks for all 36 card columns, and
// the date picker as a floating footer card that takes no room from the
// cards. Costs and History get the same skeleton, so the dashboard reads
// as the native one with two tabs added.
const WIDE = { condition: "view_columns", min: 2 };
const NARROW = { condition: "view_columns", max: 1 };
const main = (card) => ({ ...card, grid_options: { columns: 36 } });

function nativeView({ title, path, icon, aside, cards, dated }) {
  const view = { title, path, icon, type: "sections", sections: [] };
  if (aside.length) {
    view.sidebar = { sections: [{ cards: aside }], visibility: [WIDE] };
    for (const card of aside) {
      // A grid of gauges in the sidebar is the gauges side by side inline.
      const inline =
        card.type === "grid" ? card.cards.map((one) => ({ ...one, grid_options: { columns: 6 } })) : [card];
      view.sections.push({ type: "grid", column_span: 1, visibility: [NARROW], cards: inline });
    }
  }
  view.sections.push({ type: "grid", column_span: 3, cards: cards.map(main) });
  if (dated) {
    view.footer = {
      card: { type: "energy-date-selection", opening_direction: "right", vertical_opening_direction: "up" },
    };
  }
  return view;
}

const native = (hass, key) => hass.localize(`ui.panel.energy.cards.${key}`);
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
  const grid = named.imported.length > 0;
  const both = grid && named.exported.length > 0;

  const gauges = [
    ...(both ? [{ type: "energy-grid-neutrality-gauge" }] : []),
    ...(named.solar ? [{ type: "energy-solar-consumed-gauge" }, { type: "energy-self-sufficiency-gauge" }] : []),
  ];
  const energy = nativeView({
    title: `${prefix}${t(hass, "view_energy")}`,
    path: `energy${suffix}`,
    icon: "mdi:lightning-bolt",
    dated: true,
    aside: [
      { title: native(hass, "energy_distribution_title"), type: "energy-distribution" },
      ...(both ? [{ type: "energy-grid-balance" }] : []),
      ...(gauges.length ? [{ type: "grid", columns: gauges.length === 1 ? 1 : 2, cards: gauges }] : []),
    ],
    cards: [
      { type: "energy-compare" },
      ...(grid || named.battery
        ? [{ title: native(hass, "energy_usage_graph_title"), type: "energy-usage-graph" }]
        : []),
      ...(named.solar ? [{ title: native(hass, "energy_solar_graph_title"), type: "energy-solar-graph" }] : []),
      ...graph(t(hass, "house_consumption"), ["house_consumption", "self_consumed_solar"]),
      {
        title: native(hass, "energy_sources_table_title"),
        type: "energy-sources-table",
        types: ["grid", "solar", "battery"],
      },
      ...(named.devices
        ? [
            { title: native(hass, "energy_devices_detail_graph_title"), type: "energy-devices-detail-graph" },
            { title: native(hass, "energy_devices_graph_title"), type: "energy-devices-graph" },
            { title: native(hass, "energy_sankey_title"), type: "energy-sankey" },
          ]
        : []),
    ],
  });

  const costs = nativeView({
    title: `${prefix}${t(hass, "view_costs")}`,
    path: `costs${suffix}`,
    icon: "mdi:receipt-text-outline",
    dated: true,
    aside: [
      {
        type: "custom:hass-energy-bill-card",
        title: entry.title,
        entities: Object.fromEntries(Object.entries(byLine).filter(([line]) => BILL_LINES.includes(line))),
      },
      ...entities(t(hass, "outlook"), [
        "projected_total_payable",
        "projected_billed_energy",
        "allowance_runs_out",
        "allowance_remaining",
        "period_days",
      ]),
      ...entities(t(hass, "solar_battery"), [
        "solar_value",
        "self_consumed_solar",
        "house_consumption",
        "consumption_cost",
        "battery_saving",
      ]),
    ],
    cards: [
      ...graph(t(hass, "cost_and_value"), ["consumption_cost", "solar_value"]),
      {
        type: "custom:hass-energy-devices-card",
        title: t(hass, "devices_period"),
        devices,
        entities: Object.fromEntries(
          Object.entries(byLine).filter(([line]) => ["consumption_cost", "house_consumption"].includes(line))
        ),
      },
      ...(own.devices.length ? [statisticsGraph(t(hass, "devices_range"), own.devices)] : []),
    ],
  });

  const monthly = (title, statistic) =>
    statistic ? [{ type: "custom:hass-energy-history-card", title, statistic, years: 3 }] : [];
  const settled = ["settlement_cost", "imported_energy"].map((kind) => own.ofKind(kind)).filter(Boolean);
  const history = nativeView({
    title: `${prefix}${t(hass, "view_history")}`,
    path: `history${suffix}`,
    icon: "mdi:history",
    dated: false,
    aside: [],
    cards: [
      ...monthly(t(hass, "grid_import"), named.imported[0]),
      ...monthly(t(hass, "grid_export"), named.exported[0]),
      ...monthly(t(hass, "house_by_month"), own.ofKind("house_consumption")),
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
    ],
  });

  return [energy, costs, history];
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
