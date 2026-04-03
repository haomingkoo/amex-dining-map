# Codex Prompt: Analyze 288 Unmatched Tabelog Restaurants

## Context

We have 844 Japan restaurants from Amex Pocket Concierge. We're matching each one to its Tabelog listing to get ratings/reviews. We successfully matched 547/844 (64.8%), but 288 remain unmatched ("rejected").

The matching pipeline works like this:
1. **Browse Tabelog listing pages** sorted by rating for each prefecture (top ~1000-1200 restaurants per area, with sub-area browsing for Tokyo/Osaka/Kyoto)
2. **Match by name** (Japanese + English) against the browse pool
3. **Fetch detail pages** for top candidates and verify using phone number, address digits, district, station name
4. **Score confidence** and classify as verified (>=70, no conflicts), review (>=55), or reject

The 288 rejects all have candidates found, but the candidates have conflicting phone/address data - meaning the browse pool returned the **wrong restaurant** (similar name, different location).

## The Data

Read `/tmp/rejects_for_codex.json` - it contains all 288 rejects with:
- `name`, `native_title` - restaurant name in English and Japanese
- `prefecture`, `city`, `district` - location from source
- `src_phone`, `src_addr` - source phone and address
- `matched_name`, `matched_url`, `matched_phone`, `matched_addr` - what our matcher found (wrong match)
- `confidence`, `reasons`, `conflicts` - why it was rejected

## Questions to Answer

1. **Categorize the rejects** - What % are:
   - a) Likely on Tabelog but our browse pool missed them (similar name exists, just wrong one)
   - b) Possibly not on Tabelog at all (hotel restaurants, very niche, closed)
   - c) Listed under a very different name on Tabelog
   - d) Branches where we matched the wrong branch

2. **Pattern analysis** - Are there common patterns in the failures? For example:
   - Do most Tokyo rejects share a specific district pattern?
   - Are certain cuisine types harder to match?
   - Do restaurants with certain name patterns (e.g., generic "Sushi [Name]") fail more?

3. **Feasibility assessment** - For each category above, what's the most practical way to close the gap?
   - Phone-based Tabelog search (we tried, Tabelog search may not index phones well)
   - Google search for "[native_title] tabelog"
   - Manual review of high-confidence rejects
   - Accept as unmatchable

4. **Quick wins** - Identify any rejects where the matched candidate is actually **correct** but our verification criteria was too strict. Look for cases where:
   - The names clearly match but address format differs
   - The restaurant likely moved (name matches, different address)
   - Phone number changed (name + district match perfectly)

## Output Format

Give me:
1. A breakdown table of categories with counts
2. Top 5 actionable recommendations ranked by impact (how many rejects it would recover)
3. A list of reject IDs that look like false negatives (our matcher was too strict)
