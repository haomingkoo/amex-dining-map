# Security audit — 30 August 2026

Scope: the public static explorer, data-driven rendering, GitHub Actions, the Railway FastAPI/SQLite reminder service, dependencies, live response controls, secrets handling, abuse paths, and the implemented, disabled-by-default Telegram ingress.

## Outcome

No secret was detected across 1,854 commits and approximately 738 MB of Git history. The live subscriber export rejected unauthenticated access, production CORS accepted only the Explorer origin, SQL statements use bound parameters, and confirmation tokens use cryptographically secure randomness.

Two high-risk paths were found, remediated, deployed, and rechecked in production:

1. Manual GitHub Action inputs could reach shell execution through direct interpolation and `eval` in a job with repository write access and a Groq secret.
2. A spoofable forwarded-IP-only limit allowed repeated confirmation email abuse, while re-subscribing a known active address replaced its preferences and disabled alerts until reconfirmation.

The hardened static revision was deployed through GitHub Pages and the reminder
service was deployed to Railway on 30 August 2026. Production probes confirmed
the expected CORS boundary, security headers, disabled OpenAPI route, and
unauthenticated export denial without creating a subscription or sending email.

## Findings and disposition

| Severity | Finding | Disposition |
| --- | --- | --- |
| High | Workflow-dispatch shell injection | Removed `eval`, moved inputs through environment variables, validated allowed shapes, and used argument arrays. |
| High | Spoofable email abuse and active-subscriber reset | Added atomic keyed-hash IP, email, and global quotas; used the trusted proxy hop rather than the attacker-controlled prefix; preserved active settings in a separate pending change until confirmation. |
| Medium | Confirmation and unsubscribe changed state on GET | GET now renders an explicit action page; POST performs the state change. The unsubscribe POST also supports email-provider one-click requests. |
| Medium | User name injected into trusted-sender HTML email | Escaped body and attribute values and added a malicious-name regression test. |
| Medium | One long-lived token controlled manage and unsubscribe | New subscriptions receive distinct management and unsubscribe capabilities; token pages are no-store and no-referrer. Existing delivered links remain compatible after migration, so legacy rows retain a shared capability until a user-confirmed rotation path exists. Plaintext capability storage also remains a future hardening opportunity. |
| Medium | Token/PII pages lacked response controls | Added CSP, HSTS, no-store, no-referrer, nosniff, frame denial, and permissions policy middleware; disabled public OpenAPI output. |
| Medium | Unbounded request and list parsing | Added a 16 KiB API-body limit and explicit list/string cardinality limits. |
| Medium | Raw IPs and expired records retained indefinitely; DB mode could be 0644 | Abuse identifiers are now keyed hashes, old events and expired pending records are purged, unsubscribed records have a retention window, confirmed rows discard the source identifier, and the SQLite file is forced to mode 0600. |
| Medium | Dynamic URLs were escaped but their protocols were not constrained | Added a DOM URL policy that removes unsafe protocols from dynamically rendered links and images, plus negative controls for `javascript:`, `data:`, and insecure remote HTTP. |
| Medium | CDN scripts lacked integrity and the static page lacked CSP | Added SRI/crossorigin attributes and a restrictive CSP/referrer meta policy. Edge-level frame and permissions headers remain recommended because GitHub Pages cannot express them in repository content. |
| Medium | Movable action tags, unrestricted Actions, no security updates | Pinned every action referenced by this repository to an immutable commit, restricted the repository to GitHub-owned actions, enabled dependency security updates, and added weekly pip/Actions Dependabot checks. Repository-wide SHA enforcement cannot remain enabled because GitHub's own Pages artifact action currently calls a transitive action by version tag; the local workflow pins remain enforced by review and verification. |
| Medium | Resolved Starlette 0.41.3 had known advisories | Upgraded FastAPI, Starlette through its resolved dependency, Uvicorn, Pydantic, and pytest; a fresh resolved-tree audit reports no known vulnerability. |
| Medium | Main has no branch protection | Residual. Scheduled data workflows currently commit directly to main, so protection needs a designed automation bypass or PR-based refresh path before enabling it. |
| Low | Runtime-installed Playwright was unpinned | Pinned the workflow installation to a reviewed version. A hashed Python lock remains desirable. |

## Telegram threat model

Before enabling either Telegram surface:

- Verify Telegram's webhook secret header with constant-time comparison.
- Deduplicate every update ID before side effects.
- Use a numeric fixed channel ID, never a username, for one-way owner delivery. Require a numeric owner-user allowlist if privileged inbound commands are added later.
- Keep owner-alert and public-guide bot identities, tokens, and secrets separate.
- Accept public v1 usage only in private chats; ignore group and channel commands.
- Keep the bot token, webhook secret, owner IDs, and ingestion token only in deployment secrets.
- Apply per-user and global limits, bounded input/output, and idempotent delivery keys. Expiring conversation state is required when Telegram reminder conversations are added.
- Treat official document and menu text as untrusted evidence, not instructions.
- Never fetch a user-supplied URL or give an optional language model credentials, network tools, subscriber exports, or delivery authority.
- Escape Telegram formatting and allow citations only through reviewed URL policies.
- Store minimal Telegram identifiers. Deletion behavior is required when persistent Telegram reminder profiles are added; the current guide stores only keyed identities, replay state, and quota state with bounded retention.
- “Find a slot” reads cached AMEXPlatSG observations only; it never books, handles Amex credentials, or guarantees inventory.

## Verification evidence

- Baseline reminder suite before changes: 40 passed on Python 3.12.
- Hardened reminder suite: 47 passed on Python 3.12.
- Post-Telegram guide suite: 100 reminder tests passed on Python 3.12; the project, Telegram guide, and Telegram security verifiers also passed for `c650dcb`.
- Updated fully resolved production dependency audit: no known vulnerabilities.
- Frontend syntax and all JavaScript regression scripts pass, including unsafe-protocol negative controls.
- Neither Telegram bot has passed real-channel or real-private-chat acceptance; both remain disabled production features until G9/G10 pass.
- Live pre-deployment evidence: static HTTPS/HSTS/nosniff present; reminder CORS restricted correctly; subscriber export returned 401 without credentials; reminder responses lacked security headers before this change.

## Production recheck

Completed after deployment:

1. Production CORS returned `200` and the allow-origin header only for
   `https://amex-explorer.kooexperience.com`; a hostile origin returned `400`
   without an allow-origin header.
2. The Railway health endpoint returned `200`; token-bearing error pages use
   `Cache-Control: no-store`, CSP, HSTS, no-referrer, nosniff, frame denial, and
   a restrictive permissions policy.
3. `/openapi.json` returned `404` and the subscriber export continued to reject
   unauthenticated access.
4. Spoofed forwarded-chain quotas, repeated-email quotas, active-user
   re-subscribe preservation, and GET-versus-POST state changes passed the
   non-delivery regression suite.
5. The deployed mobile TFT route rendered VUE details, official menu and T&C
   links, qualified release-pattern wording, and observed availability without
   browser-visible application errors.
6. A resolved dependency audit reported no known vulnerabilities; GitHub
   Dependabot had no open alerts, security updates were enabled, repository
   Actions were restricted to GitHub-owned actions, and repository workflow
   actions remained pinned to reviewed commits.

Residual items remain documented above: scheduled refreshes still require a
branch-protection design, GitHub Pages cannot set every desired edge header,
and legacy reminder links retain their original shared capability until rotated.
