# TFT Card Tiers, Phase 1 (Roster for Both Tiers) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Track the Centurion booking project's roster next to Platinum. Every venue records which tiers can book it. New Amex booking projects raise an alert, and the site shows and filters by tier. Slots stay Platinum-only.

**Architecture:** The existing Platinum membership pass in `scripts/scrape_table_for_two.py` stays byte-for-byte the same and keeps owning `booking_project_status` and `booking_project_source`. A second pass runs the same functions with `tier="centurion"` over the Platinum result. It writes `booking_project_sources.centurion` and adds Centurion-only venues under their own `roster_basis`. Each venue gains `tiers`, `booking_project_statuses` and `tier_membership`. Telegram, the slot snapshot and the Railway refresh already drop `booking_project_status == "not_listed"`, so Centurion-only venues stay out of them until Phase 2.

**Tech Stack:** Python 3.12 (stdlib urllib, pytest), vanilla JS (`web/app.js`), GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-11-02-tft-card-tiers-design.md`

## Global Constraints

- Tier codes: `platinum → AMEXPlatSG` ("AMEX Platinum SG"), `centurion → AMEXCentSG` ("AMEX Centurion SG"). Only `scripts/tft_tiers.py` holds these codes for the roster code.
- Confirm-twice: `AUTO_MEMBERSHIP_CONFIRMATIONS = 2` applies per (venue, tier) for additions and removals.
- Existing Platinum outputs (`booking_project_status`, `booking_project_source`, `slot_source_status`, `roster_basis == "diningcity_booking_project_confirmed"`) keep their current meaning and values.
- `linked_only` admission needs `program_and_event` to list the project **and** at least one `dining_dates?project=` date. Once admitted, it stays while `program_and_event` lists the project. Zero dates does not count as absence.
- No data-value assertions in `Deploy Pages`. Data-shaped checks go in `Tests`.
- Test fixture dates are relative to now. Unit tests mock DiningCity.
- Do not commit `data/*.json` produced by local runs. The refresh workflow owns those commits.
- Tests: `reminders/.venv/bin/python -m pytest scripts/tests -q`, `python3 -m pytest reminders/tests -q`, `for f in scripts/tests/*.js; do node "$f"; done`, `node scripts/verify-project.mjs --static-only`.

## Review Focus

1. **Centurion observation errors** (DiningCity 5xx on `/projects/AMEXCentSG/restaurants`): Centurion supplements are retained, Platinum is unaffected, and the refresh still succeeds. Test in Task 3.
2. **A Centurion-only venue later joins Platinum:** it must not appear twice. The Platinum pass flags `duplicate_venue_id` for review and the venue keeps one record. Test in Task 3.
3. **First run after deploy:** every existing venue gains `tiers`. The source-change alert lists them as changed once and never again. Test in Task 5.
4. **`program_and_event` fails for one venue:** that venue's `linked_only` state is retained from the previous run, not dropped. Test in Task 2.
5. **Site with an old catalog (no `tiers` field):** the TFT view still shows every venue whose `booking_project_status !== "not_listed"`, and the tier filter hides itself. Test in Task 6.

---

### Task 1: Tier table

**Files:**
- Create: `scripts/tft_tiers.py`
- Test: `scripts/tests/test_tft_tiers.py`

**Interfaces:**
- Produces: `TIER_ORDER: tuple[str, ...] = ("platinum", "centurion")`. `TIERS: dict[str, dict]` with keys `project`, `project_title`, `label`. `project_for(tier: str) -> str` (KeyError on unknown). `tier_for_project(code: str) -> str | None`. `roster_basis_for(tier: str) -> str` returns `"diningcity_booking_project_confirmed"` for platinum and `"diningcity_centurion_project_confirmed"` for centurion.

- [ ] **Step 1: Write the failing test**

```python
def test_tier_table_maps_both_projects():
    assert tft_tiers.project_for("platinum") == "AMEXPlatSG"
    assert tft_tiers.project_for("centurion") == "AMEXCentSG"
    assert tft_tiers.tier_for_project("AMEXCentSG") == "centurion"
    assert tft_tiers.tier_for_project("AMEXNewSG") is None
    assert tft_tiers.roster_basis_for("platinum") == "diningcity_booking_project_confirmed"
    assert tft_tiers.roster_basis_for("centurion") == "diningcity_centurion_project_confirmed"
    with pytest.raises(KeyError):
        tft_tiers.project_for("gold")
```

- [ ] **Step 2:** Run `reminders/.venv/bin/python -m pytest scripts/tests/test_tft_tiers.py -q`. Expected: FAIL (module missing).
- [ ] **Step 3:** Implement `scripts/tft_tiers.py` per the Interfaces block.
- [ ] **Step 4:** Rerun. Expected: PASS.
- [ ] **Step 5:** Commit `feat(tft): add card tier table`.

### Task 2: Membership fetch per tier, with linked_only records and project codes

**Files:**
- Modify: `scripts/scrape_table_for_two.py` (`fetch_booking_project_membership` ~420, `_booking_project_record` ~160, `has_project` ~151)
- Test: `scripts/tests/test_booking_project_membership.py`

**Interfaces:**
- Consumes: `tft_tiers.project_for`.
- Produces:
  - `fetch_booking_project_membership(reviewed_roster, checked_at, existing_payload=None, *, tier="platinum", linked_candidates=None) -> dict`. For `tier="platinum"` the output is unchanged. For centurion, `previous` comes from `existing_payload["booking_project_sources"]["centurion"]`. `project` and `source_url` use `project_for(tier)`. The result adds `"tier": tier`. Each record gains `"membership": "listed"`.
  - `linked_only_membership_records(candidates: list[dict], project: str, listed_ids: set[str], previous_source: dict, fetch=fetch_json) -> tuple[list[dict], dict[str, list[str]]]`. `candidates` are Platinum observed records (same shape as `_booking_project_record` output) for venues not in `listed_ids`. Returns `(records, codes_by_id)`. `records` are copies with `availability_project=project` and `membership="linked_only"`. `codes_by_id` maps each candidate id to the sorted `project` codes from `/restaurants/{id}/projects/program_and_event`.
  - Admission: linked AND (id was `linked_only` in `previous_source["observed_venues"]`, OR `dining_dates?project=` returns at least one `available: True`).
  - On a fetch error for one id: keep that id's previous `linked_only` record, if any, and omit it from `codes_by_id`.
  - The centurion `fetch_booking_project_membership` appends these records to `observed_venues` before streaks are computed, and stores `codes_by_id` as `"project_codes_by_id"`.
  - `_membership_record_sha256` includes `membership`.

- [ ] **Step 1: Write the failing tests**

```python
def test_platinum_membership_output_is_unchanged(monkeypatch): ...
    # fixture rows → result has project "AMEXPlatSG", tier "platinum",
    # every record membership == "listed"; existing keys/values unchanged

def test_centurion_lists_its_own_project_and_previous_source(monkeypatch):
    # fetch_json asserts path == "/projects/AMEXCentSG/restaurants"
    # previous streaks read from existing_payload["booking_project_sources"]["centurion"]
    assert result["project"] == "AMEXCentSG" and result["tier"] == "centurion"

def test_linked_only_admitted_with_dates_and_kept_without_dates():
    # run 1: program_and_event lists AMEXCentSG, dining_dates has one available date → 1 record, membership "linked_only"
    # run 2: same link, dining_dates [] , previous_source has it as linked_only → still admitted
    # run 3: program_and_event no longer lists AMEXCentSG → not admitted

def test_linked_only_not_admitted_without_dates_first_time(): ...
    assert records == []

def test_linked_only_fetch_error_keeps_previous_record():
    # fetch raises for that id → previous linked_only record returned, id absent from codes_by_id

def test_project_codes_collected_per_venue():
    assert codes == {"205196578": ["AMEXCentSG", "AMEXPlatSG", "asia_award_dining"]}
```

- [ ] **Step 2:** Run `reminders/.venv/bin/python -m pytest scripts/tests/test_booking_project_membership.py -q`. Expected: the new tests FAIL.
- [ ] **Step 3:** Implement the signatures above. Keep the error branch's retained-evidence behaviour for both tiers.
- [ ] **Step 4:** Rerun that file and the whole `scripts/tests` suite. Expected: PASS. Existing Platinum tests unchanged.
- [ ] **Step 5:** Commit `feat(tft): fetch booking-project membership per tier`.

### Task 3: Published roster per tier

**Files:**
- Modify: `scripts/scrape_table_for_two.py` (`current_published_roster` ~498, `booking_project_status_for_venue` ~749)
- Test: `scripts/tests/test_booking_project_status.py` (add) and `scripts/tests/test_booking_project_membership.py`

**Interfaces:**
- Consumes: Task 1 `roster_basis_for`. Task 2 source dicts.
- Produces:
  - `current_published_roster(reviewed_roster, booking_project_source, existing_payload=None, *, tier="platinum") -> tuple[list[dict], dict]`. Supplements are filtered by `roster_basis_for(tier)`. Auto-added venues get that `roster_basis` and evidence `source` text `f"DiningCity {project} booking-project membership"`. For platinum, the output equals today's.
  - `booking_project_status_for_venue(venue, source, existing_record=None, *, tier="platinum") -> str`. For centurion, `previous_status` is `existing_record["booking_project_statuses"]["centurion"]`.

- [ ] **Step 1: Write the failing tests**

```python
def test_centurion_only_venue_added_after_two_observations():
    # roster = platinum combined (no JAAN); centurion source observes JAAN 205189592 twice
    # run 1 → JAAN in pending_booking_project_additions, not in roster
    # run 2 → JAAN in roster with roster_basis "diningcity_centurion_project_confirmed"

def test_platinum_pass_ignores_centurion_supplements():
    # existing_payload venues include a centurion-basis JAAN; platinum current_published_roster
    # neither returns it nor lists it in pending/confirmed removals

def test_centurion_error_retains_centurion_supplements():
    # centurion source observation_status "error" → JAAN retained; maintenance outcome "retained_after_source_error"

def test_centurion_tier_dropped_only_after_two_absences():
    # shared venue absent from centurion twice → centurion status "not_listed"; platinum status still "active"

def test_centurion_only_venue_joining_platinum_is_not_duplicated():
    # JAAN (centurion basis) now also in AMEXPlatSG observed → platinum pass flags duplicate_venue_id review item; one JAAN record
```

- [ ] **Step 2:** Run the two files. Expected: new tests FAIL.
- [ ] **Step 3:** Implement the `tier` parameter. Platinum defaults keep every current call site unchanged.
- [ ] **Step 4:** Run the full `scripts/tests`. Expected: PASS.
- [ ] **Step 5:** Commit `feat(tft): publish roster additions and removals per tier`.

### Task 4: Wire the Centurion pass into the payload

**Files:**
- Modify: `scripts/scrape_table_for_two.py` (`build_payload` ~1203, `refresh_availability_payload` ~1353, `normalized_venues` ~1154)
- Test: `scripts/tests/test_table_for_two_data.py`

**Interfaces:**
- Consumes: Tasks 2 and 3.
- Produces payload fields:
  - top level `booking_project_sources: {"centurion": <centurion source>}`. `booking_project_source` is still Platinum.
  - top level `booking_project_codes: {"known": [...], "unknown_amex": [...]}`. `unknown_amex` is the sorted codes from `project_codes_by_id` that start with `AMEX` and where `tier_for_project` is None.
  - per venue `booking_project_statuses: {"platinum": str, "centurion": str}`.
  - per venue `tiers: list[str]`, in `TIER_ORDER` order, of tiers whose status is `"active"`.
  - per venue `tier_membership: {"centurion": "listed" | "linked_only"}`, only when centurion is active.
- Order in both builders:
  1. Platinum fetch, then Platinum roster.
  2. Centurion fetch, with `linked_candidates` = Platinum observed records not in the Centurion listing.
  3. Centurion roster over the Platinum roster.
  4. `normalized_venues(..., centurion_source=...)`.
- The availability roster stays Platinum-active only.

- [ ] **Step 1: Write the failing tests**

```python
def test_payload_tiers_for_shared_platinum_only_and_centurion_only(monkeypatch):
    # fixtures: shared venue in both listings; platinum-only venue; JAAN centurion-only (2nd observation);
    # Zui Yu Xuan: platinum-listed, centurion linked_only with a date
    assert by_name["Shared"]["tiers"] == ["platinum", "centurion"]
    assert by_name["PlatOnly"]["tiers"] == ["platinum"]
    assert by_name["JAAN By Kirk Westaway"]["tiers"] == ["centurion"]
    assert by_name["JAAN By Kirk Westaway"]["booking_project_status"] == "not_listed"
    assert by_name["Zui Yu Xuan"]["tier_membership"] == {"centurion": "linked_only"}
    assert payload["booking_project_source"]["project"] == "AMEXPlatSG"
    assert payload["booking_project_sources"]["centurion"]["project"] == "AMEXCentSG"

def test_unknown_amex_project_is_reported_once_per_value():
    # program_and_event returns "AMEXNewSG" → payload["booking_project_codes"]["unknown_amex"] == ["AMEXNewSG"]
    # non-AMEX codes ("mastercardAsia") are not reported

def test_centurion_only_venue_gets_no_platinum_slot_fetch(monkeypatch):
    # fetch_live_availability called only with platinum-active venues
```

- [ ] **Step 2:** Run `reminders/.venv/bin/python -m pytest scripts/tests/test_table_for_two_data.py -q`. Expected: new tests FAIL.
- [ ] **Step 3:** Implement the wiring.
- [ ] **Step 4:** Run all suites in Global Constraints. Expected: PASS.
- [ ] **Step 5:** Commit `feat(tft): record card tiers on every venue`.

### Task 5: Alerts, parity, and Platinum-only consumers

**Files:**
- Modify: `scripts/source_change_alert.py` (`META_FIELD_LABELS` ~67)
- Modify: `scripts/check_roster_parity.py`
- Modify: `.github/workflows/refresh-table-for-two.yml` (parity step)
- Test: `scripts/tests/test_source_change_updates.py`, `scripts/tests/test_roster_parity.py`, `scripts/tests/test_tft_guide_catalog*.py` / slot-snapshot test (whichever exists, otherwise add `scripts/tests/test_tft_tier_exclusion.py`)

**Interfaces:**
- `META_FIELD_LABELS` adds:
  - `"booking_project_codes.unknown_amex": "Unknown Amex booking projects"`
  - `"booking_project_sources.centurion.observation_status": "Centurion booking-project observation"`
  - `"booking_project_sources.centurion.observed_count": "Centurion booking-project venue count"`
  - `"booking_project_sources.centurion.observed_membership_sha256": "Centurion booking-project membership fingerprint"`
- `check_roster_parity.py` gains `--tier {platinum,centurion}` (default platinum). Centurion uses `booking_project_statuses.centurion` and `/projects/AMEXCentSG/restaurants`. Venues with `tier_membership.centurion == "linked_only"` are excused from "published as active but not listed". The workflow runs parity once per tier.

- [ ] **Step 1: Write the failing tests**

```python
def test_unknown_amex_project_raises_one_signal_then_none():
    # old meta unknown_amex [] → new ["AMEXNewSG"] → one change labelled "Unknown Amex booking projects"
    # same → same: no change

def test_centurion_parity_excuses_linked_only_and_flags_missing():
    # JAAN listed in AMEXCentSG and published active → OK
    # Zui Yu Xuan linked_only, not listed → OK
    # Isabel listed but absent from roster → fault "listed in AMEXCentSG but absent from the roster"

def test_centurion_only_venues_stay_out_of_guide_catalog_and_slot_snapshot():
    # payload with JAAN (booking_project_status not_listed, tiers ["centurion"])
    # build_tft_guide_catalog output venue ids exclude tft-jaan-*; build_tft_slot_snapshot venues exclude it
```

- [ ] **Step 2:** Run the three files. Expected: new tests FAIL. The exclusion test may already pass. If it does, keep it as a regression pin and note that in the commit.
- [ ] **Step 3:** Implement the labels, `--tier`, and the workflow step (`python3 scripts/check_roster_parity.py --tier platinum && python3 scripts/check_roster_parity.py --tier centurion`).
- [ ] **Step 4:** Run all suites. Expected: PASS.
- [ ] **Step 5:** Commit `feat(tft): alert on new Amex projects and check parity per tier`.

### Task 6: Site tier badges and filter

**Files:**
- Modify: `web/index.html` (TFT filter toolbar, next to `tft-category-filter`)
- Modify: `web/app.js` (`tableForTwoVenues` ~5353, the TFT filter function next to `tableForTwoCategoryFilter`, the venue card and focus-card renderers, menu link selection)
- Test: add `scripts/tests/tft-tier-filter.test.js`, following the existing JS test pattern in `scripts/tests/*.js`

**Interfaces:**
- `tableForTwoVenues()` returns records with a non-empty `tiers`. When a record has no `tiers` field, fall back to `booking_project_status !== "not_listed"`.
- `<select id="tft-tier-filter">` with options `""` (All cards), `platinum` (Platinum), `centurion` (Centurion). It is hidden when no venue has `tiers`. Reset clears it.
- Card and focus card show a tier badge per entry in `tiers` ("Platinum", "Centurion").
- Menu link order: when the filter is set, use `menu_pdfs[filter]` first. Otherwise use the existing order.
- For a venue without `platinum` in `tiers`, the availability line reads `Centurion slots are not tracked yet.` in place of the not-in-project text.

- [ ] **Step 1: Write the failing test** that loads the functions under test the way existing JS tests do and asserts:
  - All shows JAAN and a Platinum-only venue.
  - `platinum` hides JAAN.
  - `centurion` shows JAAN and hides the Platinum-only venue.
  - A payload without `tiers` shows every non-`not_listed` venue, and the filter reports hidden.
  - The centurion filter picks `menu_pdfs.centurion.url`.
- [ ] **Step 2:** Run `node scripts/tests/tft-tier-filter.test.js`. Expected: FAIL.
- [ ] **Step 3:** Implement. Run `impeccable`, then `antislop` + `antislop-human`, on the changed UI, following `DESIGN.md`. Use `antislop-copywriting` for the badge, option and empty-state copy.
- [ ] **Step 4:** Run all JS tests and `node scripts/verify-project.mjs --static-only`. Expected: PASS.
- [ ] **Step 5:** Commit `feat(site): show and filter Table for Two venues by card tier`.

### Task 7: Live verification and PR

- [ ] **Step 1:** Copy `data/table-for-two.json` to the scratchpad. Run the real refresh locally twice: `python3 scripts/scrape_table_for_two.py` (or the workflow's exact roster command). Assert against the output:
  - All 9 Centurion-only venues have `tiers == ["centurion"]`.
  - Zui Yu Xuan has `["platinum", "centurion"]` and `tier_membership.centurion == "linked_only"`.
  - Madame Fan and the 30 shared venues have both tiers.
  - `booking_project_codes.unknown_amex == []`.
  - `python3 scripts/check_roster_parity.py --tier centurion` exits 0.
- [ ] **Step 2:** Serve the site locally with the generated data. In a browser, confirm the Centurion filter shows JAAN, and the Platinum filter does not. Take screenshots for the PR.
- [ ] **Step 3:** Restore `data/` with `git checkout -- data`. Confirm `git status` shows no data files.
- [ ] **Step 4:** Push `feat/tft-card-tiers` and open the PR with the `pr` skill, including the before/after screenshots. After merge (owner confirms), dispatch `Refresh Table for Two` twice and re-check acceptance items 1, 2, 3 and 7 on the live site.
