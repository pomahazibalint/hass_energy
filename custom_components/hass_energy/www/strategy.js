// The dashboard strategy: builds the dashboard's configuration in the
// browser when it is opened, from the integration's entries, their entities
// and the statistics they wrote. Nothing is stored; the user creates the
// dashboard from the new-dashboard dialog and owns it like any other.
//
// A strategy is a custom element named ll-strategy-dashboard-<name> with a
// static generate(); the entry in window.customStrategies is what makes the
// new-dashboard dialog offer it.
//
// The native energy dashboard's own tabs, built by Home Assistant's view
// strategies exactly as its own dashboard builds them, and then two of
// ours per metering point: Costs, the invoice and the outlook beside the
// costs for the selected range and the devices; and History, the long
// view by month.

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
    // The native tabs' and cards' titles are in the energy panel's own
    // translation fragment, which only that panel loads; a dashboard has
    // the lovelace fragment alone. Loading it hands back the localize that
    // knows the words, and the dashboard regenerates when localize changes.
    const localize = (await hass.loadFragmentTranslation?.("energy").catch(() => null)) || hass.localize;
    const views = nativeTabs(hass, prefs, localize);
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

// The native dashboard's tabs, chosen as the native dashboard chooses them:
// electricity when there is a grid, solar, battery or devices; gas and
// water when named; Now when any source reports power; and the summary
// when there is power or more than one kind of energy. Titles are Home
// Assistant's own. All but Now are views Home Assistant's own strategies
// build, over the collection the native dashboard keys its date-picked
// tabs by. Now is built here, see nowView.
const COLLECTION = "energy_dashboard";
const NOW_COLLECTION = "energy_dashboard_now";

const hasPower = (prefs) =>
  (prefs?.energy_sources || []).some(
    (source) =>
      (["solar", "battery"].includes(source.type) && source.stat_rate) ||
      (source.type === "grid" && (source.stat_rate || source.power_config))
  );
const hasRate = (list) => (list || []).some((one) => one.stat_rate);
const hasRateOf = (prefs, kind) => (prefs?.energy_sources || []).some((s) => s.type === kind && s.stat_rate);

function nativeTabs(hass, prefs, localize) {
  const sources = prefs?.energy_sources || [];
  const kinds = new Set(sources.map((source) => source.type));
  const energy = ["grid", "solar", "battery"].some((kind) => kinds.has(kind));
  const devices = (prefs?.device_consumption || []).length > 0;
  const gas = kinds.has("gas");
  const water = kinds.has("water") || (prefs?.device_consumption_water || []).length > 0;
  const power =
    hasPower(prefs) ||
    hasRate(prefs?.device_consumption) ||
    hasRate(prefs?.device_consumption_water) ||
    hasRateOf(prefs, "water") ||
    hasRateOf(prefs, "gas");
  const title = (path) => localize(`ui.panel.energy.title.${path}`) || path;
  const tab = (path, type) => ({
    path,
    title: title(path),
    strategy: { type, collection_key: COLLECTION },
  });
  const tabs = [];
  if (energy || devices) tabs.push(tab("electricity", "energy"));
  if (gas) tabs.push(tab("gas", "gas"));
  if (water) tabs.push(tab("water", "water"));
  if (power) tabs.push(nowView(hass, prefs, localize, title("now")));
  if (power || [energy, gas, water].filter(Boolean).length > 1) tabs.unshift(tab("overview", "energy-overview"));
  return tabs;
}

// The Now tab, the native power view's cards and badges over the native
// dashboard's own collection for it. Built here rather than delegated
// because the native view is one section of the sections grid and the
// energy panel widens it to the view with a style of its own; in a
// dashboard the section would be one column wide. This one spans them all.
function nowView(hass, prefs, localize, title) {
  const sources = prefs?.energy_sources || [];
  const native = (card) => ({ ...card, collection_key: NOW_COLLECTION });
  const badges = [];
  if (hasPower(prefs)) badges.push(native({ type: "power-total" }));
  if (hasRateOf(prefs, "gas")) badges.push(native({ type: "gas-total" }));
  if (hasRateOf(prefs, "water")) badges.push(native({ type: "water-total" }));
  for (const source of sources) {
    if (source.type === "battery" && source.stat_soc) badges.push({ type: "entity", entity: source.stat_soc });
  }
  const cards = [];
  if (hasPower(prefs)) {
    cards.push(
      native({ title: localize("ui.panel.energy.cards.power_sources_graph_title"), type: "power-sources-graph" })
    );
  }
  if (hasRate(prefs?.device_consumption)) {
    const grouped = groupedByPlace(prefs.device_consumption, hass);
    cards.push(
      native({
        title: localize("ui.panel.energy.cards.power_sankey_title"),
        type: "power-sankey",
        group_by_floor: grouped,
        group_by_area: grouped,
      })
    );
  }
  if (hasRate(prefs?.device_consumption_water)) {
    const grouped = groupedByPlace(prefs.device_consumption_water, hass);
    cards.push(
      native({
        title: localize("ui.panel.energy.cards.water_flow_sankey_title"),
        type: "water-flow-sankey",
        group_by_floor: grouped,
        group_by_area: grouped,
      })
    );
  }
  const view = {
    path: "now",
    title,
    type: "sections",
    sections: [{ type: "grid", column_span: 4, cards: cards.map(main) }],
  };
  if (badges.length) view.badges = badges;
  return view;
}

// Whether the sankey may group devices by floor and area, as the native
// view decides it: not when a device included in another's figure sits in
// a different area from it, since the grouping would then split the pair.
function groupedByPlace(devices, hass) {
  if (!devices.some((device) => device.included_in_stat)) return true;
  const areaOf = (statistic) => {
    const entity = hass.entities?.[statistic];
    if (!entity) return undefined;
    let device = entity.device_id ? hass.devices?.[entity.device_id] : undefined;
    let area = entity.area_id;
    while (!area && device) {
      area = device.area_id;
      device = device.parent_device_id ? hass.devices?.[device.parent_device_id] : undefined;
    }
    return area || undefined;
  };
  const byStatistic = new Map(devices.map((device) => [device.stat_consumption, device]));
  for (const device of devices) {
    if (!device.included_in_stat) continue;
    const parent = byStatistic.get(device.included_in_stat);
    if (!parent || !device.stat_rate || !parent.stat_rate) continue;
    const own = areaOf(device.stat_rate);
    const parents = areaOf(parent.stat_rate);
    if (own && parents && own !== parents) return false;
  }
  return true;
}

// The shape of Home Assistant's own energy view, for the tabs that are
// ours: a sidebar of small cards shown when the view has two or more
// columns, the same cards inline when it has one, a main section three
// columns wide in which a card asks for all 36 card columns, and the date
// picker as a floating footer card that takes no room from the cards.
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

const statisticsGraph = (title, entities, extra = {}) => ({
  type: "statistics-graph",
  title,
  entities,
  stat_types: ["change"],
  chart_type: "bar",
  // The bucket follows the selected range as the native cards' does: hours
  // for a day, days for a month, months for a year.
  period: "auto",
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
  "net_position_under_gross",
  "allowance_remaining",
  "period_days",
];

function viewsFor(entry, registry, statistics, prefs, hass, index, several) {
  const { byLine, devices } = entitiesOf(entry, registry);
  const own = statisticsOf(entry, statistics);
  const named = preferencesOf(prefs);
  const suffix = index ? `-${index + 1}` : "";
  const prefix = several ? `${entry.title}: ` : "";
  // Each row named here: the entity's own name carries the device's, which
  // an entities card shows as is and cuts off on a phone.
  const entities = (title, lines) => {
    const rows = lines
      .filter((line) => byLine[line])
      .map((line) => ({ entity: byLine[line], name: t(hass, `line_${line}`) }));
    return rows.length ? [{ type: "entities", title, entities: rows }] : [];
  };
  const graph = (title, kinds) => {
    const ids = kinds.map((kind) => own.ofKind(kind)).filter(Boolean);
    return ids.length ? [statisticsGraph(title, ids)] : [];
  };
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
      ...graph(t(hass, "house_consumption"), ["house_consumption", "self_consumed_solar"]),
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

  return [costs, history];
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
