# Table for Two Reminders Service

FastAPI + SQLite service that powers email reminder signups for the Table for Two map.
People subscribe via a native form on `amex-explorer.kooexperience.com`, confirm by email
(double opt-in), and the existing GitHub Action alert job pulls active subscribers from
here and emails them when availability matches.

Mirrors the `trader-koo` pattern. Email is sent via the Resend HTTP API (no SDK).

## Local development

```bash
cd reminders
python3.11 -m venv .venv          # 3.11–3.13 locally; Railway runs 3.12
.venv/bin/python -m pip install -r requirements-dev.txt
cp .env.example .env              # fill in values
.venv/bin/python -m pytest -v     # run tests
.venv/bin/uvicorn app.main:app --reload   # run locally
```

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET  | `/healthz` | Liveness check |
| POST | `/api/subscribe` | Create a pending subscription, send confirm email |
| GET  | `/api/confirm?token=` | Render the confirmation action |
| POST | `/api/confirm?token=` | Activate new or changed settings |
| GET  | `/api/unsubscribe?token=` | Render the unsubscribe action |
| POST | `/api/unsubscribe?token=` | Unsubscribe, including email-provider one-click requests |
| GET/POST | `/api/manage?token=` | View or update reminder settings with the dedicated manage token |
| GET  | `/api/subscribers` | Active subscribers export (Bearer `ALERT_EXPORT_TOKEN`) |
| POST | `/api/owner-alerts/events` | Reviewed update ingestion (Bearer `OWNER_ALERT_INGEST_TOKEN`) |
| POST | `/api/telegram/guide/webhook` | Authenticated private-chat Telegram guide ingress |

## Deployment (Railway)

Service root = `reminders/`. Mount a persistent volume at `/data` and set `DB_PATH=/data/reminders.db`.
See `.env.example` for the full env var list.

For a CLI deployment from the repository root, preserve that service root:

```bash
railway up reminders --path-as-root --detach --service amex-reminders --json
```

Capture the returned deployment ID, poll `railway deployment list --json` until
that exact deployment is `SUCCESS`, then require `/healthz` to return `200` with
the same `deployment_id`. A health response from the previous instance is not
acceptance. Record `revision` (Railway Git SHA when supplied, otherwise the
deterministic guide/app bundle fingerprint) and verify
`catalog_ok`, `catalog_sha256`, schema, roster/menu check times, release snapshot
time, and exact `AMEXPlatSG` release and slot provenance. These fields contain no
credentials or subscriber data and identify the source bundle actually serving.
Finally probe the intended disabled/enabled feature state.

`feature_state.email_delivery_configured`, `owner_alerts_enabled`,
`telegram_guide_enabled`, and `telegram_reminders_enabled` are non-secret
troubleshooting fields. A disabled optional endpoint must return `503`; that is
different from a stale deployment or a missing route.

Pages production acceptance is separate: wait for the exact `Deploy Pages` run
for the intended commit, open the deployed TFT route at 390x844 and 320x740,
verify its revision-bound assets and source timestamps, and check console and
failed-resource logs. If acceptance fails, revert the narrow change, push, wait
for that exact replacement Pages run, and repeat the browser checks. Do not call
a successful workflow run browser acceptance.

Security controls include explicit double opt-in actions, separate manage and
unsubscribe capabilities, atomic keyed-hash IP/email/global quotas, 16 KiB API
body limits, owner-only SQLite permissions, bounded subscriber and abuse-metadata
retention, restricted CORS,
no-store token pages, and browser security headers. Set a strong independent
`ABUSE_HASH_SALT` in production and keep every token in deployment secrets.

## Private owner alerts

The source refresh workflows replay a bounded recent window of
`status: published` entries from `data/updates.json` to the authenticated
Railway ingestion endpoint. Backend idempotency makes confirmed replays cheap,
while `OWNER_ALERT_NOT_BEFORE` prevents enabling the integration from flooding
the channel with historical events and still permits a later-reviewed event.
Each event uses its own HTTP request so one slow Telegram call cannot hold a
batch open. Railway is
the only component that holds the Telegram bot token and the exact private
channel ID. The request body cannot select a destination. Confirmed deliveries
are durably deduplicated in SQLite; review-required entries are withheld without
consuming their event ID.

The public update ledger separates a semantic transition from its occurrence.
A workflow retry of the latest A→B transition is deduplicated, while a later
A→B after B→A receives a new occurrence ID and can notify again. Stable stream
keys are hashes; raw source entity keys are not published. Ledger updates use
an exclusive process lock and fsync-backed atomic replacement. Compact hashed
occurrence state survives display-ledger retention and migrates legacy events.
Review-required and
published-but-undelivered events are protected from the resolved-event cap;
terminal ingestion outcomes are written back as non-secret states by a second,
conflict-failing workflow commit and are not automatically posted again.

Owner Telegram delivery is intentionally narrower than the public audit ledger.
Restaurant additions/removals, menu changes, meaningful detail corrections,
persistent source failures, and review-required source changes are actionable.
Routine stale/recovered/coverage flapping remains recorded in source health but
is marked `withheld` instead of producing repeated owner messages.

Telegram has no idempotency key. A timeout can happen after Telegram accepted a
message but before the service received proof, so ambiguous outcomes are stored
as `unknown` and are not retried automatically. Definite retryable failures are
stored as `retry`; confirmed deliveries replay without another API call. A
terminal `unknown` or `dead` delivery is surfaced as a GitHub Actions warning
without leaving every source refresh permanently failed. It stays quarantined
until an operator resolves it; it is never blindly resent.

Keep `OWNER_ALERTS_ENABLED=false` until the BotFather bot, private owner channel,
numeric channel ID, activation cutoff, and independent ingestion token are configured. The GitHub
refresh jobs also need `OWNER_ALERT_INGEST_URL` and `OWNER_ALERT_INGEST_TOKEN`;
when both are absent, dispatch safely skips.

Generate the ingestion token with `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'`.
Immediately before enabling, set `OWNER_ALERT_NOT_BEFORE` to the current UTC
instant; do not copy an old fixed date, because that could release recent
historical ledger events on the first run.

Create the owner-alert bot separately in BotFather, add it to a private channel
with post-only permission, and obtain the numeric `-100...` channel ID from a
trusted Telegram update/API inspection. Verify the ID against a test channel
message before enabling. Enable in this order: configure the bot, channel,
cutoff, and ingestion token; set `OWNER_ALERTS_ENABLED=true`; deploy; verify
`/healthz` reports `owner_alerts_enabled=true`; send one reviewed test event;
then verify its single `sent` row. While disabled, probe only for the expected
`503`; authenticated ingestion acceptance is possible only after the enabled
deployment. On `unknown` or `dead`, inspect aggregate owner delivery state and
the Railway `owner_alert_delivery` event; never blindly replay an ambiguous
delivery. Rotate by disabling, replacing the bot token and ingestion token
independently, redeploying, testing, then enabling. Roll back by setting
`OWNER_ALERTS_ENABLED=false`, deploying, and removing both
`OWNER_ALERT_INGEST_URL` and `OWNER_ALERT_INGEST_TOKEN` from GitHub Actions so
refresh workflows safely skip dispatch. Public guide and email reminders remain
independent.

## Public Telegram guide

The guide bot is a separate, disabled-by-default Telegram identity. Its current
surface is private chats only: `/start`, `/help`, `/about`, `/venues`,
`/venue <exact venue>`, exact venue/menu lookup,
`/release <venue> [lunch|dinner]` observed release-pattern answers, and
strict `/slots venue | party | meal | date/range/weekend | preferred time`
queries. `/terms <topic>` and `/faq <topic>` return page-aware reviewed official
document summaries. Bounded common questions such as “What is Table for Two?”,
“Where is VUE?”, and “Does VUE have a menu?” route to the same deterministic,
cited interfaces; typos and ambiguous venues are never guessed.
It uses a generated source catalogue with official Amex menu links and
never invokes an LLM, follows a user URL, joins groups, or reads owner-channel
configuration. The catalogue is bundled with the Railway revision; the TFT
refresh rebuilds it, but a normal reviewed Railway deployment is required to
serve that newer revision. Substantive venue and menu answers expose the source check time and warn
when the bundled roster or menu index is stale. Release answers expose exact
observation counts, median and range, tracker confidence, latest detection, and
history freshness. They explicitly describe scheduled AMEXPlatSG cache
detection—not an official release policy or current availability.

The document reader is deterministic. Runtime code never downloads or executes
a PDF and does not use an LLM, embeddings, or a vector database. The TFT refresh
projects only hash-bound review records from
`data/reviews/official-documents/`; each fixed summary is tied to one official
Amex URL, raw PDF hash, reviewed page, page-text hash, capture time, and version.
A new source hash is archived by hash but cannot replace the approved review.
The Railway catalogue retains the last reviewed clauses and the bot warns that
a newer observed version awaits review. Extracted full-page text is not
committed or returned to users.
Eligibility answers describe the official document's card scope but never say
that a particular user qualifies. Ambiguous, merchant-specific, or legal
interpretation requests fail closed.

The current T&C and two-page FAQ are page-reviewed baselines. Their exact bytes
are retained by hash. Earlier FAQ bytes were not available when the baseline
was established, so no retroactive clause-level before-and-after claim is made.
Future successors require complete predecessor-to-successor clause accounting
through the TFT official-document review runbook. This is independent of the
reviewed roster, which currently has 21 active and two historical venues.

Public slot lookup reads one bounded Railway snapshot from `/api/tft/slots`.
The single-replica reminders service checks the AMEXPlatSG project immediately
after startup and then ten minutes after each completed check. It fetches project
membership once, checks only approved active catalogue venues with bounded
concurrency, atomically replaces `/data/tft-live-slots.json`, and retains each
venue's last good observation when an individual request fails. A missing
project member is explicit `not_in_project` evidence; it is not a claim that the
physical restaurant closed. The endpoint rejects malformed, oversized, or
wrong-project snapshots, returns `Cache-Control: no-store`, and is compressed.
Matching uses each venue's own `checked_at`, never the top-level generation time.
Anything older than 30 minutes is labelled stale and cannot be described as
current availability. An empty fresh match means only that no matching slot was
observed in the cached check—not that the Amex Experiences App is sold out.

The committed `data/table-for-two-slots.json` and manual GitHub workflow remain
rollback and history inputs during the live-path observation period; they are no
longer the browser's primary freshness path. Enable Railway with
`TFT_LIVE_REFRESH_ENABLED=true` and
`TFT_LIVE_SINGLE_REPLICA_CONFIRMED=true`. The interval defaults to 600 seconds;
keep the snapshot beside `DB_PATH` on the mounted `/data` volume.

The guide also contains a disabled-by-default, one-shot reminder lifecycle:
`/remind`, `/reminders`, `/cancel [reminder ID]`, and `/delete_me`. Setup collects
one exact venue, party size, lunch or dinner, and an absolute SGT date, range,
or up to ten specific dates. A confirmed reminder sends at most one notification
after the first fresh cached AMEXPlatSG match, then closes. It is separate from
email subscribers. Telegram reminder dispatch still consumes the committed
projection until that delivery path is migrated and separately accepted; do not
claim it has the same freshness as the public Railway endpoint yet.

Spam controls are intentionally quiet: Telegram's webhook secret is checked
before JSON parsing, update IDs are durably deduplicated, and guide-only
identities are stored as keyed hashes. A reminder draft stores no raw Telegram
identity. After explicit confirmation, proactive delivery necessarily stores
the private chat ID in SQLite; it is never logged or exported and is erased when
the reminder is cancelled or reaches a terminal delivery state. Per-user/global
minute and daily quotas are
consumed atomically. Groups, bots, unsupported updates, and rate-limited bursts
return success without sending a reply, preventing warning-message
amplification. Replay metadata expires after seven days and quota metadata
after 24 hours; message text and usernames are not stored.

Before enabling, create a separate BotFather bot and generate two independent
43+ character values for `TELEGRAM_GUIDE_WEBHOOK_SECRET` and
`TELEGRAM_IDENTITY_HASH_SALT`. To enable reminders, also generate an independent
`TELEGRAM_REMINDER_DISPATCH_TOKEN`, add the same dispatch token and
`REMINDERS_API_BASE` as GitHub Actions secrets, and set
`TELEGRAM_REMINDERS_ENABLED=true` on Railway. After live acceptance, set the
GitHub Actions repository variable `TELEGRAM_REMINDERS_EXPECTED_ENABLED=true`;
then a missing API base or dispatch token fails Pages instead of silently
skipping. Before activation, missing secrets produce a visible workflow warning.
Keep Railway on one persistent SQLite-backed
replica. Register `/api/telegram/guide/webhook` with Telegram using the secret
token, `allowed_updates=["message"]`, and `drop_pending_updates=true` only for
the first activation. Real private-chat, replay, group-ignore, and rate-limit
acceptance remains mandatory before calling the bot live. Enable in this order:
configure the separate guide bot and independent secrets; set
`TELEGRAM_GUIDE_ENABLED=true`; deploy; verify `/healthz` reports
`telegram_guide_enabled=true`; then call `setWebhook` and run live chat
acceptance. Enable reminders only after guide acceptance: configure the dispatch
token on Railway and GitHub, set `TELEGRAM_REMINDERS_ENABLED=true`, deploy,
verify health, create/list/cancel a real test reminder, and only then set
`TELEGRAM_REMINDERS_EXPECTED_ENABLED=true` in GitHub Actions.

Set the non-secret GitHub Actions repository variable
`TELEGRAM_GUIDE_BOT_USERNAME` to the guide bot's public username only after the
guide passes live acceptance. Pages validates the username and then exposes
venue-specific `Ask on Telegram` and `Set Telegram reminder` actions. The bot
accepts only bounded `venue_<venue-id>` and `remind_<venue-id>` start payloads;
unknown payloads fall back to reviewed help and cannot inject a URL or command.

Use the secret-safe readiness checker from the repository root. It reads values
from the environment, prints no identifiers, Telegram response bodies, or
secret values, and never sends a message:

```bash
railway run --service amex-reminders python3 scripts/check_telegram_readiness.py --phase config
railway run --service amex-reminders python3 scripts/check_telegram_readiness.py --phase identities
railway run --service amex-reminders python3 scripts/check_telegram_readiness.py --phase owner
railway run --service amex-reminders python3 scripts/check_telegram_readiness.py --phase guide
railway run --service amex-reminders python3 scripts/check_telegram_readiness.py --phase reminders
```

Run `config` and `identities` before activation. Run the other read-only phases
after each corresponding deployment; they verify health, exact bot/channel
identity, least channel privilege, webhook separation, public username parity,
and wrong-credential rejection. A successful check prints only
`TELEGRAM READINESS OK phase=<phase>`. Real message delivery still requires the
explicit G9/G10 acceptance procedure; the readiness checker cannot prove that a
human saw the intended message.

### Guide bot activation and operations

Read secrets into an ephemeral shell without echoing or command-line arguments,
then register the webhook. `drop_pending_updates=true` is for first activation
or an intentional queue reset only. Unset all temporary values immediately.

```bash
read -rs TELEGRAM_GUIDE_BOT_TOKEN; export TELEGRAM_GUIDE_BOT_TOKEN
read -rs TELEGRAM_GUIDE_WEBHOOK_SECRET; export TELEGRAM_GUIDE_WEBHOOK_SECRET
export GUIDE_WEBHOOK_URL='https://<service-host>/api/telegram/guide/webhook'

python3 - <<'PY'
import json
import os
import urllib.parse
import urllib.request

base = f"https://api.telegram.org/bot{os.environ['TELEGRAM_GUIDE_BOT_TOKEN']}"
payload = urllib.parse.urlencode({
    "url": os.environ["GUIDE_WEBHOOK_URL"],
    "secret_token": os.environ["TELEGRAM_GUIDE_WEBHOOK_SECRET"],
    "allowed_updates": json.dumps(["message"]),
    "drop_pending_updates": "true",
}).encode()
with urllib.request.urlopen(base + "/setWebhook", data=payload, timeout=30) as response:
    assert json.load(response).get("ok") is True
with urllib.request.urlopen(base + "/getWebhookInfo", timeout=30) as response:
    info = json.load(response)
    assert info.get("ok") is True
    print(json.dumps(info["result"], indent=2))
PY

unset TELEGRAM_GUIDE_BOT_TOKEN TELEGRAM_GUIDE_WEBHOOK_SECRET GUIDE_WEBHOOK_URL
```

Monitor Railway health and error rates, Telegram `pending_update_count` and
`last_error_message`, SQLite volume use, and the age/manual-review fields in the
bundled TFT catalogue. A healthy HTTP endpoint is not proof of a working bot;
send `/venues`, both VUE menu variants, `/release VUE dinner`, the exact `/slots`
and conversational weekend queries, then create/list/cancel a test reminder and
send a group message
from real Telegram clients after each activation.

Treat a roster check, menu-index check, or release snapshot older than 36 hours
as actionable catalogue staleness. Confirm the corresponding scheduled workflow
ran, inspect its review queue and source response, rerun the exact refresh when
safe, then deploy the resulting reviewed Railway bundle. Slot projections use a
stricter per-venue 30-minute threshold: inspect the half-hour Table for Two
availability workflow and the exact successful Pages deployment before calling
any slot current.

For ordinary token rotation, first set
`TELEGRAM_REMINDERS_EXPECTED_ENABLED=false` and pause or remove the GitHub
dispatch credentials. Then set `TELEGRAM_REMINDERS_ENABLED=false`, deploy, set
`TELEGRAM_GUIDE_ENABLED=false`, deploy, and delete the webhook with
`drop_pending_updates=false`. Rotate the BotFather token, webhook secret, and
dispatch token, configure them, re-enable the guide, deploy, register the new
webhook without dropping pending updates, repeat guide acceptance, then enable
and accept reminders before restoring the GitHub expected-enabled variable.
Rotate owner-alert and guide-bot credentials separately.
Identity-salt migration is a separate operation, not routine token rotation.
Before rotating `TELEGRAM_IDENTITY_HASH_SALT`, disable reminder creation and
dispatch and verify SQLite has zero reminder rows in `active`, `claimed`, or
`sending` state. Drain or cancel them first; startup deliberately fails if a new
salt would strand live reminders. The bot token, webhook secret, and dispatch
token can be rotated without changing reminder ownership.

```bash
read -rs TELEGRAM_GUIDE_BOT_TOKEN; export TELEGRAM_GUIDE_BOT_TOKEN
python3 - <<'PY'
import json
import os
import urllib.parse
import urllib.request

url = f"https://api.telegram.org/bot{os.environ['TELEGRAM_GUIDE_BOT_TOKEN']}/deleteWebhook"
payload = urllib.parse.urlencode({"drop_pending_updates": "false"}).encode()
with urllib.request.urlopen(url, data=payload, timeout=30) as response:
    assert json.load(response).get("ok") is True
PY
unset TELEGRAM_GUIDE_BOT_TOKEN
```

Rollback in this safe order: set the GitHub expected-enabled variable false and
pause or remove reminder dispatch credentials; disable reminders and deploy;
disable the guide and deploy; then delete its webhook without dropping pending
updates. Owner alerts and email reminders remain independent. If delivery is ambiguous, inspect the
stored terminal state and Telegram webhook information instead of resending.
Restore only from the persistent SQLite volume or a verified backup, never from
chat logs. The service stores no message text or usernames. Reminder delivery is
at-most-once across ambiguous Telegram failures: a timeout, malformed response,
stale in-flight claim, or 5xx becomes terminal `unknown` and is not blindly
resent. The post-Pages workflow calls the authenticated Railway dispatch endpoint
with the exact deployed snapshot generation; a mismatch fails closed.
Each request claims at most two matched reminders, moves each from `claimed` to
`sending` only immediately before the provider call, and returns a random run ID
plus aggregate counts. The workflow performs at most 25 bounded calls while
`more=true`. A stale never-attempted `claimed` row safely returns to active;
only a stale `sending` row becomes terminal `unknown`.
The service transactionally caps the complete `active`/`claimed`/`sending`
population at 1,000, so every live reminder remains inside one bounded scan and
newer matches cannot be stranded behind an unbounded nonmatching queue.

## Operational logs

Uvicorn startup and application lifecycle records are emitted to stdout, so
Railway does not classify normal `INFO` startup lines as errors. Application
events are structured fields: filter by `event`, `status`, `path`, or
`request_id` rather than searching message bodies.

Daily source-writing GitHub workflows share `source-ledger-refresh`.
`commit_and_push.sh` reconciles pushes after concurrent writers update `main`,
but GitHub scheduling is best-effort and is not the live public freshness
boundary. The source-health monitor also checks the Railway TFT contract twice
per hour and fails visibly if the snapshot is older than 30 minutes, incomplete,
partial, or inconsistent with its generated time. `/healthz` reports `ok=false`
and `tft_live.status=stale` when an enabled live snapshot crosses that boundary.
For a TFT availability incident, inspect Railway `/healthz` field
`tft_live`, then `/api/tft/slots`, then the bounded `tft_live_refresh` log. Use
the manual `Table for Two Alerts` workflow only as rollback/history evidence.

Start with the narrowest public signal before opening provider logs:

| Symptom | First check | Correlation evidence |
|---|---|---|
| Map watermark or blank tiles | Open the actual tile response and inspect its image content and response headers | Pages run and deployed app revision |
| Old, failed, or review-held programme data | Open **Updates & source health**, then the named refresh workflow | Source ID, last attempt, last success, and workflow run |
| Site still shows an older build | Compare the Pages run commit with the deployed asset revision | Git commit and Pages deployment run |
| Reminder API request fails | Capture the response `X-Request-ID` and status | Matching Railway `http_request` JSON event |
| TFT availability is old | Check `/healthz` `tft_live.age_seconds`, then `/api/tft/slots` | Railway deployment ID, generated time, refresh status, and aggregate counts |
| Email alert does not arrive | Check the Table for Two Alerts workflow before the provider dashboard | Workflow run, bounded provider error code, and sent-key receipt |
| Telegram action does not work | Run the readiness checker for the affected phase, then inspect `/healthz` | Readiness phase, feature flag, UTC window, and bounded delivery outcome |

The source-health artifact is public operational metadata, not a raw error log.
It contains only bounded states and counts. Raw exception text stays in GitHub
Actions, while the public surface records values such as
`workflow_step_failed`, `review_required`, `stale`, or `partial`. Never paste
tokens, chat IDs, subscriber rows, Telegram updates, or provider response bodies
into an issue when troubleshooting.

Railway emits one JSON line per HTTP request with a generated request ID, method,
path, status, and latency. Subscription events record only a short keyed recipient
fingerprint and the state transition; emails, names, tokens, query strings,
Telegram message text, and credentials are never logged. Use the `X-Request-ID`
response header to correlate a direct browser or API failure with Railway logs.
Confirmation-provider failures return a generic `502` and emit
`confirmation_email_failed` with only a bounded `error_code` such as
`provider_http_429`, `provider_unreachable`, or `unexpected_failure`. Provider
response bodies are discarded because they may echo recipient or management data.

Guide and owner delivery attempts also emit privacy-safe outcome events with
state, bounded error code, command class where applicable, attempt, and latency.
HTTP 200 can still contain a terminal Telegram outcome, so alert on `unknown`,
`dead`, and `catalog_invalid`, and inspect their SQLite rows before intervention.
Reminder dispatch emits `telegram_reminder_run` aggregate counts and
`telegram_reminder_delivery` terminal outcomes. These logs never include chat
IDs, principal hashes, reminder IDs, venue/date criteria, message text, provider
responses, or tokens. Telegram owner and guide calls have no shared request ID
with Telegram; correlate those narrowly by UTC time, endpoint path, outcome
state, and bounded error code. Correlate reminder dispatch with its random run
ID and the matching successful Pages run and its `generated_at`; `409` means the
public projection did not match the deployed generation, while `503` means the
feature or fixed source was unavailable. Do not manually resend `unknown` rows.

For aggregate diagnosis in an authorized Railway shell, query counts and oldest
state timestamps only—never dump rows. Owner delivery rows include a configured
destination required for durable deduplication and are not covered by the
subscriber retention statement above:

```sql
SELECT state, COUNT(*) AS count, MIN(updated_ts) AS oldest
FROM telegram_reminders GROUP BY state ORDER BY state;
SELECT state, COUNT(*) AS count, MIN(updated_ts) AS oldest
FROM telegram_reminder_deliveries GROUP BY state ORDER BY state;
SELECT state, COUNT(*) AS count, MIN(updated_ts) AS oldest
FROM owner_alert_deliveries GROUP BY state ORDER BY state;
```

Compare `claimed` older than five minutes with the next run's
`reconciled_claimed_count`; it should return to active. A nonzero
`reconciled_unknown_count`, `receipt_conflict`, or `store_unavailable` needs
operator review, not manual resend. The random run ID in the workflow summary,
endpoint response, delivery events, and aggregate run event is the correlation
key; it is not a user or reminder identifier.

For email reminders, monitor the Table for Two Alerts workflow conclusion,
Resend delivery/bounce events, the cached availability age, and the incremental
sent-key receipt file. A failed delivery step still commits refreshed availability
and then fails the job visibly. Rotate export/hash/Resend secrets one at a time:
pause the workflow, update Railway and GitHub copies where shared, probe export,
send one controlled test, then resume. Back up the SQLite volume before schema or
credential work, verify the copy opens and passes an integrity check, and test a
restore in a temporary service before relying on it. During an incident, disable
the affected surface first; do not delete the volume or sent receipts.
