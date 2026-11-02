# Table for Two card tiers (Platinum and Centurion)

Date: 2026-11-02. Status: approved to build ("please make it happen").

## Why

Amex runs Table for Two as two separate DiningCity booking projects, and we only read one.

| Project | Card | Venues listed (2026-11-02) |
|---|---|---|
| `AMEXPlatSG` | Platinum | 31 |
| `AMEXCentSG` | Centurion | 39 |

So Centurion members get nothing for the nine Centurion-only venues: JAAN By Kirk Westaway, Ginger.Lily, Isabel, Lerouy 3.0, Prada Caffè, Restaurant JAG, Shisen Hanten, Summer Pavilion and The Courtyard. A group-chat member found JAAN before we did.

What we measured live on 2026-11-02:

- **Inventory is separate per tier.** On dates both tiers have, only 23 of 53 venue-dates had identical times and seats. VUE had 0 Platinum dates and 13 Centurion dates. Zui Yu Xuan on 5 Nov lunch: Platinum 12:00 and 13:00, Centurion 12:00, 12:30, 13:00 and more. Madame Fan on 6 Nov 12:30: Platinum 8 seats, Centurion 10. A booking under one project does not use seats in the other.
- **Menus differ per tier.** Amex publishes `*_Platinum.pdf` and `*_Centurion.pdf`. Zui Yu Xuan Platinum is 5 courses ($108++ per extra guest). Centurion is 6 courses with foie gras, cod and hashima ($158++). `scripts/fetch_tft_menus.py` already reads both Amex folders.
- **A project's venue list is not the whole truth.** Zui Yu Xuan is not in `AMEXCentSG`'s venue list (all pages checked). But `/restaurants/205196578/projects/program_and_event` lists `AMEXCentSG`, `dining_dates?project=AMEXCentSG` returns dates, and a Centurion menu exists.
- **Same restaurant, same id.** The 30 venues both projects share use the same DiningCity `restaurant_id`.

## Goals

1. Track both tiers' rosters automatically, with the existing confirm-twice rule for additions and removals.
2. Track slots per tier. A Platinum reminder never fires on Centurion seats, and the reverse.
3. Every registration names a tier: Telegram reminders, `/slots` queries and email sign-ups. Members only see and register for venues their tier can book.
4. Map and guide show which tiers each venue is open to, with the matching menu.
5. Detect new Amex booking projects (a new tier or event) and alert the owner rather than ignore them.

## Non-goals

- Other cards (Gold, Krisflyer) and non-Singapore programmes.
- Proving card ownership. We take the member's word for their tier.
- Booking on the member's behalf.

## Anti-goals (a failure even if it "works")

- A member is alerted for seats they cannot book with their own link.
- An existing Platinum reminder or subscription stops firing, or changes meaning, after the migration.
- A Centurion-only venue shows up for a Platinum member without a clear tier label.
- DiningCity load roughly doubles and trips rate limits so that Platinum freshness (30-minute rule) gets worse.
- A live data value gets asserted in `Deploy Pages` (see CLAUDE.md gotcha).

## Domain terms

- **Tier:** `platinum` or `centurion`. Maps 1:1 to a DiningCity project: `platinum → AMEXPlatSG`, `centurion → AMEXCentSG`. One table in one module owns this mapping. Nothing else hard-codes project codes.
- **Venue tiers:** the set of tiers a venue is bookable under. A venue is bookable under a tier if it's online in that project's venue list, **or** its `program_and_event` lists the project and `dining_dates?project=` returns at least one date (the Zui Yu Xuan case). Record which rule admitted it: `listed` or `linked_only`.
- **Tier slot:** availability for a (venue, tier) pair.

## Decided

- Existing data defaults to `platinum`: every current reminder and email subscription. Nobody gets moved to Centurion without choosing it.
- Each reminder or query names one tier. Centurion does not automatically include Platinum, because Platinum seats need a Platinum booking link.
- Zui Yu Xuan and any other `linked_only` venue *is* shown to Centurion members, with the Centurion menu and Centurion slots, plus a note that it's missing from the Centurion venue list and they should check the booking link.
- Tier is part of a reminder's identity: (venue, tier, party, meal, dates). The same venue under two tiers is two reminders.
- Ship in phases, each its own PR, each safe to stop after.

## Phases

### Phase 1: roster for both tiers (data and site only)

- `scripts/scrape_table_for_two.py` reads both projects and builds one venue list keyed by DiningCity id. Each venue gets `tiers` (sorted list) and per-tier membership evidence (`listed` / `linked_only`, record hash, source URL). Membership streaks are per (venue, tier), so one tier dropping a venue does not remove the other.
- Centurion-only venues go through the existing addition confirmation (`AUTO_MEMBERSHIP_CONFIRMATIONS`).
- Menus: `venue.menu_pdfs` already has per-card keys. Centurion-only venues get Centurion menus through the existing review queue.
- **New-project detector:** collect every project code seen in `program_and_event` across all venues. A code starting `AMEX` that is not in the tier table opens a source-change alert. Store the codes seen so it fires once.
- `scripts/check_roster_parity.py` checks parity per tier.
- Site (`web/app.js`): tier badges on venue cards and a Platinum / Centurion / All filter. The default is All, with badges. Menu links use the selected tier when there is one.
- Slots stay Platinum-only in this phase. Centurion-only venues show "slots not tracked yet", not "no seats".

### Phase 2: slots per tier

- Slot snapshot moves to schema v2: each venue entry gets per-tier results `{tier, project, status, meals, checked_at, ...}`. Keep serving the v1 Platinum shape at `/api/tft/slots` until every consumer reads v2 (site, alert job, Telegram). Then remove it in a later PR.
- `reminders/app/tft_live_refresh.py` fetches (venue, tier) pairs. Measured 2026-11-02: one Platinum cycle is 141 DiningCity calls and 16.5s run sequentially, so both tiers fit easily in `TFT_LIVE_REFRESH_INTERVAL_SECONDS` (600s). No staggering needed. Platinum freshness must not regress.
- Validators (`tft_slot_source.py`, `tft_slots.py`, `build_tft_slot_snapshot.py`) check the project against the tier table, not a constant.
- `tft_slot_history` / `tft_patterns` key by (venue, tier). Release-pattern history so far is Platinum.

### Phase 3: registration and matching per tier

- **Telegram (owner decision 2026-11-02: ask per reminder):** the new-reminder flow gains a Platinum / Centurion step before the venue step. The venue picker then lists only that tier's venues. `/slots` takes a tier argument, or asks when it is missing. Nothing about the member is stored beyond what reminders already store, so the privacy copy and `/delete_me` stay as they are. `telegram_reminders` gains a `tier` column defaulting to `platinum` (SQLite migration in the style of `db.py`'s `ALTER TABLE`). The conversation state machine gains a `tier` state. Dispatch matches tier slots only. Existing reminders stay Platinum and are unaffected.
- **Email:** the sign-up form gets a tier field. `subscribers.tier` defaults to `platinum`. `scripts/send_table_for_two_alerts.py` matches by tier. Email copy names the tier.
- **Guide:** `build_tft_guide_catalog.py` and `tft_guide` answers name the tier and use that tier's menu. A tier-less question about a venue answers for both and says so.

### Phase 4: clean-up

- Remove the v1 slot shape. Update `PRODUCT.md`, `README.md` and `reminders/README.md`. Add `Centurion` to the Telegram `/about` copy.

## Acceptance (observable)

1. With the live API, the roster includes all 9 Centurion-only venues with `tiers == ["centurion"]`, after two refreshes.
2. Zui Yu Xuan has `tiers == ["centurion", "platinum"]` with Centurion evidence `linked_only`.
3. The 30 shared venues have both tiers. Madame Fan has both.
4. A fixture `program_and_event` with `AMEXNewSG` produces exactly one source-change alert, and no second alert on the next run.
5. If a venue leaves `AMEXCentSG` for two runs, only its Centurion tier goes. Platinum stays.
6. Grand Cru (and every shared venue that has both PDFs) shows both menus. The Centurion filter shows the Centurion menu link.
7. On the live site, the Centurion filter shows JAAN, and the Platinum filter does not.
8. The slot snapshot v2 has separate Platinum and Centurion results for VUE, and they differ when the live data differs.
9. Platinum freshness after Phase 2: every Platinum venue `checked_at` within 30 minutes at `/healthz` time, same as before.
10. A Centurion reminder for Zui Yu Xuan fires on a Centurion slot, and not on a Platinum-only slot (unit test with fixtures).
11. After migration, every pre-existing reminder and subscriber has `tier == "platinum"` and still matches the same slots as before (test against a copy of the schema with seeded rows).
12. After choosing Platinum in the reminder flow, the venue picker does not list JAAN. After choosing Centurion, it does.
13. `Deploy Pages` gains no data-value assertions. New data-shaped checks live in `Tests`.

## Constraints

- Railway service deploys are manual (`reminders/README.md`). Phase 2 and Phase 3 each need a deploy plus a `/healthz` `deployment_id` check.
- Data workflows commit to main. Pull before branching.
- Use the existing confirm-twice and review-queue mechanisms. No new bypasses.
- Test fixtures use relative dates (engineering rule).
- Never commit user/session-specific app values (existing source note).

## Left to the builder

- Exact JSON field names beyond `tiers`, and the tier table's module location.
- Staggering strategy for the refresh, if needed.
- Telegram copy and button layout. Follow existing keyboard patterns.
- Site filter UI details. Follow `DESIGN.md`.

## Calls made after the builder check

These are the builder's calls, not decisions the owner made. The owner can override them.

- **Centurion roster source:** DiningCity `AMEXCentSG` is the source of truth. Amex has no scrapeable Centurion roster page: `/en-sg/benefits/centurion/dining-and-lifestyle/` renders client-side and lists no venues. Centurion-only venues come in through the same auto-membership path that added Madame Fan on 2026-11-01. A Centurion menu PDF in the Amex folder counts as corroboration. Roster parity runs per tier against each project.
- **`linked_only` debounce:** dates are needed only to *admit* a `linked_only` tier. Once admitted, it stays while `program_and_event` still lists the project. Absence means the link is gone for two runs in a row. Zero dates in a quiet week does not count as absence.
- **GitHub-side availability:** `scripts/tft_live_availability.py` and the `scrape_table_for_two.py` overlay follow the tier table in Phase 2. That doubles their calls (about 141 more per run, once a day). That is acceptable.
- **Digest:** `telegram_digest` is a slot consumer. It is tier-scoped in Phase 3 and blocks v1 removal.
