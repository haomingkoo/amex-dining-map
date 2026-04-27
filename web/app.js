const DATA_URL = "../data/japan-restaurants.json";
const JAPAN_META_URL = "../data/japan-dining-source.json";
const GLOBAL_DATA_URL = "../data/global-restaurants.json";
const GLOBAL_META_URL = "../data/global-dining-source.json";
const STAYS_DATA_URL = "../data/plat-stays.json";
const STAYS_META_URL = "../data/plat-stay-source.json";
const LOVE_DINING_DATA_URL = "../data/love-dining.json";
const LOVE_DINING_META_URL = "../data/love-dining-source.json";
const TABLE_FOR_TWO_DATA_URL = "../data/table-for-two.json";
const GOOGLE_RATINGS_URL = "../data/google-maps-ratings.json";
const DINING_FIT_OPTIONS = { padding: [48, 48], maxZoom: 11 };
const STAYS_FIT_OPTIONS = { padding: [56, 56], maxZoom: 6 };
const LOVE_FIT_OPTIONS = { padding: [48, 48], maxZoom: 15 };
const TABLE_FOR_TWO_FIT_OPTIONS = { padding: [48, 48], maxZoom: 14 };
const INTRO_STORAGE_KEY = "amex-benefits-intro-v3";
const THEME_STORAGE_KEY = "theme-preference";
const MOBILE_BREAKPOINT = 820;
const THEME_TILE_URLS = {
  dark: "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
  light: "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
};
const TILE_OPTS = {
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>',
  subdomains: "abcd",
  maxZoom: 20,
};
const GLOBAL_DINING_OFFICIAL_URL = "https://www.americanexpress.com/en-sg/benefits/diningbenefit/";
const GLOBAL_DINING_CREDIT_TERMS_URL = "https://www.americanexpress.com/en-sg/benefits/the-platinum-card/dining/global-dining-credit/?extlink=SG-Web-null-sgplatdincredit";
const SINGAPORE_LOCAL_DINING_NOTICE =
  "Singapore restaurants are Local Dining Credit entries, not the abroad Global Dining Credit. For Singapore-issued Platinum Cards, the abroad Global Dining Credit applies to participating restaurants outside Singapore.";
const LOVE_DINING_RESTAURANTS_URL = "https://www.americanexpress.com/sg/benefits/love-dining/love-restaurants.html";
const LOVE_DINING_HOTELS_URL = "https://www.americanexpress.com/sg/benefits/love-dining/love-dining-hotels.html";
const LOVE_DINING_RESTAURANTS_TNC_URL = "https://www.americanexpress.com/content/dam/amex/sg/benefits/Love_Dining_Restaurants_TnCs.pdf";
const LOVE_DINING_HOTELS_TNC_URL = "https://www.americanexpress.com/content/dam/amex/sg/benefits/Love_Dining_Hotels_TnC.pdf";
const TABLE_FOR_TWO_OFFICIAL_URL = "https://www.americanexpress.com/en-sg/benefits/the-platinum-card/dining/table-for-two/";
const TABLE_FOR_TWO_TNC_URL = "https://www.americanexpress.com/content/dam/amex/en-sg/benefits/the-platinum-card/TableforTwo-Plat-TnCs.pdf";
const TABLE_FOR_TWO_FAQ_URL = "https://www.americanexpress.com/content/dam/amex/en-sg/benefits/the-platinum-card/dining/TableforTwo_FAQ.pdf";
const TABLE_FOR_TWO_AVAILABILITY_STALE_MINUTES = 30;
const TABLE_FOR_TWO_DININGCITY_API_BASE = "https://api.diningcity.asia/public";
const TABLE_FOR_TWO_DININGCITY_PROJECT = "AMEXPlatSG";
const TABLE_FOR_TWO_DININGCITY_PROJECT_TITLE = "AMEX Platinum SG";
const TABLE_FOR_TWO_LIVE_REFRESH_INTERVAL_MS = 5 * 60 * 1000;
const TABLE_FOR_TWO_DEFAULT_PARTY_SIZE = 2;
const TABLE_FOR_TWO_MAX_TIMES = 12;
const TABLE_FOR_TWO_TIME_WINDOW_MINUTES = 60;
const TABLE_FOR_TWO_TIME_WINDOW_LABEL = "1 hour";
const LOVE_DINING_FIXED_20_IDS = new Set([
  "love-pan-pacific-orchard-singapore-florette",
  "love-swissotel-the-stamford-skai-bar",
  "love-paradox-singapore-merchant-court-crossroads-bar",
]);

function normalizeTheme(theme) {
  return theme === "light" ? "light" : "dark";
}

function resolveThemePreference() {
  try {
    const storedTheme = window.localStorage.getItem(THEME_STORAGE_KEY);
    if (storedTheme === "light" || storedTheme === "dark") {
      return storedTheme;
    }
  } catch {
    // Ignore storage errors and fall back to the system setting.
  }

  // Dark mode is the default
  return "dark";
}

let currentTheme = normalizeTheme(resolveThemePreference());

function setDocumentTheme(theme) {
  currentTheme = normalizeTheme(theme);
  document.documentElement.setAttribute("data-theme", currentTheme);
  document.documentElement.style.colorScheme = currentTheme;
  document.querySelector('meta[name="theme-color"]')?.setAttribute(
    "content",
    currentTheme === "light" ? "#f5f5f5" : "#070d16",
  );
}

setDocumentTheme(currentTheme);

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
      "Amex Platinum dining partners, split by local Singapore credit and overseas Global Dining Credit.",
    defaultRoute: "dining/world",
  },
  stays: {
    id: "stays",
    label: "Plat Stay",
    title: "Plat Stay",
    description:
      "Plat Stay properties worldwide. Filter by travel dates to surface blackout conflicts.",
    defaultRoute: "stays",
  },
  "love-dining": {
    id: "love-dining",
    label: "Love Dining",
    title: "Love Dining",
    description:
      "Singapore Love Dining benefits with official savings, minimum-order filters, outlet notes, and T&C links.",
    defaultRoute: "love-dining",
  },
  "table-for-two": {
    id: "table-for-two",
    label: "Table for Two",
    title: "Table for Two",
    description:
      "Singapore Platinum set-menu roster with cached AMEXPlatSG slot availability.",
    defaultRoute: "table-for-two",
  },
  alerts: {
    id: "alerts",
    label: "Alerts",
    title: "Alerts",
    description:
      "Change watch for property additions, removals, and blackout note updates.",
    defaultRoute: "alerts",
  },
};

const ROUTES = {
  "dining/world": {
    id: "dining/world",
    programId: "dining",
    label: "All",
    eyebrow: "Dining / All",
    title: "Dining Explorer",
    description:
      "Amex Platinum dining directory — Singapore Local Dining Credit, Japan via Pocket Concierge, and abroad Global Dining Credit partners.",
    note:
      "All markets. Singapore is local dining credit; the abroad Global Dining Credit is for participating restaurants outside Singapore.",
    mapSummary:
      "All Amex Platinum dining records. Filter by country or city; Singapore records are local credit, not abroad Global Dining Credit.",
    matcher: () => true,
    defaultView: [25, 15],
    defaultZoom: 2,
  },
  "dining/japan": {
    id: "dining/japan",
    programId: "dining",
    label: "Japan",
    eyebrow: "Dining / Japan",
    title: "Japan",
    description: "Japan restaurants via Pocket Concierge, enriched with Tabelog ratings.",
    note: "Pocket Concierge partners across Japan.",
    mapSummary: "Japan-wide dining. Use the City filter to zoom into a specific city.",
    matcher: (record) => record.country === "Japan",
    defaultView: [35.676, 137.5],
    defaultZoom: 5,
  },
  "dining/singapore": {
    id: "dining/singapore",
    programId: "dining",
    label: "Singapore",
    eyebrow: "Dining / Singapore",
    title: "Singapore Local Dining Credit",
    description:
      "Singapore restaurants are Local Dining Credit entries. They are not eligible for the abroad Global Dining Credit; use Love Dining and Table for Two for separate local benefits.",
    note: "Singapore local dining credit restaurants.",
    mapSummary:
      "Singapore Local Dining Credit records. The abroad Global Dining Credit excludes Singapore restaurants.",
    matcher: (record) => record.country === "Singapore",
    defaultView: [1.3521, 103.8198],
    defaultZoom: 12,
  },
  "dining/hong-kong": {
    id: "dining/hong-kong",
    programId: "dining",
    label: "Hong Kong",
    eyebrow: "Dining / Hong Kong",
    title: "Hong Kong",
    description: "Amex Platinum Global Dining Credit partners in Hong Kong.",
    note: "Hong Kong dining credit partners.",
    mapSummary: "Hong Kong dining credit restaurants.",
    matcher: (record) => record.country === "Hong Kong",
    defaultView: [22.3193, 114.1694],
    defaultZoom: 12,
  },
  "dining/australia": {
    id: "dining/australia",
    programId: "dining",
    label: "Australia",
    eyebrow: "Dining / Australia",
    title: "Australia",
    description: "Amex Platinum Global Dining Credit partners in Australia.",
    note: "Australia dining credit partners.",
    mapSummary: "Australia dining credit restaurants.",
    matcher: (record) => record.country === "Australia",
    defaultView: [-25.2744, 133.7751],
    defaultZoom: 4,
  },
  "dining/united-kingdom": {
    id: "dining/united-kingdom",
    programId: "dining",
    label: "UK",
    eyebrow: "Dining / United Kingdom",
    title: "United Kingdom",
    description: "Amex Platinum Global Dining Credit partners in the United Kingdom.",
    note: "UK dining credit partners.",
    mapSummary: "United Kingdom dining credit restaurants.",
    matcher: (record) => record.country === "United Kingdom",
    defaultView: [54.0, -2.0],
    defaultZoom: 6,
  },
  "dining/france": {
    id: "dining/france",
    programId: "dining",
    label: "France",
    eyebrow: "Dining / France",
    title: "France",
    description: "Amex Platinum Global Dining Credit partners in France.",
    note: "France dining credit partners.",
    mapSummary: "France dining credit restaurants.",
    matcher: (record) => record.country === "France",
    defaultView: [46.2276, 2.2137],
    defaultZoom: 6,
  },
  "dining/united-states": {
    id: "dining/united-states",
    programId: "dining",
    label: "USA",
    eyebrow: "Dining / United States",
    title: "United States",
    description: "Amex Platinum Global Dining Credit partners in the United States.",
    note: "US dining credit partners.",
    mapSummary: "United States dining credit restaurants.",
    matcher: (record) => record.country === "United States",
    defaultView: [37.0902, -95.7129],
    defaultZoom: 4,
  },
  "dining/thailand": {
    id: "dining/thailand",
    programId: "dining",
    label: "Thailand",
    eyebrow: "Dining / Thailand",
    title: "Thailand",
    description: "Amex Platinum Global Dining Credit partners in Thailand.",
    note: "Thailand dining credit partners.",
    mapSummary: "Thailand dining credit restaurants.",
    matcher: (record) => record.country === "Thailand",
    defaultView: [15.87, 100.99],
    defaultZoom: 6,
  },
  "dining/taiwan": {
    id: "dining/taiwan",
    programId: "dining",
    label: "Taiwan",
    eyebrow: "Dining / Taiwan",
    title: "Taiwan",
    description: "Amex Platinum Global Dining Credit partners in Taiwan.",
    note: "Taiwan dining credit partners.",
    mapSummary: "Taiwan dining credit restaurants.",
    matcher: (record) => record.country === "Taiwan",
    defaultView: [23.5, 121.0],
    defaultZoom: 8,
  },
  "dining/germany": {
    id: "dining/germany",
    programId: "dining",
    label: "Germany",
    eyebrow: "Dining / Germany",
    title: "Germany",
    description: "Amex Platinum Global Dining Credit partners in Germany.",
    note: "Germany dining credit partners.",
    mapSummary: "Germany dining credit restaurants.",
    matcher: (record) => record.country === "Germany",
    defaultView: [51.1657, 10.4515],
    defaultZoom: 6,
  },
  "dining/mexico": {
    id: "dining/mexico",
    programId: "dining",
    label: "Mexico",
    eyebrow: "Dining / Mexico",
    title: "Mexico",
    description: "Amex Platinum Global Dining Credit partners in Mexico.",
    note: "Mexico dining credit partners.",
    mapSummary: "Mexico dining credit restaurants.",
    matcher: (record) => record.country === "Mexico",
    defaultView: [23.6345, -102.5528],
    defaultZoom: 5,
  },
  "dining/canada": {
    id: "dining/canada",
    programId: "dining",
    label: "Canada",
    eyebrow: "Dining / Canada",
    title: "Canada",
    description: "Amex Platinum Global Dining Credit partners in Canada.",
    note: "Canada dining credit partners.",
    mapSummary: "Canada dining credit restaurants.",
    matcher: (record) => record.country === "Canada",
    defaultView: [56.1304, -106.3468],
    defaultZoom: 4,
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
    eyebrow: "Love Dining / Singapore",
    title: "Love Dining",
    description:
      "Up to 50% off at Singapore restaurants and hotel outlets, with savings bands, order rules, outlet notes, and official T&C links.",
    briefCards: [
      {
        kicker: "Primary sources",
        title: "Merge page cards with PDFs",
        body:
          "The page cards are useful for map links, addresses, phones, and websites. The PDFs are the source of truth for savings structure, exclusions, and participating coverage.",
        links: [
          {
            label: "Restaurants page",
            href: LOVE_DINING_RESTAURANTS_URL,
          },
          {
            label: "Restaurants T&C PDF",
            href: LOVE_DINING_RESTAURANTS_TNC_URL,
          },
          {
            label: "Hotels page",
            href: LOVE_DINING_HOTELS_URL,
          },
          {
            label: "Hotels T&C PDF",
            href: LOVE_DINING_HOTELS_TNC_URL,
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
  "table-for-two": {
    id: "table-for-two",
    programId: "table-for-two",
    label: "Singapore",
    eyebrow: "Table For Two / Singapore",
    title: "Table for Two",
    description:
      "Singapore Platinum Table for Two venues from the official Amex 2026 roster image, with cached DiningCity AMEXPlatSG availability and app-only booking notes.",
    mapSummary:
      "Table for Two is booked via the Amex Experiences App. Generic public DiningCity restaurant slots are not treated as Table for Two allocation.",
  },
};

const state = {
  restaurants: [],
  japanSourceMeta: null,
  globalSourceMeta: null,
  stays: [],
  staysSourceMeta: null,
  scopeRecords: [],
  filtered: [],
  markers: new Map(),
  activeId: null,
  routeId: "dining/world",
  mobileToolbarOpen: false,
  tableOpen: false,
  tableSearchQuery: "",
  stayScopeRecords: [],
  stayFiltered: [],
  stayMarkers: new Map(),
  stayActiveId: null,
  stayToolbarOpen: false,
  stayTableOpen: false,
  stayBlockedCount: 0,
  loveDining: [],
  loveDiningFiltered: [],
  loveDiningMarkers: new Map(),
  loveDiningActiveId: null,
  loveDiningSourceMeta: null,
  loveToolbarOpen: false,
  tableForTwo: null,
  tableForTwoFiltered: [],
  tableForTwoMarkers: new Map(),
  tableForTwoActiveId: null,
  tableForTwoCurrentFilters: {},
  tableForTwoLiveRefreshInFlight: false,
  tableForTwoLiveRefreshAt: null,
  tableForTwoLiveRefreshTimer: null,
  googleRatings: {},
};

const hasLeaflet = typeof window !== "undefined" && typeof window.L !== "undefined";
const mapElement = document.getElementById("map");
const staysMapElement = document.getElementById("stays-map");
const loveDiningMapElement = document.getElementById("love-map");
const tableForTwoMapElement = document.getElementById("tft-map");
let themedTileLayers = [];

// Maps are initialized in init() after DOM is ready
let map = null;
let staysMap = null;
let loveMap = null;
let tableForTwoMap = null;

function initMaps() {
  if (!hasLeaflet) return;

  // Create Leaflet map instances now that DOM is ready
  if (mapElement && !map) {
    map = L.map("map", {
      zoomControl: true,
      scrollWheelZoom: true,
    }).setView([25, 15], 2);
  }

  if (staysMapElement && !staysMap) {
    staysMap = L.map("stays-map", {
      zoomControl: true,
      scrollWheelZoom: true,
    }).setView([20, 10], 2);
  }

  if (loveDiningMapElement && !loveMap) {
    loveMap = L.map("love-map", {
      zoomControl: true,
      scrollWheelZoom: true,
    }).setView([1.3521, 103.8198], 12);
  }

  if (tableForTwoMapElement && !tableForTwoMap) {
    tableForTwoMap = L.map("tft-map", {
      zoomControl: true,
      scrollWheelZoom: true,
    }).setView([1.2903, 103.8519], 12);
  }

  // Set up tile layers for all maps
  setupTileLayers();
}

function setupTileLayers() {
  if (!hasLeaflet) return;

  // Remove existing tile layers
  themedTileLayers.forEach(({ instance, layer }) => {
    if (instance && layer) instance.removeLayer(layer);
  });

  // Add new tile layers for current theme
  const tileUrl = THEME_TILE_URLS[normalizeTheme(currentTheme)];
  themedTileLayers = [map, staysMap, loveMap, tableForTwoMap]
    .filter(Boolean)
    .map((instance) => ({
      instance,
      layer: L.tileLayer(tileUrl, TILE_OPTS).addTo(instance),
    }));
}

function syncMapTheme(theme) {
  if (!hasLeaflet) return;
  currentTheme = normalizeTheme(theme);
  setupTileLayers();
}

// Note: Maps are initialized in init() after DOM is ready
// Tile layers are set up in setupTileLayers() called from initMaps()
if (!hasLeaflet) {
  if (mapElement) mapElement.innerHTML =
    '<div class="empty-state">Map library failed to load. Dining results are still available below.</div>';
  if (staysMapElement) staysMapElement.innerHTML =
    '<div class="empty-state">Map library failed to load. Plat Stay results are still available below.</div>';
  if (loveDiningMapElement) loveDiningMapElement.innerHTML =
    '<div class="empty-state">Map library failed to load. Venue list is still available below.</div>';
  if (tableForTwoMapElement) tableForTwoMapElement.innerHTML =
    '<div class="empty-state">Map library failed to load. Table for Two results are still available below.</div>';
}

const routeEyebrow = document.getElementById("route-eyebrow");
const routeTitle = document.getElementById("route-title");
const routeDescription = document.getElementById("route-description");
const introGate = document.getElementById("intro-gate");
const introSkipTopButton = document.getElementById("intro-skip-top");
const introSkipBottomButton = document.getElementById("intro-skip-bottom");
const introStartTravelButton = document.getElementById("intro-start-travel");
const introStartDiningButton = document.getElementById("intro-start-dining");
const themeToggleButton = document.getElementById("theme-toggle");
const themeToggleIcon = document.getElementById("theme-toggle-icon");
const themeToggleLabel = document.getElementById("theme-toggle-label");
const replayGuideButton = document.getElementById("replay-guide");
const programTitle = document.getElementById("program-title");
const programDescription = document.getElementById("program-description");
const journeyNav = document.getElementById("journey-nav");
const journeyLinks = [...journeyNav.querySelectorAll("[data-journey]")];
const programStrip = document.querySelector(".app-nav");
const programNav = document.getElementById("program-nav");
const programLinks = [...programNav.querySelectorAll("[data-program]")];
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
const countryFilter = document.getElementById("country-filter");
const countryFilterWrap = document.getElementById("country-filter-wrap");
const cityFilter = document.getElementById("city-filter");
const districtFilter = document.getElementById("district-filter");
const districtFilterWrap = document.getElementById("district-filter-wrap");
const tabelogFilterWrap = document.getElementById("tabelog-filter-wrap");
const lunchFilterWrap = document.getElementById("lunch-filter-wrap");
const dinnerFilterWrap = document.getElementById("dinner-filter-wrap");
const kidsFilterWrap = document.getElementById("kids-filter-wrap");
const menuFilterWrap = document.getElementById("menu-filter-wrap");
const reservationFilterWrap = document.getElementById("reservation-filter-wrap");
const googleRatingFilterWrap = document.getElementById("google-rating-filter-wrap");
const sortFilterWrap = document.getElementById("sort-filter-wrap");
const JAPAN_ONLY_FILTER_WRAPS = [tabelogFilterWrap, lunchFilterWrap, dinnerFilterWrap, kidsFilterWrap, menuFilterWrap, reservationFilterWrap];
const cuisineFilter = document.getElementById("cuisine-filter");
const tabelogFilter = document.getElementById("tabelog-filter");
const googleRatingFilter = document.getElementById("google-rating-filter");
const sortFilter = document.getElementById("sort-filter");
const lunchFilter = document.getElementById("lunch-filter");
const dinnerFilter = document.getElementById("dinner-filter");
const kidsFilter = document.getElementById("kids-filter");
const menuFilter = document.getElementById("menu-filter");
const reservationFilter = document.getElementById("reservation-filter");
const resetFiltersButton = document.getElementById("reset-filters");
const summaryStripText = document.getElementById("summary-strip-text");
const mapSummary = document.getElementById("map-summary");
const resultsText = document.getElementById("results-text");
const focusCard = document.getElementById("focus-card");
const tableSummary = document.getElementById("table-summary");
const mobileSummary = document.getElementById("mobile-summary");
const resultsTableBody = document.getElementById("results-table-body");
const mobileResultsList = document.getElementById("mobile-results-list");

// New unified mobile sheets (redesigned)
const mobileDiningSheet = document.getElementById("mobile-dining-sheet");
const mobileStaysSheet = document.getElementById("mobile-stays-sheet");
const mobileLoveDiningSheet = document.getElementById("mobile-love-dining-sheet");

const sheetElements = {
  dining: mobileDiningSheet,
  stays: mobileStaysSheet,
  loveDining: mobileLoveDiningSheet,
};
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
const staysGoogleRatingFilter = document.getElementById("stays-google-rating-filter");
const staysSortFilter = document.getElementById("stays-sort-filter");
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

const loveDiningExplorer = document.getElementById("love-dining-explorer");
const loveSummaryStripText = document.getElementById("love-summary-strip-text");
const loveMapFilterShell = document.getElementById("love-map-filter-shell");
const loveToolbar = document.getElementById("love-filter-toolbar");
const loveToolbarToggle = document.getElementById("love-toolbar-toggle");
const loveToolbarToggleMeta = document.getElementById("love-toolbar-toggle-meta");
const loveSearchInput = document.getElementById("love-search-input");
const loveTypeFilter = document.getElementById("love-type-filter");
const loveCuisineFilter = document.getElementById("love-cuisine-filter");
const loveSavingsFilter = document.getElementById("love-savings-filter");
const loveOrderFilter = document.getElementById("love-order-filter");
const loveAppliesFilter = document.getElementById("love-applies-filter");
const loveBookingFilter = document.getElementById("love-booking-filter");
const loveLocationFilter = document.getElementById("love-location-filter");
const loveResetFiltersBtn = document.getElementById("love-reset-filters");
const loveResultsText = document.getElementById("love-results-text");
const loveFocusCard = document.getElementById("love-focus-card");
const loveMobileSummary = document.getElementById("love-mobile-summary");
const loveMobileResultsList = document.getElementById("love-mobile-results-list");
const tableForTwoExplorer = document.getElementById("table-for-two-explorer");
const tableForTwoSummaryStripText = document.getElementById("tft-summary-strip-text");
const tableForTwoMapSummary = document.getElementById("tft-map-summary");
const tableForTwoListSummary = document.getElementById("tft-list-summary");
const tableForTwoSearchInput = document.getElementById("tft-search-input");
const tableForTwoCategoryFilter = document.getElementById("tft-category-filter");
const tableForTwoAvailabilityFilter = document.getElementById("tft-availability-filter");
const tableForTwoPartySizeFilter = document.getElementById("tft-party-size-filter");
const tableForTwoSessionFilter = document.getElementById("tft-session-filter");
const tableForTwoDateFilter = document.getElementById("tft-date-filter");
const tableForTwoTimeFilter = document.getElementById("tft-time-filter");
const tableForTwoDayFilter = document.getElementById("tft-day-filter");
const tableForTwoResetFiltersBtn = document.getElementById("tft-reset-filters");
const tableForTwoResultsList = document.getElementById("tft-results-list");
const tableForTwoResultsText = document.getElementById("tft-results-text");
const tableForTwoFocusCard = document.getElementById("tft-focus-card");
const tableForTwoAlertSignupPanel = document.getElementById("tft-alert-signup-panel");
const tableForTwoAlertSignupLink = document.getElementById("tft-alert-signup-link");

function updateThemeToggle(theme) {
  if (!themeToggleButton) return;

  const normalizedTheme = normalizeTheme(theme);
  const isLightTheme = normalizedTheme === "light";
  themeToggleButton.setAttribute("aria-pressed", String(isLightTheme));
  themeToggleButton.setAttribute(
    "aria-label",
    isLightTheme ? "Switch to dark theme" : "Switch to light theme",
  );

  if (themeToggleIcon) {
    themeToggleIcon.textContent = isLightTheme ? "☀" : "☾";
  }
  if (themeToggleLabel) {
    themeToggleLabel.textContent = isLightTheme ? "Light" : "Dark";
  }
}

function applyTheme(theme, { persist = false } = {}) {
  const normalizedTheme = normalizeTheme(theme);
  setDocumentTheme(normalizedTheme);
  syncMapTheme(normalizedTheme);
  updateThemeToggle(normalizedTheme);

  if (!persist) return;

  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, normalizedTheme);
  } catch {
    // Ignore storage errors; the theme still applies for this session.
  }
}

function initTheme() {
  const preferredTheme = normalizeTheme(resolveThemePreference());
  applyTheme(preferredTheme);

  themeToggleButton?.addEventListener("click", () => {
    const nextTheme = currentTheme === "light" ? "dark" : "light";
    applyTheme(nextTheme, { persist: true });
  });
}

function fuzzyMatchSearch(text, query) {
  const normalizedText = String(text || "").toLowerCase();
  const normalizedQuery = String(query || "").trim().toLowerCase();

  if (!normalizedQuery) return true;
  if (normalizedText.includes(normalizedQuery)) return true;

  const textWords = normalizedText.match(/[\p{L}\p{N}]+/gu) || [];
  const queryWords = normalizedQuery.match(/[\p{L}\p{N}]+/gu) || [];

  if (!queryWords.length) return true;
  if (!textWords.length) return false;

  const levenshteinWithinThreshold = (source, target, maxDistance) => {
    if (source === target) return true;
    if (Math.abs(source.length - target.length) > maxDistance) return false;

    let previousRow = Array.from({ length: target.length + 1 }, (_, index) => index);
    let currentRow = new Array(target.length + 1);

    for (let i = 1; i <= source.length; i += 1) {
      currentRow[0] = i;
      let rowMin = currentRow[0];
      const sourceChar = source.charCodeAt(i - 1);

      for (let j = 1; j <= target.length; j += 1) {
        const cost = sourceChar === target.charCodeAt(j - 1) ? 0 : 1;
        currentRow[j] = Math.min(
          previousRow[j] + 1,
          currentRow[j - 1] + 1,
          previousRow[j - 1] + cost
        );
        if (currentRow[j] < rowMin) rowMin = currentRow[j];
      }

      if (rowMin > maxDistance) return false;
      [previousRow, currentRow] = [currentRow, previousRow];
    }

    return previousRow[target.length] <= maxDistance;
  };

  return queryWords.every((queryWord) => {
    if (queryWord.length < 3) {
      return textWords.some((textWord) => textWord.includes(queryWord));
    }

    const maxDistance = Math.floor(queryWord.length * 0.3);
    return textWords.some((textWord) => {
      if (textWord.includes(queryWord)) return true;
      return levenshteinWithinThreshold(queryWord, textWord, maxDistance);
    });
  });
}

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

function labeledBadge(label, value, tone = "") {
  if (!value) return "";
  const className = ["badge", tone].filter(Boolean).join(" ");
  return `<span class="${className}">${escapeHtml(`${label}: ${value}`)}</span>`;
}

function pushLabeledBadge(entries, seen, label, value, tone = "") {
  if (!value) return;
  const text = String(value).trim();
  if (!text) return;
  const normalized = text.toLowerCase();
  if (seen.has(normalized)) return;
  seen.add(normalized);
  entries.push(labeledBadge(label, text, tone));
}

function sourceConfidenceLabel(value) {
  const labels = {
    manual_verified: "Verified listing",
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

const REGION_COLORS = {
  "east-asia":     "#e8a235",  // warm amber  — Japan, Hong Kong, Taiwan
  "southeast-asia":"#e07248",  // coral       — Singapore, Thailand
  "europe":        "#9b7ee8",  // violet      — UK, France, Germany, Austria, Italy, Spain, Monaco
  "americas":      "#4b95e0",  // sky blue    — USA, Canada, Mexico
  "oceania":       "#5ec9aa",  // mint teal   — Australia, New Zealand
  "other":         "#8899aa",  // muted gray
};

function regionForRecord(record) {
  const c = record.country;
  if (c === "Japan" || c === "Hong Kong" || c === "Taiwan") return "east-asia";
  if (c === "Singapore" || c === "Thailand") return "southeast-asia";
  if (c === "United Kingdom" || c === "France" || c === "Germany" || c === "Austria" ||
      c === "Italy" || c === "Spain" || c === "Monaco") return "europe";
  if (c === "United States" || c === "Canada" || c === "Mexico") return "americas";
  if (c === "Australia" || c === "New Zealand") return "oceania";
  return "other";
}

function markerColor(record) {
  return REGION_COLORS[regionForRecord(record)] || REGION_COLORS.other;
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

function recordLongitude(record) {
  if (!record) return null;
  return record.lng ?? record.lon ?? null;
}

function hasCoordinates(record) {
  return record?.lat != null && recordLongitude(record) != null;
}

function latLngForRecord(record) {
  if (!hasCoordinates(record)) return null;
  return [record.lat, recordLongitude(record)];
}

function hasSourceCoordinates(record) {
  return record.lat != null && record.lng != null && record.coordinate_confidence === "source";
}

function hasVerifiedCoordinates(record) {
  return (
    record.lat != null
    && record.lng != null
    && [
      "manual_verified",
      "poi_address_matched",
      "google_place_verified",
    ].includes(record.coordinate_confidence)
  );
}

function diningLocationBadge(record) {
  if (record.lat == null || record.lng == null) return "";
  if (record.coordinate_confidence === "location_conflict") {
    return '<span class="badge amber">Location needs review</span>';
  }
  if (record.coordinate_confidence === "approximate") {
    return '<span class="badge amber">Approximate pin</span>';
  }
  if (record.coordinate_confidence === "source_map_verified") {
    return '<span class="badge blue">Source map pin</span>';
  }
  if (record.coordinate_confidence === "google_place_verified") {
    return '<span class="badge green">Place matched</span>';
  }
  if (record.coordinate_confidence === "address_validated") {
    return '<span class="badge blue">Address geocoded</span>';
  }
  if (record.coordinate_confidence === "manual_verified") {
    return '<span class="badge green">Manual pin check</span>';
  }
  if (hasVerifiedCoordinates(record)) {
    return '<span class="badge green">Place matched</span>';
  }
  return "";
}

function diningCreditBadge(record) {
  if (record.country === "Singapore") {
    return '<span class="badge amber">SG Local Dining Credit</span>';
  }
  if (record.source === "Amex Platinum Dining" && record.country && record.country !== "Japan") {
    return '<span class="badge green">Abroad Global Dining Credit</span>';
  }
  return "";
}

function googleMapsSearchUrl(parts) {
  const query = parts.filter(Boolean).join(", ");
  if (!query) return null;
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`;
}

function googleRating(record) {
  return state.googleRatings[record.id] || null;
}

function bestGoogleMapsUrl(record) {
  const scraped = state.googleRatings[record.id];
  if (scraped && scraped.maps_url) return scraped.maps_url;
  return null;
}

function googleRatingBadge(record) {
  const g = googleRating(record);
  if (!g || g.rating == null) return "";
  const url = bestGoogleMapsUrl(record)
    || (record.dataset === "plat_stay" ? stayGoogleMapsUrl(record) : diningGoogleMapsUrl(record));
  const countStr = g.review_count ? ` · ${Number(g.review_count).toLocaleString()} reviews` : "";
  const tag = url ? "a" : "span";
  const attrs = url
    ? ` href="${escapeHtml(url)}" target="_blank" rel="noopener"`
    : "";
  return `<${tag} class="google-badge"${attrs}>
    <span class="google-stars">${escapeHtml(String(g.rating))}</span>
    <span class="google-meta">Google Maps${escapeHtml(countStr)}</span>
  </${tag}>`;
}

function diningKicker(record) {
  const sub = record.district || record.region || record.area_title || record.prefecture || "";
  if (record.country && record.country !== "Japan") {
    const parts = [record.country, record.city, sub].filter(Boolean);
    return parts.join(" / ");
  }
  return [record.city, sub].filter(Boolean).join(" / ");
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
  const signals = qualitySignals(record);
  const tabelogSignal = signals.tabelog;
  if (record.country === "Japan" && tabelogSignal && tabelogSignal.google_query) {
    return googleMapsSearchUrl([tabelogSignal.google_query]);
  }

  const fallback = googleMapsSearchUrl([
    record.name,
    record.source_localized_address || record.district || record.city,
    record.country !== "Japan" ? record.country : (record.prefecture || "Japan"),
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

function diningLocationTags(record) {
  const entries = [];
  const seen = new Set();
  if (record.country && record.country !== "Japan") {
    pushLabeledBadge(entries, seen, "Country", record.country, "gold");
  }
  pushLabeledBadge(entries, seen, "City", record.city, record.country === "Japan" ? "gold" : "");
  if (record.district) {
    pushLabeledBadge(entries, seen, "District", record.district);
  } else if (record.area_title) {
    pushLabeledBadge(entries, seen, "Area", record.area_title);
  } else if (record.prefecture) {
    pushLabeledBadge(entries, seen, "Prefecture", record.prefecture);
  } else if (record.region) {
    pushLabeledBadge(entries, seen, "Region", record.region);
  }
  return entries;
}

function stayLocationTags(record) {
  const entries = [];
  const seen = new Set();
  pushLabeledBadge(entries, seen, "Country", record.country, "gold");
  pushLabeledBadge(entries, seen, "City", record.city);
  return entries;
}

function focusLocationNote(record) {
  if (record.coordinate_confidence === "location_conflict") {
    return "Location may be imprecise — verify the address before visiting.";
  }
  if (record.coordinate_confidence === "approximate") {
    return "Location is approximate — confirm the address before visiting.";
  }
  if (["manual_verified", "google_place_verified"].includes(record.coordinate_confidence) && record.map_pin_note) {
    return record.map_pin_note;
  }
  if (record.coordinate_confidence === "source_map_verified") {
    return "Pin follows the official source map link, but this is not an independent 20m verification.";
  }
  if (record.coordinate_confidence === "address_validated") {
    return "Pin is address-geocoded; confirm the exact entrance before visiting.";
  }
  return "";
}

function diningCreditEligibilityNote(record) {
  if (record.country === "Singapore") {
    return SINGAPORE_LOCAL_DINING_NOTICE;
  }
  return "";
}

function formatAddress(raw, country) {
  if (!raw) return "";
  // Replace " / " separators from scraper, remove trailing country
  let addr = raw.replace(/\s*\/\s*/g, ", ");
  // Remove country from end if present
  if (country) {
    const trailingCountry = new RegExp(",?\\s*" + country.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "\\s*$", "i");
    addr = addr.replace(trailingCountry, "");
  }
  // Deduplicate consecutive repeated segments (e.g. "Wellington, Wellington")
  const parts = addr.split(",").map(p => p.trim()).filter(Boolean);
  const deduped = parts.filter((p, i) => i === 0 || p.toLowerCase() !== parts[i - 1].toLowerCase());
  return deduped.join(", ");
}

function naturalList(items) {
  const values = (items || []).filter(Boolean);
  if (!values.length) return "";
  if (values.length === 1) return values[0];
  if (values.length === 2) return `${values[0]} and ${values[1]}`;
  return `${values.slice(0, -1).join(", ")}, and ${values[values.length - 1]}`;
}

function diningSummaryPayload(record) {
  const official = (record.summary_official || "").trim();
  if (official) {
    return { text: official, isAi: false };
  }

  const knownFor = Array.isArray(record.known_for_tags) ? record.known_for_tags.filter(Boolean) : [];
  const specialties = Array.isArray(record.signature_dish_tags) ? record.signature_dish_tags.filter(Boolean) : [];
  if (knownFor.length || specialties.length) {
    const parts = [];
    if (knownFor.length) {
      parts.push(`Known for ${naturalList(knownFor)}.`);
    }
    if (specialties.length) {
      parts.push(`Signature dishes: ${naturalList(specialties)}.`);
    }
    return { text: parts.join(" "), isAi: false };
  }

  return null;
}

function createMarker(record) {
  if (!hasLeaflet) return null;
  if (record.lat == null || record.lng == null) return null;

  const dinnerBand = priceBandLabel(record.price_dinner_band_tier, record.price_dinner_band_label);
  const lunchBand = priceBandLabel(record.price_lunch_band_tier, record.price_lunch_band_label);
  const summary = diningSummaryPayload(record);

  // Use a custom div icon instead of circleMarker which doesn't render reliably
  const markerColor_val = markerColor(record);
  const marker = L.marker([record.lat, record.lng], {
    icon: L.divIcon({
      html: `<div style="width: 16px; height: 16px; border-radius: 50%; background: ${markerColor_val}; border: 2px solid #091018; opacity: 0.92; cursor: pointer;"></div>`,
      iconSize: [16, 16],
      className: 'custom-marker-icon'
    })
  });

  // Simple popup: name + cuisine + rating + Google Maps link
  const gRating = googleRating(record);
  const cuisine = (record.cuisines || []).join(", ") || "";
  const ratingHtml = gRating && gRating.rating != null
    ? `<div style="margin-top:4px; font-size:0.9em">★ ${gRating.rating}${gRating.review_count ? ` (${gRating.review_count})` : ""}</div>`
    : "";
  marker.on("click", () => {
    setActiveRecord(record.id);
    if (map && hasLeaflet) {
      smartZoomToMarker(map, marker.getLatLng());
    }
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

function isTableForTwoRoute(route = currentRoute()) {
  return route.programId === "table-for-two";
}

function isLiveDataRoute(route = currentRoute()) {
  return isDiningRoute(route) || isStayRoute(route) || isLoveDiningRoute(route) || isTableForTwoRoute(route);
}

function currentJourneyId(route = currentRoute()) {
  if (isDiningRoute(route) || isStayRoute(route)) return "travel";
  if (route.programId === "love-dining" || route.programId === "table-for-two") return "singapore";
  if (route.programId === "alerts") return "alerts";
  return null;
}

function visibleProgramIdsForJourney(journeyId) {
  if (journeyId === "travel") {
    return ["dining", "stays"];
  }
  if (journeyId === "singapore") {
    return ["love-dining", "table-for-two"];
  }
  if (journeyId === "alerts") {
    return ["alerts"];
  }
  return ["dining", "stays", "love-dining", "table-for-two"];
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

function diningSourceKind(record) {
  if (!record) return null;
  if (record.country === "Japan" || record.source === "Pocket Concierge") return "japan";
  if (record.source === "Amex Platinum Dining" || record.country) return "global";
  return null;
}

function diningSourceMeta(kind) {
  if (kind === "japan") return state.japanSourceMeta;
  if (kind === "global") return state.globalSourceMeta;
  return null;
}

function diningSourceName(kind) {
  if (kind === "japan") return "Pocket Concierge";
  if (kind === "global") return "Amex official directory";
  return "Source";
}

function diningSourceCacheLabelForKind(kind) {
  const meta = diningSourceMeta(kind);
  if (!meta?.fetched_at) return "";
  return `${diningSourceName(kind)} cached ${formatTimestamp(meta.fetched_at)}`;
}

function diningSourceCacheLabel(record) {
  return diningSourceCacheLabelForKind(diningSourceKind(record));
}

function diningRouteCacheSummary(records = state.scopeRecords) {
  const order = ["global", "japan"];
  const kinds = new Set(records.map((record) => diningSourceKind(record)).filter(Boolean));
  return order
    .filter((kind) => kinds.has(kind))
    .map((kind) => diningSourceCacheLabelForKind(kind))
    .filter(Boolean)
    .join(" · ");
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
  if (countryFilter.value) count += 1;
  if (!route.fixedCity && cityFilter.value) count += 1;
  if (districtFilter.value) count += 1;
  if (cuisineFilter.value) count += 1;
  if (tabelogFilter.value) count += 1;
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

function normalizeRouteHash(hashValue = window.location.hash) {
  return String(hashValue || "")
    .replace(/^#\/?/, "")
    .split(/[?&]/)[0]
    .replace(/\/+$/, "")
    .trim()
    .toLowerCase();
}

function resolveRouteFromHash(hashValue = window.location.hash) {
  const hash = normalizeRouteHash(hashValue);
  const aliases = {
    all: "dining/world",
    world: "dining/world",
    japan: "dining/japan",
    tokyo: "dining/japan",
    kyoto: "dining/japan",
    osaka: "dining/japan",
    dining: "dining/world",
    "plat-stay": "stays",
    tft: "table-for-two",
    "table-for-two": "table-for-two",
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
  document.body.classList.toggle("route-dining", route.programId === "dining");
  document.body.classList.toggle("route-stays", route.programId === "stays");
  document.body.classList.toggle("route-love-dining", route.programId === "love-dining");
  document.body.classList.toggle("route-table-for-two", route.programId === "table-for-two");
  document.body.classList.toggle("route-alerts", route.programId === "alerts");
  if (routeEyebrow) routeEyebrow.textContent = route.eyebrow;
  if (routeDescription) routeDescription.textContent = route.description;
  programTitle.textContent = program.title;
  programDescription.textContent = program.description;

  // Always keep primary nav visible — mark active tab only
  programLinks.forEach((link) => {
    link.hidden = false;
    link.classList.toggle("active", link.dataset.program === program.id);
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
    navigateToRouteHash(routeHash);
  }
  window.setTimeout(() => {
    const routeId = resolveRouteFromHash();
    const route = ROUTES[routeId] || ROUTES["dining/world"];
    const target = isStayRoute(route)
      ? staysExplorer
      : isLoveDiningRoute(route)
        ? loveDiningExplorer
        : isTableForTwoRoute(route)
          ? tableForTwoExplorer
          : dataExplorer;
    target?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, 80);
}

function renderScopeShell(route) {
  routeTitle.textContent = route.label;
  mapSummary.textContent = route.mapSummary;
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
  countryFilter.value = "";
  districtFilter.value = "";
  cuisineFilter.value = "";
  tabelogFilter.value = "";
  googleRatingFilter.value = "";
  sortFilter.value = "";
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

  // Country filter: visible only when scope spans multiple countries
  const uniqueCountries = new Set(scopeRecords.map((r) => r.country));
  const isMultiCountry = uniqueCountries.size > 1;
  if (countryFilterWrap) {
    countryFilterWrap.hidden = !isMultiCountry;
  }
  if (isMultiCountry) {
    fillSelect(countryFilter, uniqueValues(scopeRecords.map((r) => r.country)), "All countries");
  }

  // Japan-only filters: show only when the entire scope is Japan, or user picked Japan
  const selectedCountry = countryFilter.value;
  const allJapan = scopeRecords.length > 0 && scopeRecords.every((r) => r.country === "Japan");
  const showJapanFilters = allJapan || selectedCountry === "Japan";
  JAPAN_ONLY_FILTER_WRAPS.forEach((wrap) => { if (wrap) wrap.hidden = !showJapanFilters; });
  if (districtFilterWrap) districtFilterWrap.hidden = !showJapanFilters;

  const countryPool = selectedCountry
    ? scopeRecords.filter((r) => r.country === selectedCountry)
    : scopeRecords;

  const selectedCity = route.fixedCity || cityFilter.value;

  if (route.fixedCity) {
    cityFilter.innerHTML = `<option value="${route.fixedCity}">${route.fixedCity}</option>`;
    cityFilter.value = route.fixedCity;
    cityFilter.disabled = true;
  } else {
    cityFilter.disabled = false;
    fillSelect(cityFilter, uniqueValues(countryPool.map((record) => record.city)), "All cities");
  }

  const districtPool = scopeRecords.filter((record) => {
    if (selectedCountry && record.country !== selectedCountry) return false;
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
  // If active record was filtered out, clear it — but never auto-select
  if (state.activeId && !state.filtered.some((record) => record.id === state.activeId)) {
    state.activeId = null;
  }
}

function filterRestaurants(options = {}) {
  const search = searchInput.value.trim().toLowerCase();
  const route = currentRoute();
  const country = countryFilter.value;
  const hasSelectedCity = Object.prototype.hasOwnProperty.call(options, "selectedCity");
  const city = route.fixedCity || (hasSelectedCity ? options.selectedCity : cityFilter.value);
  const district = districtFilter.value;
  const cuisine = cuisineFilter.value;
  const tabelog = tabelogFilter.value;
  const googleRatingFilterValue = googleRatingFilter.value;
  const sort = sortFilter.value;
  const lunchBand = lunchFilter.value;
  const dinnerBand = dinnerFilter.value;
  const kids = kidsFilter.value;
  const menu = menuFilter.value;
  const reservation = reservationFilter.value;

  state.filtered = state.scopeRecords.filter((record) => {
    if (country && record.country !== country) return false;
    if (city && record.city !== city) return false;
    if (district && (record.district || record.region || record.area_title) !== district) return false;
    if (cuisine && !(record.cuisines || []).includes(cuisine)) return false;
    const tabelogSignal = qualitySignals(record).tabelog;
    if (tabelog === "available" && !tabelogSignal) return false;
    const tScore = tabelogSignal ? (tabelogSignal.score_raw ?? tabelogSignal.honest_stars) : null;
    if (tabelog === "3_5plus" && !(tScore != null && tScore >= 3.5)) return false;
    if (tabelog === "3_8plus" && !(tScore != null && tScore >= 3.8)) return false;
    if (tabelog === "4plus" && !(tScore != null && tScore >= 4.0)) return false;
    if (tabelog === "4_5plus" && !(tScore != null && tScore >= 4.5)) return false;

    // Google Maps rating filter
    const gRating = googleRating(record);
    if (googleRatingFilterValue === "has_rating" && !gRating) return false;
    if (googleRatingFilterValue === "3plus" && !(gRating && gRating.rating >= 3.0)) return false;
    if (googleRatingFilterValue === "3_5plus" && !(gRating && gRating.rating >= 3.5)) return false;
    if (googleRatingFilterValue === "4plus" && !(gRating && gRating.rating >= 4.0)) return false;
    if (googleRatingFilterValue === "4_5plus" && !(gRating && gRating.rating >= 4.5)) return false;

    if (lunchBand && record.price_lunch_band_key !== lunchBand) return false;
    if (dinnerBand && record.price_dinner_band_key !== dinnerBand) return false;
    if (kids === "older_kids_only" && !["older_children_only", "teens_only"].includes(record.child_policy_norm)) {
      return false;
    }
    if (kids && kids !== "older_kids_only" && record.child_policy_norm !== kids) return false;
    if (menu === "yes" && !record.english_menu) return false;
    if (menu === "no" && record.english_menu) return false;
    if (reservation && record.reservation_type !== reservation) return false;
    if (search && !fuzzyMatchSearch(record.search_text || "", search)) return false;
    return true;
  });

  // Apply sorting
  if (sort === "rating_high") {
    state.filtered.sort((a, b) => {
      const aRating = googleRating(a)?.rating ?? -1;
      const bRating = googleRating(b)?.rating ?? -1;
      return bRating - aRating;
    });
  } else if (sort === "reviews_high") {
    state.filtered.sort((a, b) => {
      const aCount = googleRating(a)?.review_count ?? 0;
      const bCount = googleRating(b)?.review_count ?? 0;
      return bCount - aCount;
    });
  } else if (sort === "name_a") {
    state.filtered.sort((a, b) => (a.name || "").localeCompare(b.name || ""));
  }

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
  const scopeCountries = uniqueValues(state.scopeRecords.map((r) => r.country));
  const filteredCountries = uniqueValues(state.filtered.map((r) => r.country));
  const scopeCities = uniqueValues(state.scopeRecords.map((record) => record.city));
  const filteredCities = uniqueValues(state.filtered.map((record) => record.city));
  const filterCount = activeFilterCount();
  const isMulti = scopeCountries.length > 1;

  const scopeLoc = isMulti
    ? `${scopeCountries.length} countries, ${scopeCities.length} cities`
    : `${scopeCities.length} cities`;
  const filteredLoc = isMulti
    ? `${filteredCountries.length} ${filteredCountries.length === 1 ? "country" : "countries"}, ${filteredCities.length} ${filteredCities.length === 1 ? "city" : "cities"}`
    : `${filteredCities.length} ${filteredCities.length === 1 ? "city" : "cities"}`;

  const mappedText = filteredMapped === state.filtered.length ? "" : `, ${filteredMapped} mapped`;
  const scopeMappedText = filteredMapped === state.scopeRecords.length ? "" : `, ${filteredMapped} mapped`;
  const cacheSummary = diningRouteCacheSummary();
  const cacheText = cacheSummary ? ` · ${cacheSummary}.` : ".";

  summaryStripText.textContent =
    filterCount > 0
      ? `${state.filtered.length} of ${state.scopeRecords.length} venues shown across ${filteredLoc}${mappedText}${cacheText}`
      : `${state.scopeRecords.length} venues across ${scopeLoc}${scopeMappedText}${cacheText}`;

  resultsText.textContent = state.activeId ? `Selected venue · ${route.label}` : `Click a dot to select · ${route.label}`;
  tableSummary.textContent =
    filterCount > 0 ? "Current filtered shortlist in table form." : "Current route list in table form.";
  mobileSummary.textContent = `${state.filtered.length} venues${state.filtered.length > MOBILE_PAGE_SIZE ? ` — scroll to browse all` : ""}`;
  mapSummary.textContent = window.innerWidth <= MOBILE_BREAKPOINT ? "Tap a dot to explore a restaurant" : route.mapSummary;
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
  const diningFocusPanel = focusCard.closest(".focus-panel");
  if (!record) {
    focusCard.innerHTML = state.filtered.length > 0
      ? `<div class="empty-state map-cta">
          <div class="map-cta-icon" aria-hidden="true">◉</div>
          <p class="map-cta-heading">Select a dining venue</p>
          <p class="map-cta-sub">Use a map pin or table row to review cuisine, ratings, and eligibility notes.</p>
        </div>`
      : '<div class="empty-state">No matches. Adjust filters to expand results.</div>';
    // Hide focus-panel on mobile when no record
    if (window.innerWidth <= MOBILE_BREAKPOINT) {
      if (diningFocusPanel) diningFocusPanel.style.display = 'none';
    } else if (diningFocusPanel) {
      diningFocusPanel.style.display = '';
    }
    return;
  }

  // On mobile, show selected dining details inline below the map.
  if (window.innerWidth <= MOBILE_BREAKPOINT) {
    if (diningFocusPanel) diningFocusPanel.style.display = 'flex';
  } else if (diningFocusPanel) {
    diningFocusPanel.style.display = '';
  }

  const isJapan = record.country === "Japan";
  const hasDinnerPrice = !!(record.price_dinner_band_tier || record.price_dinner_min_jpy);
  const hasLunchPrice = !!(record.price_lunch_band_tier || record.price_lunch_min_jpy);
  const showPriceGrid = isJapan && (hasDinnerPrice || hasLunchPrice);
  const kidPolicyKnown = isJapan && record.child_policy_norm && record.child_policy_norm !== "unknown";

  const tags = [
    ...diningLocationTags(record),
    diningCreditBadge(record),
    diningLocationBadge(record),
    isJapan && record.price_dinner_band_tier && record.price_dinner_band_label
      ? `<span class="badge amber">${escapeHtml(priceBandLabel(record.price_dinner_band_tier, record.price_dinner_band_label))}</span>`
      : "",
    isJapan && record.price_lunch_band_tier && record.price_lunch_band_label
      ? `<span class="badge blue">${escapeHtml(priceBandLabel(record.price_lunch_band_tier, record.price_lunch_band_label))}</span>`
      : "",
    kidPolicyKnown ? `<span class="badge">${escapeHtml(kidLabel(record.child_policy_norm))}</span>` : "",
    isJapan && record.english_menu ? '<span class="badge green">English menu</span>' : "",
    isJapan && record.reservation_type ? `<span class="badge purple">${escapeHtml(record.reservation_type)}</span>` : "",
  ]
    .filter(Boolean)
    .join("");

  const tabelogSignal = qualitySignals(record).tabelog;
  const tabelogScore = tabelogSignal?.score_raw ?? tabelogSignal?.honest_stars;
  const tabelogBadge = tabelogSignal && tabelogScore != null
    ? `<a class="tabelog-badge" href="${escapeHtml(tabelogSignal.url || tabelogSearchUrl(record) || "#")}" target="_blank" rel="noopener">
        <span class="tabelog-stars">${escapeHtml(String(tabelogScore))}</span>
        <span class="tabelog-meta">Tabelog${tabelogSignal.review_count ? ` · ${Number(tabelogSignal.review_count).toLocaleString()} reviews` : ""}</span>
      </a>`
    : "";

  const gBadge = googleRatingBadge(record);
  const ratingBadges = tabelogBadge || gBadge ? `<div class="focus-ratings">${tabelogBadge}${gBadge}</div>` : "";
  const googleMapsUrl = bestGoogleMapsUrl(record) || diningGoogleMapsUrl(record);
  const tSearchUrl = tabelogSignal && tabelogSignal.url ? tabelogSignal.url : tabelogSearchUrl(record);
  const summary = diningSummaryPayload(record);
  const sourceCacheLabel = diningSourceCacheLabel(record);

  focusCard.innerHTML = `
    <div class="focus-kicker">${escapeHtml(diningKicker(record))}</div>
    <div class="focus-title-row">
      <div class="focus-title-block">
        <h3 class="focus-title">${escapeHtml(record.name)}</h3>
        <div class="focus-subtitle">${escapeHtml((record.cuisines || []).join(", ") || "Cuisine unknown")}</div>
      </div>
      ${ratingBadges}
    </div>
    ${
      record.source_localized_address
        ? `<div class="focus-address">${escapeHtml(formatAddress(record.source_localized_address, record.country))}</div>`
        : ""
    }
    ${
      record.nearest_stations && record.nearest_stations.length
        ? `<div class="focus-transit">${escapeHtml(record.nearest_stations.join(" | "))}</div>`
        : ""
    }
    <div class="focus-tags">${tags}</div>
    ${tagSection("Known for", record.known_for_tags, "gold")}
    ${tagSection("Signature dishes", record.signature_dish_tags, "blue")}
    ${summary ? `<p class="focus-summary${summary.isAi ? " focus-summary-ai" : ""}">${escapeHtml(summary.text)}</p>` : ""}
    ${showPriceGrid ? `
    <div class="price-grid">
      ${hasDinnerPrice ? `<div class="price-card">
        <span class="price-label">Dinner</span>
        ${priceMarkup(record.price_dinner_min_jpy, record.price_dinner_max_jpy, record.price_dinner_band_tier, record.price_dinner_band_label)}
      </div>` : ""}
      ${hasLunchPrice ? `<div class="price-card">
        <span class="price-label">Lunch</span>
        ${priceMarkup(record.price_lunch_min_jpy, record.price_lunch_max_jpy, record.price_lunch_band_tier, record.price_lunch_band_label)}
      </div>` : ""}
    </div>` : ""}
    ${diningCreditEligibilityNote(record) ? `<div class="focus-note focus-note-warn">${escapeHtml(diningCreditEligibilityNote(record))}</div>` : ""}
    ${sourceCacheLabel ? `<div class="focus-note">Data source: ${escapeHtml(sourceCacheLabel)}.</div>` : ""}
    ${focusLocationNote(record) ? `<div class="focus-note">${escapeHtml(focusLocationNote(record))}</div>` : ""}
    <div class="focus-actions">
      ${
        googleMapsUrl
          ? `<a class="inline-link primary-action" href="${escapeHtml(googleMapsUrl)}" target="_blank" rel="noopener">Open in Google Maps</a>`
          : ""
      }
      ${
        record.country === "Japan" && tSearchUrl
          ? `<a class="inline-link" href="${escapeHtml(tSearchUrl)}" target="_blank" rel="noopener">${tabelogSignal && tabelogSignal.url ? "View on Tabelog" : "Search Tabelog"}</a>`
          : ""
      }
      ${
        record.website_url
          ? `<a class="inline-link subtle" href="${escapeHtml(record.website_url)}" target="_blank" rel="noopener">Restaurant website</a>`
          : record.source_url
          ? `<a class="inline-link subtle" href="${escapeHtml(record.source_url)}" target="_blank" rel="noopener">${record.source === "Amex Platinum Dining" ? "Amex Dining page" : "Pocket Concierge"}</a>`
          : ""
      }
      ${
        record.source === "Amex Platinum Dining"
          ? `<a class="inline-link subtle" href="${escapeHtml(GLOBAL_DINING_CREDIT_TERMS_URL)}" target="_blank" rel="noopener">Credit terms</a>`
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
      '<tr><td colspan="8" class="empty-table">No matches. Adjust filters to expand results.</td></tr>';
    return;
  }

  const tq = state.tableSearchQuery.toLowerCase();
  const tableRows = tq
    ? state.filtered.filter((r) =>
        (r.name || "").toLowerCase().includes(tq) ||
        (r.city || "").toLowerCase().includes(tq) ||
        (r.country || "").toLowerCase().includes(tq) ||
        (r.cuisines || []).join(" ").toLowerCase().includes(tq)
      )
    : state.filtered;

  resultsTableBody.innerHTML = "";
  if (!tableRows.length) {
    resultsTableBody.innerHTML =
      '<tr><td colspan="8" class="empty-table">No matches in table. Try a different search.</td></tr>';
    return;
  }

  tableRows.forEach((record) => {
    const row = document.createElement("tr");
    row.className = record.id === state.activeId ? "active" : "";
    row.addEventListener("click", () => {
      setActiveRecord(record.id);
      focusActiveRecordOnMap();
    });

    const isJapanRow = record.country === "Japan";
    const gRow = googleRating(record);
    const gRatingCell = gRow && gRow.rating != null
      ? `<span class="table-rating">${gRow.rating}${gRow.review_count ? `<span class="table-rating-count"> (${Number(gRow.review_count).toLocaleString()})</span>` : ""}</span>`
      : "—";

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
        <div>${escapeHtml(record.country !== "Japan" ? record.country + " / " + record.city : record.city)}</div>
        <div class="table-sub">${escapeHtml(formatAddress(record.source_localized_address, record.country) || record.district || record.region || record.area_title || "")}</div>
      </td>
      <td>${escapeHtml((record.cuisines || []).join(", ") || "Unknown")}</td>
      <td>${isJapanRow ? priceMarkup(
        record.price_dinner_min_jpy,
        record.price_dinner_max_jpy,
        record.price_dinner_band_tier,
        record.price_dinner_band_label
      ) : "—"}</td>
      <td>${isJapanRow ? priceMarkup(
        record.price_lunch_min_jpy,
        record.price_lunch_max_jpy,
        record.price_lunch_band_tier,
        record.price_lunch_band_label
      ) : "—"}</td>
      <td>${isJapanRow && record.child_policy_norm && record.child_policy_norm !== "unknown" ? escapeHtml(kidLabel(record.child_policy_norm)) : "—"}</td>
      <td>${isJapanRow ? (record.english_menu ? "Yes" : "No") : "—"}</td>
      <td>${gRatingCell}</td>
    `;
    resultsTableBody.appendChild(row);
  });
}

const MOBILE_PAGE_SIZE = 50;
let mobileCardPage = 1;

function renderMobileCards(resetPage = true) {
  if (resetPage) mobileCardPage = 1;
  if (!state.filtered.length) {
    mobileResultsList.innerHTML =
      '<div class="empty-state">No matches. Adjust filters to expand results.</div>';
    return;
  }

  const pageLimit = mobileCardPage * MOBILE_PAGE_SIZE;
  const visible = state.filtered.slice(0, pageLimit);
  const remaining = state.filtered.length - visible.length;

  mobileResultsList.innerHTML = "";
  visible.forEach((record) => {
    const card = document.createElement("article");
    card.className = `mobile-card${record.id === state.activeId ? " active" : ""}`;
    const isJapan = record.country === "Japan";
    const dinnerBand = isJapan ? priceBandLabel(record.price_dinner_band_tier, record.price_dinner_band_label) : "";
    const lunchBand = isJapan ? priceBandLabel(record.price_lunch_band_tier, record.price_lunch_band_label) : "";
    const kidPolicyKnown = isJapan && record.child_policy_norm && record.child_policy_norm !== "unknown";
    const gMobile = googleRating(record);
    const googleRatingInline = gMobile && gMobile.rating != null
      ? `<span class="card-google-rating">★ ${gMobile.rating}${gMobile.review_count ? ` · ${Number(gMobile.review_count).toLocaleString()}` : ""}</span>`
      : "";
    const regionDot = `<span class="card-region-dot" style="background:${markerColor(record)}" aria-hidden="true"></span>`;
    const cardSummary = diningSummaryPayload(record);

    card.innerHTML = `
      <div class="mobile-card-top">
        <div>
          <div class="focus-kicker">${regionDot}${escapeHtml(diningKicker(record))}</div>
          <h3 class="mobile-card-title">${escapeHtml(record.name)}</h3>
          <div class="mobile-card-meta-row">
            <span class="mobile-card-subtitle">${escapeHtml((record.cuisines || []).join(", ") || "Cuisine unknown")}</span>
            ${googleRatingInline}
          </div>
        </div>
      </div>
      ${cardSummary ? `<p class="mobile-card-desc">${escapeHtml(cardSummary.text)}</p>` : ""}
      ${
        record.source_localized_address
          ? `<div class="mobile-card-address">${escapeHtml(formatAddress(record.source_localized_address, record.country))}</div>`
          : ""
      }
      ${
        record.nearest_stations && record.nearest_stations.length
          ? `<div class="mobile-card-transit">${escapeHtml(record.nearest_stations.join(" | "))}</div>`
          : ""
      }
      <div class="venue-tags">
        ${diningCreditBadge(record)}
        ${dinnerBand ? `<span class="badge amber">${escapeHtml(dinnerBand)}</span>` : ""}
        ${lunchBand ? `<span class="badge blue">${escapeHtml(lunchBand)}</span>` : ""}
        ${kidPolicyKnown ? `<span class="badge">${escapeHtml(kidLabel(record.child_policy_norm))}</span>` : ""}
        ${isJapan && record.english_menu ? '<span class="badge green">English menu</span>' : ""}
      </div>
      ${tagSection("Known for", record.known_for_tags, "gold")}
      ${tagSection("Signature dishes", record.signature_dish_tags, "blue")}
      ${externalSignalsSection(record)}
      ${isJapan ? `<div class="mobile-price-grid">
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
      </div>` : ""}
      <div class="mobile-card-actions">
        <button type="button" class="ghost-btn secondary" data-mobile-focus="${escapeHtml(record.id)}">
          Show on map
        </button>
        ${
          (bestGoogleMapsUrl(record) || diningGoogleMapsUrl(record))
            ? `<a class="inline-link" href="${escapeHtml(bestGoogleMapsUrl(record) || diningGoogleMapsUrl(record))}" target="_blank" rel="noopener">Google Maps</a>`
            : ""
        }
        ${
          record.country === "Japan" && tabelogSearchUrl(record)
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
        if (window.innerWidth <= MOBILE_BREAKPOINT && hasLeaflet && map) {
          const mapTop = map.getContainer().getBoundingClientRect().top + window.scrollY - 16;
          window.scrollTo({ top: Math.max(mapTop, 0), behavior: "smooth" });
        }
      });
    }

    mobileResultsList.appendChild(card);
  });

  if (remaining > 0) {
    const showMore = document.createElement("button");
    showMore.className = "mobile-show-more";
    showMore.textContent = `Show ${Math.min(MOBILE_PAGE_SIZE, remaining).toLocaleString()} more of ${remaining.toLocaleString()} remaining`;
    showMore.addEventListener("click", () => {
      mobileCardPage += 1;
      renderMobileCards(false);
    });
    mobileResultsList.appendChild(showMore);
  }

  // Scroll active card into view after render
  requestAnimationFrame(() => {
    const activeCard = mobileResultsList.querySelector(".mobile-card.active");
    if (activeCard) activeCard.scrollIntoView({ block: "nearest" });
  });
}

function setActiveRecord(id) {
  state.activeId = id;
  const route = currentRoute();
  resultsText.textContent = id ? `Selected venue · ${route.label}` : `Click a dot to select · ${route.label}`;
  renderFocusCard();
  renderTable();
  // Ensure the active card's page is loaded on mobile
  if (id) {
    const idx = state.filtered.findIndex((r) => r.id === id);
    if (idx >= 0) {
      const neededPage = Math.ceil((idx + 1) / MOBILE_PAGE_SIZE);
      if (neededPage > mobileCardPage) mobileCardPage = neededPage;
    }
  }
  renderMobileCards(false);
  updateDiningMarkerStyles();
  const record = activeRecord();
  if (record) renderMobileSheet("dining", record);
}

/** Mobile Sheet Renderer - DISABLED on mobile
 * On mobile, details show inline in .focus-panel below the map (via renderFocusCard)
 * This function is kept for potential future use but doesn't show popups on mobile
 */
function renderMobileSheet(type, record) {
  // On mobile, details are shown inline via renderFocusCard()
  // No popup sheet should appear
  // This function is a no-op on mobile
}


// ─── Mobile Sheet Rendering Helpers ────────────────────────────────────────

/** Centralized zoom configuration - single source of truth */
const ZOOM_CONFIG = {
  FAR_OUT_THRESHOLD: 10,           // If below this, zoom in on marker click
  MARKER_TARGET_LEVEL: 10,         // Default zoom level keeps nearby pins in context
  CONTINENT_VIEW_THRESHOLD: 6,     // Threshold between continent view and country view
  COUNTRY_VIEW_THRESHOLD: 9,       // Threshold between country view and city view
  CONTINENT_ZOOM: 9,               // World/continent view → city context
  COUNTRY_ZOOM: 10,                // Country view → city/neighborhood context
  ZOOM_ANIMATION_DURATION: 0.8,    // Animation duration for zoom (allows visual focus before details appear)
  PAN_ANIMATION_DURATION: 0.4,     // Animation duration for pan-only (already zoomed in)
};

/** Centralized smart zoom for all maps (dining, stays, love dining) */
function smartZoomToMarker(map, latLng) {
  if (!map || !latLng) return;
  const currentZoom = map.getZoom();
  // Only zoom if currently far out; otherwise just pan to marker
  if (currentZoom < ZOOM_CONFIG.FAR_OUT_THRESHOLD) {
    // Adaptive zoom based on current view: more dramatic from very far away
    let targetZoom = ZOOM_CONFIG.MARKER_TARGET_LEVEL;
    if (currentZoom < ZOOM_CONFIG.CONTINENT_VIEW_THRESHOLD) {
      targetZoom = ZOOM_CONFIG.CONTINENT_ZOOM;  // World/continent view → zoom to max
    } else if (currentZoom < ZOOM_CONFIG.COUNTRY_VIEW_THRESHOLD) {
      targetZoom = ZOOM_CONFIG.COUNTRY_ZOOM;    // Country view → zoom to high level
    }
    map.flyTo(latLng, targetZoom, { duration: ZOOM_CONFIG.ZOOM_ANIMATION_DURATION });
  } else {
    map.flyTo(latLng, currentZoom, { duration: ZOOM_CONFIG.PAN_ANIMATION_DURATION });
  }
}

/** Build a single detail line with icon and text */
function buildDetailLine(icon, text) {
  return `
    <div class="detail-line">
      <span class="detail-icon">${icon}</span>
      <span class="detail-text">${escapeHtml(text)}</span>
    </div>
  `;
}

/** Build warnings list HTML */
function buildWarningsList(warnings) {
  return warnings.length > 0 ? warnings.join(" • ") : "";
}

/** Build action buttons for maps and phone */
function buildActionButtons(mapsUrl, phone) {
  return `
    ${mapsUrl ? `<a class="btn primary" href="${escapeHtml(mapsUrl)}" target="_blank" rel="noopener">📍 Maps</a>` : ""}
    ${phone ? `<a class="btn secondary" href="tel:${escapeHtml(phone)}">☎ Call</a>` : ""}
  `;
}

/** Dining-specific sheet rendering - RUTHLESSLY MINIMAL upfront */
function renderDiningSheet(record, quickInfoEl, detailsEl, warningsEl, actionsEl) {
  // Quick info: cuisine + price + kid policy (upfront)
  const cuisines = (record.cuisines || []).join(", ") || "Cuisine";
  const priceLabel = record.price_dinner_band_label || "—";
  const kidPolicyLabel = record.child_policy_norm && record.child_policy_norm !== "unknown"
    ? kidLabel(record.child_policy_norm)
    : null;

  quickInfoEl.innerHTML = `
    <span class="quick-tag">${escapeHtml(cuisines)}</span>
    <span class="divider">•</span>
    <span class="quick-price">${escapeHtml(priceLabel)}</span>
    ${kidPolicyLabel ? `<span class="divider">•</span><span class="quick-tag">${escapeHtml(kidPolicyLabel)}</span>` : ""}
  `;

  // UPFRONT details: address + phone + hours ONLY (what fits without scroll)
  const address = record.source_localized_address;
  const phone = record.phone_number;
  const hours = record.hours;
  const district = record.district || "";

  let detailsHTML = "";

  // Only show address if it exists
  if (address) {
    detailsHTML += `
      <div class="detail-line">
        <span class="detail-icon">📍</span>
        <span class="detail-text">${escapeHtml(address)}${district ? ` (${escapeHtml(district)})` : ""}</span>
      </div>
    `;
  }

  // Only show phone/hours if they exist
  if (phone) {
    detailsHTML += buildDetailLine("☎", phone);
  }

  if (hours) {
    detailsHTML += buildDetailLine("🕐", hours);
  }

  // SCROLLABLE SECTION: station, prices, summary (hidden until scroll)
  const station = record.station;
  const summary = diningSummaryPayload(record);

  if (station || (record.price_lunch_min_jpy || record.price_lunch_max_jpy) || (record.price_dinner_min_jpy || record.price_dinner_max_jpy) || summary) {
    detailsHTML += `<div class="detail-divider"></div>`;

    if (station) {
      detailsHTML += buildDetailLine("🚇", station);
    }

    // Price tiers
    if (record.price_lunch_min_jpy || record.price_lunch_max_jpy) {
      const lunchMin = record.price_lunch_min_jpy || "—";
      const lunchMax = record.price_lunch_max_jpy || "—";
      detailsHTML += `
        <div class="detail-line">
          <span class="detail-icon">🍽️</span>
          <span class="detail-text">Lunch: ¥${escapeHtml(String(lunchMin))}${lunchMin !== lunchMax ? `–¥${escapeHtml(String(lunchMax))}` : ""}</span>
        </div>
      `;
    }

    if (record.price_dinner_min_jpy || record.price_dinner_max_jpy) {
      const dinnerMin = record.price_dinner_min_jpy || "—";
      const dinnerMax = record.price_dinner_max_jpy || "—";
      detailsHTML += `
        <div class="detail-line">
          <span class="detail-icon">🍷</span>
          <span class="detail-text">Dinner: ¥${escapeHtml(String(dinnerMin))}${dinnerMin !== dinnerMax ? `–¥${escapeHtml(String(dinnerMax))}` : ""}</span>
        </div>
      `;
    }

    // Summary at bottom
    if (summary) {
      detailsHTML += `
        <div class="detail-line detail-summary-divider">
          <span class="detail-text detail-summary-text">${escapeHtml(summary.text)}</span>
        </div>
      `;
    }
  }

  detailsEl.innerHTML = detailsHTML;

  // Warnings (scrollable section)
  const warningsList = [];
  if (record.only_kids_allowed) warningsList.push("👨‍👧‍👦 Kids only");
  if (record.no_kids_under_12) warningsList.push("⚠️ No kids under 12");
  if (record.english_menu) warningsList.push("🇬🇧 English menu available");
  if (record.reservation_type) warningsList.push(`📅 ${escapeHtml(record.reservation_type)}`);

  if (warningsList.length > 0) {
    warningsEl.innerHTML = warningsList.join(" • ");
    warningsEl.classList.add("active");
  } else {
    warningsEl.classList.remove("active");
  }

  // Actions: Only 2 buttons - Google Maps + Call
  const mapsUrl = bestGoogleMapsUrl(record) || diningGoogleMapsUrl(record);
  actionsEl.innerHTML = buildActionButtons(mapsUrl, phone);
}

/** Stays-specific sheet rendering - RUTHLESSLY MINIMAL upfront */
function renderStaysSheet(record, quickInfoEl, detailsEl, warningsEl, actionsEl) {
  const roomType = record.eligible_room_type || "Room";
  const availabilityStatus = stayAvailability(record);
  // Don't show price for Amex benefit properties - they're discounted/free
  const priceDisplay = record.price_per_night ? `$${record.price_per_night}/night` : null;
  const priceTag = priceDisplay ? `<span class="divider">•</span><span class="quick-price">${escapeHtml(priceDisplay)}</span>` : "";

  quickInfoEl.innerHTML = `
    <span class="quick-tag">${escapeHtml(roomType)}</span>
    <span class="divider">•</span>
    <span class="quick-status ${availabilityStatus.key === "available" ? "" : "closed"}">${escapeHtml(availabilityStatus.label)}</span>
  `;

  // UPFRONT details: address + city + phone ONLY
  const address = record.address || "Address not available";
  const city = record.city || "";
  const phone = record.reservation_phone;

  let detailsHTML = `
    <div class="detail-line">
      <span class="detail-icon">📍</span>
      <span class="detail-text">${escapeHtml(address)}${city ? `, ${escapeHtml(city)}` : ""}</span>
    </div>
  `;

  if (phone) {
    detailsHTML += buildDetailLine("☎", phone);
  }

  // SCROLLABLE SECTION: check-in/out, pricing, amenities, summary
  const checkIn = record.check_in_date;
  const checkOut = record.check_out_date;
  const nights = record.nights || 1;
  const totalPrice = record.price_per_night ? `$${record.price_per_night * nights}` : null;
  const amenities = record.amenities ? (Array.isArray(record.amenities) ? record.amenities : [record.amenities]) : [];
  const summary = record.summary || record.description || "";

  if (checkIn || checkOut || totalPrice || amenities.length > 0 || summary) {
    detailsHTML += `<div class="detail-divider"></div>`;

    if (checkIn) {
      detailsHTML += `
        <div class="detail-line">
          <span class="detail-icon">📅</span>
          <span class="detail-text">Check-in: ${escapeHtml(checkIn)}</span>
        </div>
      `;
    }

    if (checkOut) {
      detailsHTML += `
        <div class="detail-line">
          <span class="detail-icon">📅</span>
          <span class="detail-text">Check-out: ${escapeHtml(checkOut)}</span>
        </div>
      `;
    }

    if (totalPrice) {
      detailsHTML += `
        <div class="detail-line">
          <span class="detail-icon">💰</span>
          <span class="detail-text">Total: ${escapeHtml(totalPrice)} (${nights} night${nights !== 1 ? 's' : ''})</span>
        </div>
      `;
    }

    if (amenities.length > 0) {
      detailsHTML += `
        <div class="detail-line" style="margin-top: 8px;">
          <span class="detail-icon">✨</span>
          <span class="detail-text">${escapeHtml(amenities.join(", "))}</span>
        </div>
      `;
    }

    if (summary) {
      detailsHTML += `
        <div class="detail-line detail-summary-divider">
          <span class="detail-text detail-summary-text">${escapeHtml(summary)}</span>
        </div>
      `;
    }
  }

  detailsEl.innerHTML = detailsHTML;

  // Warnings
  const warningsList = [];
  if (record.is_closing_soon) warningsList.push("⚠️ Closing soon");
  if (record.is_refurbishing) warningsList.push("🔨 Currently refurbishing");

  const warningsHtml = buildWarningsList(warningsList);
  if (warningsHtml) {
    warningsEl.innerHTML = warningsHtml;
    warningsEl.classList.add("active");
  } else {
    warningsEl.classList.remove("active");
  }

  // Actions: Only 2 buttons - Google Maps + Call
  const mapsUrl = stayGoogleMapsUrl(record);
  actionsEl.innerHTML = buildActionButtons(mapsUrl, phone);
}

/** Love Dining-specific sheet rendering */
/** Love Dining-specific sheet rendering - RUTHLESSLY MINIMAL upfront */
function renderLoveDiningSheet(record, quickInfoEl, detailsEl, warningsEl, actionsEl) {
  const venueType = record.type === "hotel" ? "Hotel" : "Restaurant";
  const cuisine = record.cuisine || "Venue";

  quickInfoEl.innerHTML = `
    <span class="quick-tag">${escapeHtml(venueType)}</span>
    <span class="divider">•</span>
    <span class="quick-tag">${escapeHtml(cuisine)}</span>
  `;

  // UPFRONT: address only (essential for location)
  const address = record.address;
  const city = record.city;
  const phone = record.phone;

  let detailsHTML = "";

  if (address || city) {
    detailsHTML += `
      <div class="detail-line">
        <span class="detail-icon">📍</span>
        <span class="detail-text">${escapeHtml(address)}${city ? `, ${escapeHtml(city)}` : ""}</span>
      </div>
    `;
  }

  // SCROLLABLE: phone only if it exists
  if (phone) {
    detailsHTML += `
      <div class="detail-line">
        <span class="detail-icon">☎</span>
        <span class="detail-text"><a href="tel:${escapeHtml(phone)}">${escapeHtml(phone)}</a></span>
      </div>
    `;
  }

  // Add benefit/discount info and notes
  if (record.notes) {
    detailsHTML += `
      <div class="detail-summary-divider">
        <div class="detail-summary-text">💳 ${escapeHtml(record.notes)}</div>
      </div>
    `;
  }

  detailsEl.innerHTML = detailsHTML;

  // Warnings
  const warningsList = [];
  if (record.is_closing) warningsList.push("⚠️ Permanently closed");
  if (record.is_halal) warningsList.push("✓ Halal certified");

  const warningsHtml = buildWarningsList(warningsList);
  if (warningsHtml) {
    warningsEl.innerHTML = warningsHtml;
    warningsEl.classList.add("active");
  } else {
    warningsEl.classList.remove("active");
  }

  // Actions: Only 2 buttons - Google Maps + Call
  const mapsUrl = record.maps_url || record.google_maps_url;
  actionsEl.innerHTML = buildActionButtons(mapsUrl, phone);
}

/** Apply selected (active) marker styling: white with glow, larger size */
function applySelectedMarkerStyle(iconEl) {
  iconEl.style.background = "#ffffff";
  iconEl.style.boxShadow = "0 0 0 4px rgba(255, 255, 255, 0.3), 0 0 16px rgba(255, 255, 255, 0.6)";
  iconEl.style.width = "24px";
  iconEl.style.height = "24px";
  iconEl.style.opacity = "1";
}

/** Apply unselected (inactive) marker styling: original color, smaller size */
function applyUnselectedMarkerStyle(iconEl, originalColor) {
  iconEl.style.background = originalColor;
  iconEl.style.boxShadow = "none";
  iconEl.style.width = "16px";
  iconEl.style.height = "16px";
  iconEl.style.opacity = "0.92";
}

function updateDiningMarkerStyles() {
  if (!hasLeaflet || !map) return;
  state.markers.forEach((marker, id) => {
    const isActive = id === state.activeId;
    const iconEl = marker.getElement()?.querySelector('.custom-marker-icon div');
    if (iconEl) {
      if (isActive) {
        applySelectedMarkerStyle(iconEl);
      } else {
        const record = state.filtered.find(r => r.id === id);
        const originalColor = record ? markerColor(record) : "#8899aa";
        applyUnselectedMarkerStyle(iconEl, originalColor);
      }
    }
  });
}

function focusActiveRecordOnMap() {
  if (!hasLeaflet || !map) return;
  const record = activeRecord();
  if (!record) return;
  const marker = state.markers.get(record.id);
  if (!marker) return;
  smartZoomToMarker(map, marker.getLatLng());
  marker.closePopup();
}

function stayGoogleMapsUrl(record) {
  const scraped = bestGoogleMapsUrl(record);
  if (scraped) return scraped;
  const query = [record.name, record.address, record.country].filter(Boolean).join(", ");
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`;
}

function stayLocationBadge(record) {
  if (record.coordinate_confidence === "location_conflict") {
    return '<span class="badge amber">Location conflict</span>';
  }
  if (record.lat == null || record.lng == null) return "";
  if (record.coordinate_confidence === "google_place_verified") {
    return '<span class="badge green">Place matched</span>';
  }
  if (record.coordinate_confidence === "poi_address_matched" || record.coordinate_confidence === "address_matched") {
    return '<span class="badge green">POI + address matched</span>';
  }
  if (record.coordinate_confidence === "poi_matched") {
    return '<span class="badge blue">POI matched</span>';
  }
  if (record.coordinate_confidence === "manual_verified") {
    return '<span class="badge green">Manual pin check</span>';
  }
  if (record.coordinate_confidence === "approximate") {
    return '<span class="badge amber">Approximate pin</span>';
  }
  return "";
}

function stayLocationNote(record) {
  if (record.coordinate_confidence === "location_conflict") {
    return "Location may be imprecise — verify the property address before booking.";
  }
  if (record.coordinate_confidence === "approximate") {
    return "Location is approximate — confirm the address before travelling.";
  }
  if (["poi_matched", "poi_address_matched", "address_matched", "google_place_verified"].includes(record.coordinate_confidence)) {
    return "Pin is matched to a place/address signal, not guaranteed to a specific hotel entrance.";
  }
  return "";
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
    return `<a class="inline-link compact" href="${escapeHtml(record.reservation_primary_url)}" target="_blank" rel="noopener">${escapeHtml(record.reservation_raw)}</a>`;
  }
  return fallback;
}

function staySourceMetaLink(record) {
  const sourceUrl = record.source_document_url || record.source_url;
  if (!sourceUrl) return "";
  if (record.reservation_primary_url && record.reservation_primary_url !== sourceUrl) {
    return `<a class="meta-link" href="${escapeHtml(sourceUrl)}" target="_blank" rel="noopener">View official source</a>`;
  }
  return "";
}

function stayOfficialSourceAction(record) {
  const sourceUrl = record.source_document_url || record.source_url;
  if (!sourceUrl) return "";
  return `<a class="inline-link subtle" href="${escapeHtml(sourceUrl)}" target="_blank" rel="noopener">Official Plat Stay PDF</a>`;
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
  const sourceAction = stayOfficialSourceAction(record);
  if (sourceAction) links.push(sourceAction);
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
  staysGoogleRatingFilter.value = "";
  staysSortFilter.value = "";
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
  if (state.stayActiveId && !state.stayFiltered.some((record) => record.id === state.stayActiveId)) {
    state.stayActiveId = null;
  }
}

function activeStayRecord() {
  return state.stayFiltered.find((record) => record.id === state.stayActiveId) || null;
}

function createStayMarker(record) {
  if (!hasLeaflet) return null;
  if (record.lat == null || record.lng == null) return null;
  const status = stayAvailability(record);
  const gRating = googleRating(record);
  const mapsUrl = stayGoogleMapsUrl(record);

  // Use a custom div icon instead of circleMarker which doesn't render reliably
  const color_val = status.key === "blocked" ? "#d6a44c" : "#5fb9a6";
  const marker = L.marker([record.lat, record.lng], {
    icon: L.divIcon({
      html: `<div style="width: 16px; height: 16px; border-radius: 50%; background: ${color_val}; border: 2px solid #091018; opacity: 0.92; cursor: pointer;"></div>`,
      iconSize: [16, 16],
      className: 'custom-marker-icon'
    })
  });

  // Simple popup: just name + location + rating + Google Maps link (matching Dining style)
  const ratingHtml = gRating && gRating.rating != null
    ? `<div style="margin-top:4px; font-size:0.9em">★ ${gRating.rating}${gRating.review_count ? ` (${gRating.review_count})` : ""}</div>`
    : "";
  marker.on("click", () => {
    setActiveStayRecord(record.id);
    if (staysMap && hasLeaflet) {
      smartZoomToMarker(staysMap, marker.getLatLng());
    }
  });
  return marker;
}

function filterStays() {
  const search = staysSearchInput.value.trim().toLowerCase();
  const country = staysCountryFilter.value;
  const city = staysCityFilter.value;
  const googleRatingFilterValue = staysGoogleRatingFilter.value;
  const sort = staysSortFilter.value;

  state.stayBlockedCount = 0;
  state.stayFiltered = state.stays.filter((record) => {
    if (country && record.country !== country) return false;
    if (city && record.city !== city) return false;
    if (search && !fuzzyMatchSearch(record.search_text || "", search)) return false;

    const status = stayAvailability(record);
    if (status.blocked) {
      state.stayBlockedCount += 1;
      return false;
    }

    // Google Maps rating filter
    const gRating = googleRating(record);
    if (googleRatingFilterValue === "has_rating" && !gRating) return false;
    if (googleRatingFilterValue === "3plus" && !(gRating && gRating.rating >= 3.0)) return false;
    if (googleRatingFilterValue === "3_5plus" && !(gRating && gRating.rating >= 3.5)) return false;
    if (googleRatingFilterValue === "4plus" && !(gRating && gRating.rating >= 4.0)) return false;
    if (googleRatingFilterValue === "4_5plus" && !(gRating && gRating.rating >= 4.5)) return false;

    return true;
  });

  // Apply sorting
  if (sort === "rating_high") {
    state.stayFiltered.sort((a, b) => {
      const aRating = googleRating(a)?.rating ?? -1;
      const bRating = googleRating(b)?.rating ?? -1;
      return bRating - aRating;
    });
  } else if (sort === "reviews_high") {
    state.stayFiltered.sort((a, b) => {
      const aCount = googleRating(a)?.review_count ?? 0;
      const bCount = googleRating(b)?.review_count ?? 0;
      return bCount - aCount;
    });
  } else if (sort === "name_a") {
    state.stayFiltered.sort((a, b) => (a.name || "").localeCompare(b.name || ""));
  }

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
    const mappedText = mapped === state.stayFiltered.length ? "" : `, ${mapped} mapped`;
    const filterSummary = selected
      ? `${state.stayFiltered.length} of ${state.stays.length} properties remain after date and location filters, across ${filteredCountries.length} countries${mappedText}.`
      : `${state.stayFiltered.length} of ${state.stays.length} properties shown after filters, across ${filteredCountries.length} countries${mappedText}.`;
    staysSummaryStripText.textContent = filterSummary;
  } else {
    const mappedText = mapped === state.stays.length ? "" : `, ${mapped} mapped`;
    staysSummaryStripText.textContent = `${state.stays.length} properties across ${scopeCountries.length} countries${mappedText}.`;
  }

  staysResultsText.textContent = state.stayActiveId ? "Selected property · Plat Stay" : "Click a pin to select · Plat Stay";
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
    staysFocusCard.innerHTML = state.stayFiltered.length > 0
      ? `<div class="empty-state map-cta">
          <div class="map-cta-icon" aria-hidden="true">◉</div>
          <p class="map-cta-heading">Click any pin on the map</p>
          <p class="map-cta-sub">or select a property from the list below</p>
        </div>`
      : '<div class="empty-state">No matches. Adjust filters or dates to expand results.</div>';
    return;
  }

  const status = stayAvailability(record);
  const locationBadge = stayLocationBadge(record);
  const gBadge = googleRatingBadge(record);
  const tags = [
    ...stayLocationTags(record),
    record.breakfast_included ? "" : '<span class="badge blue">Room only</span>',
    locationBadge,
  ]
    .filter(Boolean)
    .join("");
  const summary = stayFocusSummary(record, status);
  const locationNote = stayLocationNote(record);

  staysFocusCard.innerHTML = `
    <div class="focus-kicker">${escapeHtml(record.city || "City unknown")} / ${escapeHtml(record.country || "Country unknown")}</div>
    <h3 class="focus-title">${escapeHtml(record.name)}</h3>
    ${gBadge ? `<div class="focus-ratings">${gBadge}</div>` : ""}
    <div class="focus-subtitle">${escapeHtml(record.eligible_room_type || "Eligible room type not listed")}</div>
    <div class="focus-address">${escapeHtml(record.address)}</div>
    <div class="focus-tags">${tags}</div>
    <div class="price-grid stay-detail-grid">
      <div class="price-card">
        <span class="price-label">Stay Availability</span>
        <div class="price-tier">${escapeHtml(status.label)}</div>
        <div class="price-raw">${escapeHtml(status.detail)}</div>
      </div>
      <div class="price-card">
        <span class="price-label">Reservation</span>
        <div class="price-tier">${escapeHtml(stayReservationModeLabel(record.reservation_mode))}</div>
        <div class="price-raw">${stayReservationSummaryHtml(record)}</div>
        ${staySourceMetaLink(record)}
      </div>
    </div>
    ${summary ? `<p class="focus-summary">${escapeHtml(summary)}</p>` : ""}
    ${locationNote ? `<div class="focus-note">${escapeHtml(locationNote)}</div>` : ""}
    <div class="focus-actions">
      <a class="inline-link" href="${escapeHtml(stayGoogleMapsUrl(record))}" target="_blank" rel="noopener">Open in Google Maps</a>
      ${stayOfficialSourceAction(record)}
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
      '<tr><td colspan="5" class="empty-table">No matches. Adjust filters or dates to expand results.</td></tr>';
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
      '<div class="empty-state">No matches. Adjust filters or dates to expand results.</div>';
    return;
  }

  staysMobileResultsList.innerHTML = "";
  state.stayFiltered.forEach((record) => {
    const status = stayAvailability(record);
    const g = googleRating(record);
    const googleRatingInline = g && g.rating != null
      ? `<span class="badge blue">★ ${g.rating}${g.review_count ? ` · ${Number(g.review_count).toLocaleString()}` : ""}</span>`
      : "";
    const locationBadge = stayLocationBadge(record);
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
        ${locationBadge}
        ${googleRatingInline}
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
        if (window.innerWidth <= MOBILE_BREAKPOINT && hasLeaflet && staysMap) {
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
  staysResultsText.textContent = id ? "Selected property · Plat Stay" : "Click a pin to select · Plat Stay";
  renderStayFocusCard();
  renderStayTable();
  renderStayMobileCards();
  updateStayMarkerStyles();
  const record = activeStayRecord();
  if (record) renderMobileSheet("stays", record);
}

function updateStayMarkerStyles() {
  if (!hasLeaflet || !staysMap) return;
  state.stayMarkers.forEach((marker, id) => {
    const isActive = id === state.stayActiveId;
    const iconEl = marker.getElement()?.querySelector('.custom-marker-icon div');
    if (iconEl) {
      if (isActive) {
        applySelectedMarkerStyle(iconEl);
      } else {
        applyUnselectedMarkerStyle(iconEl, "#5fb9a6"); // Stays always use teal
      }
    }
  });
}

function focusActiveStayOnMap() {
  if (!hasLeaflet || !staysMap) return;
  const record = activeStayRecord();
  if (!record) return;
  const marker = state.stayMarkers.get(record.id);
  if (!marker) return;
  smartZoomToMarker(staysMap, marker.getLatLng());
  marker.closePopup();
}

// ─── Table for Two ───────────────────────────────────────────────────────────

function tableForTwoPayload() {
  return state.tableForTwo || { venues: [] };
}

function tableForTwoVenues() {
  const payload = tableForTwoPayload();
  return Array.isArray(payload.venues) ? payload.venues : [];
}

function tableForTwoLiveSourceUrl(record) {
  if (!record?.dining_city_id) return "";
  const params = new URLSearchParams({ project: TABLE_FOR_TWO_DININGCITY_PROJECT });
  return `${TABLE_FOR_TWO_DININGCITY_API_BASE}/restaurants/${record.dining_city_id}/available_2018?${params.toString()}`;
}

function tableForTwoFetchHeaders() {
  return {
    "api-key": "cgecegcegcc",
    "accept-version": "application/json; version=2",
    lang: "en",
  };
}

function tableForTwoSlotSeatValues(slot) {
  const rawValues = Array.isArray(slot?.seats?.available) ? slot.seats.available : [];
  return rawValues
    .map((value) => Number(value))
    .filter((value) => Number.isFinite(value));
}

function tableForTwoSlotMaxSeats(slot) {
  const values = tableForTwoSlotSeatValues(slot);
  const listedMax = values.length ? Math.max(...values) : 0;
  const total = Number(slot?.seats?.total_available_seats || 0);
  return Math.max(listedMax, Number.isFinite(total) ? total : 0);
}

function tableForTwoSlotHasMinimumSeats(slot, minimum = TABLE_FOR_TWO_DEFAULT_PARTY_SIZE) {
  return tableForTwoSlotMaxSeats(slot) >= minimum;
}

function tableForTwoAvailabilityFromRows(record, rows, checkedAt) {
  const grouped = new Map();
  const visibleDates = new Set();
  let availableSlotCount = 0;

  (Array.isArray(rows) ? rows : []).forEach((row) => {
    const date = row?.date;
    if (date) visibleDates.add(date);
    (row?.times || []).forEach((slot) => {
      const maxSeats = tableForTwoSlotMaxSeats(slot);
      if (maxSeats < TABLE_FOR_TWO_DEFAULT_PARTY_SIZE) return;
      const meal = slot.meal_type_text || slot.meal_type || "Session";
      if (!grouped.has(meal)) {
        grouped.set(meal, { dates: new Set(), times: new Set(), slots: [], slotCount: 0, maxSeats: 0 });
      }
      const bucket = grouped.get(meal);
      if (date) bucket.dates.add(date);
      if (slot.time) bucket.times.add(slot.time);
      bucket.slots.push({
        date,
        weekday: row?.weekday || "",
        time: slot.time || "",
        meal,
        max_seats: maxSeats,
      });
      bucket.slotCount += 1;
      bucket.maxSeats = Math.max(bucket.maxSeats, maxSeats);
      availableSlotCount += 1;
    });
  });

  const meals = [...grouped.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([meal, bucket]) => ({
    meal,
    status: "available",
    seats: TABLE_FOR_TWO_DEFAULT_PARTY_SIZE,
    max_seats: bucket.maxSeats,
    dates: [...bucket.dates].sort(),
    times: [...bucket.times].sort().slice(0, TABLE_FOR_TWO_MAX_TIMES),
    slots: bucket.slots.sort((a, b) => `${a.date || ""} ${a.time || ""}`.localeCompare(`${b.date || ""} ${b.time || ""}`)),
    slot_count: bucket.slotCount,
  }));
  const visibleDateList = [...visibleDates].sort();
  const sourceUrl = tableForTwoLiveSourceUrl(record);
  const sourceNote =
    `Availability is from DiningCity project ${TABLE_FOR_TWO_DININGCITY_PROJECT} (${TABLE_FOR_TWO_DININGCITY_PROJECT_TITLE}). Book and redeem through the Amex Experiences App.`;

  if (availableSlotCount) {
    const availableDates = uniqueValues(meals.flatMap((meal) => meal.dates || []));
    const mealSummary = meals
      .map((meal) => `${meal.meal} ${(meal.dates || []).length} dates`)
      .join(", ");
    return {
      status: "live_available",
      source: `DiningCity public API project ${TABLE_FOR_TWO_DININGCITY_PROJECT}`,
      source_url: sourceUrl,
      project: TABLE_FOR_TWO_DININGCITY_PROJECT,
      project_title: TABLE_FOR_TWO_DININGCITY_PROJECT_TITLE,
      captured_at: checkedAt,
      checked_at: checkedAt,
      confidence: "diningcity_amex_platinum_project",
      visible_dates: visibleDateList,
      summary:
        `${availableDates.length} dates with Table for Two slots returned by DiningCity ${TABLE_FOR_TWO_DININGCITY_PROJECT}${mealSummary ? ` (${mealSummary})` : ""}.`,
      meals,
      notes: [sourceNote],
    };
  }

  return {
    status: "live_no_seats",
    source: `DiningCity public API project ${TABLE_FOR_TWO_DININGCITY_PROJECT}`,
    source_url: sourceUrl,
    project: TABLE_FOR_TWO_DININGCITY_PROJECT,
    project_title: TABLE_FOR_TWO_DININGCITY_PROJECT_TITLE,
    captured_at: checkedAt,
    checked_at: checkedAt,
    confidence: "diningcity_amex_platinum_project",
    visible_dates: visibleDateList,
    summary:
      `No Table for Two slots were returned by DiningCity ${TABLE_FOR_TWO_DININGCITY_PROJECT} at this check.`,
    meals: [],
    notes: [sourceNote],
  };
}

async function fetchTableForTwoLiveAvailability(record, checkedAt) {
  if (!record?.dining_city_id) return null;
  const response = await fetch(tableForTwoLiveSourceUrl(record), {
    headers: tableForTwoFetchHeaders(),
  });
  if (!response.ok) {
    throw new Error(`DiningCity ${response.status}`);
  }
  const payload = await response.json();
  return tableForTwoAvailabilityFromRows(record, payload?.data || [], checkedAt);
}

async function refreshTableForTwoLiveAvailability({ force = false } = {}) {
  if (!state.tableForTwo || state.tableForTwoLiveRefreshInFlight) return;
  const now = Date.now();
  if (!force && state.tableForTwoLiveRefreshAt && now - state.tableForTwoLiveRefreshAt < 60 * 1000) return;

  const venues = tableForTwoVenues().filter((record) => record.dining_city_id);
  if (!venues.length) return;

  state.tableForTwoLiveRefreshInFlight = true;
  const checkedAt = new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
  try {
    const results = await Promise.allSettled(
      venues.map((record) => fetchTableForTwoLiveAvailability(record, checkedAt))
    );
    const errors = {};
    let checkedCount = 0;
    results.forEach((result, index) => {
      const record = venues[index];
      if (result.status === "fulfilled" && result.value) {
        record.availability = result.value;
        record.slot_source_status = "diningcity_amex_platinum_project";
        record.search_text = tableForTwoSearchText(record);
        checkedCount += 1;
      } else if (result.status === "rejected") {
        errors[record.id] = result.reason?.message || String(result.reason);
      }
    });
    state.tableForTwo.availability_last_checked_at = checkedAt;
    state.tableForTwo.availability_source = {
      type: "diningcity_public_api",
      api_base: TABLE_FOR_TWO_DININGCITY_API_BASE,
      project: TABLE_FOR_TWO_DININGCITY_PROJECT,
      project_title: TABLE_FOR_TWO_DININGCITY_PROJECT_TITLE,
      checked_venues: checkedCount,
      error_count: Object.keys(errors).length,
      errors,
    };
    state.tableForTwoLiveRefreshAt = now;
    if (isTableForTwoRoute(resolveRouteFromHash())) {
      refreshTableForTwoDateOptions();
      filterTableForTwo();
    }
  } finally {
    state.tableForTwoLiveRefreshInFlight = false;
  }
}

function ensureTableForTwoLiveRefresh() {
  if (!state.tableForTwoLiveRefreshTimer) {
    state.tableForTwoLiveRefreshTimer = window.setInterval(() => {
      if (isTableForTwoRoute(resolveRouteFromHash())) {
        refreshTableForTwoLiveAvailability();
      }
    }, TABLE_FOR_TWO_LIVE_REFRESH_INTERVAL_MS);
  }
  refreshTableForTwoLiveAvailability();
}

function activeTableForTwoRecord() {
  return tableForTwoVenues().find((record) => record.id === state.tableForTwoActiveId) || null;
}

function tableForTwoCategoryLabel(category) {
  if (category === "buffet") return "Buffet";
  if (category === "cafe") return "Café";
  if (category === "restaurant") return "Restaurant";
  return category ? category.replaceAll("_", " ") : "Venue";
}

function tableForTwoSearchText(record) {
  return [
    record.name,
    record.app_name,
    record.category,
    record.app_area,
    record.address,
    record.map_pin_source,
    ...(record.app_tags || []),
    record.booking_channel,
    record.dining_city_id,
    record.availability?.status,
    record.availability?.summary,
    record.availability?.source,
    record.availability?.project,
    record.availability?.date,
    record.availability?.date_label,
    ...(record.availability?.visible_dates || []),
    ...(record.availability?.meals || []).flatMap((meal) => [
      meal.meal,
      meal.date,
      ...(meal.dates || []),
      meal.date_label,
      ...(meal.times || []),
      meal.max_seats,
      ...(meal.slots || []).flatMap((slot) => [
        slot.date,
        slot.time,
        slot.meal,
        slot.max_seats,
        slot.total_available_seats,
      ]),
    ]),
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

function refreshTableForTwoCategoryOptions() {
  if (!tableForTwoCategoryFilter) return;
  const current = tableForTwoCategoryFilter.value;
  const categories = uniqueValues(tableForTwoVenues().map((record) => record.category));
  tableForTwoCategoryFilter.innerHTML = '<option value="">All categories</option>';
  categories.forEach((category) => {
    const option = document.createElement("option");
    option.value = category;
    option.textContent = tableForTwoCategoryLabel(category);
    tableForTwoCategoryFilter.appendChild(option);
  });
  if (categories.includes(current)) {
    tableForTwoCategoryFilter.value = current;
  }
}

function tableForTwoSelectedPartySize() {
  const value = Number(tableForTwoPartySizeFilter?.value || TABLE_FOR_TWO_DEFAULT_PARTY_SIZE);
  if (!Number.isFinite(value) || value < 1) return TABLE_FOR_TWO_DEFAULT_PARTY_SIZE;
  return Math.floor(value);
}

function tableForTwoDateOptionLabel(dateValue) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(dateValue || "")) return dateValue;
  const [year, month, day] = dateValue.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  const weekday = date.toLocaleDateString("en-SG", { weekday: "short", timeZone: "UTC" });
  const dayMonth = date.toLocaleDateString("en-SG", { day: "2-digit", month: "short", timeZone: "UTC" });
  return `${dateValue} · ${weekday}, ${dayMonth}`;
}

function tableForTwoTimeToMinutes(timeValue) {
  const match = /^(\d{1,2}):(\d{2})$/.exec(timeValue || "");
  if (!match) return null;
  const hours = Number(match[1]);
  const minutes = Number(match[2]);
  if (!Number.isFinite(hours) || !Number.isFinite(minutes) || hours > 23 || minutes > 59) return null;
  return hours * 60 + minutes;
}

function tableForTwoSlotTimeDistance(slot, preferredTime) {
  const preferredMinutes = tableForTwoTimeToMinutes(preferredTime);
  const slotMinutes = tableForTwoTimeToMinutes(slot?.time);
  if (preferredMinutes === null || slotMinutes === null) return null;
  return slotMinutes - preferredMinutes;
}

function tableForTwoAbsTimeDistance(slot, preferredTime) {
  const distance = tableForTwoSlotTimeDistance(slot, preferredTime);
  return distance === null ? Number.POSITIVE_INFINITY : Math.abs(distance);
}

function tableForTwoTimeDistanceLabel(distance) {
  if (distance === null || !Number.isFinite(distance)) return "";
  if (distance === 0) return "exact";
  const absDistance = Math.abs(distance);
  return `${absDistance} min ${distance > 0 ? "after" : "before"}`;
}

function tableForTwoAllAvailableDates(filters = {}) {
  const dates = new Set();
  tableForTwoVenues().forEach((record) => {
    tableForTwoMatchingSlots(record, { ...filters, date: "", availability: "" }).forEach((slot) => {
      if (slot.date) dates.add(slot.date);
    });
  });
  return [...dates].sort();
}

function refreshTableForTwoDateOptions() {
  if (!tableForTwoDateFilter) return;
  const current = tableForTwoDateFilter.value;
  const dates = tableForTwoAllAvailableDates({
    partySize: tableForTwoSelectedPartySize(),
    session: tableForTwoSessionFilter?.value || "",
    day: tableForTwoDayFilter?.value || "",
  });
  tableForTwoDateFilter.min = dates[0] || "";
  tableForTwoDateFilter.max = dates[dates.length - 1] || "";
  tableForTwoDateFilter.value = current;
}

function renderTableForTwoAlertSignup() {
  if (!tableForTwoAlertSignupPanel || !tableForTwoAlertSignupLink) return;
  const signupUrl = tableForTwoPayload().alert_signup_url || "";
  tableForTwoAlertSignupPanel.hidden = !signupUrl;
  if (signupUrl) {
    tableForTwoAlertSignupLink.href = signupUrl;
  }
}

function tableForTwoHasMapPin(record) {
  return hasCoordinates(record);
}

function tableForTwoPinColor(record) {
  if (!record) return "#c9a55a";
  const key = tableForTwoAvailabilityKey(record, state.tableForTwoCurrentFilters || {});
  if (key === "available") return "#5fb9a6";
  if (key === "no_seats") return "#d6a44c";
  return "#c9a55a";
}

function clearTableForTwoMarkers() {
  if (!hasLeaflet || !tableForTwoMap) {
    state.tableForTwoMarkers.clear();
    return;
  }
  state.tableForTwoMarkers.forEach((marker) => tableForTwoMap.removeLayer(marker));
  state.tableForTwoMarkers.clear();
}

function createTableForTwoMarker(record) {
  if (!hasLeaflet || !tableForTwoMap || !tableForTwoHasMapPin(record)) return null;
  const color = tableForTwoPinColor(record);
  const marker = L.marker(latLngForRecord(record), {
    icon: L.divIcon({
      html: `<div style="width: 16px; height: 16px; border-radius: 50%; background: ${color}; border: 2px solid #091018; opacity: 0.92; cursor: pointer;"></div>`,
      iconSize: [16, 16],
      className: "custom-marker-icon",
    }),
  });
  marker.on("click", () => {
    setActiveTableForTwoRecord(record.id);
    if (tableForTwoMap && hasLeaflet) {
      smartZoomToMarker(tableForTwoMap, marker.getLatLng());
    }
  });
  return marker;
}

function updateTableForTwoMarkerStyles() {
  if (!hasLeaflet || !tableForTwoMap) return;
  state.tableForTwoMarkers.forEach((marker, id) => {
    const iconEl = marker.getElement()?.querySelector(".custom-marker-icon div");
    if (!iconEl) return;
    if (id === state.tableForTwoActiveId) {
      applySelectedMarkerStyle(iconEl);
      return;
    }
    const record = tableForTwoVenues().find((item) => item.id === id);
    applyUnselectedMarkerStyle(iconEl, tableForTwoPinColor(record));
  });
}

function renderTableForTwoMarkers() {
  if (!hasLeaflet || !tableForTwoMap) return;
  clearTableForTwoMarkers();
  tableForTwoVenues().forEach((record) => {
    const marker = createTableForTwoMarker(record);
    if (!marker) return;
    marker.addTo(tableForTwoMap);
    state.tableForTwoMarkers.set(record.id, marker);
  });
  updateTableForTwoMarkerStyles();
}

function fitTableForTwoMap() {
  if (!hasLeaflet || !tableForTwoMap) return;
  const latLngs = tableForTwoVenues()
    .filter((record) => tableForTwoHasMapPin(record))
    .map((record) => latLngForRecord(record));
  if (!latLngs.length) {
    tableForTwoMap.setView([1.2903, 103.8519], 12);
    return;
  }
  if (latLngs.length === 1) {
    tableForTwoMap.setView(latLngs[0], 14);
    return;
  }
  tableForTwoMap.fitBounds(L.latLngBounds(latLngs), TABLE_FOR_TWO_FIT_OPTIONS);
}

function focusTableForTwoOnMap(record) {
  if (!hasLeaflet || !tableForTwoMap || !tableForTwoHasMapPin(record)) return;
  const marker = state.tableForTwoMarkers.get(record.id);
  smartZoomToMarker(tableForTwoMap, marker?.getLatLng?.() || latLngForRecord(record));
}

function scrollTableForTwoFocusIntoView() {
  const panel = tableForTwoFocusCard?.closest(".focus-panel");
  tableForTwoFocusCard?.scrollTo?.({ top: 0, behavior: "smooth" });
  if (!panel) return;
  panel.scrollIntoView({ behavior: "smooth", block: "start" });
}

function setActiveTableForTwoRecord(id, { scroll = false } = {}) {
  state.tableForTwoActiveId = id;
  const record = activeTableForTwoRecord();
  tableForTwoResultsText.textContent = record
    ? "Selected venue · Table for Two"
    : `${state.tableForTwoFiltered.length} venue${state.tableForTwoFiltered.length === 1 ? "" : "s"} shown`;
  renderTableForTwoCard();
  renderTableForTwoList();
  updateTableForTwoMarkerStyles();
  if (record) focusTableForTwoOnMap(record);
  if (scroll && record) {
    window.requestAnimationFrame(scrollTableForTwoFocusIntoView);
  }
}

function filterTableForTwo() {
  const search = (tableForTwoSearchInput.value || "").trim().toLowerCase();
  const inferredFilters = tableForTwoInferredFilters(search);
  const residualSearch = tableForTwoResidualSearch(search);
  const category = tableForTwoCategoryFilter.value;
  const availability = tableForTwoAvailabilityFilter.value || inferredFilters.availability;
  const partySize = tableForTwoSelectedPartySize();
  const session = tableForTwoSessionFilter.value || inferredFilters.session;
  const date = tableForTwoDateFilter.value;
  const time = tableForTwoTimeFilter?.value || "";
  const day = tableForTwoDayFilter.value || inferredFilters.day;
  const venues = tableForTwoVenues();
  const filters = { availability, partySize, session, date, time, day };
  state.tableForTwoCurrentFilters = filters;
  state.tableForTwoFiltered = venues.filter((record) => {
    if (category && record.category !== category) return false;
    if (!tableForTwoRecordMatchesFilters(record, filters)) return false;
    if (residualSearch && !fuzzyMatchSearch(record.search_text || tableForTwoSearchText(record), residualSearch)) return false;
    return true;
  });
  const availabilityRank = { available: 0, no_seats: 1, unknown: 2 };
  state.tableForTwoFiltered.sort((a, b) => {
    const rankA = availabilityRank[tableForTwoAvailabilityKey(a, filters)] ?? 4;
    const rankB = availabilityRank[tableForTwoAvailabilityKey(b, filters)] ?? 4;
    if (rankA !== rankB) return rankA - rankB;
    if (time) {
      const slotA = tableForTwoClosestSlot(tableForTwoMatchingSlots(a, filters), time);
      const slotB = tableForTwoClosestSlot(tableForTwoMatchingSlots(b, filters), time);
      const distanceA = slotA ? tableForTwoAbsTimeDistance(slotA, time) : Number.POSITIVE_INFINITY;
      const distanceB = slotB ? tableForTwoAbsTimeDistance(slotB, time) : Number.POSITIVE_INFINITY;
      if (distanceA !== distanceB) return distanceA - distanceB;
    }
    return (a.app_name || a.name || "").localeCompare(b.app_name || b.name || "");
  });

  if (state.tableForTwoActiveId && !state.tableForTwoFiltered.some((record) => record.id === state.tableForTwoActiveId)) {
    state.tableForTwoActiveId = null;
  }

  const total = venues.length;
  const shown = state.tableForTwoFiltered.length;
  const payload = tableForTwoPayload();
  const freshAvailableCount = venues.filter((record) => tableForTwoAvailabilityKey(record, filters) === "available").length;
  const freshNoSeatCount = venues.filter((record) => tableForTwoAvailabilityKey(record, filters) === "no_seats").length;
  const staleCaptureCount = venues.filter((record) => tableForTwoAvailabilityIsStale(record)).length;
  const pendingCount = venues.filter((record) => tableForTwoAvailabilityKey(record, filters) === "unknown").length;
  const filterLabel = [
    `${partySize} pax`,
    session || "",
    date ? tableForTwoDateOptionLabel(date) : "",
    time ? `within ${TABLE_FOR_TWO_TIME_WINDOW_LABEL} of ${time}` : "",
    day || "",
  ].filter(Boolean).join(" · ");
  const verifiedText = payload.last_verified_at
    ? `Roster checked ${formatTimestamp(payload.last_verified_at)}`
    : "Roster check pending";
  const latestAvailabilityCheckedAt = tableForTwoLatestAvailabilityCheckedAt(venues) || payload.availability_last_checked_at;
  const availabilityCheckedText = latestAvailabilityCheckedAt
    ? `Availability checked ${formatTimestamp(latestAvailabilityCheckedAt)}`
    : "Availability check pending";
  const statusBits = [
    `${shown === total ? total : `${shown} of ${total}`} roster venues`,
    filterLabel,
    freshAvailableCount ? `${freshAvailableCount} with matching slots` : "",
    freshNoSeatCount ? `${freshNoSeatCount} no match` : "",
    staleCaptureCount ? "source older than 30 min" : "",
    pendingCount ? `${pendingCount} not checked` : "",
    availabilityCheckedText,
    verifiedText,
  ].filter(Boolean);
  tableForTwoSummaryStripText.textContent = `${statusBits.join(" · ")}.`;
  tableForTwoListSummary.textContent =
    "Start with all roster venues, then narrow by party size, date, session, status, or category.";
  if (tableForTwoMapSummary) {
    const mappedCount = venues.filter((record) => tableForTwoHasMapPin(record)).length;
    tableForTwoMapSummary.textContent =
      `${mappedCount}/${total} roster venues mapped. Green pins match the current filters; amber pins have no matching slot.`;
  }
  tableForTwoResultsText.textContent = state.tableForTwoActiveId
    ? "Selected venue · Table for Two"
    : `${shown} venue${shown === 1 ? "" : "s"} shown`;

  renderTableForTwoMarkers();
  if (!state.tableForTwoActiveId) fitTableForTwoMap();
  renderTableForTwoList();
  renderTableForTwoCard();
}

function tableForTwoInferredFilters(search) {
  return {
    availability: /\b(available|free|2\s*(seats?|pax|people)?|two\s*(seats?|pax|people)?)\b/.test(search) ? "available" : "",
    session: /\bdinner\b/.test(search) ? "Dinner" : /\blunch\b/.test(search) ? "Lunch" : "",
    day: /\bweekends?\b/.test(search) ? "weekend" : /\bweekdays?\b/.test(search) ? "weekday" : "",
  };
}

function tableForTwoResidualSearch(search) {
  return search
    .replace(/\b(available|free|weekends?|weekdays?|dinner|lunch|2\s*(seats?|pax|people)?|two\s*(seats?|pax|people)?)\b/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function tableForTwoRawAvailabilityKey(record) {
  const status = record.availability?.status || "unknown";
  if (status === "live_available" || status === "captured_available" || status === "available") return "available";
  if (status === "live_no_seats" || status === "captured_no_seats" || status === "no_seats") return "no_seats";
  return "unknown";
}

function tableForTwoAvailabilityMeals(record) {
  return Array.isArray(record.availability?.meals) ? record.availability.meals : [];
}

function tableForTwoDateIsWeekend(dateValue) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(dateValue || "")) return false;
  const [year, month, day] = dateValue.split("-").map(Number);
  const weekday = new Date(Date.UTC(year, month - 1, day)).getUTCDay();
  return weekday === 0 || weekday === 6;
}

function tableForTwoSlotMaxSeatValue(slot, fallback = TABLE_FOR_TWO_DEFAULT_PARTY_SIZE) {
  const values = Array.isArray(slot?.available_seats) ? slot.available_seats.map(Number).filter(Number.isFinite) : [];
  const listed = values.length ? Math.max(...values) : 0;
  const maxSeats = Number(slot?.max_seats || 0);
  const total = Number(slot?.total_available_seats || 0);
  return Math.max(listed, Number.isFinite(maxSeats) ? maxSeats : 0, Number.isFinite(total) ? total : 0, fallback || 0);
}

function tableForTwoMealSlots(meal) {
  if (!meal || meal.status !== "available") return [];
  if (Array.isArray(meal.slots) && meal.slots.length) {
    return meal.slots
      .map((slot) => ({
        date: slot.date || meal.date || "",
        weekday: slot.weekday || "",
        time: slot.time || "",
        meal: slot.meal || meal.meal || "Session",
        available_seats: Array.isArray(slot.available_seats) ? slot.available_seats : [],
        max_seats: Number(slot.max_seats || slot.total_available_seats || meal.max_seats || meal.seats || 0),
        total_available_seats: Number(slot.total_available_seats || slot.max_seats || meal.max_seats || meal.seats || 0),
      }))
      .filter((slot) => slot.time || slot.date);
  }

  const dates = uniqueValues([meal.date, ...(meal.dates || [])].filter(Boolean));
  const times = Array.isArray(meal.times) ? meal.times : [];
  const fallbackMaxSeats = Number(meal.max_seats || meal.seats || TABLE_FOR_TWO_DEFAULT_PARTY_SIZE);
  if (!dates.length) {
    return times.map((time) => ({
      date: "",
      weekday: "",
      time,
      meal: meal.meal || "Session",
      available_seats: [],
      max_seats: fallbackMaxSeats,
      total_available_seats: fallbackMaxSeats,
    }));
  }
  return dates.flatMap((date) => times.map((time) => ({
    date,
    weekday: "",
    time,
    meal: meal.meal || "Session",
    available_seats: [],
    max_seats: fallbackMaxSeats,
    total_available_seats: fallbackMaxSeats,
  })));
}

function tableForTwoAllSlots(record) {
  return tableForTwoAvailabilityMeals(record).flatMap((meal) => tableForTwoMealSlots(meal));
}

function tableForTwoSlotMatchesFilters(slot, filters = {}) {
  const partySize = Number(filters.partySize || TABLE_FOR_TWO_DEFAULT_PARTY_SIZE);
  if (tableForTwoSlotMaxSeatValue(slot) < partySize) return false;
  if (filters.session && normalizeInlineText(slot.meal).toLowerCase() !== filters.session.toLowerCase()) return false;
  if (filters.date && slot.date !== filters.date) return false;
  if (filters.time && tableForTwoAbsTimeDistance(slot, filters.time) > TABLE_FOR_TWO_TIME_WINDOW_MINUTES) return false;
  if (filters.day && slot.date) {
    const isWeekend = tableForTwoDateIsWeekend(slot.date);
    if (filters.day === "weekend" && !isWeekend) return false;
    if (filters.day === "weekday" && isWeekend) return false;
  } else if (filters.day) {
    return false;
  }
  return true;
}

function tableForTwoMatchingSlots(record, filters = {}) {
  if (tableForTwoRawAvailabilityKey(record) !== "available") return [];
  return tableForTwoAllSlots(record)
    .filter((slot) => tableForTwoSlotMatchesFilters(slot, filters))
    .sort((a, b) => {
      if (filters.time) {
        const distanceA = tableForTwoAbsTimeDistance(a, filters.time);
        const distanceB = tableForTwoAbsTimeDistance(b, filters.time);
        if (distanceA !== distanceB) return distanceA - distanceB;
      }
      return `${a.date || ""} ${a.time || ""}`.localeCompare(`${b.date || ""} ${b.time || ""}`);
    });
}

function tableForTwoAvailabilityKey(record, filters = {}) {
  const rawKey = tableForTwoRawAvailabilityKey(record);
  if (rawKey === "unknown") return "unknown";
  if (rawKey === "no_seats") return "no_seats";
  return tableForTwoMatchingSlots(record, filters).length ? "available" : "no_seats";
}

function tableForTwoLatestAvailabilityCheckedAt(records = tableForTwoVenues()) {
  const timestamps = records
    .map((record) => record.availability?.checked_at || record.availability?.captured_at)
    .filter(Boolean)
    .map((value) => ({ value, time: new Date(value).getTime() }))
    .filter((item) => Number.isFinite(item.time))
    .sort((a, b) => b.time - a.time);
  return timestamps[0]?.value || "";
}

function tableForTwoRecordMatchesFilters(record, filters) {
  const key = tableForTwoAvailabilityKey(record, filters);
  if (filters.availability === "available") {
    return key === "available";
  }
  if (filters.availability === "no_seats") return key === "no_seats";
  if (filters.availability === "stale") return tableForTwoAvailabilityIsStale(record);
  if (filters.availability === "unknown") return key === "unknown";
  return true;
}

function tableForTwoAvailabilityLabel(record, filters = state.tableForTwoCurrentFilters || {}) {
  const partySize = Number(filters.partySize || tableForTwoSelectedPartySize());
  const key = tableForTwoAvailabilityKey(record, filters);
  if (key === "available") return `${partySize} pax available`;
  if (key === "no_seats" && (filters.date || filters.session || filters.time || filters.day)) return "No match";
  if (key === "no_seats") return `No ${partySize}-pax slots`;
  return "Not checked";
}

function tableForTwoAvailabilityBadgeClass(record, filters = state.tableForTwoCurrentFilters || {}) {
  const key = tableForTwoAvailabilityKey(record, filters);
  if (key === "available") return "green";
  if (key === "no_seats") return "amber";
  return "";
}

function tableForTwoShortDate(dateValue) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(dateValue || "")) return dateValue || "";
  const [year, month, day] = dateValue.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day)).toLocaleDateString("en-SG", {
    day: "2-digit",
    month: "short",
    timeZone: "UTC",
  });
}

function tableForTwoMonthLabel(monthKey) {
  const [year, month] = monthKey.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, 1)).toLocaleDateString("en-SG", {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
}

function tableForTwoDateRangeSummary(dates, fallback = "No availability calendar yet") {
  const sortedDates = uniqueValues(dates.filter(Boolean)).sort();
  if (!sortedDates.length) return fallback;
  if (sortedDates.length === 1) return tableForTwoDateOptionLabel(sortedDates[0]);
  return `${sortedDates.length} dates · ${tableForTwoShortDate(sortedDates[0])} to ${tableForTwoShortDate(sortedDates[sortedDates.length - 1])}`;
}

function tableForTwoSlotGroupSummaries(slots) {
  const grouped = new Map();
  slots.forEach((slot) => {
    const meal = slot.meal || "Session";
    if (!grouped.has(meal)) grouped.set(meal, []);
    grouped.get(meal).push(slot);
  });
  return [...grouped.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([meal, mealSlots]) => {
    const times = uniqueValues(mealSlots.map((slot) => slot.time).filter(Boolean)).slice(0, TABLE_FOR_TWO_MAX_TIMES);
    const maxSeats = Math.max(...mealSlots.map((slot) => tableForTwoSlotMaxSeatValue(slot)));
    const timeText = times.length ? times.join(", ") : `${mealSlots.length} slots`;
    const moreText = uniqueValues(mealSlots.map((slot) => slot.time).filter(Boolean)).length > times.length ? " +" : "";
    const dateText = tableForTwoDateRangeSummary(mealSlots.map((slot) => slot.date).filter(Boolean), "");
    return `${meal}: ${timeText}${moreText}${dateText ? ` · ${dateText}` : ""} · up to ${maxSeats} pax`;
  });
}

function tableForTwoSessionLabel(meal) {
  const normalized = normalizeInlineText(meal).toLowerCase();
  if (normalized === "lunch") return "Lunch";
  if (normalized === "dinner") return "Dinner";
  return meal || "Session";
}

function tableForTwoSessionShortLabel(meal) {
  const label = tableForTwoSessionLabel(meal);
  if (label === "Lunch") return "L";
  if (label === "Dinner") return "D";
  return label.slice(0, 1).toUpperCase();
}

function tableForTwoSlotsByDate(slots) {
  const byDate = new Map();
  slots.forEach((slot) => {
    if (!slot.date) return;
    if (!byDate.has(slot.date)) byDate.set(slot.date, []);
    byDate.get(slot.date).push(slot);
  });
  return byDate;
}

function tableForTwoDateSessionSummaries(slots) {
  const grouped = new Map();
  slots.forEach((slot) => {
    const meal = tableForTwoSessionLabel(slot.meal);
    if (!grouped.has(meal)) grouped.set(meal, []);
    grouped.get(meal).push(slot);
  });
  return [...grouped.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([meal, mealSlots]) => {
      const times = uniqueValues(mealSlots.map((slot) => slot.time).filter(Boolean));
      const maxSeats = Math.max(...mealSlots.map((slot) => tableForTwoSlotMaxSeatValue(slot)));
      const visibleTimes = times.slice(0, 4).join(", ");
      const more = times.length > 4 ? ` +${times.length - 4}` : "";
      return {
        meal,
        label: `${meal}: ${visibleTimes || `${mealSlots.length} slots`}${more}`,
        shortLabel: `${tableForTwoSessionShortLabel(meal)} ${times.length}`,
        maxSeats,
      };
    });
}

function tableForTwoClosestSlot(slots, preferredTime) {
  if (!preferredTime || !slots.length) return null;
  return [...slots].sort((a, b) => {
    const distanceA = tableForTwoAbsTimeDistance(a, preferredTime);
    const distanceB = tableForTwoAbsTimeDistance(b, preferredTime);
    if (distanceA !== distanceB) return distanceA - distanceB;
    return `${a.date || ""} ${a.time || ""}`.localeCompare(`${b.date || ""} ${b.time || ""}`);
  })[0] || null;
}

function tableForTwoNoMatchLine(record, filters = state.tableForTwoCurrentFilters || {}) {
  const partySize = Number(filters.partySize || tableForTwoSelectedPartySize());
  const dateText = filters.date ? ` on ${tableForTwoShortDate(filters.date)}` : "";
  const timeText = filters.time ? ` within ${TABLE_FOR_TWO_TIME_WINDOW_LABEL} of ${filters.time}` : "";
  if (filters.time) return `No ${partySize}-pax slots${dateText}${timeText}.`;
  if (filters.date || filters.session || filters.day) return `No ${partySize}-pax match${dateText}.`;
  return `No ${partySize}-pax slots in the cached check.`;
}

function tableForTwoCompactAvailabilityLine(record, filters = state.tableForTwoCurrentFilters || {}) {
  const key = tableForTwoAvailabilityKey(record, filters);
  const slots = tableForTwoMatchingSlots(record, filters);
  if (!slots.length) {
    if (key === "unknown") return "Not checked yet";
    return tableForTwoNoMatchLine(record, filters);
  }
  const dates = uniqueValues(slots.map((slot) => slot.date).filter(Boolean)).sort();
  const sessions = uniqueValues(slots.map((slot) => tableForTwoSessionLabel(slot.meal)).filter(Boolean));
  const maxSeats = Math.max(...slots.map((slot) => tableForTwoSlotMaxSeatValue(slot)));
  if (filters.time) {
    const closest = tableForTwoClosestSlot(slots, filters.time);
    const distance = tableForTwoSlotTimeDistance(closest, filters.time);
    const distanceLabel = tableForTwoTimeDistanceLabel(distance);
    return `${tableForTwoDateRangeSummary(dates)} · closest ${closest?.time || ""}${distanceLabel ? ` (${distanceLabel})` : ""} · up to ${maxSeats} pax`;
  }
  return `${tableForTwoDateRangeSummary(dates)} · ${sessions.join(" + ")} · up to ${maxSeats} pax`;
}

function tableForTwoBestAvailabilityLine(record, filters = state.tableForTwoCurrentFilters || {}) {
  const key = tableForTwoAvailabilityKey(record, filters);
  const matchingSlots = tableForTwoMatchingSlots(record, filters);
  if (!matchingSlots.length) {
    if (key === "unknown") return "No Table for Two availability check has been captured yet.";
    return tableForTwoNoMatchLine(record, filters);
  }
  return tableForTwoSlotGroupSummaries(matchingSlots).join(" | ");
}

function tableForTwoFreshnessLabel(record) {
  const capturedAt = record.availability?.captured_at;
  if (!capturedAt) return "No availability check yet";
  return `Checked ${formatTimestamp(capturedAt)}`;
}

function tableForTwoAvailabilityIsStale(record) {
  const capturedAt = record.availability?.captured_at;
  if (!capturedAt) return false;
  const capturedDate = new Date(capturedAt);
  if (Number.isNaN(capturedDate.getTime())) return false;
  const ageMs = Date.now() - capturedDate.getTime();
  return ageMs > TABLE_FOR_TWO_AVAILABILITY_STALE_MINUTES * 60 * 1000;
}

function tableForTwoDateListSummary(dates, prefix = "Dates") {
  if (!dates.length) return "";
  if (dates.length <= 4) return `${prefix}: ${dates.join(", ")}`;
  return `${prefix}: ${dates.length} dates from ${dates[0]} to ${dates[dates.length - 1]}`;
}

function tableForTwoDateSummary(record, filters = state.tableForTwoCurrentFilters || {}) {
  const availability = record.availability || {};
  const matchingDates = uniqueValues(tableForTwoMatchingSlots(record, filters).map((slot) => slot.date).filter(Boolean));
  if (matchingDates.length) return tableForTwoDateRangeSummary(matchingDates);
  if (filters.date) return `No match on ${tableForTwoDateOptionLabel(filters.date)}`;
  if (filters.time || filters.session || filters.day) return "No matching dates";
  const visibleDates = uniqueValues(availability.visible_dates || []);
  if (visibleDates.length) return tableForTwoDateRangeSummary(visibleDates, "No matching dates");
  return availability.date_label || "No availability calendar yet";
}

function tableForTwoCalendarMonthHtml(monthKey, slotsByDate, selectedDate = "") {
  const [year, month] = monthKey.split("-").map(Number);
  const firstDay = new Date(Date.UTC(year, month - 1, 1));
  const daysInMonth = new Date(Date.UTC(year, month, 0)).getUTCDate();
  const leadingBlanks = firstDay.getUTCDay();
  const cells = [];
  for (let index = 0; index < leadingBlanks; index += 1) {
    cells.push('<div class="tft-calendar-cell is-empty" aria-hidden="true"></div>');
  }
  for (let day = 1; day <= daysInMonth; day += 1) {
    const dateValue = `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    const slots = slotsByDate.get(dateValue) || [];
    const summaries = tableForTwoDateSessionSummaries(slots);
    const title = summaries.map((summary) => summary.label).join(" | ");
    const sessionPills = summaries
      .slice(0, 2)
      .map((summary) => `<span class="tft-session-pill">${escapeHtml(summary.shortLabel)}</span>`)
      .join("");
    const moreSessions = summaries.length > 2 ? '<span class="tft-session-pill">+</span>' : "";
    const classes = [
      "tft-calendar-cell",
      slots.length ? "is-available" : "",
      selectedDate === dateValue ? "is-selected" : "",
    ].filter(Boolean).join(" ");
    const tag = slots.length ? "button" : "div";
    const buttonAttrs = slots.length ? ` type="button" data-tft-calendar-date="${escapeHtml(dateValue)}" aria-label="${escapeHtml(`${tableForTwoDateOptionLabel(dateValue)}: ${title}`)}"` : "";
    cells.push(`
      <${tag} class="${classes}"${buttonAttrs}${title ? ` title="${escapeHtml(title)}"` : ""}>
        <span class="tft-day-number">${day}</span>
        ${slots.length ? `<span class="tft-day-slots">${sessionPills}${moreSessions}</span>` : ""}
      </${tag}>
    `);
  }

  return `
    <section class="tft-calendar-month">
      <h5>${escapeHtml(tableForTwoMonthLabel(monthKey))}</h5>
      <div class="tft-calendar-weekdays" aria-hidden="true">
        <span>Su</span><span>Mo</span><span>Tu</span><span>We</span><span>Th</span><span>Fr</span><span>Sa</span>
      </div>
      <div class="tft-calendar-grid">${cells.join("")}</div>
    </section>
  `;
}

function tableForTwoSelectedDateSlotsHtml(slots, filters = state.tableForTwoCurrentFilters || {}) {
  const dates = uniqueValues(slots.map((slot) => slot.date).filter(Boolean)).sort();
  const selectedDate = filters.date || dates[0] || "";
  if (!selectedDate) {
    return '<div class="tft-date-detail muted">Choose a date to see exact Lunch and Dinner times.</div>';
  }
  const slotsForDate = slots
    .filter((slot) => slot.date === selectedDate)
    .sort((a, b) => `${tableForTwoSessionLabel(a.meal)} ${a.time || ""}`.localeCompare(`${tableForTwoSessionLabel(b.meal)} ${b.time || ""}`));
  if (!slotsForDate.length) {
    return `
      <div class="tft-date-detail">
        <h5>${escapeHtml(tableForTwoDateOptionLabel(selectedDate))}</h5>
        <p>${escapeHtml(filters.time ? `No available timing within ${TABLE_FOR_TWO_TIME_WINDOW_LABEL} of ${filters.time}.` : "No matching slots for this date.")}</p>
      </div>
    `;
  }
  const groupedRows = [...new Set(slotsForDate.map((slot) => tableForTwoSessionLabel(slot.meal)))]
    .sort()
    .map((meal) => {
      const mealSlots = slotsForDate.filter((slot) => tableForTwoSessionLabel(slot.meal) === meal);
      const timeChips = mealSlots
        .map((slot) => {
          const distance = filters.time ? tableForTwoSlotTimeDistance(slot, filters.time) : null;
          const distanceLabel = filters.time ? tableForTwoTimeDistanceLabel(distance) : "";
          return `<span class="tft-time-chip">${escapeHtml(slot.time || "Time")} ${distanceLabel ? `<em>${escapeHtml(distanceLabel)}</em>` : ""}</span>`;
        })
        .join("");
      return `
        <div class="tft-date-session">
          <span class="focus-label">${escapeHtml(meal)}</span>
          <span class="tft-time-chip-row">${timeChips}</span>
        </div>
      `;
    })
    .join("");
  return `
    <div class="tft-date-detail">
      <h5>${escapeHtml(tableForTwoDateOptionLabel(selectedDate))}</h5>
      ${groupedRows}
    </div>
  `;
}

function tableForTwoSlotMatchesHtml(record, filters = state.tableForTwoCurrentFilters || {}) {
  const slots = tableForTwoMatchingSlots(record, filters);
  if (!slots.length) {
    return `
      <div class="tft-calendar-empty">
        <div class="focus-kicker">Matching slots</div>
        <h4>No slot match</h4>
        <p>${escapeHtml(tableForTwoBestAvailabilityLine(record, filters))}</p>
      </div>
    `;
  }

  const dates = uniqueValues(slots.map((slot) => slot.date).filter(Boolean));
  const slotsByDate = tableForTwoSlotsByDate(slots);
  const monthKeys = uniqueValues(dates.map((dateValue) => dateValue.slice(0, 7))).sort();
  const monthsHtml = monthKeys
    .map((monthKey) => tableForTwoCalendarMonthHtml(monthKey, slotsByDate, filters.date || ""))
    .join("");
  const headingParts = [
    tableForTwoDateRangeSummary(dates),
    `${filters.partySize || tableForTwoSelectedPartySize()} pax`,
    filters.time ? `near ${filters.time}` : "",
  ].filter(Boolean);

  return `
    <div class="tft-calendar-card">
      <div class="tft-calendar-head">
        <div>
          <div class="focus-kicker">Availability calendar</div>
          <h4>${escapeHtml(headingParts.join(" · "))}</h4>
        </div>
        <span class="badge amber">${escapeHtml(`${slots.length} slot time${slots.length === 1 ? "" : "s"}`)}</span>
      </div>
      <div class="tft-calendar-months">${monthsHtml}</div>
      ${tableForTwoSelectedDateSlotsHtml(slots, filters)}
      <div class="tft-calendar-legend">
        <span><i class="is-available"></i>Available date</span>
        <span><i class="is-selected"></i>Selected date</span>
      </div>
    </div>
  `;
}

function tableForTwoMenuSourceUrl(menu) {
  return menu?.source_url || menu?.url || menu?.public_url || "";
}

function renderTableForTwoList() {
  if (!state.tableForTwoFiltered.length) {
    tableForTwoResultsList.innerHTML = '<div class="empty-state">No matches. Adjust filters to expand results.</div>';
    return;
  }

  tableForTwoResultsList.innerHTML = "";
  state.tableForTwoFiltered.forEach((record) => {
    const card = document.createElement("article");
    card.className = `mobile-card tft-card${record.id === state.tableForTwoActiveId ? " active" : ""}`;
    const displayName = record.app_name || record.name;
    const filters = state.tableForTwoCurrentFilters || {};
    const availabilityBadgeClass = tableForTwoAvailabilityBadgeClass(record, filters);
    const menuSourceUrl = tableForTwoMenuSourceUrl(record.sample_menu);
    const tags = [
      menuSourceUrl ? '<span class="badge amber">Menu linked</span>' : "",
    ]
      .filter(Boolean)
      .join("");

    card.innerHTML = `
      <div class="mobile-card-head">
        <div>
          <div class="mobile-card-kicker">${escapeHtml(tableForTwoCategoryLabel(record.category))}${record.app_area ? ` / ${escapeHtml(record.app_area)}` : ""}</div>
          <div class="mobile-card-title">${escapeHtml(displayName)}</div>
          <div class="mobile-card-sub"><span class="badge ${availabilityBadgeClass}">${escapeHtml(tableForTwoAvailabilityLabel(record, filters))}</span>${record.availability?.captured_at ? ` ${escapeHtml(tableForTwoFreshnessLabel(record))}` : ""}</div>
        </div>
      </div>
      ${tags ? `<div class="venue-tags">${tags}</div>` : ""}
      <p class="mobile-card-desc">${escapeHtml(tableForTwoCompactAvailabilityLine(record, filters))}</p>
      <div class="mobile-card-meta">
        <span>${escapeHtml(tableForTwoDateSummary(record, filters))}</span>
        <span>Amex app</span>
      </div>
    `;
    card.addEventListener("click", () => {
      setActiveTableForTwoRecord(record.id, { scroll: true });
    });
    tableForTwoResultsList.appendChild(card);
  });
}

function renderTableForTwoCard() {
  const payload = tableForTwoPayload();
  const record = activeTableForTwoRecord();
  if (!record) {
    const reviewNote = payload.manual_review_required
      ? '<div class="focus-note focus-note-warn">Official roster changed. Manual review is required before trusting the venue list.</div>'
      : "";
    const latestAvailabilityCheckedAt = tableForTwoLatestAvailabilityCheckedAt();
    tableForTwoFocusCard.innerHTML = `
      <div class="focus-kicker">Official roster</div>
      <h3 class="focus-title">Select a venue</h3>
      <p class="focus-summary">Use party size, session, and date to find matching AMEXPlatSG slots. Booking and redemption still happen in the Amex Experiences App.</p>
      <div class="price-grid tft-status-grid">
        <div class="price-card">
          <span class="price-label">Roster</span>
          <div class="price-tier">${escapeHtml(payload.venues?.length ? `${payload.venues.length} venues` : "No venues loaded")}</div>
          <div class="price-raw">Official Amex source checked ${escapeHtml(payload.last_verified_at ? formatTimestamp(payload.last_verified_at) : "pending")}.</div>
        </div>
        <div class="price-card">
          <span class="price-label">Availability source</span>
          <div class="price-tier">${escapeHtml(payload.availability_source?.project || "AMEXPlatSG")}</div>
          <div class="price-raw">${escapeHtml(latestAvailabilityCheckedAt ? `Checked ${formatTimestamp(latestAvailabilityCheckedAt)}.` : "Availability check pending.")}</div>
        </div>
      </div>
      <div class="focus-note">Slot coverage: DiningCity AMEXPlatSG availability is cached here. Complete booking and voucher redemption in the Amex Experiences App.</div>
      ${reviewNote}
      <div class="focus-actions">
        <a class="inline-link primary-action" href="${escapeHtml(payload.official_url || TABLE_FOR_TWO_OFFICIAL_URL)}" target="_blank" rel="noopener">Official Table for Two page</a>
        <a class="inline-link subtle" href="${escapeHtml(payload.terms_url || TABLE_FOR_TWO_TNC_URL)}" target="_blank" rel="noopener">T&Cs PDF</a>
        <a class="inline-link subtle" href="${escapeHtml(payload.faq_url || TABLE_FOR_TWO_FAQ_URL)}" target="_blank" rel="noopener">FAQ PDF</a>
      </div>
    `;
    return;
  }

  const displayName = record.app_name || record.name;
  const filters = state.tableForTwoCurrentFilters || {};
  const menu = record.sample_menu;
  const menuSourceUrl = tableForTwoMenuSourceUrl(menu);
  const menuHtml = menu && menuSourceUrl
    ? `
      <div class="focus-section tft-menu">
        <div class="focus-kicker">Captured menu</div>
        <h4>${escapeHtml(menu.title || "Table for Two menu")}</h4>
        ${(menu.courses || []).map((course) => `
          <div class="focus-row">
            <span class="focus-label">${escapeHtml(course.course)}</span>
            <span>${escapeHtml((course.choices || []).join(" / "))}</span>
          </div>
        `).join("")}
        ${menu.additional_cover_note ? `<div class="focus-note">${escapeHtml(menu.additional_cover_note)}</div>` : ""}
        <div class="focus-actions">
          <a class="inline-link" href="${escapeHtml(menuSourceUrl)}" target="_blank" rel="noopener">Menu source</a>
        </div>
      </div>
    `
    : "";
  const googleMapsUrl = googleMapsSearchUrl([displayName, "Singapore"]);

  tableForTwoFocusCard.innerHTML = `
    <div class="focus-kicker">${escapeHtml(tableForTwoCategoryLabel(record.category))} / Singapore</div>
    <h3 class="focus-title">${escapeHtml(displayName)}</h3>
    <div class="focus-tags">
      <span class="badge ${tableForTwoAvailabilityBadgeClass(record, filters)}">${escapeHtml(tableForTwoAvailabilityLabel(record, filters))}</span>
      ${record.app_area ? `<span class="badge blue">${escapeHtml(record.app_area)}</span>` : ""}
      ${menuSourceUrl ? '<span class="badge amber">Menu linked</span>' : ""}
    </div>
    ${record.address ? `<div class="focus-address">${escapeHtml(record.address)}</div>` : ""}
    ${tableForTwoSlotMatchesHtml(record, filters)}
    <div class="price-grid tft-status-grid">
      <div class="price-card">
        <span class="price-label">Booking</span>
        <div class="price-tier">${escapeHtml(record.booking_channel || payload.booking_channel || "Amex Experiences App")}</div>
        <div class="price-raw">Book and redeem inside the Amex Experiences App.</div>
      </div>
      <div class="price-card">
        <span class="price-label">Current filters</span>
        <div class="price-tier">${escapeHtml(tableForTwoAvailabilityLabel(record, filters))}</div>
        <div class="price-raw">${escapeHtml(tableForTwoCompactAvailabilityLine(record, filters))}</div>
      </div>
    </div>
    <div class="focus-section">
      <div class="focus-row">
        <span class="focus-label">Range</span>
        <span>${escapeHtml(tableForTwoDateSummary(record, filters))}</span>
      </div>
      <div class="focus-row">
        <span class="focus-label">Refreshed</span>
        <span>${escapeHtml(tableForTwoFreshnessLabel(record))}</span>
      </div>
    </div>
    ${menuHtml}
    <div class="focus-actions">
      <a class="inline-link primary-action" href="${escapeHtml(googleMapsUrl)}" target="_blank" rel="noopener">Search Google Maps</a>
      ${record.dining_city_public_url ? `<a class="inline-link" href="${escapeHtml(record.dining_city_public_url)}" target="_blank" rel="noopener">Public DiningCity page</a>` : ""}
      ${record.venue_source_url && !record.dining_city_public_url ? `<a class="inline-link" href="${escapeHtml(record.venue_source_url)}" target="_blank" rel="noopener">Venue source</a>` : ""}
      ${tableForTwoHasMapPin(record) ? `<button type="button" class="ghost-btn secondary" data-tft-focus-map="true">Center on map</button>` : ""}
      <a class="inline-link subtle" href="${escapeHtml(payload.official_url || TABLE_FOR_TWO_OFFICIAL_URL)}" target="_blank" rel="noopener">Official roster</a>
      <a class="inline-link subtle" href="${escapeHtml(payload.terms_url || TABLE_FOR_TWO_TNC_URL)}" target="_blank" rel="noopener">T&Cs PDF</a>
    </div>
  `;

  const centerButton = tableForTwoFocusCard.querySelector("[data-tft-focus-map='true']");
  if (centerButton) {
    centerButton.addEventListener("click", () => {
      const active = activeTableForTwoRecord();
      if (active) focusTableForTwoOnMap(active);
    });
  }
  tableForTwoFocusCard.querySelectorAll("[data-tft-calendar-date]").forEach((button) => {
    button.addEventListener("click", () => {
      tableForTwoDateFilter.value = button.getAttribute("data-tft-calendar-date") || "";
      refreshTableForTwoDateOptions();
      filterTableForTwo();
      window.requestAnimationFrame(scrollTableForTwoFocusIntoView);
    });
  });
}

function activeLoveDiningRecord() {
  return state.loveDining.find((r) => r.id === state.loveDiningActiveId) || null;
}

function setActiveLoveDiningRecord(id) {
  state.loveDiningActiveId = id;
  const record = activeLoveDiningRecord();
  loveResultsText.textContent = record ? "Selected venue · Love Dining" : `${state.loveDiningFiltered.length} venue${state.loveDiningFiltered.length === 1 ? "" : "s"} shown`;
  if (record) {
    renderLoveDiningCard();
    renderLoveDiningMobileList();
    updateLoveDiningMarkerStyles();
    renderMobileSheet("loveDining", record);
  }
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

// ─── Love Dining ──────────────────────────────────────────────────────────────

function isLoveDiningRoute(route = currentRoute()) {
  return route.programId === "love-dining";
}

function clearLoveDiningMarkers() {
  if (!hasLeaflet || !loveMap) {
    state.loveDiningMarkers.clear();
    return;
  }
  state.loveDiningMarkers.forEach((m) => loveMap.removeLayer(m));
  state.loveDiningMarkers.clear();
}

function createLoveDiningMarker(record) {
  if (!hasLeaflet || !loveMap) return null;
  if (!loveDiningHasMapPin(record)) return null;
  const color = record.type === "hotel" ? "#9b6bd6" : "#e06b8b";

  // Use a custom div icon instead of circleMarker which doesn't render reliably
  const marker = L.marker(latLngForRecord(record), {
    icon: L.divIcon({
      html: `<div style="width: 16px; height: 16px; border-radius: 50%; background: ${color}; border: 2px solid #091018; opacity: 0.9; cursor: pointer;"></div>`,
      iconSize: [16, 16],
      className: 'custom-marker-icon'
    })
  });

  // Simple popup: name + cuisine + rating + Google Maps link
  const gRating = googleRating(record);
  const cuisine = record.cuisine || "";
  const ratingHtml = gRating && gRating.rating != null
    ? `<div style="margin-top:4px; font-size:0.9em">★ ${gRating.rating}${gRating.review_count ? ` (${gRating.review_count})` : ""}</div>`
    : "";
  marker.on("click", () => {
    setActiveLoveDiningRecord(record.id);
    if (loveMap && hasLeaflet) {
      smartZoomToMarker(loveMap, marker.getLatLng());
    }
  });
  return marker;
}

function updateLoveDiningMarkerStyles() {
  if (!hasLeaflet || !loveMap) return;
  state.loveDiningMarkers.forEach((marker, id) => {
    const isActive = id === state.loveDiningActiveId;
    const iconEl = marker.getElement()?.querySelector('.custom-marker-icon div');
    if (iconEl) {
      if (isActive) {
        applySelectedMarkerStyle(iconEl);
      } else {
        const record = state.loveDining.find(r => r.id === id);
        const originalColor = record ? (record.type === "hotel" ? "#9b6bd6" : "#e06b8b") : "#9b6bd6";
        applyUnselectedMarkerStyle(iconEl, originalColor);
      }
    }
  });
}

function renderLoveDiningMarkers() {
  if (!hasLeaflet || !loveMap) return;
  clearLoveDiningMarkers();
  state.loveDiningFiltered.forEach((record) => {
    const marker = createLoveDiningMarker(record);
    if (!marker) return;
    marker.addTo(loveMap);
    state.loveDiningMarkers.set(record.id, marker);
  });
}

function fitLoveDiningMap() {
  if (!hasLeaflet || !loveMap) return;
  const latLngs = state.loveDiningFiltered
    .filter((r) => loveDiningHasMapPin(r))
    .map((r) => latLngForRecord(r));
  if (!latLngs.length) return;
  if (latLngs.length === 1) {
    loveMap.setView(latLngs[0], 15);
    return;
  }
  loveMap.fitBounds(L.latLngBounds(latLngs), LOVE_FIT_OPTIONS);
}

function focusLoveDiningOnMap(record) {
  if (!hasLeaflet || !loveMap || !loveDiningHasMapPin(record)) return;
  loveMap.setView(latLngForRecord(record), 14);
}

function normalizeInlineText(value) {
  return String(value || "")
    .replace(/\u00a0/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function loveDiningPhoneCount(record) {
  const phone = normalizeInlineText(record.phone);
  if (!phone) return 0;
  return phone.split(/\s*\/\s*/).filter(Boolean).length;
}

function loveDiningRepeatsNameInNotes(record) {
  const name = normalizeInlineText(record.name).toLowerCase();
  const notes = normalizeInlineText(record.notes).toLowerCase();
  if (!name || !notes) return false;
  return notes.split(name).length - 1 >= 2;
}

function loveDiningAddressBlockCount(record) {
  const address = normalizeInlineText(record.address);
  if (!address) return 0;
  const postalMatches = address.match(/\b\d{6}\b/g) || [];
  const streetMatches = address.match(
    /\b\d{1,4}[A-Z]?\s+(?:[A-Za-z0-9'.&/-]+\s+){0,7}(?:Road|Rd|Street|St|Avenue|Ave|Drive|Dr|Quay|Boulevard|Blvd|Turn|Way|Crescent|Close|Lane|Ln|Park|Place|Walk|View|Hill|Court|Centre|Center|Terrace|Link)\b/gi,
  ) || [];
  return Math.max(postalMatches.length, streetMatches.length);
}

function loveDiningHasMultipleLocations(record) {
  if (record.multi_location === true) return true;
  return loveDiningPhoneCount(record) > 1
    && (loveDiningRepeatsNameInNotes(record) || loveDiningAddressBlockCount(record) > 1);
}

function loveDiningShouldHideMapPin(record) {
  if (record.location_pin_hidden === true) return true;
  return loveDiningHasMultipleLocations(record);
}

function loveDiningHasMapPin(record) {
  return hasCoordinates(record) && !loveDiningShouldHideMapPin(record);
}

function loveDiningTermsUrl(record) {
  if (record.terms_url) return record.terms_url;
  return record.type === "hotel" ? LOVE_DINING_HOTELS_TNC_URL : LOVE_DINING_RESTAURANTS_TNC_URL;
}

function loveDiningSourceUrl(record) {
  if (record.source_url) return record.source_url;
  return record.type === "hotel" ? LOVE_DINING_HOTELS_URL : LOVE_DINING_RESTAURANTS_URL;
}

function loveDiningUnavailable(record) {
  const combined = normalizeInlineText(`${record.closing_note || ""} ${record.notes || ""}`).toLowerCase();
  return /not eligible|permanently closed|temporarily closed|closed for renovation/.test(combined);
}

function loveDiningOrderProfile(record) {
  const combined = normalizeInlineText(`${record.name || ""} ${record.cuisine || ""} ${record.notes || ""}`).toLowerCase();
  if (/not eligible|permanently closed|temporarily closed|closed for renovation/.test(combined)) {
    return {
      key: "special",
      label: "Check eligibility",
      detail: "Eligibility is restricted or changing. Confirm with the official listing before booking.",
    };
  }
  if (/minimum order of three|three\s*\(3\)\s+dishes|three\s*\(3\)/.test(combined)) {
    return {
      key: "three_items",
      label: "3 qualifying dishes",
      detail: "Requires at least three qualifying dishes from the listed menu categories.",
    };
  }
  if (/buffet|hotpot|grill buffet/.test(combined)) {
    return {
      key: "buffet",
      label: "Buffet / per diner",
      detail: "Buffet venues generally require the eligible buffet or one qualifying food item per diner.",
    };
  }
  if (record.type === "hotel") {
    return {
      key: "one_per_diner",
      label: "1 main/item per diner",
      detail: "Hotel outlets generally require at least one qualifying main course, buffet, or food item per diner.",
    };
  }
  if (/minimum order of two|two\s*\(2\)|two qualifying|2 qualifying|two main|2 main/.test(combined)) {
    return {
      key: "two_mains",
      label: "2 qualifying mains/items",
      detail: "Requires at least two qualifying à la carte main courses or food items, unless the outlet states otherwise.",
    };
  }
  return {
    key: "two_mains",
    label: "2 qualifying mains/items",
    detail: "Restaurant default: at least two qualifying à la carte main courses for parties of two or more, unless otherwise stated.",
  };
}

function loveDiningBenefitProfile(record) {
  const order = loveDiningOrderProfile(record);
  const isUnavailable = loveDiningUnavailable(record);
  const isFixed20 = LOVE_DINING_FIXED_20_IDS.has(record.id);
  const maxSavingsPct = isFixed20 ? 20 : 50;
  const isHotel = record.type === "hotel";
  const savingsKey = isUnavailable ? "unavailable" : isFixed20 ? "twenty" : "fifty";
  const savingsLabel = isUnavailable
    ? "Eligibility warning"
    : isFixed20
      ? "20% special outlet"
      : "Up to 50%";
  const savingsDetail = isUnavailable
    ? "This venue has a closure, renovation, or future ineligibility note in the official listing."
    : isFixed20
      ? "This outlet is listed with a fixed or special 20% benefit in the official hotel terms."
      : isHotel
        ? "Hotel benefit scale: 50% for 2 adults, 35%/33% for 3, 25% for 4, and 20% for larger eligible parties."
        : "Restaurant benefit scale: 50% for 2 diners, 35% for 3, 25% for 4, and 20% for 5–20 diners.";
  const appliesTo = isUnavailable
    ? "Eligibility is restricted for this venue; verify the official listing before planning."
    : isFixed20
      ? "Specified hotel item or total-food-bill offer in the hotel T&Cs."
      : isHotel
        ? "Total food bill at most hotel outlets, or qualifying food items for named exception outlets; lunch and dinner unless otherwise stated."
        : "Dine-in à la carte food items during lunch and dinner, unless the outlet states otherwise.";
  const ladder = isHotel
    ? "1 adult 15%; 2 adults 50%; 3 adults 35% or 33% depending on hotel group; 4 adults 25%; 5–10 adults 20%."
    : "1 diner 15%; 2 diners 50%; 3 diners 35%; 4 diners 25%; 5–20 diners 20%.";
  const appliesKey = isUnavailable || isFixed20
    ? "special"
    : order.key === "buffet"
      ? "buffet"
      : isHotel
        ? "hotel_food"
        : "ala_carte";
  const appliesLabel = appliesKey === "hotel_food"
    ? "Hotel food bill/items"
    : appliesKey === "buffet"
      ? "Buffet"
      : appliesKey === "special"
        ? "Special / eligibility"
        : "À la carte food";
  const cardRequirement =
    "Pay with an eligible Singapore-issued physical Amex Platinum/Centurion/Platinum Reserve/Platinum Credit Card; digital wallet eligibility depends on merchant advice.";

  return {
    maxSavingsPct,
    savingsKey,
    savingsLabel,
    savingsDetail,
    appliesKey,
    appliesLabel,
    appliesTo,
    ladder,
    cardRequirement,
    orderKey: order.key,
    orderLabel: order.label,
    orderDetail: order.detail,
    termsUrl: loveDiningTermsUrl(record),
    sourceUrl: loveDiningSourceUrl(record),
    sourceLabel: record.type === "hotel" ? "Official hotel listing" : "Official restaurant listing",
    termsLabel: record.type === "hotel" ? "Hotel T&Cs PDF" : "Restaurant T&Cs PDF",
    exclusions:
      "Common exclusions: beverages, tax, service charge, set/promotional menus, blackout dates, and outlet-specific item exclusions.",
  };
}

function loveDiningCachedAt() {
  return state.loveDiningSourceMeta?.last_checked_at || state.loveDiningSourceMeta?.fetched_at || "";
}

function loveDiningCachedLabel() {
  const cachedAt = loveDiningCachedAt();
  return cachedAt ? formatTimestamp(cachedAt) : "Cache time not recorded";
}

function loveDiningBookingKeys(record) {
  const combined = normalizeInlineText(`${record.notes || ""} ${record.opening_hours || ""}`).toLowerCase();
  const keys = new Set();
  if (/48\s*hours?|48h/.test(combined)) keys.add("48h");
  if (/24\s*hours?|24h/.test(combined)) keys.add("24h");
  if (/via phone|by phone|call|contact\s*\+?65|quote/.test(combined)) keys.add("phone");
  if (/walk-?ins?/.test(combined)) keys.add("walk_in");
  if (/advanced reservations?|reservations? are required|make your reservations?|reservation/.test(combined)) {
    keys.add("reservation_required");
  }
  if (!keys.size) keys.add("not_stated");
  return keys;
}

function loveDiningBookingLabel(record) {
  const keys = loveDiningBookingKeys(record);
  if (keys.has("48h")) return "48h booking";
  if (keys.has("24h")) return "24h booking";
  if (keys.has("phone")) return "Phone booking";
  if (keys.has("walk_in")) return "Walk-in mentioned";
  if (keys.has("reservation_required")) return "Reservation required";
  return "Booking note not stated";
}

function loveDiningLocationKey(record) {
  if (loveDiningHasMultipleLocations(record)) return "bundled";
  if (loveDiningHasMapPin(record)) return "mapped";
  return "unmapped";
}

function loveDiningLocationFilterLabel(record) {
  const key = loveDiningLocationKey(record);
  if (key === "bundled") return "Bundled locations";
  if (key === "mapped") return "Mapped outlet";
  return "No map pin";
}

function loveDiningLocationNote(record) {
  if (!loveDiningHasMultipleLocations(record)) return "";
  if (loveDiningShouldHideMapPin(record)) {
    return "This Love Dining entry bundles multiple outlets into one record, so the map pin and branch-specific Google rating are hidden until the locations are split cleanly.";
  }
  return "This Love Dining entry includes additional outlet details in the same record. Double-check the branch before booking or travelling.";
}

function loveDiningSourceDescription(record, benefit) {
  const type = record.type === "hotel"
    ? `hotel outlet${record.hotel ? ` at ${record.hotel}` : ""}`
    : "standalone restaurant";
  const cuisine = record.cuisine ? `${record.cuisine} ` : "";
  const location = record.address || record.area || record.hotel || "Singapore";
  const booking = loveDiningBookingLabel(record).toLowerCase();
  return `${record.name} is a Love Dining ${type} listed for ${cuisine}dining at ${location}. The cached terms show ${benefit.savingsLabel.toLowerCase()} for eligible cardmembers, with ${benefit.appliesLabel.toLowerCase()} and ${booking}.`;
}

function refreshLoveDiningCuisineOptions() {
  const cuisines = [...new Set(state.loveDining.map((r) => r.cuisine).filter(Boolean))].sort();
  const current = loveCuisineFilter.value;
  loveCuisineFilter.innerHTML = '<option value="">All cuisines</option>';
  cuisines.forEach((c) => {
    const opt = document.createElement("option");
    opt.value = c;
    opt.textContent = c;
    if (c === current) opt.selected = true;
    loveCuisineFilter.appendChild(opt);
  });
}

function filterLoveDining() {
  const search = (loveSearchInput.value || "").trim().toLowerCase();
  const type = loveTypeFilter.value;
  const cuisine = loveCuisineFilter.value;
  const savings = loveSavingsFilter.value;
  const order = loveOrderFilter.value;
  const applies = loveAppliesFilter.value;
  const booking = loveBookingFilter.value;
  const location = loveLocationFilter.value;

  state.loveDiningFiltered = state.loveDining.filter((record) => {
    const benefit = loveDiningBenefitProfile(record);
    if (type && record.type !== type) return false;
    if (cuisine && record.cuisine !== cuisine) return false;
    if (savings && benefit.savingsKey !== savings) return false;
    if (order && benefit.orderKey !== order) return false;
    if (applies && benefit.appliesKey !== applies) return false;
    if (booking && !loveDiningBookingKeys(record).has(booking)) return false;
    if (location && loveDiningLocationKey(record) !== location) return false;
    if (search && !fuzzyMatchSearch(record.search_text || "", search)) return false;
    return true;
  });

  const n = state.loveDiningFiltered.length;
  const total = state.loveDining.length;
  const cachedLabel = loveDiningCachedLabel();
  const reviewSuffix = state.loveDiningSourceMeta?.manual_review_required ? " · source review required" : "";
  loveSummaryStripText.textContent = n === total
    ? `${total} venues · 50% for 2 eligible diners · cached ${cachedLabel}${reviewSuffix}`
    : `${n} of ${total} venues · cached ${cachedLabel}${reviewSuffix}`;
  loveResultsText.textContent = `${n} venue${n === 1 ? "" : "s"} shown`;
  loveMobileSummary.textContent = `${n} venue${n === 1 ? "" : "s"}`;

  // Active filters summary
  const savingsLabel = savings
    ? loveSavingsFilter.options[loveSavingsFilter.selectedIndex]?.textContent
    : "";
  const orderLabel = order
    ? loveOrderFilter.options[loveOrderFilter.selectedIndex]?.textContent
    : "";
  const appliesLabel = applies
    ? loveAppliesFilter.options[loveAppliesFilter.selectedIndex]?.textContent
    : "";
  const bookingLabel = booking
    ? loveBookingFilter.options[loveBookingFilter.selectedIndex]?.textContent
    : "";
  const locationLabel = location
    ? loveLocationFilter.options[loveLocationFilter.selectedIndex]?.textContent
    : "";
  const active = [
    type && (type === "hotel" ? "Hotels" : "Restaurants"),
    cuisine,
    savingsLabel && savingsLabel.replace("Savings: ", ""),
    orderLabel && orderLabel.replace("Order: ", ""),
    appliesLabel,
    bookingLabel,
    locationLabel,
  ].filter(Boolean);
  loveToolbarToggleMeta.textContent = active.length ? active.join(", ") : "All filters off";

  renderLoveDiningMarkers();
  renderLoveDiningCard();
  renderLoveDiningMobileList();
}

function renderLoveDiningCard() {
  const record = state.loveDining.find((r) => r.id === state.loveDiningActiveId) || null;
  if (!record) {
    loveFocusCard.innerHTML = `<div class="empty-state map-cta">
      <div class="map-cta-icon" aria-hidden="true">◉</div>
      <p class="map-cta-heading">Select a Love Dining venue</p>
      <p class="map-cta-sub">Use a map pin or result card to check savings, booking rules, and T&C links.</p>
    </div>`;
    return;
  }

  const hotelLine = record.hotel ? `<div class="focus-kicker">${escapeHtml(record.hotel)}</div>` : "";
  const benefit = loveDiningBenefitProfile(record);
  const typeBadge = `<span class="badge ${record.type === "hotel" ? "love-hotel" : "love-rest"}">${record.type === "hotel" ? "Hotel outlet" : "Restaurant"}</span>`;
  const cuisineBadge = record.cuisine ? `<span class="badge">${escapeHtml(record.cuisine)}</span>` : "";
  const bookingBadge = `<span class="badge blue">${escapeHtml(loveDiningBookingLabel(record))}</span>`;
  const appliesBadge = `<span class="badge green">${escapeHtml(benefit.appliesLabel)}</span>`;
  const multiLocationBadge = loveDiningHasMultipleLocations(record)
    ? '<span class="badge amber">Multiple locations</span>'
    : "";
  const closingNote = record.closing_note
    ? `<div class="focus-note focus-note-warn">${escapeHtml(record.closing_note)}</div>` : "";
  const halal = record.notes && (record.notes.includes("Halal") || record.notes.includes("Muslim"))
    ? `<div class="focus-note">Halal certified</div>` : "";
  const locationNote = loveDiningLocationNote(record)
    ? `<div class="focus-note">${escapeHtml(loveDiningLocationNote(record))}</div>`
    : "";

  const scrapedRating = googleRating(record);
  const googleMapsUrl = loveDiningShouldHideMapPin(record)
    ? googleMapsSearchUrl([record.name, "Singapore"])
    : (scrapedRating && scrapedRating.maps_url)
      ? scrapedRating.maps_url
      : record.address
        ? googleMapsSearchUrl([record.name, record.address, "Singapore"])
        : null;
  const gBadge = loveDiningShouldHideMapPin(record) ? "" : googleRatingBadge(record);
  const googleMapsLabel = loveDiningShouldHideMapPin(record) ? "Search in Google Maps" : "Open in Google Maps";
  const cachedLabel = loveDiningCachedLabel();
  const sourceReviewWarning = state.loveDiningSourceMeta?.manual_review_required
    ? `<div class="focus-note focus-note-warn">Official Love Dining source changed since the last reviewed baseline: ${escapeHtml((state.loveDiningSourceMeta.major_change_reasons || ["manual review required"]).join("; "))}</div>`
    : "";

  loveFocusCard.innerHTML = `
    <div class="focus-head">
      ${hotelLine}
      <div class="focus-title-row">
        <div class="focus-name">${escapeHtml(record.name)}</div>
        ${gBadge ? `<div class="focus-ratings">${gBadge}</div>` : ""}
      </div>
      <div class="venue-tags" style="margin-top:6px">${typeBadge}${cuisineBadge}${appliesBadge}${bookingBadge}${multiLocationBadge}</div>
    </div>
    ${closingNote}
    ${sourceReviewWarning}
    ${halal}
    ${locationNote}
    <div class="price-grid">
      <div class="price-card">
        <span class="price-label">Savings</span>
        <div class="price-tier">${escapeHtml(benefit.savingsLabel)}</div>
        <div class="price-raw">${escapeHtml(benefit.ladder)}</div>
      </div>
      <div class="price-card">
        <span class="price-label">Eligible spend</span>
        <div class="price-tier">${escapeHtml(record.type === "hotel" ? "Food bill / qualifying items" : "À la carte food")}</div>
        <div class="price-raw">${escapeHtml(benefit.appliesTo)}</div>
      </div>
      <div class="price-card">
        <span class="price-label">Order rule</span>
        <div class="price-tier">${escapeHtml(benefit.orderLabel)}</div>
        <div class="price-raw">${escapeHtml(benefit.orderDetail)}</div>
      </div>
      <div class="price-card">
        <span class="price-label">Source check</span>
        <div class="price-tier">${escapeHtml(cachedLabel)}</div>
        <div class="price-raw">Based on the official venue listing and Love Dining T&Cs.</div>
      </div>
    </div>
    <div class="focus-note">${escapeHtml(benefit.cardRequirement)} ${escapeHtml(benefit.exclusions)}</div>
    ${record.notes ? `<div class="focus-section">
      <div class="focus-kicker">Outlet-specific notes</div>
      <div class="focus-note">${escapeHtml(record.notes)}</div>
    </div>` : ""}
    <div class="focus-section">
      <div class="focus-row"><span class="focus-label">Type</span><span>${escapeHtml(record.type === "hotel" ? `Hotel outlet${record.hotel ? ` at ${record.hotel}` : ""}` : "Standalone restaurant")}</span></div>
      <div class="focus-row"><span class="focus-label">Booking</span><span>${escapeHtml(loveDiningBookingLabel(record))}</span></div>
      <div class="focus-row"><span class="focus-label">Location</span><span>${escapeHtml(loveDiningLocationFilterLabel(record))}</span></div>
      ${record.cuisine ? `<div class="focus-row"><span class="focus-label">Cuisine</span><span>${escapeHtml(record.cuisine)}</span></div>` : ""}
      ${record.address ? `<div class="focus-row"><span class="focus-label">Address</span><span>${escapeHtml(record.address)}</span></div>` : ""}
      ${record.phone ? `<div class="focus-row"><span class="focus-label">Phone</span><span>${escapeHtml(record.phone)}</span></div>` : ""}
      ${record.opening_hours ? `<div class="focus-row"><span class="focus-label">Hours</span><span>${escapeHtml(record.opening_hours)}</span></div>` : ""}
    </div>
    <div class="focus-actions">
      ${googleMapsUrl ? `<a class="inline-link primary-action" href="${escapeHtml(googleMapsUrl)}" target="_blank" rel="noopener">${googleMapsLabel}</a>` : ""}
      <a class="inline-link subtle" href="${escapeHtml(benefit.sourceUrl)}" target="_blank" rel="noopener">${escapeHtml(benefit.sourceLabel)}</a>
      <a class="inline-link subtle" href="${escapeHtml(benefit.termsUrl)}" target="_blank" rel="noopener">${escapeHtml(benefit.termsLabel)}</a>
      ${loveDiningHasMapPin(record) ? `<button type="button" class="ghost-btn secondary" data-love-focus-map="true">Center on map</button>` : ""}
    </div>
  `;

  const centerBtn = loveFocusCard.querySelector("[data-love-focus-map='true']");
  if (centerBtn) {
    centerBtn.addEventListener("click", () => {
      const r = state.loveDining.find((x) => x.id === state.loveDiningActiveId);
      if (r) focusLoveDiningOnMap(r);
    });
  }
}

function renderLoveDiningMobileList() {
  if (!state.loveDiningFiltered.length) {
    loveMobileResultsList.innerHTML = '<div class="empty-state">No matches. Adjust filters to expand results.</div>';
    return;
  }
  loveMobileResultsList.innerHTML = "";
  state.loveDiningFiltered.forEach((record) => {
    const card = document.createElement("article");
    card.className = `mobile-card${record.id === state.loveDiningActiveId ? " active" : ""}`;
    const g = loveDiningShouldHideMapPin(record) ? null : googleRating(record);
    const benefit = loveDiningBenefitProfile(record);
    const ratingStr = g && g.rating != null
      ? `<span class="card-google-rating">★ ${g.rating}${g.review_count ? ` (${Number(g.review_count).toLocaleString()})` : ""}</span>`
      : "";
    card.innerHTML = `
      <div class="mobile-card-head">
        <div>
          ${record.hotel ? `<div class="mobile-card-kicker">${escapeHtml(record.hotel)}</div>` : ""}
          <div class="mobile-card-title">${escapeHtml(record.name)}</div>
          <div class="mobile-card-sub">${escapeHtml(record.cuisine || "")} · ${record.type === "hotel" ? "Hotel outlet" : "Restaurant"} ${ratingStr}</div>
        </div>
      </div>
      <div class="mobile-card-meta">
        ${record.address ? `<span>${escapeHtml(record.address)}</span>` : ""}
        ${record.phone ? `<span>${escapeHtml(record.phone)}</span>` : ""}
      </div>
      <div class="venue-tags">
        <span class="badge ${benefit.savingsKey === "unavailable" ? "amber" : "green"}">${escapeHtml(benefit.savingsLabel)}</span>
        <span class="badge blue">${escapeHtml(benefit.orderLabel)}</span>
        <span class="badge green">${escapeHtml(benefit.appliesLabel)}</span>
        <span class="badge blue">${escapeHtml(loveDiningBookingLabel(record))}</span>
        ${loveDiningHasMultipleLocations(record) ? '<span class="badge amber">Bundled locations</span>' : ""}
        <span class="badge">Cached ${escapeHtml(loveDiningCachedLabel())}</span>
      </div>
    `;
    card.addEventListener("click", () => {
      setActiveLoveDiningRecord(record.id);
      if (loveDiningHasMapPin(record)) focusLoveDiningOnMap(record);
    });
    loveMobileResultsList.appendChild(card);
  });
}

function setLoveToolbarOpen(open) {
  state.loveToolbarOpen = open;
  loveToolbar.classList.toggle("is-open", open);
  loveToolbarToggle.setAttribute("aria-expanded", String(open));
  loveToolbarToggle.querySelector(".toolbar-toggle-icon").textContent = open ? "−" : "+";
}

function eventOccurredWithin(event, container) {
  if (!container) return false;
  if (typeof event.composedPath === "function") {
    return event.composedPath().includes(container);
  }
  return event.target instanceof Node && container.contains(event.target);
}

// ─────────────────────────────────────────────────────────────────────────────

function applyRoute(routeId) {
  state.routeId = ROUTES[routeId] ? routeId : PROGRAMS.dining.defaultRoute;
  const route = currentRoute();
  const program = currentProgram();

  // Dismiss all mobile sheets when switching routes
  Object.values(sheetElements).forEach(sheet => {
    if (sheet) sheet.classList.remove("sheet-visible");
  });

  document.title = `${route.title} | Unofficial Platinum Experience`;
  renderJourneyShell(route);
  renderProgramShell(program, route);
  renderProgramBrief(route);
  renderScopeShell(route);

  if (isStayRoute(route)) {
    dataExplorer.hidden = true;
    staysExplorer.hidden = false;
    loveDiningExplorer.hidden = true;
    tableForTwoExplorer.hidden = true;
    clearTableForTwoMarkers();
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

  if (isLoveDiningRoute(route)) {
    dataExplorer.hidden = true;
    staysExplorer.hidden = true;
    loveDiningExplorer.hidden = false;
    tableForTwoExplorer.hidden = true;
    clearTableForTwoMarkers();
    setLoveToolbarOpen(false);
    state.loveDiningActiveId = null;
    filterLoveDining();
    if (hasLeaflet && loveMap) {
      setTimeout(() => {
        loveMap.invalidateSize();
        fitLoveDiningMap();
      }, 0);
    }
    return;
  }

  if (isTableForTwoRoute(route)) {
    dataExplorer.hidden = true;
    staysExplorer.hidden = true;
    loveDiningExplorer.hidden = true;
    tableForTwoExplorer.hidden = false;
    state.tableForTwoActiveId = null;
    refreshTableForTwoCategoryOptions();
    refreshTableForTwoDateOptions();
    renderTableForTwoAlertSignup();
    filterTableForTwo();
    ensureTableForTwoLiveRefresh();
    if (hasLeaflet && tableForTwoMap) {
      setTimeout(() => {
        tableForTwoMap.invalidateSize();
        fitTableForTwoMap();
      }, 0);
    }
    return;
  }

  if (!isDiningRoute(route)) {
    dataExplorer.hidden = true;
    staysExplorer.hidden = true;
    loveDiningExplorer.hidden = true;
    tableForTwoExplorer.hidden = true;
    state.scopeRecords = [];
    state.filtered = [];
    state.activeId = null;
    state.stayFiltered = [];
    state.stayActiveId = null;
    clearMarkers();
    clearStayMarkers();
    clearLoveDiningMarkers();
    clearTableForTwoMarkers();
    setToolbarOpen(false);
    setTableOpen(false);
    setStayToolbarOpen(false);
    setStayTableOpen(false);
    return;
  }

  dataExplorer.hidden = false;
  staysExplorer.hidden = true;
  loveDiningExplorer.hidden = true;
  tableForTwoExplorer.hidden = true;
  clearTableForTwoMarkers();
  setToolbarOpen(false);
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

function navigateToRouteHash(routeHash) {
  const nextHash = routeHash && routeHash.startsWith("#") ? routeHash : `#/${routeHash || ""}`;
  if (window.location.hash !== nextHash) {
    window.location.hash = nextHash;
  }
  applyRoute(resolveRouteFromHash(nextHash));
}

async function init() {
  initTheme();

  const [
    restaurantResponse,
    japanMetaResponse,
    globalResponse,
    globalMetaResponse,
    staysResponse,
    staysMetaResponse,
    loveDiningResponse,
    loveDiningMetaResponse,
    tableForTwoResponse,
    ratingsResponse,
  ] = await Promise.all([
    fetch(DATA_URL).catch(() => null),
    fetch(JAPAN_META_URL).catch(() => null),
    fetch(GLOBAL_DATA_URL).catch(() => null),
    fetch(GLOBAL_META_URL).catch(() => null),
    fetch(STAYS_DATA_URL).catch(() => null),
    fetch(STAYS_META_URL).catch(() => null),
    fetch(LOVE_DINING_DATA_URL).catch(() => null),
    fetch(LOVE_DINING_META_URL).catch(() => null),
    fetch(TABLE_FOR_TWO_DATA_URL).catch(() => null),
    fetch(GOOGLE_RATINGS_URL).catch(() => null),
  ]);
  if (restaurantResponse && restaurantResponse.ok) {
    state.restaurants = await restaurantResponse.json();
  }
  if (japanMetaResponse && japanMetaResponse.ok) {
    state.japanSourceMeta = await japanMetaResponse.json();
  }
  if (globalResponse && globalResponse.ok) {
    const globalRecs = await globalResponse.json();
    state.restaurants = [...state.restaurants, ...globalRecs];
  }
  if (globalMetaResponse && globalMetaResponse.ok) {
    state.globalSourceMeta = await globalMetaResponse.json();
  }
  state.restaurants.forEach((record) => {
    record.search_text = (record.search_text || "").toLowerCase();
  });
  if (staysResponse && staysResponse.ok) {
    state.stays = await staysResponse.json();
    state.stays.forEach((record) => {
      record.search_text = (record.search_text || "").toLowerCase();
    });
  }
  if (staysMetaResponse && staysMetaResponse.ok) {
    state.staysSourceMeta = await staysMetaResponse.json();
  }
  if (loveDiningResponse && loveDiningResponse.ok) {
    state.loveDining = await loveDiningResponse.json();
    state.loveDining.forEach((record) => {
      const benefit = loveDiningBenefitProfile(record);
      record.search_text = [
        record.search_text,
        record.name,
        record.hotel,
        record.cuisine,
        record.address,
        benefit.savingsLabel,
        benefit.orderLabel,
        benefit.orderDetail,
        benefit.appliesTo,
        benefit.appliesLabel,
        benefit.ladder,
        benefit.exclusions,
        loveDiningBookingLabel(record),
        loveDiningLocationFilterLabel(record),
      ].filter(Boolean).join(" ").toLowerCase();
    });
    refreshLoveDiningCuisineOptions();
  }
  if (loveDiningMetaResponse && loveDiningMetaResponse.ok) {
    state.loveDiningSourceMeta = await loveDiningMetaResponse.json();
  }
  if (tableForTwoResponse && tableForTwoResponse.ok) {
    state.tableForTwo = await tableForTwoResponse.json();
    tableForTwoVenues().forEach((record) => {
      record.search_text = tableForTwoSearchText(record);
    });
    refreshTableForTwoCategoryOptions();
  }
  if (ratingsResponse && ratingsResponse.ok) {
    state.googleRatings = await ratingsResponse.json();
  }

  // Set min date on stays date inputs to today
  const today = new Date().toISOString().split("T")[0];
  staysCheckinInput.min = today;
  staysCheckoutInput.min = today;

  setToolbarOpen(false);
  setTableOpen(false);
  setStayToolbarOpen(false);
  setLoveToolbarOpen(false);

  // Initialize Leaflet maps now that DOM is fully ready
  initMaps();

  handleHashRoute();
  if (!window.location.hash) {
    window.location.hash = "#/dining/world";
  }
  showIntroGate();
}

searchInput.addEventListener("input", filterRestaurants);
countryFilter.addEventListener("change", () => {
  cityFilter.value = "";
  refreshFilterOptions();
  filterRestaurants();
});
cityFilter.addEventListener("change", () => {
  const route = currentRoute();
  const selectedCity = cityFilter.value;
  refreshFilterOptions();
  if (!route.fixedCity && selectedCity && Array.from(cityFilter.options).some((option) => option.value === selectedCity)) {
    cityFilter.value = selectedCity;
  }
  filterRestaurants({ selectedCity });
});

[
  districtFilter,
  cuisineFilter,
  tabelogFilter,
  googleRatingFilter,
  sortFilter,
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

// Love Dining events
loveSearchInput.addEventListener("input", filterLoveDining);
loveTypeFilter.addEventListener("change", filterLoveDining);
loveCuisineFilter.addEventListener("change", filterLoveDining);
loveSavingsFilter.addEventListener("change", filterLoveDining);
loveOrderFilter.addEventListener("change", filterLoveDining);
loveAppliesFilter.addEventListener("change", filterLoveDining);
loveBookingFilter.addEventListener("change", filterLoveDining);
loveLocationFilter.addEventListener("change", filterLoveDining);
loveResetFiltersBtn.addEventListener("click", () => {
  loveSearchInput.value = "";
  loveTypeFilter.value = "";
  loveCuisineFilter.value = "";
  loveSavingsFilter.value = "";
  loveOrderFilter.value = "";
  loveAppliesFilter.value = "";
  loveBookingFilter.value = "";
  loveLocationFilter.value = "";
  filterLoveDining();
});
loveToolbarToggle.addEventListener("click", (event) => {
  event.stopPropagation();
  setLoveToolbarOpen(!state.loveToolbarOpen);
});

// Table for Two events
tableForTwoSearchInput.addEventListener("input", filterTableForTwo);
tableForTwoCategoryFilter.addEventListener("change", filterTableForTwo);
tableForTwoAvailabilityFilter.addEventListener("change", filterTableForTwo);
tableForTwoPartySizeFilter.addEventListener("change", () => {
  refreshTableForTwoDateOptions();
  filterTableForTwo();
});
tableForTwoSessionFilter.addEventListener("change", () => {
  refreshTableForTwoDateOptions();
  filterTableForTwo();
});
tableForTwoDateFilter.addEventListener("change", filterTableForTwo);
tableForTwoTimeFilter.addEventListener("change", filterTableForTwo);
tableForTwoDayFilter.addEventListener("change", () => {
  refreshTableForTwoDateOptions();
  filterTableForTwo();
});
tableForTwoResetFiltersBtn.addEventListener("click", () => {
  tableForTwoSearchInput.value = "";
  tableForTwoCategoryFilter.value = "";
  tableForTwoAvailabilityFilter.value = "";
  tableForTwoPartySizeFilter.value = String(TABLE_FOR_TWO_DEFAULT_PARTY_SIZE);
  tableForTwoSessionFilter.value = "";
  tableForTwoDateFilter.value = "";
  tableForTwoTimeFilter.value = "";
  tableForTwoDayFilter.value = "";
  refreshTableForTwoDateOptions();
  filterTableForTwo();
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

document.getElementById("intro-start-love")?.addEventListener("click", (e) => {
  jumpIntoExplorer(e.currentTarget.dataset.introRoute);
});

document.getElementById("intro-start-tft")?.addEventListener("click", (event) => {
  jumpIntoExplorer(event.currentTarget.dataset.introRoute);
});

replayGuideButton?.addEventListener("click", () => {
  showIntroGate(true);
});

programLinks.forEach((link) => {
  link.addEventListener("click", (event) => {
    event.preventDefault();
    navigateToRouteHash(link.getAttribute("href") || "#/dining/world");
  });
});

toolbarToggle.addEventListener("click", () => {
  setToolbarOpen(!state.mobileToolbarOpen);
});

tableToggle.addEventListener("click", () => {
  setTableOpen(!state.tableOpen);
  renderTableToggle();
});

document.getElementById("table-search-input")?.addEventListener("input", (e) => {
  state.tableSearchQuery = e.target.value.trim();
  renderTable();
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
staysGoogleRatingFilter.addEventListener("change", filterStays);
staysSortFilter.addEventListener("change", filterStays);
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

  if (state.loveToolbarOpen && !eventOccurredWithin(event, loveMapFilterShell)) {
    setLoveToolbarOpen(false);
  }
});

// ─── Mobile Bottom Sheet Handling ───────────────────────────────────────────
// The mobile-venue-sheet is already rendered by renderMobileSheet() in setActiveRecord()
// No additional JS needed - CSS handles the bottom sheet animation via sheet-visible class

// Re-initialize on hash route change (when switching between dining/stays/love)
const originalHashChange = window.onhashchange;
window.addEventListener("hashchange", () => {
  // Collapse all sheets when changing routes
  document.querySelectorAll('.focus-panel.expanded').forEach(panel => {
    panel.classList.remove('expanded');
  });
  if (originalHashChange) originalHashChange();
});

window.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  if (state.mobileToolbarOpen) setToolbarOpen(false);
  if (state.stayToolbarOpen) setStayToolbarOpen(false);
  if (state.loveToolbarOpen) setLoveToolbarOpen(false);
});

window.addEventListener("hashchange", handleHashRoute);
window.addEventListener("resize", () => {
  if (!hasLeaflet) return;
  if (isStayRoute()) {
    staysMap.invalidateSize();
    fitStayMapToVisibleMarkers();
    return;
  }
  if (isTableForTwoRoute()) {
    tableForTwoMap?.invalidateSize();
    fitTableForTwoMap();
    return;
  }
  if (isDiningRoute()) {
    map.invalidateSize();
    fitDiningMapToVisibleMarkers();
  }
  // Hide all sheets if resized to desktop
  if (window.innerWidth > MOBILE_BREAKPOINT) {
    mobileDiningSheet?.classList.remove("sheet-visible");
    mobileStaysSheet?.classList.remove("sheet-visible");
    mobileLoveDiningSheet?.classList.remove("sheet-visible");
  }
});

// Mobile sheet dismiss handlers removed - sheets are now disabled
// Details show inline via .focus-panel on mobile instead of popup overlay

// Mobile sheet dismissal removed - sheets no longer used

// Hide header clutter on mobile to maximize map visibility
let mobileClutterObserver = null;

function hideMobileClutter() {
  const selectors = [
    '.context-title',
    '.context-strip',
    '.summary-strip',
    '.map-instructions',
    '.refine-panel',
    '#summary-strip-text',
    // '.focus-panel',  -- REMOVED: we want to show details inline on mobile, not hide them
    '.map-panel .panel-head',
    '.toolbar-toggle-meta'
  ];

  if (window.innerWidth <= MOBILE_BREAKPOINT) {
    // Hide clutter elements on mobile
    selectors.forEach(selector => {
      document.querySelectorAll(selector).forEach(el => {
        el.hidden = true;
      });
    });

    // Start observer only on mobile to catch dynamically inserted elements
    startMobileClutterObserver();
  } else {
    // Unhide all elements on desktop
    selectors.forEach(selector => {
      document.querySelectorAll(selector).forEach(el => {
        el.hidden = false;
      });
    });

    // Disconnect observer on desktop to save CPU
    stopMobileClutterObserver();
  }
}

function startMobileClutterObserver() {
  if (mobileClutterObserver) return;
  mobileClutterObserver = new MutationObserver(() => {
    hideMobileClutter();
  });
  mobileClutterObserver.observe(document.body, {
    childList: true,
    subtree: true
  });
}

function stopMobileClutterObserver() {
  if (mobileClutterObserver) {
    mobileClutterObserver.disconnect();
    mobileClutterObserver = null;
  }
}

// Debounced resize handler to avoid excessive calls
let resizeTimeout;
function onResizeDebounced() {
  clearTimeout(resizeTimeout);
  resizeTimeout = setTimeout(hideMobileClutter, 150);
}

// Run on init and when content changes
hideMobileClutter();
window.addEventListener('resize', onResizeDebounced);
document.addEventListener('readystatechange', hideMobileClutter);

// Cleanup on page unload to prevent memory leaks
window.addEventListener('beforeunload', stopMobileClutterObserver);

init().catch(() => {
  focusCard.innerHTML =
    '<div class="empty-state">Data failed to load. Please refresh the page.</div>';
  staysFocusCard.innerHTML =
    '<div class="empty-state">Data failed to load. Please refresh the page.</div>';
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
