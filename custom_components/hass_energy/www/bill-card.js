// The settlement as an invoice.
//
// An invoice is a list of lines, not one number, and the integration's
// sensors are those lines. The card reads them in order and shows the ones
// the household has: a line whose sensor is unavailable is a figure whose
// sources the household lacks, and is left out rather than shown as nothing.

import { languageOf, t } from "./strings.js";

const LINES = [
  ["energy_cost", "net"],
  ["solar_value", "info"],
  ["surplus_value", "credit"],
  ["standing_charge", "net"],
  ["vat", "net"],
  ["total_payable", "total"],
  ["net_position", "total"],
  ["net_position_under_gross", "info"],
  ["allowance_remaining", "info"],
  ["period_days", "info"],
];

const STYLE = `
  :host { display: block; }
  ha-card { padding: 0 16px 8px; }
  h1 { font-size: var(--ha-card-header-font-size, 24px); font-weight: normal;
       margin: 0; padding: 16px 0 8px; color: var(--ha-card-header-color, var(--primary-text-color)); }
  table { width: 100%; border-collapse: collapse; }
  td { padding: 8px 0; border-top: 1px solid var(--divider-color); color: var(--primary-text-color); }
  tr:first-child td { border-top: none; }
  td.value { text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
  tr.total td { font-weight: 500; }
  tr.credit td.value { color: var(--success-color, var(--primary-color)); }
  tr.info td { color: var(--secondary-text-color); }
  tr.line { cursor: pointer; }
  tr.line td:first-child::after { content: " ?"; color: var(--secondary-text-color); font-size: 0.85em; }
  tr.behind td { border-top: none; padding: 0 0 10px; color: var(--secondary-text-color); font-size: 0.9em; line-height: 1.4; }
  tr.behind[hidden] { display: none; }
  .period, .footer { color: var(--secondary-text-color); font-size: 0.9em; padding: 4px 0 8px; }
  .footer a { color: var(--primary-color); text-decoration: none; }
`;

class HassEnergyBillCard extends HTMLElement {
  setConfig(config) {
    if (!config.entities || typeof config.entities !== "object") {
      throw new Error("The bill card needs an entities map, one entity id per line.");
    }
    this._config = config;
    this._rendered = null;
  }

  set hass(hass) {
    this._hass = hass;
    // Re-render only when a line changed: the hass object changes on every
    // state in the house, and this card is on a dashboard full of them.
    const key =
      hass.locale?.language + "|" + LINES.map(([line]) => this._state(line)?.last_updated ?? "").join("|");
    if (key !== this._rendered) {
      this._rendered = key;
      this._render();
    }
  }

  getCardSize() {
    return 1 + LINES.filter(([line]) => this._state(line)).length / 2;
  }

  _state(line) {
    const entityId = this._config?.entities?.[line];
    return entityId ? this._hass?.states?.[entityId] : undefined;
  }

  _render() {
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
    }
    const hass = this._hass;
    const rows = [];
    const open = this._open || new Set();
    this._open = open;
    for (const [line, kind] of LINES) {
      const state = this._state(line);
      if (!state || state.state === "unavailable") continue;
      const value = state.state === "unknown" ? "—" : hass.formatEntityState(state);
      const behind = explain(hass, line, state);
      const toggle = behind ? ` line" data-line="${line}` : "";
      rows.push(
        `<tr class="${kind}${toggle}"><td>${escape(t(hass, `line_${line}`))}</td><td class="value">${escape(value)}</td></tr>`
      );
      if (behind) {
        rows.push(`<tr class="behind" data-for="${line}"${open.has(line) ? "" : " hidden"}><td colspan="2">${escape(behind)}</td></tr>`);
      }
    }
    const payable = this._state("total_payable");
    const period = payable?.attributes?.period_start
      ? `<div class="period">${escape(t(hass, "period_from", { date: payable.attributes.period_start }))}</div>`
      : "";
    const title = this._config.title ? `<h1>${escape(this._config.title)}</h1>` : "";
    const link = `<a href="/config/energy">${escape(t(hass, "sources_link"))}</a>`;
    const footer = this._config.hide_footer
      ? ""
      : `<div class="footer">${escape(t(hass, "sources_footer", { link: "\u0000" })).replace("\u0000", link)}</div>`;
    this.shadowRoot.innerHTML = `<style>${STYLE}</style><ha-card>${title}${period}<table>${rows.join("")}</table>${footer}</ha-card>`;
    for (const row of this.shadowRoot.querySelectorAll("tr.line")) {
      row.addEventListener("click", () => {
        const line = row.dataset.line;
        const detail = this.shadowRoot.querySelector(`tr.behind[data-for="${line}"]`);
        if (open.has(line)) open.delete(line);
        else open.add(line);
        detail.hidden = !open.has(line);
      });
    }
    const anchor = this.shadowRoot.querySelector("a");
    if (anchor) {
      anchor.addEventListener("click", (event) => {
        event.preventDefault();
        history.pushState(null, "", anchor.getAttribute("href"));
        window.dispatchEvent(new Event("location-changed"));
      });
    }
  }
}

// How a line came to be, from the figures its sensor carries. Numbers from
// the backend, words from here, so the sentence is in the user's language.
function explain(hass, line, state) {
  const a = state.attributes;
  const unit = a.unit_of_measurement || "";
  const numbers = new Intl.NumberFormat(languageOf(hass), { maximumFractionDigits: 1 });
  const money = (value) => (value === null || value === undefined ? "—" : `${numbers.format(Number(value))} ${unit}`.trim());
  const kwh = (value) => numbers.format(Number(value) || 0);
  switch (line) {
    case "energy_cost":
      return "subsidized_kwh" in a
        ? t(hass, "behind_energy_cost", { subsidized_kwh: kwh(a.subsidized_kwh), market_kwh: kwh(a.market_kwh) })
        : "";
    case "solar_value":
      return "net_position" in a
        ? t(hass, "behind_solar_value", {
            without: money(a.net_position_without_panels),
            position: money(a.net_position),
            kept: kwh(a.solar_kept_kwh),
            exported: kwh(a.exported_kwh),
          })
        : "";
    case "surplus_value":
      return "surplus_kwh" in a ? t(hass, "behind_surplus_value", { kwh: kwh(a.surplus_kwh) }) : "";
    case "standing_charge":
      return "months" in a ? t(hass, "behind_standing_charge", { months: a.months, per_month: money(a.per_month) }) : "";
    case "vat":
      return "percent" in a ? t(hass, "behind_vat", { percent: a.percent, net_total: money(a.net_total) }) : "";
    case "total_payable":
      return "energy_net" in a
        ? t(hass, "behind_total_payable", { energy: money(a.energy_net), standing: money(a.standing_charge_net), vat: money(a.vat) })
        : "";
    case "net_position":
      return "total_payable" in a
        ? t(hass, "behind_net_position", { payable: money(a.total_payable), surplus: money(a.surplus_owed) })
        : "";
    case "net_position_under_gross":
      return "difference" in a
        ? t(hass, "behind_net_position_under_gross", {
            payable: money(a.total_payable_under_gross),
            surplus: money(a.surplus_owed_under_gross),
            difference: money(a.difference),
          })
        : "";
    case "allowance_remaining":
      return "allowance_kwh" in a
        ? t(hass, "behind_allowance_remaining", { used: kwh(a.allowance_used_kwh), allowance: kwh(a.allowance_kwh), days: a.period_days })
        : "";
    case "period_days":
      return "period_start" in a ? t(hass, "behind_period_days", { start: a.period_start, end: a.period_end }) : "";
    default:
      return "";
  }
}

function escape(text) {
  return String(text).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

customElements.define("hass-energy-bill-card", HassEnergyBillCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "hass-energy-bill-card",
  name: "Energy settlement bill",
  description: "The settlement as an invoice, from the Energy Settlement integration's sensors.",
});
