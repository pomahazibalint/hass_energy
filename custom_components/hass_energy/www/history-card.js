// The long view: one statistic by calendar month, this year over the years
// before it, so the same month last year sits beside this one and the
// seasonal profile shows across years.
//
// Read from the recorder's monthly statistics over the websocket, which is
// the same long-term record the native cards read. Drawn as plain SVG: the
// plan adds a chart library only when a card needs one, and grouped bars
// with a hover tooltip do not.

import { monthNames, t } from "./strings.js";

const COLORS = ["var(--primary-color)", "var(--accent-color, #ff9800)", "var(--secondary-text-color)", "var(--disabled-color, #bdbdbd)"];
const WIDTH = 600;
const HEIGHT = 220;
const PAD = { top: 12, right: 8, bottom: 28, left: 44 };

const STYLE = `
  :host { display: block; }
  ha-card { padding: 0 16px 8px; position: relative; }
  h1 { font-size: var(--ha-card-header-font-size, 24px); font-weight: normal;
       margin: 0; padding: 16px 0 8px; color: var(--ha-card-header-color, var(--primary-text-color)); }
  svg { width: 100%; height: auto; display: block; touch-action: none; }
  text { fill: var(--secondary-text-color); font-size: 11px; }
  .grid { stroke: var(--divider-color); stroke-width: 1; }
  .hover { fill: var(--primary-text-color); opacity: 0; }
  .hover.on { opacity: 0.06; }
  .legend { display: flex; flex-wrap: wrap; gap: 16px; padding: 8px 0; color: var(--secondary-text-color); font-size: 0.9em; }
  .swatch { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 6px; vertical-align: middle; }
  .tip { position: absolute; display: none; pointer-events: none; z-index: 1; min-width: 120px;
         background: var(--card-background-color, var(--ha-card-background, #fff)); color: var(--primary-text-color);
         border: 1px solid var(--divider-color); border-radius: var(--ha-card-border-radius, 12px);
         box-shadow: var(--ha-card-box-shadow, 0 2px 8px rgba(0, 0, 0, 0.3)); padding: 8px 12px; font-size: 12px; }
  .tip.on { display: block; }
  .tip .month { font-weight: 500; margin-bottom: 4px; }
  .tip .row { display: flex; justify-content: space-between; gap: 16px; }
  .tip .value { font-variant-numeric: tabular-nums; }
  .empty { color: var(--secondary-text-color); padding: 8px 0 16px; }
`;

class HassEnergyHistoryCard extends HTMLElement {
  setConfig(config) {
    if (!config.statistic) {
      throw new Error("The history card needs a statistic id.");
    }
    this._config = config;
    this._years = Math.min(Math.max(Number(config.years) || 3, 2), COLORS.length);
    this._loaded = null;
  }

  set hass(hass) {
    this._hass = hass;
    // Monthly figures move once an hour at most; one read per hour is plenty.
    const key = `${hass.locale?.language}|${Math.floor(Date.now() / 3600000)}`;
    if (this._loaded !== key) {
      this._loaded = key;
      this._load().catch((error) => this._render(null, String(error.message || error)));
    }
  }

  getCardSize() {
    return 4;
  }

  async _load() {
    const now = new Date();
    const first = new Date(now.getFullYear() - this._years + 1, 0, 1);
    const result = await this._hass.callWS({
      type: "recorder/statistics_during_period",
      start_time: first.toISOString(),
      statistic_ids: [this._config.statistic],
      period: "month",
      types: ["change"],
      units: this._config.unit ? undefined : { energy: "kWh" },
    });
    const rows = result[this._config.statistic] || [];
    const byYear = new Map();
    for (const row of rows) {
      const start = new Date(row.start);
      const year = start.getFullYear();
      if (!byYear.has(year)) byYear.set(year, new Array(12).fill(null));
      byYear.get(year)[start.getMonth()] = Math.max(row.change || 0, 0);
    }
    this._render(byYear, null);
  }

  _render(byYear, error) {
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
    }
    const hass = this._hass;
    const title = this._config.title ? `<h1>${escape(this._config.title)}</h1>` : "";
    if (error || !byYear || !byYear.size) {
      const message = error ? t(hass, "read_error", { error }) : t(hass, "nothing_recorded");
      this.shadowRoot.innerHTML = `<style>${STYLE}</style><ha-card>${title}<div class="empty">${escape(message)}</div></ha-card>`;
      return;
    }
    const years = [...byYear.keys()].sort();
    const unit = this._config.unit || "kWh";
    const months = monthNames(hass);
    const numbers = new Intl.NumberFormat(hass.locale?.language || "en", { maximumFractionDigits: 1 });
    const top = Math.max(1, ...years.flatMap((year) => byYear.get(year).map((v) => v || 0)));
    const plotWidth = WIDTH - PAD.left - PAD.right;
    const plotHeight = HEIGHT - PAD.top - PAD.bottom;
    const group = plotWidth / 12;
    const bar = (group * 0.8) / years.length;
    const scale = (value) => plotHeight - (plotHeight * value) / top;

    const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => {
      const y = PAD.top + scale(f * top);
      return `<line class="grid" x1="${PAD.left}" x2="${WIDTH - PAD.right}" y1="${y}" y2="${y}"/>` +
        `<text x="${PAD.left - 6}" y="${y + 4}" text-anchor="end">${numbers.format(f * top)}</text>`;
    });
    const labels = months.map((name, m) =>
      `<text x="${PAD.left + group * (m + 0.5)}" y="${HEIGHT - 8}" text-anchor="middle">${escape(name)}</text>`);
    const bars = [];
    years.forEach((year, i) => {
      byYear.get(year).forEach((value, m) => {
        if (value === null) return;
        const x = PAD.left + group * m + group * 0.1 + bar * i;
        const y = PAD.top + scale(value);
        bars.push(`<rect x="${x}" y="${y}" width="${bar}" height="${plotHeight - scale(value)}" fill="${COLORS[i]}" rx="1"/>`);
      });
    });
    const legend = years.map((year, i) =>
      `<span><span class="swatch" style="background:${COLORS[i]}"></span>${year}</span>`).join("");
    this.shadowRoot.innerHTML =
      `<style>${STYLE}</style><ha-card>${title}` +
      `<svg viewBox="0 0 ${WIDTH} ${HEIGHT}" role="img" aria-label="${escape(this._config.title || "History")}">` +
      `<rect class="hover" x="0" y="${PAD.top}" width="${group}" height="${plotHeight}" rx="4"/>` +
      `${ticks.join("")}${bars.join("")}${labels.join("")}</svg>` +
      `<div class="tip"></div>` +
      `<div class="legend">${legend}<span>${escape(t(hass, "per_month", { unit }))}</span></div></ha-card>`;
    this._hover(byYear, years, months, unit, numbers, group);
  }

  // The native charts show every series for the hovered month; so does this.
  _hover(byYear, years, months, unit, numbers, group) {
    const root = this.shadowRoot;
    const svg = root.querySelector("svg");
    const card = root.querySelector("ha-card");
    const band = root.querySelector(".hover");
    const tip = root.querySelector(".tip");
    const hide = () => {
      band.classList.remove("on");
      tip.classList.remove("on");
    };
    svg.addEventListener("pointermove", (event) => {
      const box = svg.getBoundingClientRect();
      const x = ((event.clientX - box.left) * WIDTH) / box.width;
      const month = Math.floor((x - PAD.left) / group);
      if (month < 0 || month > 11) {
        hide();
        return;
      }
      band.setAttribute("x", PAD.left + group * month);
      band.classList.add("on");
      const rows = years
        .map((year, i) => {
          const value = byYear.get(year)[month];
          if (value === null) return "";
          return `<div class="row"><span><span class="swatch" style="background:${COLORS[i]}"></span>${year}</span>` +
            `<span class="value">${numbers.format(value)} ${escape(unit)}</span></div>`;
        })
        .join("");
      tip.innerHTML = `<div class="month">${escape(months[month])}</div>${rows}`;
      tip.classList.add("on");
      const frame = card.getBoundingClientRect();
      const left = Math.min(event.clientX - frame.left + 16, frame.width - tip.offsetWidth - 8);
      tip.style.left = `${Math.max(8, left)}px`;
      tip.style.top = `${Math.max(8, event.clientY - frame.top - tip.offsetHeight - 12)}px`;
    });
    svg.addEventListener("pointerleave", hide);
  }
}

function escape(text) {
  return String(text).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

customElements.define("hass-energy-history-card", HassEnergyHistoryCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "hass-energy-history-card",
  name: "Energy settlement history",
  description: "One statistic by calendar month, this year over the years before it.",
});
