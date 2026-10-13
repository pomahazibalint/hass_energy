// Energy and cost per device over the settlement period.
//
// Reads the integration's device cost sensors, which carry the device's name,
// its energy and the device it is included in, so the card shows the
// hierarchy the dashboard's own device graph shows rather than summing a
// parent and its child together. The part no device accounts for is the
// rest of the house. The range is the settlement period, the question the
// integration answers; the native cards beside this one follow the energy
// date picker for any other range.

import { languageOf, partsOf, t } from "./strings.js";

const STYLE = `
  :host { display: block; }
  ha-card { padding: 0 16px 8px; }
  h1 { font-size: var(--ha-card-header-font-size, 24px); font-weight: normal;
       margin: 0; padding: 16px 0 8px; color: var(--ha-card-header-color, var(--primary-text-color)); }
  table { width: 100%; border-collapse: collapse; }
  th { text-align: right; font-weight: normal; color: var(--secondary-text-color); padding: 4px 0; }
  th:first-child { text-align: left; }
  td { padding: 8px 0; border-top: 1px solid var(--divider-color); color: var(--primary-text-color); }
  td.value { text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
  td.nested { padding-left: 24px; color: var(--secondary-text-color); }
  tr.rest td { color: var(--secondary-text-color); }
  tr.total td { font-weight: 500; }
  .bar { height: 4px; background: var(--primary-color); border-radius: 2px; margin-top: 4px; }
  tr.line { cursor: pointer; }
  tr.behind td { border-top: none; padding: 0 0 10px; color: var(--secondary-text-color); font-size: 0.9em; line-height: 1.4; }
  tr.behind[hidden] { display: none; }
  .empty { color: var(--secondary-text-color); padding: 8px 0 16px; }
`;

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
    const devices = states.map((state) => ({
      name: state.attributes.device || state.attributes.friendly_name || state.entity_id,
      statistic: state.attributes.statistic,
      includedIn: state.attributes.included_in || "",
      kwh: Number(state.attributes.energy_kwh) || 0,
      cost: Number(state.state) || 0,
      unit: state.attributes.unit_of_measurement || "",
      attributes: state.attributes,
    }));
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
    const accounted = top.reduce((sum, device) => sum + device.cost, 0);
    const accountedKwh = top.reduce((sum, device) => sum + device.kwh, 0);
    const widest = Math.max(house?.cost ?? 0, ...top.map((device) => device.cost), 1);
    const numbers = new Intl.NumberFormat(languageOf(hass));
    const open = this._open || new Set();
    this._open = open;
    const cells = (key, name, kwh, cost, cls, behind) =>
      `<tr class="${cls}${behind ? " line" : ""}" data-key="${escape(key)}"><td${cls === "nested" ? ' class="nested"' : ""}>${escape(name)}` +
      `<div class="bar" style="width:${Math.max(0, Math.min(100, (100 * cost) / widest))}%"></div></td>` +
      `<td class="value">${numbers.format(Number(kwh.toFixed(1)))} kWh</td>` +
      `<td class="value">${numbers.format(Math.round(cost))} ${escape(unit)}</td></tr>` +
      (behind
        ? `<tr class="behind" data-for="${escape(key)}"${open.has(key) ? "" : " hidden"}><td colspan="3">${escape(behind)}</td></tr>`
        : "");
    const body = rows.map((row) =>
      cells(row.statistic, row.name, row.kwh, row.cost, row.nested ? "nested" : "device", explainDevice(hass, row, unit))
    );
    if (house) {
      body.push(cells("rest", t(hass, "rest_of_house"), Math.max(house.kwh - accountedKwh, 0), Math.max(house.cost - accounted, 0), "rest", ""));
      body.push(cells("house", t(hass, "house"), house.kwh, house.cost, "total", explainHouse(hass, house.attributes, unit)));
    }
    this.shadowRoot.innerHTML =
      `<style>${STYLE}</style><ha-card>${title}<table>` +
      `<tr><th>${escape(t(hass, "device"))}</th><th>${escape(t(hass, "energy"))}</th><th>${escape(t(hass, "cost"))}</th></tr>` +
      `${body.join("")}</table></ha-card>`;
    for (const row of this.shadowRoot.querySelectorAll("tr.line")) {
      row.addEventListener("click", () => {
        const key = row.dataset.key;
        const detail = this.shadowRoot.querySelector(`tr.behind[data-for="${CSS.escape(key)}"]`);
        if (open.has(key)) open.delete(key);
        else open.add(key);
        if (detail) detail.hidden = !open.has(key);
      });
    }
  }

  _house() {
    const ids = this._config.entities || {};
    const cost = this._hass.states[ids.consumption_cost];
    const kwh = this._hass.states[ids.house_consumption];
    if (!cost || !kwh || cost.state === "unavailable" || kwh.state === "unavailable") return null;
    return { cost: Number(cost.state) || 0, kwh: Number(kwh.state) || 0, attributes: cost.attributes };
  }
}

// How a device's cost came to be, from the figures its sensor carries.
function explainDevice(hass, device, unit) {
  const a = device.attributes;
  if (!("kwh_at_subsidized" in a)) return "";
  const numbers = new Intl.NumberFormat(languageOf(hass), { maximumFractionDigits: 1 });
  let text = t(hass, "behind_device", {
    energy: numbers.format(device.kwh),
    share: numbers.format(100 * (Number(a.share_of_house) || 0)),
    parts: partsOf(hass, a, unit),
    average: `${numbers.format(Number(a.average_per_kwh) || 0)} ${unit}`.trim(),
  });
  if (Number(a.capped_hours) > 0) text += t(hass, "behind_device_capped", { hours: a.capped_hours });
  return text;
}

function explainHouse(hass, attributes, unit) {
  if (!attributes || !("kwh_at_subsidized" in attributes)) return "";
  const numbers = new Intl.NumberFormat(languageOf(hass), { maximumFractionDigits: 1 });
  return t(hass, "behind_consumption", {
    energy: numbers.format(Number(attributes.energy_kwh) || 0),
    parts: partsOf(hass, attributes, unit),
    average: `${numbers.format(Number(attributes.average_per_kwh) || 0)} ${unit}`.trim(),
  });
}

function escape(text) {
  return String(text).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

customElements.define("hass-energy-devices-card", HassEnergyDevicesCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "hass-energy-devices-card",
  name: "Energy settlement devices",
  description: "Energy and cost per device over the settlement period, from the Energy Settlement integration.",
});
