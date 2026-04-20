# Data Maintenance & Refresh Strategy

This document outlines how to keep the Amex Dining Map data current and prevent staleness.

## Current Data Status (as of 2026-04-20)

| Dataset | Last Updated | Count | Freshness |
|---------|--------------|-------|-----------|
| Global Restaurants | Apr 20, 2026 | 2,439 | Current |
| Japan Restaurants | Apr 12, 2026 | 843 | 8 days old |
| Google Maps Ratings | Apr 12, 2026 | 3,430 venues | 8 days old |
| Plat Stays | Apr 15, 2026 | 69 properties | 5 days old |
| Love Dining (Singapore) | Apr 15, 2026 | 79 venues | 5 days old |

**Total venues: 3,430** (843 Japan + 2,439 Global + 69 Stays + 79 Love Dining)

---

## Refresh Schedule

### Monthly Maintenance (Recommended)

Run these in order at the start of each month:

#### Week 1: Check for Changes
```bash
# Check if global dining has changed (non-destructive)
python3 scripts/scrape_global_dining.py --diff

# Log snapshot date for tracking
echo "Global dining diff check: $(date)" >> logs/maintenance.log
```

#### Week 2: Refresh Ratings
```bash
# Update Google Maps ratings (only missing records to avoid rate limiting)
python3 scripts/scrape_google_ratings_playwright.py --missing-only

# This takes ~20-30 minutes for new venues only
```

#### Week 3: Validate All Data
```bash
# Run validation suite to catch quality issues
python3 scripts/validate_all_datasets.py

# Check for:
# - Invalid coordinates (outside country bounds)
# - Missing required fields
# - Duplicate records
# - Broken geocoding
```

#### Week 4: Commit Updates
```bash
# Stage changes
git add data/*.json

# Commit with date and summary
git commit -m "chore: monthly data refresh - Apr 2026"

# Push to feature branch, open PR, merge after review
git push origin feat/data-maintenance-apr-2026
```

---

## Data Source Update Frequency

### Global Dining Credit
- **Source**: `platinumdining.caffeinesoftware.com`
- **Update frequency**: Quarterly (AMEX typically adds/removes partnerships slowly)
- **How to detect changes**:
  ```bash
  python3 scripts/scrape_global_dining.py --diff
  ```
  Compares current scrape against last snapshot. Returns added/removed restaurants.
- **When to refresh**: If diff shows > 5 changes, run full scrape and commit

### Japan Restaurants
- **Source**: Internal Pocket Concierge data (static baseline)
- **Update frequency**: Annually (AMEX program structure rarely changes)
- **Tabelog matches**: Degrade over time as restaurants close/change
- **When to refresh**: 
  - New restaurants added to baseline → run `match_tabelog_candidates.py`
  - Existing rejects → run `retry_rejects_cached.py`

### Google Maps Ratings
- **Source**: Google Maps (real-time user ratings)
- **Update frequency**: Weekly (ratings change daily)
- **How to refresh**:
  ```bash
  # Missing venues only (fast, safe)
  python3 scripts/scrape_google_ratings_playwright.py --missing-only
  
  # All venues (slow, ~1-2 hours, use --dry-run first)
  python3 scripts/scrape_google_ratings_playwright.py
  ```
- **Cost**: Each venue takes 10-15 seconds; 3,430 venues ≈ 10 hours wall time

### Plat Stays & Love Dining
- **Source**: Official AMEX websites
- **Update frequency**: Annually (program structure is stable)
- **How to refresh**: Manual re-extraction if known changes (e.g., new properties announced)

---

## Automation Strategy (Future)

### GitHub Actions Scheduled Refresh
```yaml
# .github/workflows/monthly-refresh.yml
name: Monthly Data Refresh
on:
  schedule:
    - cron: '0 0 1 * *'  # First day of month at midnight UTC
jobs:
  refresh:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Refresh global dining
        run: python3 scripts/scrape_global_dining.py --diff
      - name: Refresh ratings (missing only)
        run: python3 scripts/scrape_google_ratings_playwright.py --missing-only
      - name: Validate
        run: python3 scripts/validate_all_datasets.py
      - name: Commit and push
        run: |
          git config user.email "bot@example.com"
          git config user.name "Data Refresh Bot"
          git add data/*.json
          git commit -m "chore: automated monthly data refresh"
          git push
```

---

## Detecting Stale Data

### Warning Signs
1. **Last update > 30 days old** → Run monthly refresh
2. **Restaurant closed/relocated** → Found via Google Maps rating scrape
3. **Phone number invalid** → Check Tabelog match confidence
4. **Coordinates outside bounds** → Validation error; check geocoding

### Validation Checks

Run weekly (or on-demand):
```bash
python3 scripts/validate_all_datasets.py
```

Checks:
- All coordinates within country bounds (16 countries)
- No negative ratings or invalid review counts
- All required fields present
- No obvious duplicates (by name + city + country)
- Geocoding accuracy (lat/lng within city bounds)

---

## Handling Data Issues

### If duplicate records appear
```bash
# Deduplicate by ID
python3 << 'EOF'
import json
from pathlib import Path

file = Path("data/global-restaurants.json")
with open(file) as f:
    data = json.load(f)

seen_ids = set()
deduped = []
for record in data:
    if record.get('id') not in seen_ids:
        deduped.append(record)
        seen_ids.add(record.get('id'))

with open(file, 'w') as f:
    json.dump(deduped, f, indent=2)

print(f"Removed {len(data) - len(deduped)} duplicates")
EOF
```

### If a restaurant is closed
1. Verify on Google Maps (check "Permanently Closed" label)
2. Remove from dataset or mark `status: "closed"`
3. Commit change with reason in message

### If ratings are stale
```bash
# Force refresh specific venues
python3 scripts/scrape_google_ratings_playwright.py --dataset japan --force-all
```

---

## Monitoring & Alerts

### Manual Checks (Weekly)
- [ ] Review recent Google Maps changes for big venues
- [ ] Check for new Amex announcements (partnership additions)
- [ ] Verify no restaurants have 0 ratings (uncached/failed scrape)

### Metrics to Track
- Total venues: should stay ~3,430 unless AMEX changes programs
- Countries with coverage: should remain 16 + Japan
- Venues with Google ratings: target 99%+ coverage
- Days since last refresh: should never exceed 30 days

### Commit to MEMORY

Once monthly refresh is complete, update:
```
- Last refresh: YYYY-MM-DD
- Venues added/removed: +X / -Y
- Issues found: [list]
- Next review: YYYY-MM-DD
```

---

## Development: Adding New Data

When new restaurants/properties are added to source data:

1. **Run matcher for Japan restaurants**:
   ```bash
   python3 scripts/match_tabelog_candidates.py
   ```

2. **Rebuild URL cache for new rejects** (via Claude WebSearch):
   ```bash
   # Delegate to parallel Claude agents in this CLI
   # Each agent searches for 5-10 restaurant URLs
   # Merge results into data/tabelog-url-cache.json
   ```

3. **Retry rejects with cache**:
   ```bash
   python3 scripts/retry_rejects_cached.py
   ```

4. **Promote matches**:
   ```bash
   python3 scripts/promote_tabelog_matches.py
   python3 scripts/merge_restaurant_quality_signals.py
   ```

5. **Scrape ratings for new venues**:
   ```bash
   python3 scripts/scrape_google_ratings_playwright.py --missing-only
   ```

---

## Key Caches to Preserve

Never delete without understanding impact:

| Cache | Size | Impact of Loss | Rebuild Time |
|-------|------|----------------|--------------|
| `tabelog-match-http-cache.json` | ~30MB | Slow re-matching (5 min cost) | 30 minutes |
| `tabelog-url-cache.json` | ~500KB | Rejects unsolved | 2 hours (Claude search) |
| `google-maps-ratings.json` | ~5MB | Lose all ratings | 10 hours (full scrape) |
| `web-search-signals-cache.json` | ~2MB | Re-fetch Michelin data | 30 minutes |

---

## Questions or Issues?

- **Data refresh failing?** Check that dependencies are installed: `pip install -r requirements.txt`
- **Ratings outdated?** Run `scripts/scrape_google_ratings_playwright.py --missing-only`
- **Duplicates detected?** Run deduplication script above and commit
- **Validation errors?** Run `validate_all_datasets.py` to see details
