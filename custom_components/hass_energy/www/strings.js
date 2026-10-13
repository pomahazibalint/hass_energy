// The dashboard's own words, in the languages the integration speaks.
//
// What Home Assistant renders, entity names and repairs, is translated in
// the integration's translations directory; what the strategy and the cards
// write themselves is translated here, from the user's language in hass.

const STRINGS = {
  en: {
    suggestion_title: "Energy settlement",
    listing_name: "Energy settlement",
    listing_description:
      "The settlement as an invoice, what the house used, and where the period is heading.",
    view_energy: "Energy",
    view_costs: "Costs",
    view_history: "History",
    no_entry:
      "No Energy Settlement metering point is set up. Add one under Settings > Devices & services, and this dashboard fills itself.",
    outlook: "Where the period is heading",
    solar_battery: "Solar and battery",
    house_consumption: "House consumption",
    cost_and_value: "Consumption cost and solar value",
    devices_period: "Devices this settlement period",
    devices_range: "Device cost over the selected range",
    grid_import: "Grid import by month",
    grid_export: "Grid export by month",
    house_by_month: "House consumption by month",
    past_settlements: "Past settlements",
    line_energy_cost: "Grid energy",
    line_solar_value: "What the panels avoided",
    line_surplus_value: "Surplus owed by the supplier",
    line_standing_charge: "Standing charge",
    line_vat: "VAT",
    line_total_payable: "Total payable",
    line_net_position: "Net position",
    line_allowance_remaining: "Allowance remaining",
    line_period_days: "Days into the period",
    period_from: "Settlement period from {date}",
    sources_footer: "Sources are named in the {link}.",
    sources_link: "energy dashboard settings",
    device: "Device",
    energy: "Energy",
    cost: "Cost",
    rest_of_house: "Rest of the house",
    house: "House",
    no_devices: "No device is named in the energy dashboard settings, or none has reported yet.",
    per_month: "{unit} per month",
    nothing_recorded: "Nothing recorded yet for this statistic.",
    read_error: "Could not read the statistics: {error}",
    // How a figure came to be, from the figures behind it.
    how: "How?",
    behind_energy_cost:
      "{subsidized_kwh} kWh at the subsidized price and {market_kwh} kWh at the market price, before VAT.",
    behind_solar_value:
      "Without the panels the net position would be {without}; it is {position}. {kept} kWh of their production stayed in the house, {exported} kWh was exported.",
    behind_surplus_value: "{kwh} kWh fed in beyond what netting absorbed, at the feed-in price, outside VAT.",
    behind_standing_charge: "{months} months at {per_month} a month, before VAT.",
    behind_vat: "{percent}% on {net_total} of energy and standing charge.",
    behind_total_payable: "{energy} energy, {standing} standing charge, {vat} VAT.",
    behind_net_position: "{payable} payable, less {surplus} the supplier owes for surplus.",
    behind_allowance_remaining: "{used} of {allowance} kWh used; the allowance is {days} days' worth.",
    behind_period_days: "From {start}; a nominal year to {end} until the meter is read.",
    behind_consumption:
      "{energy} kWh. Costed hour by hour at what not consuming would have saved: {parts}. {average} per kWh on average.",
    behind_device:
      "{energy} kWh, {share}% of the house. Its share of each hour at what not consuming would have saved: {parts}. {average} per kWh on average.",
    behind_device_capped: " In {hours} hours the meter claimed more than the house used; capped there.",
    part_subsidized: "{kwh} kWh at the subsidized price with VAT ({price})",
    part_market: "{kwh} kWh at the market price with VAT ({price})",
    part_feed_in: "{kwh} kWh at the feed-in price ({price})",
    part_mixed: "{kwh} kWh in hours that straddled two prices",
    parts_joiner: ", ",
    parts_none: "nothing yet",
  },
  hu: {
    suggestion_title: "Energia elszámolás",
    listing_name: "Energia elszámolás",
    listing_description:
      "Az elszámolás számlaként, amit a ház fogyasztott, és merre tart az időszak.",
    view_energy: "Energia",
    view_costs: "Költségek",
    view_history: "Előzmények",
    no_entry:
      "Nincs beállított Energia elszámolás mérési pont. Adj hozzá egyet a Beállítások > Eszközök és szolgáltatások alatt, és ez az irányítópult magától feltöltődik.",
    outlook: "Merre tart az időszak",
    solar_battery: "Napelem és akkumulátor",
    house_consumption: "A ház fogyasztása",
    cost_and_value: "A fogyasztás költsége és a napelemek értéke",
    devices_period: "Eszközök ebben az elszámolási időszakban",
    devices_range: "Eszközök költsége a kiválasztott időszakban",
    grid_import: "Hálózati vételezés havonta",
    grid_export: "Hálózati betáplálás havonta",
    house_by_month: "A ház fogyasztása havonta",
    past_settlements: "Korábbi elszámolások",
    line_energy_cost: "Hálózati energia",
    line_solar_value: "Amit a napelemek megtakarítottak",
    line_surplus_value: "A szolgáltató által fizetendő többlet",
    line_standing_charge: "Alapdíj",
    line_vat: "ÁFA",
    line_total_payable: "Fizetendő összeg",
    line_net_position: "Egyenleg",
    line_allowance_remaining: "Fennmaradó keret",
    line_period_days: "Eltelt napok",
    period_from: "Elszámolási időszak kezdete: {date}",
    sources_footer: "A forrásokat az {link} lehet megadni.",
    sources_link: "energia-irányítópult beállításaiban",
    device: "Eszköz",
    energy: "Energia",
    cost: "Költség",
    rest_of_house: "A ház többi része",
    house: "Ház",
    no_devices:
      "Nincs eszköz megadva az energia-irányítópult beállításaiban, vagy még egyik sem jelentett.",
    per_month: "{unit} havonta",
    nothing_recorded: "Ehhez a statisztikához még nincs rögzített adat.",
    read_error: "Nem sikerült beolvasni a statisztikát: {error}",
    how: "Hogyan?",
    behind_energy_cost:
      "{subsidized_kwh} kWh rezsicsökkentett áron és {market_kwh} kWh piaci áron, ÁFA nélkül.",
    behind_solar_value:
      "A napelemek nélkül az egyenleg {without} lenne; így {position}. A termelésükből {kept} kWh maradt a házban, {exported} kWh ment a hálózatba.",
    behind_surplus_value: "{kwh} kWh a nettósításon felül betáplálva, betáplálási áron, ÁFA-körön kívül.",
    behind_standing_charge: "{months} hónap, havi {per_month}, ÁFA nélkül.",
    behind_vat: "{percent}% az energia és az alapdíj {net_total} összegére.",
    behind_total_payable: "{energy} energia, {standing} alapdíj, {vat} ÁFA.",
    behind_net_position: "{payable} fizetendő, mínusz {surplus}, amit a szolgáltató a többletért fizet.",
    behind_allowance_remaining: "{used} / {allowance} kWh felhasználva; a keret {days} napra jár.",
    behind_period_days: "{start} óta; névlegesen egy év, {end}-ig, amíg a mérőt le nem olvassák.",
    behind_consumption:
      "{energy} kWh. Óránként azon az áron, amennyit a nem fogyasztás megtakarított volna: {parts}. Átlagosan {average} kWh-nként.",
    behind_device:
      "{energy} kWh, a ház {share}%-a. Minden órában a ráeső rész azon az áron, amennyit a nem fogyasztás megtakarított volna: {parts}. Átlagosan {average} kWh-nként.",
    behind_device_capped: " {hours} órában a mérő többet mutatott, mint a ház fogyasztása; ott a ház értékére korlátozva.",
    part_subsidized: "{kwh} kWh rezsicsökkentett áron, ÁFÁ-val ({price})",
    part_market: "{kwh} kWh piaci áron, ÁFÁ-val ({price})",
    part_feed_in: "{kwh} kWh betáplálási áron ({price})",
    part_mixed: "{kwh} kWh két ár közé eső órákban",
    parts_joiner: ", ",
    parts_none: "még semmi",
  },
};

export function languageOf(hass) {
  const tag = hass?.locale?.language || hass?.language || document.documentElement.lang || navigator.language || "en";
  return String(tag).toLowerCase().split("-")[0];
}

export function t(hass, key, values = {}) {
  const language = languageOf(hass);
  const text = (STRINGS[language] || STRINGS.en)[key] ?? STRINGS.en[key] ?? key;
  return text.replace(/\{(\w+)\}/g, (match, name) => (name in values ? String(values[name]) : match));
}

export function monthNames(hass) {
  const format = new Intl.DateTimeFormat(languageOf(hass), { month: "short" });
  return Array.from({ length: 12 }, (_, month) => format.format(new Date(2000, month, 1)));
}

// The sentence behind a cost that was priced hour by hour: the house's or
// a device's, from the figures the sensor carries.
export function partsOf(hass, attributes, unit) {
  const numbers = new Intl.NumberFormat(languageOf(hass), { maximumFractionDigits: 1 });
  const money = (value) => `${numbers.format(value)} ${unit}`.trim();
  const parts = [
    ["part_subsidized", attributes.kwh_at_subsidized, attributes.subsidized_price_with_vat],
    ["part_market", attributes.kwh_at_market, attributes.market_price_with_vat],
    ["part_feed_in", attributes.kwh_at_feed_in, attributes.feed_in_price],
    ["part_mixed", attributes.kwh_mixed, null],
  ]
    .filter(([, kwh]) => Number(kwh) > 0.0005)
    .map(([key, kwh, price]) =>
      t(hass, key, { kwh: numbers.format(Number(kwh)), price: price === null ? "" : money(Number(price)) })
    );
  return parts.length ? parts.join(t(hass, "parts_joiner")) : t(hass, "parts_none");
}
