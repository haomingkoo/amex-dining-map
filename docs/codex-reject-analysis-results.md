# Codex Reject Analysis

## Scope

This analysis reads:

- `/tmp/rejects_for_codex.json`
- `data/japan-restaurants.json`
- `data/tabelog-match-results.json`
- `data/tabelog-ground-truth-sample.json`

The category counts below are **estimated** from local data and heuristics, not hand-verified row by row. The strongest signals were name similarity, address overlap, cuisine overlap, repeated wrong targets, and the repo's small manually verified ground-truth sample.

## Estimated Breakdown

| Category | Count | Share | Read |
| --- | ---: | ---: | --- |
| a) Likely on Tabelog, but browse pool missed the right listing | 214 | 74.3% | This is the dominant bucket. The repo's `data/tabelog-ground-truth-sample.json` includes 11 rejects that were manually verified as exact Tabelog matches, which strongly suggests "not on Tabelog" is the minority case. |
| b) Possibly not on Tabelog at all | 20 | 6.9% | Mostly hotel/lounge/private-feeling venues or cases with very weak name evidence. |
| c) Likely listed under a very different name on Tabelog | 29 | 10.1% | Includes alias / renamed / shortened-name cases such as `ぎをん今` matching `今`. |
| d) Branches where the wrong branch was matched | 25 | 8.7% | Explicit branch/store markers are common here: `店`, `本店`, district/store suffixes, or chain branches. |

## Main Patterns

- Tokyo drives the problem: 192 of 288 rejects (66.7%) are in Tokyo.
- The worst hot spots are dense, high-signal neighborhoods with many same-cuisine competitors:
  - Tokyo / Ginza: 43 rejects, 52.4% reject rate
  - Tokyo / Roppongi: 13 rejects, 54.2% reject rate
  - Tokyo / Azabujuban: 8 rejects, 53.3% reject rate
  - Tokyo / Nishiazabu: 14 rejects, 34.1% reject rate
  - Kyoto / Gionmachi Minamigawa: 5 rejects, 41.7% reject rate
- The matcher keeps falling onto the same wrong Tabelog pages, which is a strong sign of browse-pool bias:
  - `銀座 稲葉`: 13 rejects
  - `とり澤 六本木`: 11 rejects
  - `大阪麺哲`: 9 rejects
  - `麻布十番 ふくだ`: 8 rejects
  - `京料理 木乃婦`: 5 rejects
- Cuisine types with the highest reject rates are the ones with the most branching / generic naming pressure:
  - `Steak, Teppanyaki`: 18 / 35 = 51.4%
  - `Yakitori`: 7 / 14 = 50.0%
  - `Sushi`: 73 / 185 = 39.5%
  - `Japanese, Kaiseki, Washoku`: 100 / 263 = 38.0%
  - `Italian`: 20 / 64 = 31.2%
  - `Tempura`: 8 / 26 = 30.8%

## Feasibility By Bucket

| Bucket | Best recovery path | Practicality |
| --- | --- | --- |
| a) Browse miss | Google/Tabelog search on `native_title + prefecture/district + tabelog`, especially for Tokyo Ginza/Roppongi/Azabu and Kyoto Gion clusters | High |
| b) Possibly absent | One targeted search pass, then accept as unmatchable if no clear listing appears | Low |
| c) Different listed name | Search aliases, website title, old names (`旧` / former), shortened names, and Japanese-only titles | Medium |
| d) Wrong branch | Branch-aware queries: strip / compare `店`, `本店`, district suffixes, hotel/store location labels, then search branch-by-branch | High |

## Top 5 Recommendations

1. **Run native-title web search outside the browse pool first for the dense Tokyo/Kyoto clusters.**  
   Expected recovery: **~140-170** rejects.  
   Why: category (a) is the biggest bucket, and repeated wrong targets show the browse pool is over-concentrated on a few famous listings.

2. **Add alias / rename search using source website titles and cleaned native titles.**  
   Expected recovery: **~20-30** rejects.  
   Why: several rejects look like `Pocket Concierge long/marketing name` vs `Tabelog shorter canonical name`.

3. **Add branch-aware matching for explicit store markers and chain branches.**  
   Expected recovery: **~20-25** rejects.  
   Why: branch/store suffixes show up repeatedly in the reject set and are a clean, automatable class.

4. **Create an immediate manual-review queue for exact-name, same-address, phone-only rejects.**  
   Expected recovery: **11-13** rejects immediately.  
   Why: these are likely false negatives from verification strictness, not search failure.

5. **Use building + floor + cuisine disambiguation before accepting address-block matches.**  
   Expected recovery on rerun: **~10-15** rejects.  
   Why: large mixed-use buildings are causing same-address false attractions to the wrong venue in the same tower or complex.

## Likely False Negatives

These are the rejects where the current matched candidate looks correct, or very close to correct, and the verifier likely over-rejected.

### High Confidence

- `pocket-245420` — `Makiyaki Kakehashi` / same name, same `3-2` address, phone-only conflict
- `pocket-245259` — `Suikoan` / same venue, same `2-14-8` address, phone-only conflict
- `pocket-244816` — `Kyoto Cuisine Aun` / same venue, same `1-33-6` address, phone-only conflict
- `pocket-244654` — `Azabu kuma san` / same venue, same `2-18-8` address, phone-only conflict
- `pocket-243879` — `La Paix` / same venue, same `1-9-4` address, only phone + district-format conflict
- `pocket-245545` — `Sushi Kaminari` / same venue, same `1-5-10` address, only phone + district-format conflict
- `pocket-244660` — `Tempura Takano (Toyama)` / same venue, same `7-3-6` address, only phone + district-format conflict
- `pocket-245386` — `Japanies restaurant SHINCHAYA` / same venue, same `4-1` address, city/district formatting mismatch plus phone conflict
- `pocket-244833` — `Terroir Ai to Ibukuro` / same venue, same `414` address, only phone + district-format conflict
- `pocket-244749` — `AGRISCAPE` / same venue, same `177` address, city/district formatting mismatch plus phone conflict
- `pocket-244411` — `Gion Kon` / source `ぎをん今`, matched `今`, same `570-6` address, phone-only conflict

### Borderline, But Worth Manual Review

- `pocket-245547` — `Sushi Taira` / exact-name candidate, but Tabelog address is hidden
- `pocket-244719` — `Sushimichi Sakurada` / exact-name candidate, but address suggests a likely move rather than a different restaurant
