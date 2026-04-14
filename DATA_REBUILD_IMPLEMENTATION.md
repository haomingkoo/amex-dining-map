# Data Rebuild Implementation Guide

**Status**: Ready to execute Phases 1-5 with built-in validation.

**Timeline**: ~1 week total (assumes external Playwright + PDF extraction setup)

---

## Phase 1: Lock Japan Data ✅ DONE

Japan dining data is verified and locked as Source of Truth.

```bash
# Verify Japan data (already passing)
python3 scripts/validate_phase_1_japan.py
```

**Results**:
- ✅ 843 restaurants
- ✅ 97% Tabelog match coverage (818/843 with quality signals)
- ✅ All coordinates valid
- ✅ No duplicates
- ✅ 93 cities represented

**Output**: `JAPAN_VERIFICATION_REPORT.md` (committed)

---

## Phase 2: Global Dining Credit — Official AMEX Source (2,000 restaurants)

### Setup

```bash
# Install Playwright (required for JavaScript rendering)
pip install playwright
playwright install
```

### Step 1: Test HTML Parser

User has provided official AMEX page HTML samples (Hong Kong, Japan, New Zealand, Thailand). Test extraction logic:

```bash
# Test parser with sample HTML
python3 scripts/parse_amex_html_samples.py < /path/to/amex-sample.html
```

### Step 2: Scrape Official AMEX Page

```bash
# Dry run (no file writes, test only)
python3 scripts/scrape_amex_global_dining_official.py --dry-run --limit 2

# Full scrape (all 16 countries)
python3 scripts/scrape_amex_global_dining_official.py
```

**Expected output**:
- `data/rebuilt/global-restaurants-REBUILT.json` — 2,000 restaurants
- `data/rebuilt/global-dining-metadata.json` — extraction metadata
- `data/rebuilt/global-dining-REBUILD.audit.jsonl` — full audit trail

### Step 3: Validate Extraction

```bash
# Check extraction results
python3 << 'EOF'
import json
from pathlib import Path

rebuilt = Path("data/rebuilt/global-restaurants-REBUILT.json")
with open(rebuilt) as f:
    records = json.load(f)

print(f"Total: {len(records)}")
print(f"By country:")
by_country = {}
for r in records:
    c = r.get("country", "UNKNOWN")
    by_country[c] = by_country.get(c, 0) + 1
for c, count in sorted(by_country.items(), key=lambda x: -x[1]):
    print(f"  {c}: {count}")
EOF
```

**Expected**:
- ~2,000 total (±100)
- 16 countries
- Even distribution (Austria~45-50, Thailand~150-180, etc.)

### Step 4: Verify No Duplicates

```bash
python3 << 'EOF'
import json
from collections import defaultdict

with open("data/rebuilt/global-restaurants-REBUILT.json") as f:
    records = json.load(f)

ids = defaultdict(int)
for r in records:
    ids[r["id"]] += 1

dups = {k: v for k, v in ids.items() if v > 1}
if dups:
    print(f"❌ {len(dups)} duplicate IDs found!")
    for dup_id, count in sorted(dups.items())[:5]:
        print(f"  {dup_id}: {count} instances")
else:
    print("✅ No duplicate IDs")
EOF
```

### Step 5: Manual Spot-Checks (50 venues)

Sample 50 random restaurants across all countries and verify:
- Name matches what's on official AMEX page
- Address correct
- Cuisine type reasonable
- Country matches venue location

```bash
python3 << 'EOF'
import json
import random

with open("data/rebuilt/global-restaurants-REBUILT.json") as f:
    records = json.load(f)

sample = random.sample(records, min(50, len(records)))
for r in sample:
    print(f"{r['name']}")
    print(f"  {r['country']} / {r['city']}")
    print(f"  {r.get('cuisine', 'N/A')}")
    print(f"  {r.get('address', 'N/A')[:60]}")
    print()
EOF
```

**Manually verify** in AMEX benefits page:
- Visit https://www.americanexpress.com/en-sg/benefits/platinum/dining/
- Filter by country, spot-check that these venues are listed
- Confirm address and cuisine match

---

## Phase 3: Plat Stay — Official AMEX PDF (69 properties)

### Setup

```bash
# Download official PDF
curl -o data/sources/platstay.pdf \
  "https://www.americanexpress.com/content/dam/amex/en-sg/benefits/the-platinum-card/platstay.pdf?extlink=SG"

# Install PDF extraction tool
pip install pdfplumber
```

### Step 1: Create Extraction Script

```bash
# scripts/extract_plat_stay.py (pseudocode)
def extract_plat_stay():
    with pdfplumber.open("data/sources/platstay.pdf") as pdf:
        for page in pdf.pages:
            # Extract property name, city, country, address
            # Validate: all fields present, address non-empty
            # Geocode address via Nominatim (free, rate-limited)
            # Output: {id, name, city, country, address, lat, lng, coordinate_source}
```

### Step 2: Geocode Properties

```bash
# For each property, look up coordinates
pip install geopy
```

```python
from geopy.geocoders import Nominatim

geocoder = Nominatim(user_agent="amex-rebuild")
location = geocoder.geocode("Fraser Place Chengdu, China")
# Result: lat, lng
```

### Step 3: Validate

```bash
# Check: 69 properties total, all geocoded, all within country bounds
python3 << 'EOF'
import json

with open("data/rebuilt/plat-stays-REBUILT.json") as f:
    records = json.load(f)

print(f"Total: {len(records)}")
print(f"With coordinates: {sum(1 for r in records if r.get('lat'))}")
print(f"Missing coordinates: {sum(1 for r in records if not r.get('lat'))}")

# Check by country
by_country = {}
for r in records:
    c = r.get("country", "UNKNOWN")
    by_country[c] = by_country.get(c, 0) + 1
print(f"\nBy country:")
for c, count in sorted(by_country.items(), key=lambda x: -x[1]):
    print(f"  {c}: {count}")
EOF
```

**Expected**:
- 69 total (exact)
- 100% with coordinates
- Reasonable distribution by country

### Step 4: Manual Spot-Checks (15 properties)

For 15 random properties, verify on Google Maps:
- Property name visible
- Address matches
- Location in correct city/country
- Building/hotel visible

---

## Phase 4: Love Dining — Official AMEX PDFs (79 Singapore venues)

### Setup

```bash
# Download official PDFs
# (Download manually or via wget if URLs available)

# Assumed to be in:
# data/sources/Love_Dining_Restaurants_TnC.pdf
# data/sources/Love_Dining_Hotels_TnC.pdf
```

### Step 1: Extract from PDFs

```bash
# scripts/extract_love_dining.py
def extract_love_dining():
    for pdf_file in ["Love_Dining_Restaurants_TnC.pdf", "Love_Dining_Hotels_TnC.pdf"]:
        with pdfplumber.open(f"data/sources/{pdf_file}") as pdf:
            # Extract venue name, type (restaurant/hotel), address
            # All in Singapore
            # Geocode via Nominatim with Singapore filter
            # Output: {id, name, type, address, city, lat, lng, coordinate_source}
```

### Step 2: Geocode All Venues

All venues are in Singapore (1.2-1.5°N, 103.6-104.1°E).

```python
from geopy.geocoders import Nominatim

geocoder = Nominatim(user_agent="amex-rebuild")
location = geocoder.geocode("JW Marriott South Beach Singapore, Singapore")
```

### Step 3: Validate

```bash
# Check: 79 venues total, 100% with coordinates, all in Singapore
python3 << 'EOF'
import json

with open("data/rebuilt/love-dining-REBUILT.json") as f:
    records = json.load(f)

print(f"Total: {len(records)}")
print(f"With coordinates: {sum(1 for r in records if r.get('lat'))}")

# Check bounds: Singapore is roughly 1.2-1.5N, 103.6-104.1E
in_bounds = sum(1 for r in records 
    if 1.0 <= r.get("lat", 0) <= 1.6 and 103.5 <= r.get("lng", 0) <= 104.2)
print(f"Within Singapore bounds: {in_bounds}")

# Type distribution
restaurants = sum(1 for r in records if r.get("type") == "restaurant")
hotels = sum(1 for r in records if r.get("type") == "hotel")
print(f"Restaurants: {restaurants}, Hotels: {hotels}")
EOF
```

**Expected**:
- 79 total (exact)
- 100% with coordinates
- 100% within Singapore bounds
- Mix of restaurants and hotels

### Step 4: Manual Spot-Checks (20 venues)

For 20 random venues, verify on Google Maps:
- Venue name
- Address
- Location visible in Singapore
- Type (restaurant/hotel) correct

---

## Phase 5: Deployment Validation

### Step 1: Run Pre-Deployment Checks

```bash
# This is the strict validation that gates production deployment
python3 scripts/data_sanity_check.py --strict
```

**Checks**:
1. ✅ Zero duplicate IDs (across all 4 datasets)
2. ✅ All coordinates <10m from Google Maps
3. ✅ Counts match AMEX official
4. ✅ No "wrong country" matches
5. ✅ Coordinate distribution reasonable
6. ✅ Google ratings coverage >95%
7. ✅ Data type consistency

### Step 2: Manual Cross-Dataset Validation

Spot-check 50 random venues (mix of Japan, Global, Plat Stay, Love Dining):
- Verify on actual maps
- Check for country/city consistency
- Confirm no duplicate records across datasets

### Step 3: Merge to Production

```bash
# Only if ALL validations pass:

# 1. Backup current data
git mv data/global-restaurants.json data/global-restaurants.BACKUP.json
git mv data/plat-stays.json data/plat-stays.BACKUP.json
git mv data/love-dining.json data/love-dining.BACKUP.json

# 2. Move REBUILT files
mv data/rebuilt/global-restaurants-REBUILT.json data/global-restaurants.json
mv data/rebuilt/plat-stays-REBUILT.json data/plat-stays.json
mv data/rebuilt/love-dining-REBUILT.json data/love-dining.json

# 3. Commit
git add data/*.json
git commit -m "data: rebuild from official AMEX sources (validation passed)"

# 4. Push to main (auto-deploys to production)
git push origin main
```

---

## Validation Checklist Before Deployment

- [ ] Phase 1: Japan data verified and locked ✅
- [ ] Phase 2: Global Dining scraped, 2,000 restaurants, no duplicates
- [ ] Phase 2: Manual spot-checks (50 venues) passed
- [ ] Phase 3: Plat Stay extracted, 69 properties, all geocoded
- [ ] Phase 3: Manual spot-checks (15 properties) passed
- [ ] Phase 4: Love Dining extracted, 79 venues, all geocoded
- [ ] Phase 4: Manual spot-checks (20 venues) passed
- [ ] Phase 5: `data_sanity_check.py --strict` passes
- [ ] Phase 5: Manual cross-dataset validation (50 venues) passed
- [ ] All audit trails generated and saved

**Only merge to main once ALL checks pass.**

---

## Troubleshooting

### Playwright Installation Issues

```bash
# If headless browser fails:
playwright install --with-deps
```

### PDF Extraction Issues

```bash
# If pdfplumber can't extract text:
pip install "pdfplumber[full]"

# Or use alternative:
pip install pypdf
```

### Geocoding Rate Limits

```bash
# Nominatim has rate limits (1 req/sec)
# Add delays between requests:
import time
for address in addresses:
    location = geocoder.geocode(address)
    time.sleep(1)  # 1 second delay
```

### Validation Failures

If `data_sanity_check.py --strict` fails:
1. Check audit trail: `data/rebuilt/*.audit.jsonl`
2. Identify which dataset/records failed
3. Fix extraction logic (not the data)
4. Re-run extraction for that dataset
5. Re-validate

**Do not manually edit REBUILT files** — if there's a problem, fix the source.

---

## Success Criteria

✅ All phases complete with validation passing  
✅ Zero validation errors in audit trails  
✅ Manual spot-checks confirm accuracy  
✅ All datasets merged to production  
✅ Railway auto-deploy successful  
✅ App displays 2,000+ Global, 69 Plat Stay, 79 Love Dining, 843 Japan venues  

---

## Next Steps (After Deployment)

1. Monitor production for any data issues
2. Keep audit trails for future reference
3. Update scraper if AMEX pages change
4. Quarterly validation runs to catch any drift
