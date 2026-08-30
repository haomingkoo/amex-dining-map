# Table for Two menu review runbook

The menu refresher is an inbox, not a publish boundary. New, changed, or
ambiguous PDFs stay quarantined until an exact manifest is applied. Every
successfully observed menu version is retained atomically by content hash under
`data/reviews/tft-menu-pdfs/`; a later change at the same URL cannot replace the
bytes awaiting review. A rejection keeps the current published menu. An
approval uses the retained candidate and creates one reviewed before-and-after
owner event.

## Inspect the queue

```bash
python3 -c 'import json; p=json.load(open("data/table-for-two.json")); print(json.dumps(p["menu_source"]["review_queue"], indent=2))'
```

Use the `candidate_id` for one concrete `changed_or_new_venue_menu` or
`ambiguous_exact_match` item. `missing_venue_menu` and `observation_failed`
items cannot be approved or rejected by this command because they do not carry
reviewable PDF evidence.

## Prepare a decision

```bash
python3 scripts/prepare_tft_menu_review.py \
  --candidate-id CANDIDATE_ID \
  --decision rejected \
  --reviewed-by OWNER_NAME \
  --review-note "Why this exact candidate is not the active program menu." \
  --output data/reviews/tft-menus/DECISION.json
```

For an approval, use `--decision approved` and review the exact retained file at
`data/reviews/tft-menu-pdfs/<asset_sha256>.pdf`. The official Amex URL remains
the public citation, but do not re-download it as review evidence: upstream may
already serve a successor version. Do not edit the copied URL, hash, byte count,
venue, card, roster hash, or listing hash in the manifest.

## Apply and verify

Rejection:

```bash
python3 scripts/apply_tft_menu_review.py \
  --manifest data/reviews/tft-menus/DECISION.json
```

Approval:

```bash
python3 scripts/apply_tft_menu_review.py \
  --manifest data/reviews/tft-menus/DECISION.json
```

The command validates the whole queue snapshot, exact candidate identity,
roster, listing, Amex HTTPS URL, chronology, and—for approval—the PDF magic,
size, and SHA-256 from the retained content-addressed artifact. An explicit
`--pdf` remains available for recovery but must match the same hash and size.
Missing, oversized, tampered, or conflicting archive entries fail closed. The
archive is append-only: rejection retains the observed bytes as provenance.
It atomically records the decision and active menu first,
then reconciles the owner event and bot catalogue from that durable receipt.
An exact rerun repairs a missing event or stale catalogue without creating a
duplicate; a conflicting decision fails.

Verify a previously applied decision and all of its derived files with:

```bash
python3 scripts/apply_tft_menu_review.py \
  --manifest data/reviews/tft-menus/DECISION.json \
  --check
```

Run the normal gates before commit:

```bash
node scripts/verify-project.mjs
node scripts/verify-telegram-guide.mjs
node scripts/verify-telegram-change-dispatch.mjs
git diff --check
```

If a stale-snapshot, active-menu, roster, listing, URL, or hash check fails, do
not edit around it. Refresh the source, inspect the new candidate, and prepare a
new manifest.
