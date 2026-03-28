const DATA_URL = "../data/japan-restaurants.json";

const LUNCH_BANDS = [
  { key: "under-5k", label: "Under JPY 5k", tier: "$" },
  { key: "5k-10k", label: "JPY 5k-10k", tier: "$$" },
  { key: "10k-20k", label: "JPY 10k-20k", tier: "$$$" },
  { key: "20k-plus", label: "JPY 20k+", tier: "$$$$" },
];

const DINNER_BANDS = [
  { key: "under-10k", label: "Under JPY 10k", tier: "$$" },
  { key: "10k-20k", label: "JPY 10k-20k", tier: "$$$" },
  { key: "20k-30k", label: "JPY 20k-30k", tier: "$$$$" },
  { key: "30k-plus", label: "JPY 30k+", tier: "$$$$$" },
];

const ROUTES = {
  all: {
    id: "all",
    label: "All",
    eyebrow: "Portfolio App",
    title: "All Destinations",
    description:
      "Global app shell for Amex dining discovery. The live dataset is Japan-first for now, so this route currently surfaces Japan while future markets are added.",
    note:
      "Use this as the combined explorer. Right now it shows the Japan MVP while the broader country dataset is still being built.",
    mapSummary:
      "This is the future combined route. The current live pins are the Japan MVP.",
    matcher: () => true,
    defaultView: [35.676, 137.5],
    defaultZoom: 5,
    downloads: [
      { label: "All Japan KML", href: "../data/kml/japan-all.kml", primary: true },
      { label: "Tokyo KML", href: "../data/kml/tokyo.kml" },
      { label: "Kyoto KML", href: "../data/kml/kyoto.kml" },
      { label: "Osaka KML", href: "../data/kml/osaka.kml" },
    ],
  },
  japan: {
    id: "japan",
    label: "Japan",
    eyebrow: "Japan MVP",
    title: "Japan Dining Explorer",
    description:
      "Map-first dining explorer for the current Japan restaurant set. Search by place, cuisine, price range, child policy, menu support, and reservation style.",
    note:
      "Japan is the first live market. The same app shell can expand later into Hong Kong, Australia, the UK, and a true all-country view.",
    mapSummary:
      "Japan-wide view across Tokyo, Kyoto, and Osaka. Pins stay on top and the full table sits below.",
    matcher: (record) => record.country === "Japan",
    defaultView: [35.676, 137.5],
    defaultZoom: 5,
    downloads: [
      { label: "All Japan KML", href: "../data/kml/japan-all.kml", primary: true },
      { label: "Tokyo KML", href: "../data/kml/tokyo.kml" },
      { label: "Kyoto KML", href: "../data/kml/kyoto.kml" },
      { label: "Osaka KML", href: "../data/kml/osaka.kml" },
    ],
  },
  tokyo: {
    id: "tokyo",
    label: "Tokyo",
    eyebrow: "City Route",
    title: "Tokyo Dining",
    description:
      "Focused route for Tokyo venues. Better when you already know the city and want to narrow by district, cuisine, price band, or family constraints.",
    note:
      "Tokyo is the densest part of the current Japan MVP, so this route is the clearest way to browse without being overwhelmed.",
    mapSummary:
      "Tokyo-only route. Use this when you want to stay inside one city and explore districts instead of the full Japan view.",
    matcher: (record) => record.country === "Japan" && record.city === "Tokyo",
    fixedCity: "Tokyo",
    defaultView: [35.6762, 139.6503],
    defaultZoom: 11,
    downloads: [
      { label: "Tokyo KML", href: "../data/kml/tokyo.kml", primary: true },
      { label: "All Japan KML", href: "../data/kml/japan-all.kml" },
    ],
  },
  kyoto: {
    id: "kyoto",
    label: "Kyoto",
    eyebrow: "City Route",
    title: "Kyoto Dining",
    description:
      "Focused Kyoto route for areas like Gion, Higashiyama, and Kodaiji or Kiyomizu. Useful when you want the map and table to stay calmer.",
    note:
      "Kyoto is smaller than Tokyo in count, so the table and map work well as a paired browse view here.",
    mapSummary:
      "Kyoto-only route centered on the live Pocket Concierge areas in the current dataset.",
    matcher: (record) => record.country === "Japan" && record.city === "Kyoto",
    fixedCity: "Kyoto",
    defaultView: [35.0116, 135.7681],
    defaultZoom: 12,
    downloads: [
      { label: "Kyoto KML", href: "../data/kml/kyoto.kml", primary: true },
      { label: "All Japan KML", href: "../data/kml/japan-all.kml" },
    ],
  },
  osaka: {
    id: "osaka",
    label: "Osaka",
    eyebrow: "City Route",
    title: "Osaka Dining",
    description:
      "Focused Osaka route for a cleaner city-level browse. Filter by cuisine, price tier, or reservation style without the wider Japan noise.",
    note:
      "Osaka is smaller than Tokyo but still benefits from city-level routing because it keeps both the map and the table easy to scan.",
    mapSummary:
      "Osaka-only route for the current Japan MVP city split.",
    matcher: (record) => record.country === "Japan" && record.city === "Osaka",
    fixedCity: "Osaka",
    defaultView: [34.6937, 135.5023],
    defaultZoom: 12,
    downloads: [
      { label: "Osaka KML", href: "../data/kml/osaka.kml", primary: true },
      { label: "All Japan KML", href: "../data/kml/japan-all.kml" },
    ],
  },
};

const state = {
  restaurants: [],
  scopeRecords: [],
  filtered: [],
  markers: new Map(),
  activeId: null,
  routeId: "japan",
  mobileToolbarOpen: false,
  tableOpen: false,
};

const map = L.map("map", {
  zoomControl: true,
  scrollWheelZoom: true,
}).setView([35.676, 137.5], 5);

L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
  attribution:
    '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>',
  subdomains: "abcd",
  maxZoom: 20,
}).addTo(map);

const routeEyebrow = document.getElementById("route-eyebrow");
const routeTitle = document.getElementById("route-title");
const routeDescription = document.getElementById("route-description");
const scopeNote = document.getElementById("scope-note");
const scopeNav = document.getElementById("scope-nav");
const routeLinks = [...scopeNav.querySelectorAll("[data-route]")];
const toolbar = document.getElementById("filter-toolbar");
const toolbarToggle = document.getElementById("toolbar-toggle");
const toolbarToggleMeta = document.getElementById("toolbar-toggle-meta");
const tablePanel = document.getElementById("results-table-panel");
const tableToggle = document.getElementById("table-toggle");
const tableToggleMeta = document.getElementById("table-toggle-meta");
const searchInput = document.getElementById("search-input");
const cityFilter = document.getElementById("city-filter");
const districtFilter = document.getElementById("district-filter");
const cuisineFilter = document.getElementById("cuisine-filter");
const lunchFilter = document.getElementById("lunch-filter");
const dinnerFilter = document.getElementById("dinner-filter");
const kidsFilter = document.getElementById("kids-filter");
const menuFilter = document.getElementById("menu-filter");
const reservationFilter = document.getElementById("reservation-filter");
const resetFiltersButton = document.getElementById("reset-filters");
const scopeCount = document.getElementById("scope-count");
const showingCount = document.getElementById("showing-count");
const mappedCount = document.getElementById("mapped-count");
const cityCount = document.getElementById("city-count");
const downloadStack = document.getElementById("download-stack");
const mapSummary = document.getElementById("map-summary");
const resultsText = document.getElementById("results-text");
const focusCard = document.getElementById("focus-card");
const tableSummary = document.getElementById("table-summary");
const mobileSummary = document.getElementById("mobile-summary");
const resultsTableBody = document.getElementById("results-table-body");
const mobileResultsList = document.getElementById("mobile-results-list");

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function uniqueValues(values) {
  return [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b));
}

function yens(min, max) {
  if (!min && !max) return null;
  if (min && max && min !== max) return `JPY ${min.toLocaleString()} - ${max.toLocaleString()}`;
  return `JPY ${(max || min).toLocaleString()}`;
}

function priceBandLabel(tier, label) {
  if (!tier && !label) return null;
  return [tier, label].filter(Boolean).join(" | ");
}

function kidLabel(value) {
  const labels = {
    kid_friendly: "Kid friendly",
    older_children_only: "Older kids only",
    teens_only: "Older kids only",
    older_kids_only: "Older kids only",
    policy_available: "Child rules listed",
    unknown: "No child policy listed",
  };
  return labels[value] || "No child policy listed";
}

function markerColor(city) {
  if (city === "Tokyo") return "#d6a44c";
  if (city === "Kyoto") return "#d38f5d";
  if (city === "Osaka") return "#5fb9a6";
  return "#78a8ff";
}

function priceMarkup(min, max, tier, label) {
  const range = yens(min, max);
  const band = priceBandLabel(tier, label);
  if (!range && !band) return '<span class="cell-muted">N/A</span>';

  const blocks = [];
  if (band) {
    blocks.push(`<div class="price-tier">${escapeHtml(band)}</div>`);
  }
  if (range) {
    blocks.push(`<div class="price-raw">${escapeHtml(range)}</div>`);
  }
  return blocks.join("");
}

function hasSourceCoordinates(record) {
  return record.lat != null && record.lng != null && record.coordinate_confidence === "source";
}

function focusLocationNote(record) {
  if (record.lat == null || record.lng == null) {
    return "This venue does not have a plotted pin yet. Use the official Pocket Concierge listing for location confirmation.";
  }

  if (hasSourceCoordinates(record)) {
    return "Pin comes from Pocket Concierge venue data. Still confirm the official listing before relying on it for dining-credit use.";
  }

  return "Pin uses approximate fallback mapping. Confirm the official Pocket Concierge listing before travelling to the venue.";
}

function createMarker(record) {
  if (record.lat == null || record.lng == null) return null;

  const dinnerBand = priceBandLabel(record.price_dinner_band_tier, record.price_dinner_band_label);
  const lunchBand = priceBandLabel(record.price_lunch_band_tier, record.price_lunch_band_label);
  const marker = L.circleMarker([record.lat, record.lng], {
    radius: 8,
    fillColor: markerColor(record.city),
    fillOpacity: 0.92,
    color: "#091018",
    weight: 2,
  });

  marker.bindPopup(`
    <div class="popup-card">
      <div class="popup-name">${escapeHtml(record.name)}</div>
      <div>${escapeHtml(record.city)} / ${escapeHtml(record.district || record.area_title)}</div>
      ${record.source_localized_address ? `<div>${escapeHtml(record.source_localized_address)}</div>` : ""}
      <div>${escapeHtml((record.cuisines || []).join(", ") || "Cuisine unknown")}</div>
      ${dinnerBand ? `<div>${escapeHtml(`Dinner band: ${dinnerBand}`)}</div>` : ""}
      ${yens(record.price_dinner_min_jpy, record.price_dinner_max_jpy) ? `<div>${escapeHtml(`Dinner: ${yens(record.price_dinner_min_jpy, record.price_dinner_max_jpy)}`)}</div>` : ""}
      ${lunchBand ? `<div>${escapeHtml(`Lunch band: ${lunchBand}`)}</div>` : ""}
      ${yens(record.price_lunch_min_jpy, record.price_lunch_max_jpy) ? `<div>${escapeHtml(`Lunch: ${yens(record.price_lunch_min_jpy, record.price_lunch_max_jpy)}`)}</div>` : ""}
      ${record.summary_official ? `<p>${escapeHtml(record.summary_official)}</p>` : ""}
      <div>${escapeHtml(record.map_pin_note || "")}</div>
      ${
        record.source_url
          ? `<p><a href="${escapeHtml(record.source_url)}" target="_blank" rel="noopener">Pocket Concierge</a></p>`
          : ""
      }
    </div>
  `);
  marker.on("click", () => {
    setActiveRecord(record.id);
  });
  return marker;
}

function fillSelect(select, values, placeholder) {
  const current = select.value;
  select.innerHTML = `<option value="">${placeholder}</option>`;
  values.forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.appendChild(option);
  });
  if (values.includes(current)) {
    select.value = current;
  }
}

function fillBandSelect(select, bands, presentKeys, placeholder) {
  const current = select.value;
  select.innerHTML = `<option value="">${placeholder}</option>`;
  bands
    .filter((band) => presentKeys.has(band.key))
    .forEach((band) => {
      const option = document.createElement("option");
      option.value = band.key;
      option.textContent = `${band.tier} | ${band.label}`;
      select.appendChild(option);
    });
  if (presentKeys.has(current)) {
    select.value = current;
  }
}

function currentRoute() {
  return ROUTES[state.routeId] || ROUTES.japan;
}

function activeFilterCount() {
  const route = currentRoute();
  let count = 0;
  if (searchInput.value.trim()) count += 1;
  if (!route.fixedCity && cityFilter.value) count += 1;
  if (districtFilter.value) count += 1;
  if (cuisineFilter.value) count += 1;
  if (lunchFilter.value) count += 1;
  if (dinnerFilter.value) count += 1;
  if (kidsFilter.value) count += 1;
  if (menuFilter.value) count += 1;
  if (reservationFilter.value) count += 1;
  return count;
}

function setToolbarOpen(isOpen) {
  state.mobileToolbarOpen = isOpen;
  toolbar.classList.toggle("is-open", isOpen);
  toolbarToggle.setAttribute("aria-expanded", String(isOpen));
  const icon = toolbarToggle.querySelector(".toolbar-toggle-icon");
  if (icon) {
    icon.textContent = isOpen ? "-" : "+";
  }
}

function renderToolbarToggle() {
  const count = activeFilterCount();
  toolbarToggleMeta.textContent =
    count > 0 ? `${count} active filter${count === 1 ? "" : "s"}` : "All filters off";
}

function setTableOpen(isOpen) {
  state.tableOpen = isOpen;
  tablePanel.classList.toggle("is-open", isOpen);
  tableToggle.setAttribute("aria-expanded", String(isOpen));
  const icon = tableToggle.querySelector(".toolbar-toggle-icon");
  if (icon) {
    icon.textContent = isOpen ? "-" : "+";
  }
}

function renderTableToggle() {
  const count = state.filtered.length;
  tableToggleMeta.textContent = state.tableOpen
    ? `Showing ${count} detailed row${count === 1 ? "" : "s"}`
    : `${count} row${count === 1 ? "" : "s"} available for deeper scanning`;
}

function activeRecord() {
  return state.filtered.find((record) => record.id === state.activeId) || null;
}

function resolveRouteFromHash() {
  const hash = window.location.hash.replace(/^#\/?/, "").trim().toLowerCase();
  if (ROUTES[hash]) {
    return hash;
  }
  return "japan";
}

function renderRouteShell(route) {
  routeEyebrow.textContent = route.eyebrow;
  routeTitle.textContent = route.title;
  routeDescription.textContent = route.description;
  scopeNote.textContent = route.note;
  mapSummary.textContent = route.mapSummary;

  routeLinks.forEach((link) => {
    link.classList.toggle("active", link.dataset.route === route.id);
  });

  downloadStack.innerHTML = "";
  route.downloads.forEach((item) => {
    const link = document.createElement("a");
    link.className = `download-btn${item.primary ? " primary" : ""}`;
    link.href = item.href;
    link.download = "";
    link.textContent = item.label;
    downloadStack.appendChild(link);
  });
}

function resetFilterControls() {
  const route = currentRoute();
  searchInput.value = "";
  districtFilter.value = "";
  cuisineFilter.value = "";
  lunchFilter.value = "";
  dinnerFilter.value = "";
  kidsFilter.value = "";
  menuFilter.value = "";
  reservationFilter.value = "";
  cityFilter.value = route.fixedCity || "";
}

function refreshFilterOptions() {
  const route = currentRoute();
  const scopeRecords = state.scopeRecords;
  const selectedCity = route.fixedCity || cityFilter.value;

  if (route.fixedCity) {
    cityFilter.innerHTML = `<option value="${route.fixedCity}">${route.fixedCity}</option>`;
    cityFilter.value = route.fixedCity;
    cityFilter.disabled = true;
  } else {
    cityFilter.disabled = false;
    fillSelect(cityFilter, uniqueValues(scopeRecords.map((record) => record.city)), "All cities");
  }

  const districtPool = scopeRecords.filter((record) => {
    if (!selectedCity) return true;
    return record.city === selectedCity;
  });

  fillSelect(
    districtFilter,
    uniqueValues(districtPool.map((record) => record.district || record.area_title)),
    "All districts"
  );
  fillSelect(
    cuisineFilter,
    uniqueValues(scopeRecords.flatMap((record) => record.cuisines || [])),
    "All cuisines"
  );
  fillBandSelect(
    lunchFilter,
    LUNCH_BANDS,
    new Set(scopeRecords.map((record) => record.price_lunch_band_key).filter(Boolean)),
    "All lunch bands"
  );
  fillBandSelect(
    dinnerFilter,
    DINNER_BANDS,
    new Set(scopeRecords.map((record) => record.price_dinner_band_key).filter(Boolean)),
    "All dinner bands"
  );
  fillSelect(
    reservationFilter,
    uniqueValues(scopeRecords.map((record) => record.reservation_type)),
    "All reservation styles"
  );
}

function ensureActiveRecord() {
  if (!state.filtered.length) {
    state.activeId = null;
    return;
  }
  if (!state.filtered.some((record) => record.id === state.activeId)) {
    state.activeId = state.filtered[0].id;
  }
}

function filterRestaurants() {
  const search = searchInput.value.trim().toLowerCase();
  const route = currentRoute();
  const city = route.fixedCity || cityFilter.value;
  const district = districtFilter.value;
  const cuisine = cuisineFilter.value;
  const lunchBand = lunchFilter.value;
  const dinnerBand = dinnerFilter.value;
  const kids = kidsFilter.value;
  const menu = menuFilter.value;
  const reservation = reservationFilter.value;

  state.filtered = state.scopeRecords.filter((record) => {
    if (city && record.city !== city) return false;
    if (district && (record.district || record.area_title) !== district) return false;
    if (cuisine && !(record.cuisines || []).includes(cuisine)) return false;
    if (lunchBand && record.price_lunch_band_key !== lunchBand) return false;
    if (dinnerBand && record.price_dinner_band_key !== dinnerBand) return false;
    if (kids === "older_kids_only" && !["older_children_only", "teens_only"].includes(record.child_policy_norm)) {
      return false;
    }
    if (kids && kids !== "older_kids_only" && record.child_policy_norm !== kids) return false;
    if (menu === "yes" && !record.english_menu) return false;
    if (menu === "no" && record.english_menu) return false;
    if (reservation && record.reservation_type !== reservation) return false;
    if (search && !(record.search_text || "").includes(search)) return false;
    return true;
  });

  ensureActiveRecord();
  renderStats();
  renderMarkers();
  renderFocusCard();
  renderTable();
  renderMobileCards();
}

function renderStats() {
  const route = currentRoute();
  const filteredMapped = state.filtered.filter((record) => record.lat != null && record.lng != null).length;
  const scopeCities = uniqueValues(state.scopeRecords.map((record) => record.city));

  scopeCount.textContent = state.scopeRecords.length;
  showingCount.textContent = state.filtered.length;
  mappedCount.textContent = filteredMapped;
  cityCount.textContent = scopeCities.length;

  const resultLine = `${state.filtered.length} result${state.filtered.length === 1 ? "" : "s"} in ${route.label}`;
  resultsText.textContent = resultLine;
  tableSummary.textContent = `Showing ${state.filtered.length} of ${state.scopeRecords.length} venues in the current route.`;
  mobileSummary.textContent = tableSummary.textContent;
  mapSummary.textContent = `${route.mapSummary} ${filteredMapped} mapped pin${filteredMapped === 1 ? "" : "s"} in the current filtered view.`;
  renderToolbarToggle();
  renderTableToggle();
}

function renderMarkers() {
  const route = currentRoute();
  state.markers.forEach((marker) => map.removeLayer(marker));
  state.markers.clear();

  const bounds = [];
  state.filtered.forEach((record) => {
    const marker = createMarker(record);
    if (!marker) return;
    marker.addTo(map);
    state.markers.set(record.id, marker);
    bounds.push(marker.getLatLng());
  });

  if (bounds.length) {
    map.fitBounds(bounds, { padding: [34, 34], maxZoom: 12 });
  } else {
    map.setView(route.defaultView, route.defaultZoom);
  }
}

function renderFocusCard() {
  const record = activeRecord();
  if (!record) {
    focusCard.innerHTML = '<div class="empty-state">No venue matches the current route and filters.</div>';
    return;
  }

  const tags = [
    `<span class="badge gold">${escapeHtml(record.city)}</span>`,
    record.lat != null && record.lng != null
      ? `<span class="badge ${hasSourceCoordinates(record) ? "green" : "amber"}">${escapeHtml(
          hasSourceCoordinates(record) ? "Source-backed pin" : "Approximate pin"
        )}</span>`
      : "",
    record.price_dinner_band_tier && record.price_dinner_band_label
      ? `<span class="badge amber">${escapeHtml(priceBandLabel(record.price_dinner_band_tier, record.price_dinner_band_label))}</span>`
      : "",
    record.price_lunch_band_tier && record.price_lunch_band_label
      ? `<span class="badge blue">${escapeHtml(priceBandLabel(record.price_lunch_band_tier, record.price_lunch_band_label))}</span>`
      : "",
    `<span class="badge">${escapeHtml(kidLabel(record.child_policy_norm))}</span>`,
    record.english_menu ? '<span class="badge green">English menu</span>' : "",
    record.reservation_type ? `<span class="badge purple">${escapeHtml(record.reservation_type)}</span>` : "",
  ]
    .filter(Boolean)
    .join("");

  focusCard.innerHTML = `
    <div class="focus-kicker">${escapeHtml(record.city)} / ${escapeHtml(record.district || record.area_title)}</div>
    <h3 class="focus-title">${escapeHtml(record.name)}</h3>
    <div class="focus-subtitle">${escapeHtml((record.cuisines || []).join(", ") || "Cuisine unknown")}</div>
    ${
      record.source_localized_address
        ? `<div class="focus-address">${escapeHtml(record.source_localized_address)}</div>`
        : ""
    }
    ${
      record.nearest_stations && record.nearest_stations.length
        ? `<div class="focus-transit">${escapeHtml(record.nearest_stations.join(" | "))}</div>`
        : ""
    }
    <div class="focus-tags">${tags}</div>
    <p class="focus-summary">${escapeHtml(record.summary_official || "No official summary available.")}</p>
    <div class="price-grid">
      <div class="price-card">
        <span class="price-label">Dinner</span>
        ${priceMarkup(
          record.price_dinner_min_jpy,
          record.price_dinner_max_jpy,
          record.price_dinner_band_tier,
          record.price_dinner_band_label
        )}
      </div>
      <div class="price-card">
        <span class="price-label">Lunch</span>
        ${priceMarkup(
          record.price_lunch_min_jpy,
          record.price_lunch_max_jpy,
          record.price_lunch_band_tier,
          record.price_lunch_band_label
        )}
      </div>
    </div>
    <div class="focus-note">${escapeHtml(focusLocationNote(record))}</div>
    <div class="focus-actions">
      ${
        record.source_google_map_url
          ? `<a class="inline-link" href="${escapeHtml(record.source_google_map_url)}" target="_blank" rel="noopener">Open source map</a>`
          : ""
      }
      ${
        record.source_url
          ? `<a class="inline-link" href="${escapeHtml(record.source_url)}" target="_blank" rel="noopener">Open Pocket Concierge</a>`
          : ""
      }
      ${
        record.lat != null && record.lng != null
          ? `<button type="button" class="ghost-btn secondary" data-focus-map="true">Center on map</button>`
          : ""
      }
    </div>
  `;

  const centerButton = focusCard.querySelector("[data-focus-map='true']");
  if (centerButton) {
    centerButton.addEventListener("click", () => {
      focusActiveRecordOnMap();
    });
  }
}

function renderTable() {
  if (!state.filtered.length) {
    resultsTableBody.innerHTML =
      '<tr><td colspan="8" class="empty-table">No venues match the current route and filters.</td></tr>';
    return;
  }

  resultsTableBody.innerHTML = "";
  state.filtered.forEach((record) => {
    const row = document.createElement("tr");
    row.className = record.id === state.activeId ? "active" : "";
    row.addEventListener("click", () => {
      setActiveRecord(record.id);
      focusActiveRecordOnMap();
    });

    row.innerHTML = `
      <td>
        <div class="table-title">${escapeHtml(record.name)}</div>
        ${
          record.nearest_stations && record.nearest_stations.length
            ? `<div class="table-sub">${escapeHtml(record.nearest_stations[0])}</div>`
            : ""
        }
      </td>
      <td>
        <div>${escapeHtml(record.city)}</div>
        <div class="table-sub">${escapeHtml(record.source_localized_address || record.district || record.area_title)}</div>
      </td>
      <td>${escapeHtml((record.cuisines || []).join(", ") || "Unknown")}</td>
      <td>${priceMarkup(
        record.price_dinner_min_jpy,
        record.price_dinner_max_jpy,
        record.price_dinner_band_tier,
        record.price_dinner_band_label
      )}</td>
      <td>${priceMarkup(
        record.price_lunch_min_jpy,
        record.price_lunch_max_jpy,
        record.price_lunch_band_tier,
        record.price_lunch_band_label
      )}</td>
      <td>${escapeHtml(kidLabel(record.child_policy_norm))}</td>
      <td>${record.english_menu ? "Yes" : "No"}</td>
      <td>${escapeHtml(record.reservation_type || "N/A")}</td>
    `;
    resultsTableBody.appendChild(row);
  });
}

function renderMobileCards() {
  if (!state.filtered.length) {
    mobileResultsList.innerHTML =
      '<div class="empty-state">No venues match the current route and filters.</div>';
    return;
  }

  mobileResultsList.innerHTML = "";
  state.filtered.forEach((record) => {
    const card = document.createElement("article");
    card.className = `mobile-card${record.id === state.activeId ? " active" : ""}`;
    const dinnerBand = priceBandLabel(record.price_dinner_band_tier, record.price_dinner_band_label);
    const lunchBand = priceBandLabel(record.price_lunch_band_tier, record.price_lunch_band_label);

    card.innerHTML = `
      <div class="mobile-card-top">
        <div>
          <div class="focus-kicker">${escapeHtml(record.city)} / ${escapeHtml(record.district || record.area_title)}</div>
          <h3 class="mobile-card-title">${escapeHtml(record.name)}</h3>
          <div class="mobile-card-subtitle">${escapeHtml((record.cuisines || []).join(", ") || "Cuisine unknown")}</div>
        </div>
      </div>
      ${
        record.source_localized_address
          ? `<div class="mobile-card-address">${escapeHtml(record.source_localized_address)}</div>`
          : ""
      }
      ${
        record.nearest_stations && record.nearest_stations.length
          ? `<div class="mobile-card-transit">${escapeHtml(record.nearest_stations.join(" | "))}</div>`
          : ""
      }
      <div class="venue-tags">
        ${dinnerBand ? `<span class="badge amber">${escapeHtml(dinnerBand)}</span>` : ""}
        ${lunchBand ? `<span class="badge blue">${escapeHtml(lunchBand)}</span>` : ""}
        <span class="badge">${escapeHtml(kidLabel(record.child_policy_norm))}</span>
        ${record.english_menu ? '<span class="badge green">English menu</span>' : ""}
      </div>
      <div class="mobile-price-grid">
        <div class="mobile-price-card">
          <span class="price-label">Dinner</span>
          ${priceMarkup(
            record.price_dinner_min_jpy,
            record.price_dinner_max_jpy,
            record.price_dinner_band_tier,
            record.price_dinner_band_label
          )}
        </div>
        <div class="mobile-price-card">
          <span class="price-label">Lunch</span>
          ${priceMarkup(
            record.price_lunch_min_jpy,
            record.price_lunch_max_jpy,
            record.price_lunch_band_tier,
            record.price_lunch_band_label
          )}
        </div>
      </div>
      <div class="mobile-card-actions">
        <button type="button" class="ghost-btn secondary" data-mobile-focus="${escapeHtml(record.id)}">
          Show on map
        </button>
        ${
          record.source_google_map_url
            ? `<a class="inline-link" href="${escapeHtml(record.source_google_map_url)}" target="_blank" rel="noopener">Source map</a>`
            : ""
        }
      </div>
    `;

    const focusButton = card.querySelector("[data-mobile-focus]");
    if (focusButton) {
      focusButton.addEventListener("click", () => {
        setActiveRecord(record.id);
        focusActiveRecordOnMap();
        if (window.innerWidth <= 820) {
          const mapTop = map.getContainer().getBoundingClientRect().top + window.scrollY - 16;
          window.scrollTo({ top: Math.max(mapTop, 0), behavior: "smooth" });
        }
      });
    }

    mobileResultsList.appendChild(card);
  });
}

function setActiveRecord(id) {
  state.activeId = id;
  renderFocusCard();
  renderTable();
  renderMobileCards();
}
function focusActiveRecordOnMap() {
  const record = activeRecord();
  if (!record) return;
  const marker = state.markers.get(record.id);
  if (!marker) return;
  map.flyTo(marker.getLatLng(), Math.max(map.getZoom(), 13), { duration: 0.6 });
  marker.openPopup();
}

function applyRoute(routeId) {
  state.routeId = ROUTES[routeId] ? routeId : "japan";
  const route = currentRoute();
  state.scopeRecords = state.restaurants.filter((record) => route.matcher(record));
  state.activeId = null;
  renderRouteShell(route);
  resetFilterControls();
  refreshFilterOptions();
  filterRestaurants();
}

function handleHashRoute() {
  applyRoute(resolveRouteFromHash());
}

async function init() {
  const response = await fetch(DATA_URL);
  state.restaurants = await response.json();
  state.restaurants.forEach((record) => {
    record.search_text = (record.search_text || "").toLowerCase();
  });

  setToolbarOpen(false);
  setTableOpen(false);
  handleHashRoute();
  if (!window.location.hash) {
    window.location.hash = "#/japan";
  }
}

searchInput.addEventListener("input", filterRestaurants);
cityFilter.addEventListener("change", () => {
  refreshFilterOptions();
  filterRestaurants();
});

[
  districtFilter,
  cuisineFilter,
  lunchFilter,
  dinnerFilter,
  kidsFilter,
  menuFilter,
  reservationFilter,
].forEach((element) => {
  element.addEventListener("change", filterRestaurants);
});

resetFiltersButton.addEventListener("click", () => {
  resetFilterControls();
  refreshFilterOptions();
  filterRestaurants();
});

toolbarToggle.addEventListener("click", () => {
  setToolbarOpen(!state.mobileToolbarOpen);
});

tableToggle.addEventListener("click", () => {
  setTableOpen(!state.tableOpen);
  renderTableToggle();
});

window.addEventListener("hashchange", handleHashRoute);

init().catch((error) => {
  console.error(error);
  focusCard.innerHTML =
    '<div class="empty-state">Data failed to load. Run the sync script and serve this folder over HTTP.</div>';
  resultsText.textContent = "Load failed";
  tableSummary.textContent = "Load failed";
  mobileSummary.textContent = "Load failed";
  resultsTableBody.innerHTML =
    '<tr><td colspan="8" class="empty-table">The dataset failed to load.</td></tr>';
  mobileResultsList.innerHTML =
    '<div class="empty-state">The dataset failed to load.</div>';
});
