const DATA_URL = "../data/japan-restaurants.json";
const STAYS_DATA_URL = "../data/plat-stays.json";
const STAYS_META_URL = "../data/plat-stay-source.json";
const DINING_FIT_OPTIONS = { padding: [48, 48], maxZoom: 11 };
const STAYS_FIT_OPTIONS = { padding: [56, 56], maxZoom: 6 };
const INTRO_STORAGE_KEY = "amex-benefits-intro-v2";

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
    label: "Dining Abroad",
    title: "Dining Abroad",
    description:
      "Overseas dining worth a look, with Japan as the deepest live market right now.",
    defaultRoute: "dining/world",
  },
  stays: {
    id: "stays",
    label: "Plat Stay",
    title: "Plat Stay",
    description:
      "Hotels worth a look, with blackout notes and official booking links.",
    defaultRoute: "stays",
  },
  "love-dining": {
    id: "love-dining",
    label: "Love Dining",
    title: "Love Dining",
    description:
      "Singapore dining spots, benefit detail, and rule context.",
    defaultRoute: "love-dining",
  },
  "10xcelerator": {
    id: "10xcelerator",
    label: "More Value",
    title: "More Value",
    description:
      "Extra value ideas when they are actually worth surfacing.",
    defaultRoute: "10xcelerator",
  },
  alerts: {
    id: "alerts",
    label: "Alerts",
    title: "Alerts",
    description:
      "Change watch for list updates, terms, and blackout movement.",
    defaultRoute: "alerts",
  },
};

const ROUTES = {
  "dining/world": {
    id: "dining/world",
    programId: "dining",
    label: "World",
    eyebrow: "Dining Abroad / World",
    title: "Dining Abroad",
    description:
      "A fan-made Amex guide for planning travel benefits without digging through benefit pages first.",
    note:
      "Start broad, then narrow into the places you actually care about.",
    mapSummary:
      "World view for overseas dining. Japan is the deepest live market today.",
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
    eyebrow: "Dining Abroad / Japan",
    title: "Japan Dining",
    description:
      "Japan-wide dining view, with the strongest live coverage in the current build.",
    note:
      "Japan is the strongest live market in the current build.",
    mapSummary:
      "Japan-wide dining view with the map first and details on the side.",
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
    eyebrow: "Dining Abroad / Tokyo",
    title: "Tokyo Dining",
    description:
      "Focused Tokyo route for quick district-level browsing.",
    note:
      "Use this when you already know you want Tokyo.",
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
    eyebrow: "Dining Abroad / Kyoto",
    title: "Kyoto Dining",
    description:
      "Focused Kyoto route for a calmer city-level browse.",
    note:
      "Use this when you want Kyoto only.",
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
    eyebrow: "Dining Abroad / Osaka",
    title: "Osaka Dining",
    description:
      "Focused Osaka route for a cleaner city-level browse.",
    note:
      "Use this when you want Osaka only.",
    mapSummary:
      "Osaka-only route for a cleaner city-level browse.",
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
    eyebrow: "Plat Stay / Live",
    title: "Stay Explorer",
    description:
      "Explore the Plat Stay hotel set, then jump to the official booking or contact page.",
    mapSummary:
      "World stay view for the current Plat Stay property set. Pins are geocoded from official property addresses and should still be verified before booking.",
    defaultView: [20, 10],
    defaultZoom: 2,
    downloads: [],
  },
  alerts: {
    id: "alerts",
    programId: "alerts",
    label: "Overview",
    eyebrow: "Alerts / Change Watch",
    title: "Alerts And Change Watch",
    description:
      "Track list changes, terms movement, and blackout note updates.",
    briefTitle: "Change Watch",
    getBriefSummary: () => buildAlertsSummary(),
    getBriefCards: () => buildAlertsCards(),
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
  stays: [],
  staysSourceMeta: null,
  scopeRecords: [],
  filtered: [],
  markers: new Map(),
  activeId: null,
  routeId: "dining/world",
  mobileToolbarOpen: false,
  tableOpen: false,
  stayScopeRecords: [],
  stayFiltered: [],
  stayMarkers: new Map(),
  stayActiveId: null,
  stayToolbarOpen: false,
  stayTableOpen: false,
  stayBlockedCount: 0,
};

const hasLeaflet = typeof window !== "undefined" && typeof window.L !== "undefined";
const mapElement = document.getElementById("map");
const staysMapElement = document.getElementById("stays-map");

const map = hasLeaflet
  ? L.map("map", {
      zoomControl: true,
      scrollWheelZoom: true,
    }).setView([35.676, 137.5], 5)
  : null;

const staysMap = hasLeaflet
  ? L.map("stays-map", {
      zoomControl: true,
      scrollWheelZoom: true,
    }).setView([20, 10], 2)
  : null;

if (hasLeaflet) {
  L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>',
    subdomains: "abcd",
    maxZoom: 20,
  }).addTo(map);

  L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>',
    subdomains: "abcd",
    maxZoom: 20,
  }).addTo(staysMap);
} else {
  mapElement.innerHTML =
    '<div class="empty-state">Map library failed to load. Dining results are still available below.</div>';
  staysMapElement.innerHTML =
    '<div class="empty-state">Map library failed to load. Plat Stay results are still available below.</div>';
}

const routeEyebrow = document.getElementById("route-eyebrow");
const routeTitle = document.getElementById("route-title");
const routeDescription = document.getElementById("route-description");
const introGate = document.getElementById("intro-gate");
const introSkipTopButton = document.getElementById("intro-skip-top");
const introSkipBottomButton = document.getElementById("intro-skip-bottom");
const introStartTravelButton = document.getElementById("intro-start-travel");
const introStartDiningButton = document.getElementById("intro-start-dining");
const replayGuideButton = document.getElementById("replay-guide");
const programTitle = document.getElementById("program-title");
const programDescription = document.getElementById("program-description");
const journeyNav = document.getElementById("journey-nav");
const journeyLinks = [...journeyNav.querySelectorAll("[data-journey]")];
const programStrip = document.querySelector(".program-strip");
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
const mapFilterShell = document.getElementById("map-filter-shell");
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
const summaryStripText = document.getElementById("summary-strip-text");
const downloadStack = document.getElementById("download-stack");
const mapSummary = document.getElementById("map-summary");
const resultsText = document.getElementById("results-text");
const focusCard = document.getElementById("focus-card");
const tableSummary = document.getElementById("table-summary");
const mobileSummary = document.getElementById("mobile-summary");
const resultsTableBody = document.getElementById("results-table-body");
const mobileResultsList = document.getElementById("mobile-results-list");
const staysExplorer = document.getElementById("stays-explorer");
const staysMapFilterShell = document.getElementById("stays-map-filter-shell");
const staysToolbar = document.getElementById("stays-filter-toolbar");
const staysToolbarToggle = document.getElementById("stays-toolbar-toggle");
const staysToolbarToggleMeta = document.getElementById("stays-toolbar-toggle-meta");
const staysTablePanel = document.getElementById("stays-results-table-panel");
const staysTableToggle = document.getElementById("stays-table-toggle");
const staysTableToggleMeta = document.getElementById("stays-table-toggle-meta");
const staysSearchInput = document.getElementById("stays-search-input");
const staysCountryFilter = document.getElementById("stays-country-filter");
const staysCityFilter = document.getElementById("stays-city-filter");
const staysCheckinInput = document.getElementById("stays-checkin-input");
const staysCheckoutInput = document.getElementById("stays-checkout-input");
const staysResetFiltersButton = document.getElementById("stays-reset-filters");
const staysSummaryStripText = document.getElementById("stays-summary-strip-text");
const staysDownloadsSection = document.getElementById("stays-downloads-section");
const staysDownloadStack = document.getElementById("stays-download-stack");
const staysMapSummary = document.getElementById("stays-map-summary");
const staysResultsText = document.getElementById("stays-results-text");
const staysFocusCard = document.getElementById("stays-focus-card");
const staysTableSummary = document.getElementById("stays-table-summary");
const staysMobileSummary = document.getElementById("stays-mobile-summary");
const staysResultsTableBody = document.getElementById("stays-results-table-body");
const staysMobileResultsList = document.getElementById("stays-mobile-results-list");
const stayPresetButtons = [...document.querySelectorAll("[data-stay-preset]")];

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function tagSection(title, tags, tone = "") {
  if (!tags || !tags.length) return "";
  const badges = tags
    .map((tag) => `<span class="badge ${tone}">${escapeHtml(tag)}</span>`)
    .join("");
  return `
    <div class="tag-section">
      <div class="tag-section-label">${escapeHtml(title)}</div>
      <div class="venue-tags">${badges}</div>
    </div>
  `;
}

function sourceConfidenceLabel(value) {
  const labels = {
    manual_verified: "Manual match",
    verified_by_consensus: "Consensus match",
    high: "High confidence",
    medium: "Medium confidence",
    low: "Low confidence",
  };
  return labels[value] || value || null;
}

function formatReviewCount(value) {
  if (!Number.isFinite(Number(value))) return null;
  const count = Number(value);
  return `${count.toLocaleString()} review${count === 1 ? "" : "s"}`;
}

function qualitySignals(record) {
  if (!record || typeof record.external_signals !== "object" || !record.external_signals) {
    return {};
  }
  return record.external_signals;
}

function externalSignalCard(source, signal) {
  if (!signal || typeof signal !== "object") return "";
  const sourceName = source === "tabelog" ? "Tabelog" : "Google";
  const ratingText =
    source === "tabelog"
      ? [
          signal.honest_stars != null ? `${signal.honest_stars} honest stars` : "",
          signal.score_raw != null ? `raw ${signal.score_raw}` : "",
        ]
          .filter(Boolean)
          .join(" · ")
      : [signal.rating != null ? `${signal.rating} rating` : "", signal.price_level || ""]
          .filter(Boolean)
          .join(" · ");

  if (!ratingText) return "";

  const ratingMarkup = signal.url
    ? `<a class="signal-rating" href="${escapeHtml(signal.url)}" target="_blank" rel="noopener">${escapeHtml(ratingText)}</a>`
    : `<div class="signal-rating">${escapeHtml(ratingText)}</div>`;

  const meta = [
    formatReviewCount(signal.review_count),
    sourceConfidenceLabel(signal.match_confidence),
  ]
    .filter(Boolean)
    .map((item) => `<span>${escapeHtml(item)}</span>`)
    .join("");

  const note = signal.notes ? `<div class="signal-note">${escapeHtml(signal.notes)}</div>` : "";

  return `
    <article class="signal-card">
      <div class="signal-source">${escapeHtml(sourceName)}</div>
      ${ratingMarkup}
      ${meta ? `<div class="signal-meta">${meta}</div>` : ""}
      ${note}
    </article>
  `;
}

function externalSignalsSection(record) {
  const signals = qualitySignals(record);
  const cards = ["tabelog", "google"]
    .map((source) => externalSignalCard(source, signals[source]))
    .filter(Boolean)
    .join("");
  if (!cards) return "";
  return `
    <div class="signal-section">
      <div class="tag-section-label">Outside signals</div>
      <div class="signal-grid">${cards}</div>
    </div>
  `;
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

function googleMapsSearchUrl(parts) {
  const query = parts.filter(Boolean).join(", ");
  if (!query) return null;
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`;
}

function tabelogSearchUrl(record) {
  if (!record || record.country !== "Japan" || !record.name) {
    return null;
  }

  const queryParts = [record.name, record.city, record.prefecture].filter(Boolean);
  if (!queryParts.length) {
    return null;
  }

  return `https://tabelog.com/en/rstLst/?sk=${encodeURIComponent(queryParts.join(" "))}`;
}

function diningGoogleMapsUrl(record) {
  const fallback = googleMapsSearchUrl([
    record.name,
    record.source_localized_address || record.district || record.city,
    record.prefecture || "Japan",
  ]);

  if (!record.source_google_map_url) {
    return fallback;
  }

  try {
    const url = new URL(record.source_google_map_url);
    const isEmbed =
      url.searchParams.get("output") === "embed" ||
      url.hostname.startsWith("maps.google.") ||
      url.pathname.includes("/embed");

    if (!isEmbed) {
      return record.source_google_map_url;
    }

    const q = url.searchParams.get("q");
    if (fallback) {
      return fallback;
    }
    if (q) {
      return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(q)}`;
    }
  } catch {
    return fallback || record.source_google_map_url;
  }

  return fallback || record.source_google_map_url;
}

function focusLocationNote(record) {
  if (record.lat == null || record.lng == null) {
    return "This venue does not have a plotted pin yet. Use the official Pocket Concierge listing for location confirmation.";
  }

  if (hasSourceCoordinates(record)) {
    return "";
  }

  return "Pin uses approximate fallback mapping. Confirm the official Pocket Concierge listing before travelling to the venue.";
}

function createMarker(record) {
  if (!hasLeaflet) return null;
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
      <div>${escapeHtml(record.city)} / ${escapeHtml(record.district || record.region || record.area_title || record.prefecture || "")}</div>
      ${record.source_localized_address ? `<div>${escapeHtml(record.source_localized_address)}</div>` : ""}
      <div>${escapeHtml((record.cuisines || []).join(", ") || "Cuisine unknown")}</div>
      ${dinnerBand ? `<div>${escapeHtml(`Dinner band: ${dinnerBand}`)}</div>` : ""}
      ${yens(record.price_dinner_min_jpy, record.price_dinner_max_jpy) ? `<div>${escapeHtml(`Dinner: ${yens(record.price_dinner_min_jpy, record.price_dinner_max_jpy)}`)}</div>` : ""}
      ${lunchBand ? `<div>${escapeHtml(`Lunch band: ${lunchBand}`)}</div>` : ""}
      ${yens(record.price_lunch_min_jpy, record.price_lunch_max_jpy) ? `<div>${escapeHtml(`Lunch: ${yens(record.price_lunch_min_jpy, record.price_lunch_max_jpy)}`)}</div>` : ""}
      ${record.summary_official ? `<p>${escapeHtml(record.summary_official)}</p>` : ""}
      ${focusLocationNote(record) ? `<div>${escapeHtml(focusLocationNote(record))}</div>` : ""}
      ${
        diningGoogleMapsUrl(record)
          ? `<p><a href="${escapeHtml(diningGoogleMapsUrl(record))}" target="_blank" rel="noopener">Google Maps</a></p>`
          : ""
      }
      ${
        tabelogSearchUrl(record)
          ? `<p><a href="${escapeHtml(tabelogSearchUrl(record))}" target="_blank" rel="noopener">Search Tabelog</a></p>`
          : ""
      }
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
  return ROUTES[state.routeId] || ROUTES["dining/world"];
}

function currentProgram() {
  return PROGRAMS[currentRoute().programId] || PROGRAMS.dining;
}

function isDiningRoute(route = currentRoute()) {
  return route.programId === "dining";
}

function isStayRoute(route = currentRoute()) {
  return route.programId === "stays";
}

function isLiveDataRoute(route = currentRoute()) {
  return isDiningRoute(route) || isStayRoute(route);
}

function currentJourneyId(route = currentRoute()) {
  if (isDiningRoute(route) || isStayRoute(route)) return "travel";
  if (route.programId === "love-dining") return "singapore";
  if (route.programId === "alerts") return "alerts";
  return null;
}

function visibleProgramIdsForJourney(journeyId) {
  if (journeyId === "travel") {
    return ["dining", "stays"];
  }
  if (journeyId === "singapore") {
    return ["love-dining"];
  }
  if (journeyId === "alerts") {
    return ["alerts"];
  }
  return ["dining", "stays", "love-dining"];
}

function formatTimestamp(value) {
  if (!value) return "Pending sync";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("en-SG", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Asia/Singapore",
  });
}

function buildAlertsSummary() {
  const meta = state.staysSourceMeta;
  if (!meta) {
    return "Wire this panel to snapshot diffs, additions, removals, and blackout changes so users can see what moved before we add nudges.";
  }

  return `Latest Plat Stay source fetched ${formatTimestamp(meta.fetched_at)}. ${meta.record_count || state.stays.length} properties are in the current snapshot.`;
}

function buildAlertsCards() {
  const meta = state.staysSourceMeta;
  const countries = new Set(state.stays.map((record) => record.country).filter(Boolean));
  return [
    {
      kicker: "Live now",
      title: "Current Plat Stay snapshot",
      body: meta
        ? `${meta.record_count || state.stays.length} properties from ${meta.page_count || "?"} PDF pages. ${state.stays.length} records are available in-app across ${countries.size} countries.`
        : "Plat Stay source metadata is not available yet, but the app is ready to surface it here once the sync writes it.",
      links: meta
        ? [
            {
              label: "Official Plat Stay PDF",
              href: meta.resolved_url || meta.canonical_url || "https://go.amex/platstay",
            },
          ]
        : [],
    },
    {
      kicker: "Watch for",
      title: "What should trigger an alert",
      body:
        "Property additions, removals, blackout-note changes, booking contact changes, and any source-file refresh that materially changes the list or rules.",
    },
    {
      kicker: "Archive",
      title: "Snapshot every sync",
      body:
        "Each sync should keep the current source hash and a structured copy of the records so we can compare adds, drops, and terms deltas without guessing.",
    },
    {
      kicker: "Nudge later",
      title: "Telegram or email",
      body:
        "Once the diff layer exists, the same alert summary can drive Telegram nudges, email digests, or a lightweight webhook without exposing noisy false alarms.",
    },
  ];
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
    dining: "dining/world",
    "plat-stay": "stays",
    accelerator: "10xcelerator",
    alerts: "alerts",
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

  const visibleIds = visibleProgramIdsForJourney(currentJourneyId(route));
  if (programStrip) {
    programStrip.hidden = visibleIds.length <= 1;
  }

  programLinks.forEach((link) => {
    const visible = visibleIds.includes(link.dataset.program);
    link.hidden = !visible;
    link.classList.toggle("active", visible && link.dataset.program === program.id);
  });
}

function renderJourneyShell(route) {
  const activeJourneyId = currentJourneyId(route);
  journeyLinks.forEach((link) => {
    link.classList.toggle("active", link.dataset.journey === activeJourneyId);
  });
}

function showIntroGate(force = false) {
  if (!introGate) return;
  if (!force && window.localStorage.getItem(INTRO_STORAGE_KEY) === "seen") {
    introGate.hidden = true;
    document.body.classList.remove("intro-active");
    return;
  }
  introGate.hidden = false;
  document.body.classList.add("intro-active");
}

function hideIntroGate({ persist = true } = {}) {
  if (!introGate) return;
  if (persist) {
    window.localStorage.setItem(INTRO_STORAGE_KEY, "seen");
  }
  introGate.hidden = true;
  document.body.classList.remove("intro-active");
}

function jumpIntoExplorer(routeHash) {
  hideIntroGate();
  if (routeHash) {
    window.location.hash = routeHash;
  }
  window.setTimeout(() => {
    const target = isStayRoute(resolveRouteFromHash()) ? staysExplorer : dataExplorer;
    target?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, 80);
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
  if (isLiveDataRoute(route)) {
    programBrief.hidden = true;
    return;
  }

  const briefTitle =
    typeof route.getBriefTitle === "function" ? route.getBriefTitle() : route.briefTitle;
  const briefSummary =
    typeof route.getBriefSummary === "function" ? route.getBriefSummary() : route.briefSummary;
  const briefCards =
    typeof route.getBriefCards === "function" ? route.getBriefCards() : route.briefCards;

  programBrief.hidden = false;
  programBriefTitle.textContent = briefTitle || `${route.title} Buildout`;
  programBriefSummary.textContent =
    briefSummary || "This dataset is being prepared as the next phase of the explorer.";

  programBriefGrid.innerHTML = "";
  (briefCards || []).forEach((card) => {
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
  if (!hasLeaflet || !map) {
    state.markers.clear();
    return;
  }
  state.markers.forEach((marker) => map.removeLayer(marker));
  state.markers.clear();
}

function clearStayMarkers() {
  if (!hasLeaflet || !staysMap) {
    state.stayMarkers.clear();
    return;
  }
  state.stayMarkers.forEach((marker) => staysMap.removeLayer(marker));
  state.stayMarkers.clear();
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
    uniqueValues(districtPool.map((record) => record.district || record.region || record.area_title)),
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
    if (district && (record.district || record.region || record.area_title) !== district) return false;
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
  fitDiningMapToVisibleMarkers();
  renderFocusCard();
  renderTable();
  renderMobileCards();
}

function renderStats() {
  const route = currentRoute();
  const filteredMapped = state.filtered.filter((record) => record.lat != null && record.lng != null).length;
  const scopeCities = uniqueValues(state.scopeRecords.map((record) => record.city));
  const filteredCities = uniqueValues(state.filtered.map((record) => record.city));
  const filterCount = activeFilterCount();

  summaryStripText.textContent =
    filterCount > 0
      ? `${state.filtered.length} of ${state.scopeRecords.length} venues shown across ${filteredCities.length} cities, ${
          filteredMapped === state.filtered.length ? "all mapped" : `${filteredMapped} mapped`
        }.`
      : `${state.scopeRecords.length} venues across ${scopeCities.length} cities, ${
          filteredMapped === state.scopeRecords.length ? "all mapped" : `${filteredMapped} mapped`
        }.`;

  resultsText.textContent = `Selected venue from ${route.label}`;
  tableSummary.textContent =
    filterCount > 0 ? "Current filtered shortlist in table form." : "Current route list in table form.";
  mobileSummary.textContent = tableSummary.textContent;
  mapSummary.textContent = route.mapSummary;
  renderToolbarToggle();
  renderTableToggle();
}

function renderMarkers() {
  if (!hasLeaflet || !map) return;
  state.markers.forEach((marker) => map.removeLayer(marker));
  state.markers.clear();

  state.filtered.forEach((record) => {
    const marker = createMarker(record);
    if (!marker) return;
    marker.addTo(map);
    state.markers.set(record.id, marker);
  });
}

function renderFocusCard() {
  const record = activeRecord();
  if (!record) {
    focusCard.innerHTML = '<div class="empty-state">No venue matches the current route and filters.</div>';
    return;
  }

  const tags = [
    `<span class="badge gold">${escapeHtml(record.city)}</span>`,
    record.lat != null && record.lng != null && !hasSourceCoordinates(record)
      ? '<span class="badge amber">Approximate pin</span>'
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
    <div class="focus-kicker">${escapeHtml(record.city)} / ${escapeHtml(record.district || record.region || record.area_title || record.prefecture || "")}</div>
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
    ${tagSection("Known for", record.known_for_tags, "gold")}
    ${tagSection("Specialties", record.signature_dish_tags, "blue")}
    ${externalSignalsSection(record)}
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
    ${focusLocationNote(record) ? `<div class="focus-note">${escapeHtml(focusLocationNote(record))}</div>` : ""}
    <div class="focus-actions">
      ${
        diningGoogleMapsUrl(record)
          ? `<a class="inline-link" href="${escapeHtml(diningGoogleMapsUrl(record))}" target="_blank" rel="noopener">Open in Google Maps</a>`
          : ""
      }
      ${
        tabelogSearchUrl(record)
          ? `<a class="inline-link" href="${escapeHtml(tabelogSearchUrl(record))}" target="_blank" rel="noopener">Search Tabelog</a>`
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
        <div class="table-sub">${escapeHtml(record.source_localized_address || record.district || record.region || record.area_title || "")}</div>
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
          <div class="focus-kicker">${escapeHtml(record.city)} / ${escapeHtml(record.district || record.region || record.area_title || record.prefecture || "")}</div>
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
      ${tagSection("Known for", record.known_for_tags, "gold")}
      ${tagSection("Specialties", record.signature_dish_tags, "blue")}
      ${externalSignalsSection(record)}
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
          diningGoogleMapsUrl(record)
            ? `<a class="inline-link" href="${escapeHtml(diningGoogleMapsUrl(record))}" target="_blank" rel="noopener">Google Maps</a>`
            : ""
        }
        ${
          tabelogSearchUrl(record)
            ? `<a class="inline-link" href="${escapeHtml(tabelogSearchUrl(record))}" target="_blank" rel="noopener">Search Tabelog</a>`
            : ""
        }
      </div>
    `;

    const focusButton = card.querySelector("[data-mobile-focus]");
    if (focusButton) {
      focusButton.addEventListener("click", () => {
        setActiveRecord(record.id);
        focusActiveRecordOnMap();
        if (window.innerWidth <= 820 && hasLeaflet && map) {
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
  if (!hasLeaflet || !map) return;
  const record = activeRecord();
  if (!record) return;
  const marker = state.markers.get(record.id);
  if (!marker) return;
  map.flyTo(marker.getLatLng(), Math.max(map.getZoom(), 13), { duration: 0.6 });
  marker.openPopup();
}

function stayGoogleMapsUrl(record) {
  const query = [record.name, record.address, record.country].filter(Boolean).join(", ");
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`;
}

function stayReservationPrimaryLabel(record) {
  if (record.reservation_mode === "booking_link_prompt" && record.reservation_raw) {
    return record.reservation_raw;
  }
  return record.reservation_primary_label || null;
}

function stayReservationSummaryHtml(record) {
  const fallback = escapeHtml(record.reservation_raw || "See official source");
  if (
    record.reservation_mode === "booking_link_prompt" &&
    record.reservation_primary_url &&
    record.reservation_raw
  ) {
    return `<a class="inline-link" href="${escapeHtml(record.reservation_primary_url)}" target="_blank" rel="noopener">${escapeHtml(record.reservation_raw)}</a>`;
  }
  return fallback;
}

function stayReservationActions(record) {
  const links = [];
  const primaryLabel = stayReservationPrimaryLabel(record);
  if (record.reservation_primary_url && primaryLabel) {
    links.push(
      `<a class="inline-link" href="${escapeHtml(record.reservation_primary_url)}" target="_blank" rel="noopener">${escapeHtml(primaryLabel)}</a>`
    );
  }
  if (record.reservation_secondary_url && record.reservation_secondary_label) {
    links.push(
      `<a class="inline-link" href="${escapeHtml(record.reservation_secondary_url)}" target="_blank" rel="noopener">${escapeHtml(record.reservation_secondary_label)}</a>`
    );
  }
  return links.join("");
}

function stayReservationModeLabel(mode) {
  switch (mode) {
    case "booking_link_prompt":
      return "Booking link";
    case "email_or_phone":
      return "Email / phone";
    case "phone":
      return "Phone";
    case "unknown":
      return "See official source";
    default:
      return (mode || "See official source").replaceAll("_", " ");
  }
}

function stayDateRange() {
  if (!staysCheckinInput.value || !staysCheckoutInput.value) {
    return null;
  }
  const start = new Date(`${staysCheckinInput.value}T00:00:00Z`);
  const end = new Date(`${staysCheckoutInput.value}T00:00:00Z`);
  if (Number.isNaN(start.valueOf()) || Number.isNaN(end.valueOf()) || end <= start) {
    return null;
  }
  return { start, end };
}

function stayRangeOverlaps(range, selected) {
  const start = new Date(`${range.start}T00:00:00Z`);
  const endInclusive = new Date(`${range.end}T00:00:00Z`);
  const endExclusive = new Date(endInclusive);
  endExclusive.setUTCDate(endExclusive.getUTCDate() + 1);
  return selected.start < endExclusive && selected.end > start;
}

function stayAvailability(record) {
  const selected = stayDateRange();
  const exactRanges = record.blackout_exact_ranges || [];
  const notes = record.blackout_notes || [];
  const raw = (record.blackout_raw || "").trim();
  const hasSpecificNotes = Boolean(raw) && raw.toLowerCase() !== "subject to availability";
  if (!selected) {
    if (exactRanges.length) {
      return {
        key: "not_evaluated",
        label: "Listed blackout dates available",
        detail: "Pick check-in and check-out dates to test conflicts against the listed blackout ranges.",
        blocked: false,
      };
    }
    if (hasSpecificNotes) {
      return {
        key: "notes_only",
        label: "Special blackout notes listed",
        detail: raw,
        blocked: false,
      };
    }
    return {
      key: "subject_to_availability",
      label:
        record.availability_mode === "subject_to_availability"
          ? "Still subject to availability"
          : "No listed blackout dates",
      detail:
        record.availability_mode === "subject_to_availability"
          ? "This property is still subject to hotel availability."
          : "Pick check-in and check-out dates to evaluate this property.",
      blocked: false,
    };
  }

  const conflicts = exactRanges.filter((range) => stayRangeOverlaps(range, selected));
  if (conflicts.length) {
    return {
      key: "blocked",
      label: "Blocked by listed blackout dates",
      detail: conflicts.map((range) => range.label).join(" | "),
      blocked: true,
    };
  }

  if (exactRanges.length && notes.length) {
    return {
      key: "not_blocked_with_notes",
      label: "Not blocked by listed dates",
      detail: notes.join(" | "),
      blocked: false,
    };
  }

  if (hasSpecificNotes) {
    return {
      key: "notes_only",
      label: "Special blackout notes listed",
      detail: raw,
      blocked: false,
    };
  }

  if (!exactRanges.length) {
    return {
      key: "subject_to_availability",
      label:
        record.availability_mode === "subject_to_availability"
          ? "Still subject to availability"
          : "Dates selected",
      detail:
        record.availability_mode === "subject_to_availability"
          ? "No exact blackout dates are listed. Final confirmation depends on hotel availability."
          : "No exact blackout dates are listed for the selected stay.",
      blocked: false,
    };
  }

  return {
    key: "not_blocked",
    label: "Not blocked by listed blackout dates",
    detail: "Still subject to hotel availability and final confirmation.",
    blocked: false,
  };
}

function stayAvailabilityBadgeClass(status) {
  if (status.key === "blocked") return "amber";
  if (status.key === "not_blocked" || status.key === "not_blocked_with_notes") return "green";
  return "blue";
}

function stayFocusSummary(record, status) {
  const boardNote = record.breakfast_included ? "" : record.breakfast_note || "Room only.";
  const raw = (record.blackout_raw || "").trim();
  if (!raw) {
    return boardNote;
  }

  if (raw.toLowerCase() === "subject to availability") {
    return boardNote;
  }

  if (status.detail && raw === status.detail) {
    return "";
  }

  const prefix = (record.blackout_exact_ranges || []).length
    ? "Official blackout dates: "
    : "Official blackout notes: ";
  return `${prefix}${raw}`;
}

function activeStayFilterCount() {
  let count = 0;
  if (staysSearchInput.value.trim()) count += 1;
  if (staysCountryFilter.value) count += 1;
  if (staysCityFilter.value) count += 1;
  if (staysCheckinInput.value) count += 1;
  if (staysCheckoutInput.value) count += 1;
  return count;
}

function setStayToolbarOpen(isOpen) {
  state.stayToolbarOpen = isOpen;
  staysToolbar.classList.toggle("is-open", isOpen);
  staysToolbarToggle.setAttribute("aria-expanded", String(isOpen));
  const icon = staysToolbarToggle.querySelector(".toolbar-toggle-icon");
  if (icon) {
    icon.textContent = isOpen ? "-" : "+";
  }
}

function renderStayToolbarToggle() {
  const count = activeStayFilterCount();
  staysToolbarToggleMeta.textContent =
    count > 0 ? `${count} active filter${count === 1 ? "" : "s"}` : "All filters off";
}

function setStayTableOpen(isOpen) {
  state.stayTableOpen = isOpen;
  staysTablePanel.classList.toggle("is-open", isOpen);
  staysTableToggle.setAttribute("aria-expanded", String(isOpen));
  const icon = staysTableToggle.querySelector(".toolbar-toggle-icon");
  if (icon) {
    icon.textContent = isOpen ? "-" : "+";
  }
}

function renderStayTableToggle() {
  const count = state.stayFiltered.length;
  staysTableToggleMeta.textContent = state.stayTableOpen
    ? `Showing ${count} detailed row${count === 1 ? "" : "s"}`
    : `${count} row${count === 1 ? "" : "s"} available for deeper scanning`;
}

function resetStayFilterControls() {
  staysSearchInput.value = "";
  staysCountryFilter.value = "";
  staysCityFilter.value = "";
  staysCheckinInput.value = "";
  staysCheckoutInput.value = "";
}

function refreshStayFilterOptions() {
  const country = staysCountryFilter.value;
  fillSelect(
    staysCountryFilter,
    uniqueValues(state.stays.map((record) => record.country)),
    "All countries"
  );
  const cityPool = state.stays.filter((record) => {
    if (!country) return true;
    return record.country === country;
  });
  fillSelect(staysCityFilter, uniqueValues(cityPool.map((record) => record.city)), "All cities");
}

function ensureActiveStayRecord() {
  if (!state.stayFiltered.length) {
    state.stayActiveId = null;
    return;
  }
  if (!state.stayFiltered.some((record) => record.id === state.stayActiveId)) {
    state.stayActiveId = state.stayFiltered[0].id;
  }
}

function activeStayRecord() {
  return state.stayFiltered.find((record) => record.id === state.stayActiveId) || null;
}

function createStayMarker(record) {
  if (!hasLeaflet) return null;
  if (record.lat == null || record.lng == null) return null;
  const status = stayAvailability(record);
  const marker = L.circleMarker([record.lat, record.lng], {
    radius: 8,
    fillColor: status.key === "blocked" ? "#d6a44c" : "#5fb9a6",
    fillOpacity: 0.92,
    color: "#091018",
    weight: 2,
  });

  marker.bindPopup(`
    <div class="popup-card">
      <div class="popup-name">${escapeHtml(record.name)}</div>
      <div>${escapeHtml(record.city || "City unknown")} / ${escapeHtml(record.country || "Country unknown")}</div>
      <div>${escapeHtml(record.address)}</div>
      <div>${escapeHtml(record.eligible_room_type)}</div>
      <div>${escapeHtml(status.label)}</div>
      ${
        record.blackout_raw
          ? `<div>${escapeHtml(`Blackouts: ${record.blackout_raw}`)}</div>`
          : ""
      }
      ${
        record.reservation_raw
          ? `<div>Reservation: ${stayReservationSummaryHtml(record)}</div>`
          : ""
      }
      ${
        record.source_url
          ? `<p><a href="${escapeHtml(record.source_url)}" target="_blank" rel="noopener">Official source</a></p>`
          : ""
      }
    </div>
  `);
  marker.on("click", () => {
    setActiveStayRecord(record.id);
  });
  return marker;
}

function filterStays() {
  const search = staysSearchInput.value.trim().toLowerCase();
  const country = staysCountryFilter.value;
  const city = staysCityFilter.value;

  state.stayBlockedCount = 0;
  state.stayFiltered = state.stays.filter((record) => {
    if (country && record.country !== country) return false;
    if (city && record.city !== city) return false;
    if (search && !(record.search_text || "").includes(search)) return false;

    const status = stayAvailability(record);
    if (status.blocked) {
      state.stayBlockedCount += 1;
      return false;
    }
    return true;
  });

  state.stayScopeRecords = state.stays;
  ensureActiveStayRecord();
  renderStayStats();
  renderStayMarkers();
  fitStayMapToVisibleMarkers();
  renderStayFocusCard();
  renderStayTable();
  renderStayMobileCards();
}

function renderStayStats() {
  const mapped = state.stayFiltered.filter((record) => record.lat != null && record.lng != null).length;
  const scopeCountries = uniqueValues(state.stays.map((record) => record.country));
  const filteredCountries = uniqueValues(state.stayFiltered.map((record) => record.country));
  const selected = stayDateRange();
  const filterCount = activeStayFilterCount();

  if (filterCount > 0) {
    const filterSummary = selected
      ? `${state.stayFiltered.length} of ${state.stays.length} properties remain after date and location filters, across ${filteredCountries.length} countries, ${
          mapped === state.stayFiltered.length ? "all mapped" : `${mapped} mapped`
        }.`
      : `${state.stayFiltered.length} of ${state.stays.length} properties shown after filters, across ${filteredCountries.length} countries, ${
          mapped === state.stayFiltered.length ? "all mapped" : `${mapped} mapped`
        }.`;
    staysSummaryStripText.textContent = filterSummary;
  } else {
    staysSummaryStripText.textContent = `${state.stays.length} properties across ${scopeCountries.length} countries, ${
      mapped === state.stays.length ? "all mapped" : `${mapped} mapped`
    }.`;
  }

  staysResultsText.textContent = "Selected property from the current Plat Stay shortlist";
  staysTableSummary.textContent = selected
    ? "Current shortlist in table form. Exact blackout conflicts are already removed."
    : "Current Plat Stay list in table form. Add travel dates to remove exact blackout conflicts.";
  staysMobileSummary.textContent = staysTableSummary.textContent;
  staysMapSummary.textContent = "Plat Stay world view. Use filters and dates to narrow the shortlist.";
  renderStayToolbarToggle();
  renderStayTableToggle();
}

function renderStayDownloads(route) {
  const downloads = route.downloads || [];
  staysDownloadStack.innerHTML = "";
  staysDownloadsSection.hidden = downloads.length === 0;
  downloads.forEach((item) => {
    const link = document.createElement("a");
    link.className = `download-btn${item.primary ? " primary" : ""}`;
    link.href = item.href;
    link.download = "";
    link.textContent = item.label;
    staysDownloadStack.appendChild(link);
  });
}

function renderStayMarkers() {
  if (!hasLeaflet || !staysMap) return;
  clearStayMarkers();

  state.stayFiltered.forEach((record) => {
    const marker = createStayMarker(record);
    if (!marker) return;
    marker.addTo(staysMap);
    state.stayMarkers.set(record.id, marker);
  });
}

function renderStayFocusCard() {
  const record = activeStayRecord();
  if (!record) {
    staysFocusCard.innerHTML = '<div class="empty-state">No property matches the current route and filters.</div>';
    return;
  }

  const status = stayAvailability(record);
  const tags = [
    record.country ? `<span class="badge gold">${escapeHtml(record.country)}</span>` : "",
    record.city ? `<span class="badge">${escapeHtml(record.city)}</span>` : "",
    record.breakfast_included ? "" : '<span class="badge blue">Room only</span>',
    record.coordinate_confidence === "approximate"
      ? '<span class="badge amber">Approximate pin</span>'
      : "",
  ]
    .filter(Boolean)
    .join("");
  const summary = stayFocusSummary(record, status);

  staysFocusCard.innerHTML = `
    <div class="focus-kicker">${escapeHtml(record.city || "City unknown")} / ${escapeHtml(record.country || "Country unknown")}</div>
    <h3 class="focus-title">${escapeHtml(record.name)}</h3>
    <div class="focus-subtitle">${escapeHtml(record.eligible_room_type || "Eligible room type not listed")}</div>
    <div class="focus-address">${escapeHtml(record.address)}</div>
    <div class="focus-tags">${tags}</div>
    <div class="price-grid">
      <div class="price-card">
        <span class="price-label">Stay Availability</span>
        <div class="price-tier">${escapeHtml(status.label)}</div>
        <div class="price-raw">${escapeHtml(status.detail)}</div>
      </div>
      <div class="price-card">
        <span class="price-label">Reservation</span>
        <div class="price-tier">${escapeHtml(stayReservationModeLabel(record.reservation_mode))}</div>
        <div class="price-raw">${stayReservationSummaryHtml(record)}</div>
      </div>
    </div>
    ${summary ? `<p class="focus-summary">${escapeHtml(summary)}</p>` : ""}
    <div class="focus-note">${escapeHtml(record.map_pin_note)}</div>
    <div class="focus-actions">
      <a class="inline-link" href="${escapeHtml(stayGoogleMapsUrl(record))}" target="_blank" rel="noopener">Open in Google Maps</a>
      <a class="inline-link" href="${escapeHtml(record.source_url)}" target="_blank" rel="noopener">Open official source</a>
      ${stayReservationActions(record)}
      ${
        record.lat != null && record.lng != null
          ? `<button type="button" class="ghost-btn secondary" data-focus-stay-map="true">Center on map</button>`
          : ""
      }
    </div>
  `;

  const centerButton = staysFocusCard.querySelector("[data-focus-stay-map='true']");
  if (centerButton) {
    centerButton.addEventListener("click", () => {
      focusActiveStayOnMap();
    });
  }
}

function renderStayTable() {
  if (!state.stayFiltered.length) {
    staysResultsTableBody.innerHTML =
      '<tr><td colspan="5" class="empty-table">No properties match the current filters and date check.</td></tr>';
    return;
  }

  staysResultsTableBody.innerHTML = "";
  state.stayFiltered.forEach((record) => {
    const row = document.createElement("tr");
    row.className = record.id === state.stayActiveId ? "active" : "";
    row.addEventListener("click", () => {
      setActiveStayRecord(record.id);
      focusActiveStayOnMap();
    });
    row.innerHTML = `
      <td><div class="table-title">${escapeHtml(record.name)}</div></td>
      <td>
        <div>${escapeHtml(record.country || "Country unknown")}</div>
        <div class="table-sub">${escapeHtml(record.city || record.address)}</div>
      </td>
      <td>${escapeHtml(record.eligible_room_type || "Unknown")}</td>
      <td>${escapeHtml(record.blackout_raw || "Subject to availability")}</td>
      <td>${escapeHtml(record.reservation_raw || "See official source")}</td>
    `;
    staysResultsTableBody.appendChild(row);
  });
}

function renderStayMobileCards() {
  if (!state.stayFiltered.length) {
    staysMobileResultsList.innerHTML =
      '<div class="empty-state">No properties match the current filters and date check.</div>';
    return;
  }

  staysMobileResultsList.innerHTML = "";
  state.stayFiltered.forEach((record) => {
    const status = stayAvailability(record);
    const card = document.createElement("article");
    card.className = `mobile-card${record.id === state.stayActiveId ? " active" : ""}`;
    card.innerHTML = `
      <div class="mobile-card-top">
        <div>
          <div class="focus-kicker">${escapeHtml(record.city || "City unknown")} / ${escapeHtml(record.country || "Country unknown")}</div>
          <h3 class="mobile-card-title">${escapeHtml(record.name)}</h3>
          <div class="mobile-card-subtitle">${escapeHtml(record.eligible_room_type || "Eligible room type not listed")}</div>
        </div>
      </div>
      <div class="mobile-card-address">${escapeHtml(record.address)}</div>
      <div class="venue-tags">
        <span class="badge ${stayAvailabilityBadgeClass(status)}">${escapeHtml(status.label)}</span>
        ${record.breakfast_included ? "" : '<span class="badge blue">Room only</span>'}
      </div>
      <p class="focus-summary">${escapeHtml(status.detail)}</p>
      <div class="mobile-card-actions">
        <button type="button" class="ghost-btn secondary" data-mobile-stay-focus="${escapeHtml(record.id)}">
          Show on map
        </button>
        <a class="inline-link" href="${escapeHtml(stayGoogleMapsUrl(record))}" target="_blank" rel="noopener">Google Maps</a>
        ${stayReservationActions(record)}
      </div>
    `;
    const focusButton = card.querySelector("[data-mobile-stay-focus]");
    if (focusButton) {
      focusButton.addEventListener("click", () => {
        setActiveStayRecord(record.id);
        focusActiveStayOnMap();
        if (window.innerWidth <= 820 && hasLeaflet && staysMap) {
          const mapTop = staysMap.getContainer().getBoundingClientRect().top + window.scrollY - 16;
          window.scrollTo({ top: Math.max(mapTop, 0), behavior: "smooth" });
        }
      });
    }
    staysMobileResultsList.appendChild(card);
  });
}

function setActiveStayRecord(id) {
  state.stayActiveId = id;
  renderStayFocusCard();
  renderStayTable();
  renderStayMobileCards();
}

function focusActiveStayOnMap() {
  if (!hasLeaflet || !staysMap) return;
  const record = activeStayRecord();
  if (!record) return;
  const marker = state.stayMarkers.get(record.id);
  if (!marker) return;
  staysMap.flyTo(marker.getLatLng(), Math.max(staysMap.getZoom(), 8), { duration: 0.6 });
  marker.openPopup();
}

function fitDiningMapToVisibleMarkers() {
  if (!hasLeaflet || !map) return;
  const route = currentRoute();
  const latLngs = state.filtered
    .filter((record) => record.lat != null && record.lng != null)
    .map((record) => L.latLng(record.lat, record.lng));

  if (!latLngs.length) {
    map.setView(route.defaultView, route.defaultZoom);
    return;
  }

  if (latLngs.length === 1) {
    map.setView(latLngs[0], Math.min(route.defaultZoom, 13));
    return;
  }

  map.fitBounds(L.latLngBounds(latLngs), DINING_FIT_OPTIONS);
}

function fitStayMapToVisibleMarkers() {
  if (!hasLeaflet || !staysMap) return;
  const route = currentRoute();
  const latLngs = state.stayFiltered
    .filter((record) => record.lat != null && record.lng != null)
    .map((record) => L.latLng(record.lat, record.lng));

  if (!latLngs.length) {
    staysMap.setView(route.defaultView, route.defaultZoom);
    return;
  }

  if (latLngs.length === 1) {
    staysMap.setView(latLngs[0], Math.min(route.defaultZoom, 8));
    return;
  }

  staysMap.fitBounds(L.latLngBounds(latLngs), STAYS_FIT_OPTIONS);
}

function applyRoute(routeId) {
  state.routeId = ROUTES[routeId] ? routeId : PROGRAMS.dining.defaultRoute;
  const route = currentRoute();
  const program = currentProgram();

  document.title = `${route.title} | Charging the Charge Card`;
  renderJourneyShell(route);
  renderProgramShell(program, route);
  renderProgramBrief(route);
  renderScopeShell(route);

  if (isStayRoute(route)) {
    dataExplorer.hidden = true;
    staysExplorer.hidden = false;
    renderStayDownloads(route);
    refreshStayFilterOptions();
    filterStays();
    if (hasLeaflet && staysMap) {
      setTimeout(() => {
        staysMap.invalidateSize();
        fitStayMapToVisibleMarkers();
      }, 0);
    }
    return;
  }

  if (!isDiningRoute(route)) {
    dataExplorer.hidden = true;
    staysExplorer.hidden = true;
    state.scopeRecords = [];
    state.filtered = [];
    state.activeId = null;
    state.stayFiltered = [];
    state.stayActiveId = null;
    clearMarkers();
    clearStayMarkers();
    setToolbarOpen(false);
    setTableOpen(false);
    setStayToolbarOpen(false);
    setStayTableOpen(false);
    return;
  }

  dataExplorer.hidden = false;
  staysExplorer.hidden = true;
  state.scopeRecords = state.restaurants.filter((record) => route.matcher(record));
  state.activeId = null;
  resetFilterControls();
  refreshFilterOptions();
  filterRestaurants();
  if (hasLeaflet && map) {
    setTimeout(() => {
      map.invalidateSize();
      fitDiningMapToVisibleMarkers();
    }, 0);
  }
}

function handleHashRoute() {
  applyRoute(resolveRouteFromHash());
}

async function init() {
  const [restaurantResponse, staysResponse, staysMetaResponse] = await Promise.all([
    fetch(DATA_URL),
    fetch(STAYS_DATA_URL),
    fetch(STAYS_META_URL).catch(() => null),
  ]);
  state.restaurants = await restaurantResponse.json();
  state.restaurants.forEach((record) => {
    record.search_text = (record.search_text || "").toLowerCase();
  });
  if (staysResponse.ok) {
    state.stays = await staysResponse.json();
    state.stays.forEach((record) => {
      record.search_text = (record.search_text || "").toLowerCase();
    });
  }
  if (staysMetaResponse && staysMetaResponse.ok) {
    state.staysSourceMeta = await staysMetaResponse.json();
  }

  setToolbarOpen(false);
  setTableOpen(false);
  setStayToolbarOpen(false);
  setStayTableOpen(false);
  handleHashRoute();
  if (!window.location.hash) {
    window.location.hash = "#/dining/world";
  }
  showIntroGate();
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

introSkipTopButton?.addEventListener("click", () => {
  hideIntroGate();
});

introSkipBottomButton?.addEventListener("click", () => {
  hideIntroGate();
});

introStartTravelButton?.addEventListener("click", () => {
  jumpIntoExplorer(introStartTravelButton.dataset.introRoute);
});

introStartDiningButton?.addEventListener("click", () => {
  jumpIntoExplorer(introStartDiningButton.dataset.introRoute);
});

replayGuideButton?.addEventListener("click", () => {
  showIntroGate(true);
});

toolbarToggle.addEventListener("click", () => {
  setToolbarOpen(!state.mobileToolbarOpen);
});

tableToggle.addEventListener("click", () => {
  setTableOpen(!state.tableOpen);
  renderTableToggle();
});

staysToolbarToggle.addEventListener("click", () => {
  setStayToolbarOpen(!state.stayToolbarOpen);
});

staysTableToggle.addEventListener("click", () => {
  setStayTableOpen(!state.stayTableOpen);
  renderStayTableToggle();
});

staysSearchInput.addEventListener("input", filterStays);
staysCountryFilter.addEventListener("change", () => {
  refreshStayFilterOptions();
  filterStays();
});
staysCityFilter.addEventListener("change", filterStays);
staysCheckinInput.addEventListener("change", filterStays);
staysCheckoutInput.addEventListener("change", filterStays);
staysResetFiltersButton.addEventListener("click", () => {
  resetStayFilterControls();
  refreshStayFilterOptions();
  filterStays();
});

stayPresetButtons.forEach((button) => {
  button.addEventListener("click", () => {
    staysCheckinInput.value = "";
    staysCheckoutInput.value = "";
    filterStays();
  });
});

document.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof Node)) return;

  if (state.mobileToolbarOpen && mapFilterShell && !mapFilterShell.contains(target)) {
    setToolbarOpen(false);
  }

  if (state.stayToolbarOpen && staysMapFilterShell && !staysMapFilterShell.contains(target)) {
    setStayToolbarOpen(false);
  }
});

window.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  if (state.mobileToolbarOpen) setToolbarOpen(false);
  if (state.stayToolbarOpen) setStayToolbarOpen(false);
});

window.addEventListener("hashchange", handleHashRoute);
window.addEventListener("resize", () => {
  if (!hasLeaflet) return;
  if (isStayRoute()) {
    staysMap.invalidateSize();
    fitStayMapToVisibleMarkers();
    return;
  }

  if (isDiningRoute()) {
    map.invalidateSize();
    fitDiningMapToVisibleMarkers();
  }
});

init().catch((error) => {
  console.error(error);
  focusCard.innerHTML =
    '<div class="empty-state">Data failed to load. Run the sync script and serve this folder over HTTP.</div>';
  staysFocusCard.innerHTML =
    '<div class="empty-state">Data failed to load. Run the sync script and serve this folder over HTTP.</div>';
  resultsText.textContent = "Load failed";
  staysResultsText.textContent = "Load failed";
  tableSummary.textContent = "Load failed";
  staysTableSummary.textContent = "Load failed";
  mobileSummary.textContent = "Load failed";
  staysMobileSummary.textContent = "Load failed";
  resultsTableBody.innerHTML =
    '<tr><td colspan="8" class="empty-table">The dataset failed to load.</td></tr>';
  staysResultsTableBody.innerHTML =
    '<tr><td colspan="7" class="empty-table">The dataset failed to load.</td></tr>';
  mobileResultsList.innerHTML =
    '<div class="empty-state">The dataset failed to load.</div>';
  staysMobileResultsList.innerHTML =
    '<div class="empty-state">The dataset failed to load.</div>';
});
