# Gates: TFT security, owner alerts, and self-help bot

OWNS: GATES.md, SECURITY_AUDIT.md, README.md, PRODUCT.md, reminders/**, scripts/**, web/**, data/**, .github/workflows/**

Scope: Audit and harden Amex Explorer, verify the live mobile TFT journey, and deliver separately secured owner-channel alerts and a source-grounded Telegram self-help bot.

Tracker: parent #34; vertical slices #35 through #42.

- [x] G0: the completion ledger has valid, reviewable acceptance oracles
  CHECK: node /Users/koohaoming/.codex/skills/unlazy/scripts/gate-lint.mjs GATES.md
  EXPECT: LINT OK
  EVIDENCE: 2026-08-30 gate-lint returned LINT OK; only real Telegram acceptance gates G9 and G10 remain manual.

- [x] G1: the security audit covers the static site, reminder API, automation workflows, dependencies, live headers, secrets, abuse paths, and Telegram threat model with no unresolved critical finding
  CHECK: node scripts/verify-security-audit.mjs
  EXPECT: security audit verification passed
  EVIDENCE: 2026-08-30 verifier passed; Pages run 33283464189 succeeded; Railway health, CORS, headers, and disabled OpenAPI were production-probed; Dependabot reported no open alerts.

- [x] G2: the deployed mobile Table for Two journey exposes venue details, current menu and official-source links, T&Cs context, release-pattern qualifications, and working reminder signup without browser-visible failures
  CHECK: node scripts/verify-tft-browser-evidence.mjs
  EXPECT: TFT browser evidence verification passed
  EVIDENCE: 2026-08-30 exact Pages run 33300418007 deployed 697eb35. Browser acceptance at 390x844 and 320x740 passed VUE, Osteria Mozza, and One-Ninety deep-link reloads, per-venue review warnings, exact reviewed menus, T&C/roster/Google links, reminder-form visibility, release qualifications, loaded OpenStreetMap tiles, zero clipped focus-card descendants, zero page console errors, and no API-key watermark. Two expected handled DiningCity 404 probes remain for stale missing-project venues. The live-bound evidence verifier passed against app SHA 5a446a4193c6 and Railway deployment 530a9425-58c8-4451-b6e4-84ccf6352f40.

- [x] G3: owner updates are formatted as concise before-and-after alerts and can only be delivered to the configured private Telegram channel
  CHECK: node scripts/verify-telegram-owner-alerts.mjs
  EXPECT: Telegram owner alert verification passed
  EVIDENCE: 2026-08-30 verifier passed. Tests prove plain-text before/after rendering, config-only destination selection, published-only delivery, replay deduplication, digest conflict rejection, and no blind retry after ambiguous transport outcomes. Real-channel delivery remains G9.

- [x] G4: menu, venue, T&C, source, and release-pattern changes can trigger owner-channel alerts without leaking bot tokens, subscriber records, or internal diagnostics
  CHECK: node scripts/verify-telegram-change-dispatch.mjs
  EXPECT: Telegram change dispatch verification passed
  EVIDENCE: 2026-08-30 expanded verifier passes source health, source-change, TFT roster/menu/document review, Love Dining review, release-pattern, owner-ingress, and delivery suites. TFT successor documents retain exact observed bytes and the prior reviewed bot projection, require canonical page-bound manifests and complete transitions, recover interrupted ledger writes before accepting another successor, distinguish FAQ events, and preserve source-scoped venue publication. Real delivery remains G9.

- [x] G5: the Telegram self-help bot answers TFT program, venue, menu, T&C, and release-pattern questions and can find currently observed slots from curated current sources with citations and freshness dates
  CHECK: node scripts/verify-telegram-guide.mjs
  EXPECT: Telegram guide verification passed
  EVIDENCE: 2026-08-30 venue/menu, observed release-pattern, observed-slot, and official-document tracers pass locally. `/terms` and `/faq` return fixed hash-bound summaries with exact reviewed page, version, capture time, and official Amex URL; a new unreviewed hash retains that reviewed answer with an explicit successor-review warning. `/release VUE dinner` remains source-qualified. `/slots` enforces exact venue/all, party, meal, date/range or transparent weekend defaults, and optional preferred time against a bounded fixed-source AMEXPlatSG projection with per-venue 30-minute freshness.

- [x] G6: unsupported, stale, ambiguous, adversarial, and prompt-injection questions fail safely without inventing eligibility, availability, booking rules, or menu facts
  CHECK: node scripts/verify-telegram-safety.mjs
  EXPECT: Telegram safety verification passed
  EVIDENCE: 2026-08-30 deterministic venue/menu/release/document surfaces reject unsupported, ambiguous, and prompt-injection-shaped questions; untrusted menu or document URLs, future review timestamps, wrong page hashes, invalid page references, and wrong release provenance fail closed. Eligibility output describes document scope without deciding that a user qualifies; merchant-specific fees, children policy, availability, and legal interpretation are not invented.

- [x] G7: Telegram webhook authentication, owner/public-bot separation, public-user rate limits, payload limits, output escaping, reminder consent, retention limits, and secret isolation pass security regression tests
  CHECK: node scripts/verify-telegram-security.mjs
  EXPECT: Telegram security verification passed
  EVIDENCE: 2026-08-30 expanded verifier passes guide webhook authentication, replay, private-chat, rate, payload, retention, escaping, secret-isolation, and the reminder consent/retention lifecycle. Real private-Telegram acceptance remains G10.

- [x] G7A: the tested Telegram lifecycle supports creating, inspecting, and cancelling a TFT slot reminder with an explicit venue, party size, meal, and date range
  CHECK: node scripts/verify-telegram-reminders.mjs
  EXPECT: Telegram reminder verification passed
  EVIDENCE: 2026-08-30 deterministic one-shot lifecycle, bounded and expiring setup, HMAC ownership, non-enumerating cancellation, two-step deletion, fresh AMEXPlatSG matching, transactional claims, terminal delivery receipts, post-Pages generation gating, and privacy-safe dispatch logs pass locally. Real private-Telegram mobile acceptance remains G10.

- [x] G7B: configuration-gated mobile Telegram actions preserve the exact TFT venue and supported slot filters, and BotFather start payloads resolve only reviewed venues
  CHECK: node scripts/verify-telegram-deep-links.mjs
  EXPECT: Telegram deep-link verification passed
  EVIDENCE: 2026-08-30 verifier passed; Pages run 33301216271 deployed c3fada7. Production mobile acceptance at 390x844 proved the exact VUE venue, party 2, dinner, 2026-10-29, 19:00, and weekday filters survive a direct link with no console error or horizontal overflow. Telegram actions correctly remain hidden while the public Bot username is disabled; visible real-bot acceptance remains G10.

- [x] G8: the complete existing automated test suite and current new security regressions pass from a production-supported Python version and the frontend remains syntactically valid
  CHECK: node scripts/verify-project.mjs
  EXPECT: project verification passed
  EVIDENCE: 2026-08-30 project verifier passed on Python 3.12; the direct suite reports 431 Python tests and 23 subtests, plus all JavaScript regression files, source-health workflow/schema checks, and frontend syntax validation.

- [ ] G9: a real before-and-after test alert is delivered once to the private owner channel, Telegram confirms the configured destination ID, and no unintended chat receives it
  EVIDENCE: pending

- [ ] G10: a real Telegram user can ask for a cited TFT menu and page-aware T&C, find a fresh observed slot or bounded empty result, create/list/receive/cancel/delete a reminder without duplicate delivery, and receive bounded behavior for adversarial and group messages
  EVIDENCE: pending

- [x] G11: the deployed site, reminder service, owner channel, and self-help bot are documented with setup, rotation, monitoring, rollback, privacy, freshness, and known-limit procedures
  CHECK: node scripts/verify-operations-docs.mjs
  EXPECT: operations documentation verification passed
  EVIDENCE: 2026-08-30 executable operations verifier passes config/example parity, disabled defaults, non-secret health state, Railway and Pages acceptance, feature activation order, safe rollback order, workflow credential seams, 36-hour catalogue and 30-minute slot thresholds, aggregate-safe diagnostics, and honest correlation limits. Real bot/channel acceptance remains G9/G10.

- [x] G12: primary venue, hotel, menu, T&C, release, stale, recovery, and review-state transitions have review-safe before-and-after owner events, including additions and removals
  CHECK: node scripts/verify-telegram-change-dispatch.mjs
  EXPECT: Telegram change dispatch verification passed
  EVIDENCE: 2026-08-30 verifier and 431-test suite pass. Venue/hotel, roster, menu, release, stale/recovery, and document transitions are source-scoped. TFT T&C/FAQ application retains exact observed and predecessor bytes, validates page-bound clause accounting, publishes additions/removals/modifications, suppresses layout-only noise, resumes interrupted ledger writes, blocks successor races, and verifies the rebuilt bot catalogue.

- [x] G13: mobile users and the owner can see source-specific freshness, retained-snapshot, failure, and review-required state without mistaking optional enrichment age for official fact age
  CHECK: node scripts/verify-source-health.mjs
  EXPECT: source health verification passed
  EVIDENCE: 2026-08-30 verifier passed; Pages run 33302192683 deployed 7c281a8. Production at 390x844 rendered all nine sources with primary/enrichment separation, exact dates, coverage, runtime staleness, review state, and no horizontal overflow. The deployed snapshot truthfully reports TFT availability stale at 21/23, Google mixed-age at 2,933/2,947, and Tabelog stale at 781/839.
