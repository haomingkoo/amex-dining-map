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

const state = {
  restaurants: [],
  filtered: [],
  markers: new Map(),
  activeId: null,
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

const cityFilter = document.getElementById("city-filter");
const districtFilter = document.getElementById("district-filter");
const cuisineFilter = document.getElementById("cuisine-filter");
const lunchFilter = document.getElementById("lunch-filter");
const dinnerFilter = document.getElementById("dinner-filter");
const kidsFilter = document.getElementById("kids-filter");
const menuFilter = document.getElementById("menu-filter");
const reservationFilter = document.getElementById("reservation-filter");
const searchInput = document.getElementById("search-input");
const venueList = document.getElementById("venue-list");
const resultsText = document.getElementById("results-text");
const venueCount = document.getElementById("venue-count");
const mappedCount = document.getElementById("mapped-count");
const cityCount = document.getElementById("city-count");

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function yens(min, max) {
  if (!min && !max) return null;
  if (min && max && min !== max) return `JPY ${min.toLocaleString()} - ${max.toLocaleString()}`;
  return `JPY ${(max || min).toLocaleString()}`;
}

function bandBadgeLabel(meal, tier, label) {
  return tier && label ? `${meal} ${tier} | ${label}` : "";
}

function kidLabel(value) {
  const labels = {
    kid_friendly: "Kid friendly",
    older_children_only: "Older children only",
    teens_only: "Teens only",
    policy_available: "Policy available",
    unknown: "Unknown",
  };
  return labels[value] || "Unknown";
}

function markerColor(city) {
  if (city === "Tokyo") return "#d2b16f";
  if (city === "Kyoto") return "#a78bfa";
  if (city === "Osaka") return "#4ade80";
  return "#60a5fa";
}

function createMarker(record) {
  if (record.lat == null || record.lng == null) return null;

  const dinner = yens(record.price_dinner_min_jpy, record.price_dinner_max_jpy);
  const lunch = yens(record.price_lunch_min_jpy, record.price_lunch_max_jpy);

  const marker = L.circleMarker([record.lat, record.lng], {
    radius: 8,
    fillColor: markerColor(record.city),
    fillOpacity: 0.92,
    color: "#0d0d10",
    weight: 2,
  });

  marker.bindPopup(`
    <div>
      <div class="popup-name">${escapeHtml(record.name)}</div>
      <div>${escapeHtml(record.city)} / ${escapeHtml(record.district || record.area_title)}</div>
      <div>${escapeHtml((record.cuisines || []).join(", ") || "Cuisine unknown")}</div>
      ${
        record.price_dinner_band_label
          ? `<div>${escapeHtml(`Dinner range: ${(record.price_dinner_band_tier || "").trim()} ${record.price_dinner_band_label}`.trim())}</div>`
          : ""
      }
      ${dinner ? `<div>${escapeHtml(`Dinner spend: ${dinner}`)}</div>` : ""}
      ${
        record.price_lunch_band_label
          ? `<div>${escapeHtml(`Lunch range: ${(record.price_lunch_band_tier || "").trim()} ${record.price_lunch_band_label}`.trim())}</div>`
          : ""
      }
      ${lunch ? `<div>${escapeHtml(`Lunch spend: ${lunch}`)}</div>` : ""}
      ${record.summary_official ? `<p>${escapeHtml(record.summary_official)}</p>` : ""}
      <div>${escapeHtml(record.map_pin_note || "")}</div>
      ${
        record.source_url
          ? `<p><a href="${escapeHtml(record.source_url)}" target="_blank" rel="noopener">Pocket Concierge</a></p>`
          : ""
      }
    </div>
  `);
  marker.on("click", () => setActiveRecord(record.id));
  return marker;
}

function uniqueValues(values) {
  return [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b));
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

function refreshFilterOptions(records) {
  fillSelect(cityFilter, uniqueValues(records.map((r) => r.city)), "All cities");
  fillSelect(
    districtFilter,
    uniqueValues(records.map((r) => r.district || r.area_title)),
    "All districts"
  );
  fillSelect(
    cuisineFilter,
    uniqueValues(records.flatMap((r) => r.cuisines || [])),
    "All cuisines"
  );
  fillBandSelect(
    lunchFilter,
    LUNCH_BANDS,
    new Set(records.map((r) => r.price_lunch_band_key).filter(Boolean)),
    "All lunch bands"
  );
  fillBandSelect(
    dinnerFilter,
    DINNER_BANDS,
    new Set(records.map((r) => r.price_dinner_band_key).filter(Boolean)),
    "All dinner bands"
  );
  fillSelect(
    reservationFilter,
    uniqueValues(records.map((r) => r.reservation_type)),
    "All"
  );
}

function filterRestaurants() {
  const search = searchInput.value.trim().toLowerCase();
  const city = cityFilter.value;
  const district = districtFilter.value;
  const cuisine = cuisineFilter.value;
  const lunchBand = lunchFilter.value;
  const dinnerBand = dinnerFilter.value;
  const kids = kidsFilter.value;
  const menu = menuFilter.value;
  const reservation = reservationFilter.value;

  state.filtered = state.restaurants.filter((record) => {
    if (city && record.city !== city) return false;
    if (district && (record.district || record.area_title) !== district) return false;
    if (cuisine && !(record.cuisines || []).includes(cuisine)) return false;
    if (lunchBand && record.price_lunch_band_key !== lunchBand) return false;
    if (dinnerBand && record.price_dinner_band_key !== dinnerBand) return false;
    if (kids && record.child_policy_norm !== kids) return false;
    if (menu === "yes" && !record.english_menu) return false;
    if (menu === "no" && record.english_menu) return false;
    if (reservation && record.reservation_type !== reservation) return false;
    if (search && !record.search_text.includes(search)) return false;
    return true;
  });

  renderList();
  renderMarkers();
  renderStats();
}

function renderStats() {
  venueCount.textContent = state.restaurants.length;
  mappedCount.textContent = state.restaurants.filter((r) => r.lat != null && r.lng != null).length;
  cityCount.textContent = uniqueValues(state.restaurants.map((r) => r.city)).length;
  resultsText.textContent = `${state.filtered.length} result${state.filtered.length === 1 ? "" : "s"}`;
}

function setActiveRecord(id) {
  state.activeId = id;
  renderList();
}

function renderList() {
  if (!state.filtered.length) {
    venueList.innerHTML = '<div class="empty-state">No venues match the current filters.</div>';
    return;
  }

  venueList.innerHTML = "";
  state.filtered.forEach((record) => {
    const card = document.createElement("article");
    card.className = `venue-card${record.id === state.activeId ? " active" : ""}`;
    card.addEventListener("click", () => {
      setActiveRecord(record.id);
      const marker = state.markers.get(record.id);
      if (marker) {
        map.flyTo(marker.getLatLng(), Math.max(map.getZoom(), 13), { duration: 0.6 });
        marker.openPopup();
      }
    });

    const dinner = yens(record.price_dinner_min_jpy, record.price_dinner_max_jpy);
    const lunch = yens(record.price_lunch_min_jpy, record.price_lunch_max_jpy);
    const tags = [
      `<span class="badge gold">${escapeHtml(record.city)}</span>`,
      record.price_dinner_band_label && record.price_dinner_band_tier
        ? `<span class="badge amber">${escapeHtml(
            bandBadgeLabel("Dinner", record.price_dinner_band_tier, record.price_dinner_band_label)
          )}</span>`
        : "",
      record.price_lunch_band_label && record.price_lunch_band_tier
        ? `<span class="badge blue">${escapeHtml(
            bandBadgeLabel("Lunch", record.price_lunch_band_tier, record.price_lunch_band_label)
          )}</span>`
        : "",
      `<span class="badge">${escapeHtml(kidLabel(record.child_policy_norm))}</span>`,
      record.english_menu ? '<span class="badge green">English menu</span>' : "",
      record.reservation_type ? `<span class="badge purple">${escapeHtml(record.reservation_type)}</span>` : "",
    ]
      .filter(Boolean)
      .join("");

    card.innerHTML = `
      <div class="venue-top">
        <h3 class="venue-name">${escapeHtml(record.name)}</h3>
        ${record.lat != null && record.lng != null ? '<span class="badge green">Mapped</span>' : '<span class="badge">Unmapped</span>'}
      </div>
      <div class="venue-meta">
        <span>${escapeHtml(record.city)} / ${escapeHtml(record.district || record.area_title)}</span>
        <span>${escapeHtml((record.cuisines || []).join(", ") || "Cuisine unknown")}</span>
      </div>
      <p class="venue-summary">${escapeHtml(record.summary_official || "No official summary available.")}</p>
      <div class="venue-tags">${tags}</div>
      <div class="venue-meta">
        ${dinner ? `<span>Dinner: ${escapeHtml(dinner)}</span>` : ""}
        ${lunch ? `<span>Lunch: ${escapeHtml(lunch)}</span>` : ""}
      </div>
      <div class="venue-meta">
        <span>${escapeHtml(record.map_pin_note || "")}</span>
      </div>
      <div class="venue-links">
        ${record.source_url ? `<a href="${escapeHtml(record.source_url)}" target="_blank" rel="noopener">Pocket Concierge</a>` : ""}
      </div>
    `;
    venueList.appendChild(card);
  });
}

function renderMarkers() {
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
    map.fitBounds(bounds, { padding: [40, 40], maxZoom: 12 });
  } else {
    map.setView([35.676, 137.5], 5);
  }
}

async function init() {
  const response = await fetch(DATA_URL);
  state.restaurants = await response.json();
  state.restaurants.forEach((record) => {
    record.search_text = (record.search_text || "").toLowerCase();
  });
  refreshFilterOptions(state.restaurants);
  filterRestaurants();
}

[
  searchInput,
  cityFilter,
  districtFilter,
  cuisineFilter,
  lunchFilter,
  dinnerFilter,
  kidsFilter,
  menuFilter,
  reservationFilter,
].forEach((element) => element.addEventListener("input", filterRestaurants));

init().catch((error) => {
  console.error(error);
  venueList.innerHTML =
    '<div class="empty-state">Data failed to load. Run the sync script and serve this folder over HTTP.</div>';
  resultsText.textContent = "Load failed";
});
