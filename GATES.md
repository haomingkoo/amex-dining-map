# Gates: TFT security, owner alerts, and self-help bot

OWNS: GATES.md, SECURITY_AUDIT.md, README.md, PRODUCT.md, reminders/**, scripts/**, web/**, data/**, .github/workflows/**

Scope: Audit and harden Amex Explorer, verify the live mobile TFT journey, and deliver separately secured owner-channel alerts and a source-grounded Telegram self-help bot.

Tracker: parent #34; vertical slices #35 through #42.

- [x] G0: the completion ledger has valid, reviewable acceptance oracles
  CHECK: node /Users/koohaoming/.codex/skills/unlazy/scripts/gate-lint.mjs GATES.md
  EXPECT: LINT OK
  EVIDENCE: 2026-08-30 gate-lint returned LINT OK; only G9 and G10 are intentionally manual production gates.

- [x] G1: the security audit covers the static site, reminder API, automation workflows, dependencies, live headers, secrets, abuse paths, and Telegram threat model with no unresolved critical finding
  CHECK: node scripts/verify-security-audit.mjs
  EXPECT: security audit verification passed
  EVIDENCE: 2026-08-30 verifier passed; Pages run 33283464189 succeeded; Railway health, CORS, headers, and disabled OpenAPI were production-probed; Dependabot reported no open alerts.

- [ ] G2: the deployed mobile Table for Two journey exposes venue details, current menu and official-source links, T&Cs context, release-pattern qualifications, and working reminder signup without browser-visible failures
  CHECK: node scripts/verify-tft-browser-evidence.mjs
  EXPECT: TFT browser evidence verification passed
  EVIDENCE: 2026-08-30 production at 390x844 preserved the first-visit VUE deep link, selected VUE, showed current AMEXPlatSG slots plus menu/release timestamps and review caveats, submitted the email reminder UI with API 200, and had no app exception or horizontal overflow. Two handled DiningCity 404 probes remain for stale missing-project venues; the executable evidence verifier is still pending, so this gate stays open.

- [x] G3: owner updates are formatted as concise before-and-after alerts and can only be delivered to the configured private Telegram channel
  CHECK: node scripts/verify-telegram-owner-alerts.mjs
  EXPECT: Telegram owner alert verification passed
  EVIDENCE: 2026-08-30 verifier passed. Tests prove plain-text before/after rendering, config-only destination selection, published-only delivery, replay deduplication, digest conflict rejection, and no blind retry after ambiguous transport outcomes. Real-channel delivery remains G9.

- [ ] G4: menu, venue, T&C, source, and release-pattern changes can trigger owner-channel alerts without leaking bot tokens, subscriber records, or internal diagnostics
  CHECK: node scripts/verify-telegram-change-dispatch.mjs
  EXPECT: Telegram change dispatch verification passed
  EVIDENCE: 2026-08-30 verifier passes for reviewed-update dispatch. Stream-scoped occurrence IDs deduplicate direct retries but preserve A→B→A→B recurrences, including after retention and legacy migration. Atomic locked ledger writes, protected review/undelivered retention, persisted terminal delivery states, and no terminal replay pass regressions. Clause-level T&C, unmatched-menu, and per-event quarantine coverage remain tracked by #51, so this gate stays open.

- [ ] G5: the Telegram self-help bot answers TFT program, venue, menu, T&C, and release-pattern questions and can find currently observed slots from curated current sources with citations and freshness dates
  CHECK: node scripts/verify-telegram-guide.mjs
  EXPECT: Telegram guide verification passed
  EVIDENCE: venue/menu and observed release-pattern tracers pass locally. `/release VUE dinner` reports the exact count, median/range, confidence, supported SGT detection bucket, latest observation, snapshot age, official source, and venue handoff while denying official-policy/current-availability status. T&C and observed-slot slices remain pending, so this gate stays open.

- [ ] G6: unsupported, stale, ambiguous, adversarial, and prompt-injection questions fail safely without inventing eligibility, availability, booking rules, or menu facts
  CHECK: node scripts/verify-telegram-safety.mjs
  EXPECT: Telegram safety verification passed
  EVIDENCE: pending

- [ ] G7: Telegram webhook authentication, owner allowlists, public-user rate limits, payload limits, output escaping, reminder consent, retention limits, and secret isolation pass security regression tests
  CHECK: node scripts/verify-telegram-security.mjs
  EXPECT: Telegram security verification passed
  EVIDENCE: 2026-08-30 guide webhook authentication, replay, private-chat, rate, payload, retention, escaping, and secret-isolation checks pass. Telegram reminder consent and privileged interactive controls remain pending.

- [ ] G7A: a Telegram user can create, inspect, and cancel a TFT slot reminder with an explicit venue, party size, meal, and date range
  CHECK: node scripts/verify-telegram-reminders.mjs
  EXPECT: Telegram reminder verification passed
  EVIDENCE: pending

- [x] G8: the complete existing automated test suite and current new security regressions pass from a production-supported Python version and the frontend remains syntactically valid
  CHECK: node scripts/verify-project.mjs
  EXPECT: project verification passed
  EVIDENCE: 2026-08-30 project verifier passed on Python 3.12 with 162 Python tests and 23 subtests, plus all JavaScript regression files. Re-run after each Telegram slice before retaining this approval.

- [ ] G9: a real before-and-after test alert is delivered to the private owner channel and no unintended chat receives it
  EVIDENCE: pending

- [ ] G10: a real Telegram user can ask for a TFT menu or T&C, find an observed slot, and create then cancel a reminder, while an adversarial question receives the bounded fallback
  EVIDENCE: pending

- [ ] G11: the deployed site, reminder service, owner channel, and self-help bot are documented with setup, rotation, monitoring, rollback, privacy, freshness, and known-limit procedures
  CHECK: node scripts/verify-operations-docs.mjs
  EXPECT: operations documentation verification passed
  EVIDENCE: Railway root deployment, health acceptance, Telegram activation, rotation, monitoring, rollback, privacy-safe logging, freshness, and disabled-state procedures are documented. A verifier and real bot/channel configuration remain pending.
