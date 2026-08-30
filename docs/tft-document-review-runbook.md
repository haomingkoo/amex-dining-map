# Table for Two official-document review runbook

The scheduled refresh hashes the live Amex T&C and FAQ PDFs but never promotes
an unknown version automatically. The Telegram guide keeps answering from the
last page-reviewed version and labels it as retained while the new file is in
review.

## Diagnose the current state

Run the same verifier used by the refresh workflow:

```bash
PYTHONPATH=. uv run --python 3.12 \
  --with-requirements reminders/requirements-dev.txt \
  python scripts/verify_tft_official_documents.py
```

Inspect only the bounded document state:

```bash
jq '{source_documents, document_reviews}' data/table-for-two.json
```

- `approved`: the observed and reviewed hashes match.
- `review_required`: `observed_sha256` is new; `approved_sha256` remains public.
- `pending_events`: an apply reached durable data but not the update ledger.
  Re-run the exact apply command. Do not delete this field by hand.
- `approved review identity mismatch`: the manifest or its recorded digest was
  edited after review.
- `retained approved evidence is missing`: restore the exact hash-addressed PDF
  and manifest before refreshing or publishing anything.

## Review one successor

Work on only `tft-terms` or `tft-faq`. The scraper archives the exact bytes that
produced the observed hash at:

```text
data/reviews/official-document-pdfs/<document-id>/<observed-sha256>.pdf
```

Review that retained file. Do not refetch the URL and substitute newer bytes.

Create a schema-v2 manifest at:

```text
data/reviews/official-documents/<document-id>/<observed-sha256>.json
```

Bind every reviewed clause to its page with `page_text_sha256` and
`evidence_text_sha256`. Set `lineage.previous_observed_sha256` to the current
approved hash. Never paste extracted page text into the manifest.

Create the complete predecessor-to-successor clause accounting at:

```text
data/reviews/official-document-transitions/<document-id>/<approved-sha256>-to-<observed-sha256>.json
```

Every predecessor and successor clause must be listed exactly once as
unchanged, added, removed, substantively modified, or layout-only. Layout-only
changes advance the reviewed version without publishing a user-facing change.

## Apply, recover, and verify

```bash
PYTHONPATH=. uv run --python 3.12 \
  --with-requirements reminders/requirements-dev.txt \
  python scripts/apply_tft_document_review.py \
  --document <document-id> \
  --manifest data/reviews/official-documents/<document-id>/<observed-sha256>.json \
  --transition data/reviews/official-document-transitions/<document-id>/<approved-sha256>-to-<observed-sha256>.json
```

The command requires the canonical hash-addressed manifest and transition paths,
verifies both exact PDFs, page evidence, lineage, complete clause
accounting, and source identity. It atomically advances the approved document,
appends source-scoped before-and-after owner events, then clears
`pending_events`, and rebuilds the bundled Telegram catalogue. An exact rerun
repairs an interrupted ledger append without duplicating an event. A different
successor is rejected until the pending event is reconciled.

Verify the applied state, cached successor, transition, and durable owner event:

```bash
PYTHONPATH=. uv run --python 3.12 \
  --with-requirements reminders/requirements-dev.txt \
  python scripts/apply_tft_document_review.py \
  --document <document-id> \
  --manifest data/reviews/official-documents/<document-id>/<observed-sha256>.json \
  --transition data/reviews/official-document-transitions/<document-id>/<approved-sha256>-to-<observed-sha256>.json \
  --check
```

Then rebuild the retained guide projection and run the operational gates:

```bash
PYTHONPATH=. uv run --python 3.12 \
  --with-requirements reminders/requirements-dev.txt \
  python scripts/build_tft_guide_catalog.py
node scripts/verify-telegram-guide.mjs
node scripts/verify-telegram-change-dispatch.mjs
node scripts/verify-project.mjs
git diff --check
```

If the live hash changes again during review, stop and make a new successor
manifest and transition from the still-approved version. Do not relabel the
superseded candidate as reviewed.
