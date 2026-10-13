// The long view: one statistic by calendar month, this year over the years
// before it, so the same month last year sits beside this one and the
// seasonal profile shows across years.
//
// Read from the recorder's monthly statistics over the websocket, which is
// the same long-term record the native cards read. Drawn as plain SVG: the
// plan adds a chart library only when a card needs one, and grouped bars do
// not.

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const COLORS = ["var(--primary-color)", "var(--accent-color, #ff9800)", "var(--secondary-text-color)", "var(--disabled-color, #bdbdbd)"];
const WIDTH = 600;
const HEIGHT = 220;
const PAD = { top: 12, right: 8, bottom: 28, left: 44 };

const STYLE = `
  :host { display: block; }
  ha-card { padding: 0 16px 8px; }
  h1 { font-size: var(--ha-card-header-font-size, 24px); font-weight: normal;
       margin: 0; padding: 16px 0 8px; color: var(--ha-card-header-color, var(--primary-text-color)); }
  svg { width: 100%; height: auto; display: block; }
  text { fill: var(--secondary-text-color); font-size: 11px; }
  .grid { stroke: var(--divider-color); stroke-width: 1; }
  .legend { display: flex; gap: 16px; padding: 8px 0; color: var(--secondary-text-color); font-size: 0.9em; }
  .swatch { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 6px; vertical-align: middle; }
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
    const hour = Math.floor(Date.now() / 3600000);
    if (this._loaded !== hour) {
      this._loaded = hour;
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
    const title = this._config.title ? `<h1>${escape(this._config.title)}</h1>` : "";
    if (error || !byYear || !byYear.size) {
      const message = error ? `Could not read the statistics: ${error}` : "Nothing recorded yet for this statistic.";
      this.shadowRoot.innerHTML = `<style>${STYLE}</style><ha-card>${title}<div class="empty">${escape(message)}</div></ha-card>`;
      return;
    }
    const years = [...byYear.keys()].sort();
    const unit = this._config.unit || "kWh";
    const top = Math.max(1, ...years.flatMap((year) => byYear.get(year).map((v) => v || 0)));
    const plotWidth = WIDTH - PAD.left - PAD.right;
    const plotHeight = HEIGHT - PAD.top - PAD.bottom;
    const group = plotWidth / 12;
    const bar = (group * 0.8) / years.length;
    const scale = (value) => plotHeight - (plotHeight * value) / top;

    const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => {
      const y = PAD.top + scale(f * top);
      return `<line class="grid" x1="${PAD.left}" x2="${WIDTH - PAD.right}" y1="${y}" y2="${y}"/>` +
        `<text x="${PAD.left - 6}" y="${y + 4}" text-anchor="end">${tidy(f * top)}</text>`;
    });
    const labels = MONTHS.map((name, m) =>
      `<text x="${PAD.left + group * (m + 0.5)}" y="${HEIGHT - 8}" text-anchor="middle">${name}</text>`);
    const bars = [];
    years.forEach((year, i) => {
      byYear.get(year).forEach((value, m) => {
        if (value === null) return;
        const x = PAD.left + group * m + group * 0.1 + bar * i;
        const y = PAD.top + scale(value);
        bars.push(`<rect x="${x}" y="${y}" width="${bar}" height="${plotHeight - scale(value) + 0}" fill="${COLORS[i]}" rx="1">` +
          `<title>${MONTHS[m]} ${year}: ${tidy(value)} ${escape(unit)}</title></rect>`);
      });
    });
    const legend = years.map((year, i) =>
      `<span><span class="swatch" style="background:${COLORS[i]}"></span>${year}</span>`).join("");
    this.shadowRoot.innerHTML =
      `<style>${STYLE}</style><ha-card>${title}` +
      `<svg viewBox="0 0 ${WIDTH} ${HEIGHT}" role="img" aria-label="${escape(this._config.title || "History")}">` +
      `${ticks.join("")}${bars.join("")}${labels.join("")}</svg>` +
      `<div class="legend">${legend}<span>${escape(unit)} per month</span></div></ha-card>`;
  }
}

function tidy(value) {
  return value >= 100 ? Math.round(value).toLocaleString() : value.toFixed(1);
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
