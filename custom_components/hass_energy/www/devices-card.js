// Energy and cost per device over the settlement period, and how each
// cost came to be, in columns.
//
// Reads the integration's device cost sensors, which carry the device's
// name, its energy, the device it is included in, and the figures behind
// its cost: its energy in the hours worth each price, its share of the
// house, the average per kWh, the hours its meter was capped at the
// house's and, with panels, what they saved on it: what the same energy
// would have cost bought from the grid, less what it cost. The card shows
// the hierarchy the dashboard's own device graph
// shows rather than summing a parent and its child together, and the part
// no device accounts for as the rest of the house, with the same columns.
// The range is the settlement period, the question the integration
// answers; the native cards beside this one follow the energy date picker.

import { languageOf, t } from "./strings.js";

const STYLE = `
  :host { display: block; }
  ha-card { padding: 0 16px 8px; }
  h1 { font-size: var(--ha-card-header-font-size, 24px); font-weight: normal;
       margin: 0; padding: 16px 0 8px; color: var(--ha-card-header-color, var(--primary-text-color)); }
  .scroll { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; white-space: nowrap; }
  th { text-align: right; font-weight: normal; color: var(--secondary-text-color); padding: 4px 0 4px 12px; vertical-align: bottom; }
  th:first-child { text-align: left; padding-left: 0; }
  th .price { display: block; font-size: 0.85em; }
  td { padding: 8px 0 8px 12px; border-top: 1px solid var(--divider-color); color: var(--primary-text-color); }
  td:first-child { padding-left: 0; }
  td.value { text-align: right; font-variant-numeric: tabular-nums; }
  td.dim { color: var(--secondary-text-color); }
  td.nested { padding-left: 24px; color: var(--secondary-text-color); }
  tr.rest td { color: var(--secondary-text-color); }
  tr.total td { font-weight: 500; }
  .bar { height: 4px; background: var(--primary-color); border-radius: 2px; margin-top: 4px; }
  .capped { color: var(--secondary-text-color); font-size: 0.85em; margin-left: 6px; }
  .note, .empty { color: var(--secondary-text-color); font-size: 0.9em; padding: 8px 0; line-height: 1.4; white-space: normal; }
`;

const BUCKETS = [
  ["kwh_at_subsidized", "at_subsidized", "subsidized_price_with_vat"],
  ["kwh_at_market", "at_market", "market_price_with_vat"],
  ["kwh_at_feed_in", "at_feed_in", "feed_in_price"],
  ["kwh_mixed", "mixed", null],
];

class HassEnergyDevicesCard extends HTMLElement {
  setConfig(config) {
    if (!Array.isArray(config.devices)) {
      throw new Error("The devices card needs a list of device cost entity ids.");
    }
    this._config = config;
    this._rendered = null;
  }

  set hass(hass) {
    this._hass = hass;
    const watched = [...this._config.devices, ...Object.values(this._config.entities || {})];
    const key = hass.locale?.language + "|" + watched.map((id) => hass.states[id]?.last_updated ?? "").join("|");
    if (key !== this._rendered) {
      this._rendered = key;
      this._render();
    }
  }

  getCardSize() {
    return 2 + this._config.devices.length / 2;
  }

  _rows() {
    const states = this._config.devices
      .map((id) => this._hass.states[id])
      .filter((state) => state && state.state !== "unavailable" && state.state !== "unknown");
    const devices = states.map((state) => {
      const a = state.attributes;
      return {
        name: a.device || a.friendly_name || state.entity_id,
        statistic: a.statistic,
        includedIn: a.included_in || "",
        kwh: Number(a.energy_kwh) || 0,
        cost: Number(state.state) || 0,
        unit: a.unit_of_measurement || "",
        buckets: Object.fromEntries(BUCKETS.map(([key]) => [key, Number(a[key]) || 0])),
        capped: Number(a.capped_hours) || 0,
        saved: saving(a),
        prices: a,
      };
    });
    const known = new Set(devices.map((device) => device.statistic));
    // A device included in one the card does not know is a top-level one here.
    const top = devices.filter((device) => !known.has(device.includedIn));
    top.sort((a, b) => b.cost - a.cost);
    const rows = [];
    for (const device of top) {
      rows.push({ ...device, nested: false });
      devices
        .filter((child) => child.includedIn === device.statistic)
        .sort((a, b) => b.cost - a.cost)
        .forEach((child) => rows.push({ ...child, nested: true }));
    }
    return { rows, top };
  }

  _house() {
    const ids = this._config.entities || {};
    const cost = this._hass.states[ids.consumption_cost];
    const kwh = this._hass.states[ids.house_consumption];
    if (!cost || !kwh || cost.state === "unavailable" || kwh.state === "unavailable") return null;
    const a = cost.attributes;
    return {
      cost: Number(cost.state) || 0,
      kwh: Number(kwh.state) || 0,
      buckets: Object.fromEntries(BUCKETS.map(([key]) => [key, Number(a[key]) || 0])),
      saved: saving(a),
      prices: a,
    };
  }

  _render() {
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
    }
    const hass = this._hass;
    const title = this._config.title ? `<h1>${escape(this._config.title)}</h1>` : "";
    const { rows, top } = this._rows();
    if (!rows.length) {
      this.shadowRoot.innerHTML = `<style>${STYLE}</style><ha-card>${title}<div class="empty">${escape(t(hass, "no_devices"))}</div></ha-card>`;
      return;
    }
    const unit = rows[0].unit;
    const house = this._house();
    const language = languageOf(hass);
    const kwh = new Intl.NumberFormat(language, { maximumFractionDigits: 1 });
    const money = new Intl.NumberFormat(language, { maximumFractionDigits: 0 });
    const rate = new Intl.NumberFormat(language, { maximumFractionDigits: 1 });
    const percent = new Intl.NumberFormat(language, { style: "percent", maximumFractionDigits: 1 });
    const prices = house?.prices || rows[0].prices;
    const all = house ? [...rows, house] : rows;
    const used = BUCKETS.filter(([key]) => all.some((row) => row.buckets[key] > 0.0005));
    // A column nobody has a figure in is left out: without panels nothing was saved.
    const saved = all.some((row) => row.saved !== null);
    const widest = Math.max(house?.cost ?? 0, ...top.map((device) => device.cost), 1);

    const line = (row, cls, label) => {
      const share = house && house.kwh ? row.kwh / house.kwh : null;
      const note = row.capped ? `<span class="capped">${escape(t(hass, "capped_note", { hours: row.capped }))}</span>` : "";
      return (
        `<tr class="${cls}"><td${cls === "nested" ? ' class="nested"' : ""}>${escape(label)}${note}` +
        `<div class="bar" style="width:${Math.max(0, Math.min(100, (100 * row.cost) / widest))}%"></div></td>` +
        `<td class="value">${kwh.format(row.kwh)} kWh</td>` +
        `<td class="value dim">${share === null ? "" : percent.format(share)}</td>` +
        used.map(([key]) => `<td class="value dim">${row.buckets[key] > 0.0005 ? kwh.format(row.buckets[key]) : ""}</td>`).join("") +
        `<td class="value dim">${row.kwh ? rate.format(row.cost / row.kwh) : ""}</td>` +
        `<td class="value">${money.format(row.cost)} ${escape(unit)}</td>` +
        (saved ? `<td class="value">${row.saved === null ? "" : `${money.format(row.saved)} ${escape(unit)}`}</td>` : "") +
        `</tr>`
      );
    };

    const body = rows.map((row) => line(row, row.nested ? "nested" : "device", row.name));
    if (house) {
      const rest = {
        kwh: Math.max(house.kwh - top.reduce((sum, d) => sum + d.kwh, 0), 0),
        cost: Math.max(house.cost - top.reduce((sum, d) => sum + d.cost, 0), 0),
        buckets: Object.fromEntries(
          BUCKETS.map(([key]) => [key, Math.max(house.buckets[key] - top.reduce((sum, d) => sum + d.buckets[key], 0), 0)])
        ),
        capped: 0,
        saved: house.saved === null ? null : house.saved - top.reduce((sum, d) => sum + (d.saved || 0), 0),
      };
      body.push(line(rest, "rest", t(hass, "rest_of_house")));
      body.push(line({ ...house, capped: 0 }, "total", t(hass, "house")));
    }
    const header =
      `<tr><th>${escape(t(hass, "device"))}</th><th>${escape(t(hass, "energy"))}</th><th>${escape(t(hass, "share"))}</th>` +
      used
        .map(([, label, priceKey]) => {
          const price = priceKey && prices[priceKey] !== undefined ? `<span class="price">${rate.format(Number(prices[priceKey]))} ${escape(unit)}/kWh</span>` : "";
          return `<th>${escape(t(hass, label))}${price}</th>`;
        })
        .join("") +
      `<th>${escape(t(hass, "average"))}<span class="price">${escape(unit)}/kWh</span></th><th>${escape(t(hass, "cost"))}</th>` +
      (saved ? `<th>${escape(t(hass, "saved"))}</th>` : "") +
      `</tr>`;
    const note = t(hass, "columns_note") + (saved ? ` ${t(hass, "saved_note")}` : "");
    this.shadowRoot.innerHTML =
      `<style>${STYLE}</style><ha-card>${title}<div class="scroll"><table>${header}${body.join("")}</table></div>` +
      `<div class="note">${escape(note)}</div></ha-card>`;
  }
}

// What the panels saved on a cost, or null for a household without them,
// whose sensors carry no such figure.
function saving(attributes) {
  return attributes.saved_by_panels === undefined ? null : Number(attributes.saved_by_panels) || 0;
}

function escape(text) {
  return String(text).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

customElements.define("hass-energy-devices-card", HassEnergyDevicesCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "hass-energy-devices-card",
  name: "Energy settlement devices",
  description: "Energy and cost per device over the settlement period, and how each cost came to be.",
});
