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

const PROGRAMS = {
  dining: {
    id: "dining",
    label: "Dining",
    title: "Dining",
    description:
      "Map-first planning for Amex dining benefits, with Japan live now and broader country coverage added over time.",
    defaultRoute: "dining/japan",
  },
  stays: {
    id: "stays",
    label: "Plat Stay",
    title: "Plat Stay",
    description:
      "Hotel and resort planner with travel-date checks, blackout-date filtering, and property mapping from official Plat Stay sources.",
    defaultRoute: "stays",
  },
  "love-dining": {
    id: "love-dining",
    label: "Love Dining",
    title: "Love Dining",
    description:
      "Singapore dining explorer for restaurant and hotel partners, with savings rules, outlet details, and direct links into the official terms.",
    defaultRoute: "love-dining",
  },
  "10xcelerator": {
    id: "10xcelerator",
    label: "10Xcelerator",
    title: "10Xcelerator",
    description:
      "Partner and points-earning planner for bonus categories and merchants, with outlet mapping only where location data can be verified.",
    defaultRoute: "10xcelerator",
  },
};

const ROUTES = {
  "dining/world": {
    id: "dining/world",
    programId: "dining",
    label: "World",
    eyebrow: "Dining / World Shell",
    title: "World Dining Explorer",
    description:
      "Top-level dining shell for planning across countries. Japan is live now while broader market coverage is still being built and verified.",
    note:
      "Start here, then narrow into Japan and city routes. As more markets ship, this becomes the true global dining overview.",
    mapSummary:
      "World dining shell. The current live pins are the Japan dataset while broader country ingestion is being built.",
    matcher: () => true,
    defaultView: [24.5, 132],
    defaultZoom: 3,
    downloads: [
      { label: "All Japan KML", href: "../data/kml/japan-all.kml", primary: true },
      { label: "Tokyo KML", href: "../data/kml/tokyo.kml" },
      { label: "Kyoto KML", href: "../data/kml/kyoto.kml" },
      { label: "Osaka KML", href: "../data/kml/osaka.kml" },
    ],
  },
  "dining/japan": {
    id: "dining/japan",
    programId: "dining",
    label: "Japan",
    eyebrow: "Dining / Japan",
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
  "dining/tokyo": {
    id: "dining/tokyo",
    programId: "dining",
    label: "Tokyo",
    eyebrow: "Dining / Tokyo",
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
  "dining/kyoto": {
    id: "dining/kyoto",
    programId: "dining",
    label: "Kyoto",
    eyebrow: "Dining / Kyoto",
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
  "dining/osaka": {
    id: "dining/osaka",
    programId: "dining",
    label: "Osaka",
    eyebrow: "Dining / Osaka",
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
  stays: {
    id: "stays",
    programId: "stays",
    label: "Overview",
    eyebrow: "Plat Stay / Sprint 2",
    title: "Plat Stay Explorer",
    description:
      "Date-aware stay planner for Platinum Stay properties. The first version will let people key in travel dates, knock out blackout conflicts, and keep only the remaining properties on the map.",
    briefTitle: "Plat Stay Buildout",
    briefSummary:
      "Plat Stay is the next dataset because the official source is PDF-first, address-rich, and ideal for deterministic blackout-date filtering.",
    briefCards: [
      {
        kicker: "Primary sources",
        title: "Use the short link as canonical",
        body:
          "Sync from the official short link first, then keep the resolved PDF URL and file hash so we can diff source changes cleanly over time.",
        links: [
          { label: "go.amex/platstay", href: "https://go.amex/platstay" },
          {
            label: "Current Plat Stay PDF",
            href: "https://www.americanexpress.com/content/dam/amex/en-sg/benefits/the-platinum-card/platstay.pdf?extlink=SG",
          },
        ],
      },
      {
        kicker: "What ships first",
        title: "Travel dates and remaining properties",
        body:
          "Users will enter check-in and check-out dates, or tap quick weekend presets, and the app will keep only properties that are not blocked by listed blackout dates.",
      },
      {
        kicker: "Trust model",
        title: "Blocked is deterministic, available is not guaranteed",
        body:
          "The app should say when a property is blocked by listed blackout dates, but only say 'not blocked by listed blackout dates' otherwise, since hotel availability can still change.",
      },
      {
        kicker: "Next milestone",
        title: "Structured stay dataset",
        body:
          "Parse the PDF into property rows with country, city, address, room type, blackout dates, and reservation contacts, then plot them on the map.",
      },
    ],
  },
  "love-dining": {
    id: "love-dining",
    programId: "love-dining",
    label: "Overview",
    eyebrow: "Love Dining / Sprint 3",
    title: "Love Dining Explorer",
    description:
      "Singapore dining explorer for restaurant and hotel dining partners. The dataset will merge official venue cards with the corresponding T&C PDFs so users can browse both the outlet and the rule set.",
    briefTitle: "Love Dining Buildout",
    briefSummary:
      "Love Dining is strong app material because the official pages expose venue detail while the T&C PDFs give the harder eligibility and savings rules.",
    briefCards: [
      {
        kicker: "Primary sources",
        title: "Merge page cards with PDFs",
        body:
          "The page cards are useful for map links, addresses, phones, and websites. The PDFs are the source of truth for savings structure, exclusions, and participating coverage.",
        links: [
          {
            label: "Restaurants page",
            href: "https://www.americanexpress.com/sg/benefits/love-dining/love-restaurants.html",
          },
          {
            label: "Restaurants T&C PDF",
            href: "https://www.americanexpress.com/content/dam/amex/sg/benefits/Love_Dining_Restaurants_Terms_and_Conditions.pdf",
          },
          {
            label: "Hotels page",
            href: "https://www.americanexpress.com/sg/benefits/love-dining/love-dining-hotels.html",
          },
          {
            label: "Hotels T&C PDF",
            href: "https://www.americanexpress.com/content/dam/amex/sg/benefits/Love_Dining_Hotels_TnC.pdf",
          },
        ],
      },
      {
        kicker: "What ships first",
        title: "Singapore outlet map",
        body:
          "Restaurants and hotel outlets should become a map + list explorer with cuisine, address, hotel grouping, and easy links into the terms for each venue.",
      },
      {
        kicker: "Trust model",
        title: "Outlet detail first, offer wording second",
        body:
          "Map and contact information can be source-backed quickly, but savings percentages and exclusions should always link back into the official Love Dining terms.",
      },
      {
        kicker: "Next milestone",
        title: "Normalize savings rules",
        body:
          "Store participation, savings bands, exclusions, and qualifying item notes in structured fields so the app can answer planning questions more safely later.",
      },
    ],
  },
  "10xcelerator": {
    id: "10xcelerator",
    programId: "10xcelerator",
    label: "Overview",
    eyebrow: "10Xcelerator / Planned",
    title: "10Xcelerator Explorer",
    description:
      "Partner and points-earning planner for bonus merchants and categories. This will start as a verified partner directory, then add outlet mapping only where the location data is dependable.",
    briefTitle: "10Xcelerator Buildout",
    briefSummary:
      "10Xcelerator is valuable, but it is less map-ready than the other programs because the official page is much stronger on partner and offer data than on outlet-level addresses.",
    briefCards: [
      {
        kicker: "Primary source",
        title: "Official partner page first",
        body:
          "Start from the official Amex page to capture partner brands, categories, and earn structure before attempting outlet mapping or partner-site enrichment.",
        links: [
          {
            label: "10Xcelerator page",
            href: "https://www.americanexpress.com/sg/benefits/promotions/shopping/10Xcelerator/10Xcelerator.html",
          },
        ],
      },
      {
        kicker: "What ships first",
        title: "Searchable partner directory",
        body:
          "The first useful version is a partner and category explorer with earn-rule summaries, then a map for outlets only where there is verified location data.",
      },
      {
        kicker: "Trust model",
        title: "Brand-level before outlet-level",
        body:
          "If the official source confirms a partner but not every store location, the app should present that honestly as a partner listing rather than pretending every outlet is verified.",
      },
      {
        kicker: "Next milestone",
        title: "Verified outlet mapping",
        body:
          "After the partner directory is stable, add mapped outlets only when there is a dependable second source for addresses and live merchant coverage.",
      },
    ],
  },
};

const state = {
  restaurants: [],
  scopeRecords: [],
  filtered: [],
  markers: new Map(),
  activeId: null,
  routeId: "dining/japan",
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
const programTitle = document.getElementById("program-title");
const programDescription = document.getElementById("program-description");
const programNav = document.getElementById("program-nav");
const programLinks = [...programNav.querySelectorAll("[data-program]")];
const scopeStrip = document.getElementById("scope-strip");
const scopeNote = document.getElementById("scope-note");
const scopeNav = document.getElementById("scope-nav");
const routeLinks = [...scopeNav.querySelectorAll("[data-route]")];
const dataExplorer = document.getElementById("data-explorer");
const programBrief = document.getElementById("program-brief");
const programBriefTitle = document.getElementById("program-brief-title");
const programBriefSummary = document.getElementById("program-brief-summary");
const programBriefGrid = document.getElementById("program-brief-grid");
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
  return ROUTES[state.routeId] || ROUTES["dining/japan"];
}

function currentProgram() {
  return PROGRAMS[currentRoute().programId] || PROGRAMS.dining;
}

function isDiningRoute(route = currentRoute()) {
  return route.programId === "dining";
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
  const aliases = {
    all: "dining/world",
    world: "dining/world",
    japan: "dining/japan",
    tokyo: "dining/tokyo",
    kyoto: "dining/kyoto",
    osaka: "dining/osaka",
    dining: "dining/japan",
    "plat-stay": "stays",
    accelerator: "10xcelerator",
  };

  if (!hash) {
    return PROGRAMS.dining.defaultRoute;
  }

  if (ROUTES[hash]) {
    return hash;
  }

  if (aliases[hash]) {
    return aliases[hash];
  }

  const [programPart] = hash.split("/");
  const program = PROGRAMS[programPart];
  if (program) {
    return program.defaultRoute;
  }

  return PROGRAMS.dining.defaultRoute;
}

function renderProgramShell(program, route) {
  routeEyebrow.textContent = route.eyebrow;
  routeDescription.textContent = route.description;
  programTitle.textContent = program.title;
  programDescription.textContent = program.description;

  programLinks.forEach((link) => {
    link.classList.toggle("active", link.dataset.program === program.id);
  });
}

function renderScopeShell(route) {
  if (!isDiningRoute(route)) {
    scopeStrip.hidden = true;
    return;
  }

  scopeStrip.hidden = false;
  routeTitle.textContent = route.label;
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

function renderProgramBrief(route) {
  if (isDiningRoute(route)) {
    programBrief.hidden = true;
    return;
  }

  programBrief.hidden = false;
  programBriefTitle.textContent = route.briefTitle || `${route.title} Buildout`;
  programBriefSummary.textContent =
    route.briefSummary || "This dataset is being prepared as the next phase of the explorer.";

  programBriefGrid.innerHTML = "";
  (route.briefCards || []).forEach((card) => {
    const article = document.createElement("article");
    article.className = "brief-card";
    const links = (card.links || [])
      .map(
        (link) =>
          `<a class="inline-link" href="${escapeHtml(link.href)}" target="_blank" rel="noopener">${escapeHtml(link.label)}</a>`
      )
      .join("");
    article.innerHTML = `
      <div class="brief-kicker">${escapeHtml(card.kicker || "Next")}</div>
      <h3>${escapeHtml(card.title)}</h3>
      <p class="brief-copy">${escapeHtml(card.body)}</p>
      ${links ? `<div class="brief-links">${links}</div>` : ""}
    `;
    programBriefGrid.appendChild(article);
  });
}

function clearMarkers() {
  state.markers.forEach((marker) => map.removeLayer(marker));
  state.markers.clear();
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
  state.routeId = ROUTES[routeId] ? routeId : PROGRAMS.dining.defaultRoute;
  const route = currentRoute();
  const program = currentProgram();

  document.title = `${route.title} | Amex Benefits Explorer`;
  renderProgramShell(program, route);
  renderProgramBrief(route);
  renderScopeShell(route);

  if (!isDiningRoute(route)) {
    dataExplorer.hidden = true;
    state.scopeRecords = [];
    state.filtered = [];
    state.activeId = null;
    clearMarkers();
    setToolbarOpen(false);
    setTableOpen(false);
    return;
  }

  dataExplorer.hidden = false;
  state.scopeRecords = state.restaurants.filter((record) => route.matcher(record));
  state.activeId = null;
  resetFilterControls();
  refreshFilterOptions();
  filterRestaurants();
  setTimeout(() => map.invalidateSize(), 0);
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
    window.location.hash = "#/dining/japan";
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
