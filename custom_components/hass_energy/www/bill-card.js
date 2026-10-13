// The settlement as an invoice.
//
// An invoice is a list of lines, not one number, and the integration's
// sensors are those lines. The card reads them in order and shows the ones
// the household has: a line whose sensor is unavailable is a figure whose
// sources the household lacks, and is left out rather than shown as nothing.

import { t } from "./strings.js";

const LINES = [
  ["energy_cost", "net"],
  ["solar_value", "info"],
  ["surplus_value", "credit"],
  ["standing_charge", "net"],
  ["vat", "net"],
  ["total_payable", "total"],
  ["net_position", "total"],
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
    for (const [line, kind] of LINES) {
      const state = this._state(line);
      if (!state || state.state === "unavailable") continue;
      const value = state.state === "unknown" ? "—" : hass.formatEntityState(state);
      rows.push(
        `<tr class="${kind}"><td>${escape(t(hass, `line_${line}`))}</td><td class="value">${escape(value)}</td></tr>`
      );
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
