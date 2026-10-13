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
    view_settlement: "Settlement",
    view_usage: "Usage",
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
  },
  hu: {
    suggestion_title: "Energia elszámolás",
    listing_name: "Energia elszámolás",
    listing_description:
      "Az elszámolás számlaként, amit a ház fogyasztott, és merre tart az időszak.",
    view_settlement: "Elszámolás",
    view_usage: "Fogyasztás",
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
