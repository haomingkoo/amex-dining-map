# Data Rebuild Plan — From Scratch

**Current Status**: Existing data has fundamental issues (duplicates, mismatches, missing validation). Japan Tabelog is the only verified dataset.

**Strategy**: Rebuild Global Dining, Plat Stay, Love Dining from authoritative sources with validation at every step.

---

## Phase 1: Lock & Verify Japan Data

- ✅ Keep `japan-restaurants.json` as-is (Tabelog-verified)
- ✅ Keep `restaurant-quality-signals.json` (Tabelog scores)
- Validate Japan data against Pocket Concierge official counts
- Document Japan data as "Source of Truth"

---

## Phase 2: Global Dining Credit (16 countries)

### Source
- **Official**: `platinumdining.caffeinesoftware.com` (sitemap + JSON-LD)
- Current scraper: `scripts/scrape_global_dining.py` (works, but needs validation)

### Rebuild Steps

1. **Fresh scrape with logging**
   ```bash
   python3 scripts/scrape_global_dining.py --fresh
   ```
   - Log every record: ID, name, country, address, source
   - Track extraction success rate

2. **Deduplicate by country+city+name**
   - Identify chains with multiple locations
   - Generate unique IDs per location: `amex-global-{country}-{city}-{name-slug}-{idx}`
   - Example: 
     - Wein & Co Bregenz → `amex-global-austria-bregenz-wein-co-1`
     - Wein & Co Graz → `amex-global-austria-graz-wein-co-1`
   - Block House Berlin → `amex-global-germany-berlin-block-house-1`
   - Block House Hamburg → `amex-global-germany-hamburg-block-house-1`

3. **Country-aware Google Maps matching**
   - When searching Google Maps, filter by country
   - Query: `"Restaurant Name" in "City, Country"`
   - Validate: Google result country must match source country
   - If mismatch (e.g., SEN in Singapore when we need Tokyo), skip and flag
   - Store match confidence: "matched", "ambiguous", "skipped"

4. **Validate against official counts**
   - AMEX publishes restaurant counts per country
   - After scrape, verify: scraped count ≈ official count
   - If mismatch > 5%, investigate and re-scrape

5. **Output**: `data/global-restaurants-REBUILT.json`
   - Same schema as original
   - With deduplication fixes
   - With match confidence metadata

---

## Phase 3: Plat Stay (69 properties)

### Source
- **Official**: AMEX Platinum Plat Stay benefits page / PDF
- Alternative: `scripts/sync_plat_stay.py` (reverse-engineer AMEX API)

### Rebuild Steps

1. **Extract from authoritative source**
   - Parse AMEX PDF or website
   - Extract: property name, city, country, address
   - Log every extraction

2. **Generate unique IDs per property**
   - No duplicates (unlike current "Wein & Co" mess)
   - Format: `amex-plat-stay-{country}-{city}-{name-slug}`
   - Example:
     - Fraser Place Chengdu → `amex-plat-stay-china-chengdu-fraser-place`
     - Fraser Place Shanghai → `amex-plat-stay-china-shanghai-fraser-place`

3. **Geocode with validation**
   - Use Google Places API (requires key, but authoritative)
   - Or use Nominatim + manual spot-checks
   - Validate: coordinates within city bounds
   - Store confidence: "official_api", "nominatim", "manual_review"

4. **Validate against AMEX counts**
   - Count properties per country
   - Compare to official AMEX list
   - If mismatch, investigate

5. **Output**: `data/plat-stays-REBUILT.json`

---

## Phase 4: Love Dining (Singapore)

### Source
- **Official**: AMEX Singapore website / Love Dining page

### Rebuild Steps

1. **Scrape from AMEX Singapore**
   - Extract: venue name, type (hotel/restaurant), address
   - Log source

2. **Geocode with Google Maps**
   - All in Singapore, so easier validation
   - Validate: coordinates within Singapore bounds
   - Confidence: "official_api", "validated"

3. **Validate against official list**
   - AMEX publishes venue count
   - Compare: scraped count vs official

4. **Output**: `data/love-dining-REBUILT.json`

---

## Phase 5: Validation Framework

### Pre-deployment Checks

```bash
# Run before any data goes live
python3 scripts/data_sanity_check.py --strict
```

Checks:
- ✅ No duplicate IDs
- ✅ All required fields present
- ✅ Coordinates within geographic bounds
- ✅ Google ratings coverage >95%
- ✅ No "0,0" coordinates
- ✅ Coordinate consistency <200m (vs Google Maps)
- ✅ Counts match official AMEX sources

### Staging Process

1. **Generate REBUILT files** (Phase 2-4)
2. **Run sanity checks** (Phase 5)
3. **Manual spot-checks**: 20-30 venues per country
4. **Count verification**: Compare to AMEX official
5. **Merge into production** files only after all pass

---

## Timeline

- **Phase 1** (Japan): 1 day — validation only
- **Phase 2** (Global): 2-3 days — scrape + dedup + geocode + validate
- **Phase 3** (Plat Stay): 1 day — extract + geocode + validate
- **Phase 4** (Love Dining): 1 day — scrape + geocode + validate
- **Phase 5** (Validation): 1 day — implement checks + manual review

**Total: ~1 week for complete rebuild**

---

## Tools & APIs Required

- **Google Maps API**: Geocoding (for Plat Stay, Love Dining)
  - Budget: ~5,000 lookups × $0.005 = $25
  - Authoritative coordinates
- **Nominatim (OpenStreetMap)**: Free alternative (rate-limited)
- **Claude WebSearch**: Verify counts, find official AMEX pages

---

## Success Criteria

✅ Zero duplicate IDs  
✅ All coordinates <200m from Google Maps  
✅ Counts match official AMEX  
✅ No "wrong country" matches (like SEN in Singapore)  
✅ Full audit trail (what was scraped, when, from where)  
✅ Validation passes --strict mode  
✅ Manual spot-checks on 20-30 venues per program  

---

## Do NOT Deploy Current Branch

The `feat/ui-improvements` branch has:
- ✅ UI improvements (tier 3 fixes, map panning) — GOOD
- ❌ Data validation scripts — GOOD
- ❌ Coordinate "fixes" based on wrong Google data — BAD

**Action**: 
1. Extract UI improvements to separate PR
2. Hold data rebuild until Phase 1-5 complete
3. Restart with clean, verified datasets
