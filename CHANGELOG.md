# Changelog

## 2026-04-25

### Added

- Table for Two map with all 18 official roster venues pinned and source-labelled
  coordinate confidence for DiningCity, OneMap, or existing source-backed pins.
- Table for Two explorer at `/#/table-for-two` with official roster, T&C/FAQ
  links, menu notes, cache-only availability labels, and availability/session
  filters.
- Love Dining cache metadata, source hashes, T&C PDF hashes, reviewed-hash
  baseline, and richer discount/filter UI.
- Source-change alert framework for Japan Dining, Global Dining, Plat Stay, Love
  Dining, and Table for Two refresh workflows.
- Dining cache labels in the route summary and selected-venue panel so users can
  see when official source data was last cached.
- Singapore Local Dining Credit wording to clarify that Singapore restaurants are
  not abroad Global Dining Credit destinations.

### Changed

- Dining selected-card copy no longer emits generic fallback summaries when no
  source-backed description exists; it shows structured facts, tags, cache, and
  coordinate notes instead.
- Love Dining selected cards now remove repeated promo prose and keep the focus
  on savings, eligible spend, order rule, source check, outlet notes, and T&Cs.
- Plat Stay availability/reservation cards now use a cleaner stacked card layout
  with improved spacing and link wrapping.
- Love Dining source links now point to the correct restaurant/hotel pages and
  T&C PDFs instead of the Global Dining Credit page.
- Love Dining cards now show promo structure, what the discount applies to,
  minimum-order rules, booking notes, exclusions, and last cache time.
- Table for Two now frames the page as cache-backed availability, removes raw
  source/hash artifacts from the UI, and shows a selected-venue calendar panel.
- Table for Two filters now start from user availability: free session, free
  date, day type, 2-seat cache, then category.
- Table for Two exact-date filters now only match stored exact slot dates; visible
  app-calendar dates are shown as context, not treated as confirmed slot dates.
- Refresh workflows now rebase before pushing, reducing GitHub Actions push
  failures when multiple refresh jobs update `main`.
- Japan dining sync now writes `data/japan-dining-source.json` with cache time,
  counts, and a stable official-record hash.
- README now uses the canonical `https://amex-explorer.kooexperience.com/` URL.

### Verified

- Public DiningCity availability for 15 Stamford returned generic same-day seat
  counts and does not match the Amex Experiences App Table for Two screenshot,
  so it remains labelled as public DiningCity info only.
- Coordinate audit now reports missing-coordinate counts: Global Dining has 457
  unmapped records, Love Dining has 5 unmapped/bundled records, and Table for Two
  has 18/18 mapped records.
- Taiwan Global Dining Credit data matched the official Amex API expanded count:
  90 official expanded records and 90 local records.
- `Chope Chope Eatery National Taichung Theater` is not present in the active
  official Taiwan dining dataset; it only remains in inactive/audit data.
- Love Dining browser smoke test confirmed filters and promo/cache details render
  correctly.

### Boundaries

- Table for Two live slot scraping is not implemented because booking inventory
  is inside the Amex Experiences App. The site only displays manual/cache-backed
  availability and tells users to reconfirm in the app.
