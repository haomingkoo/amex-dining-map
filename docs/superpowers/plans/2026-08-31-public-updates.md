# Diner-focused public updates

## Outcome

A cardholder opening Amex Explorer can immediately answer:

1. Were restaurants added?
2. Were restaurants removed from a checked official listing?
3. Did a reviewed menu or benefit detail change?

Monitoring and review mechanics remain available for trust and troubleshooting, but they do not replace those answers in the primary update message.

## Experience contract

- The closed trigger is labelled **What's new**.
- Its headline summarizes unread confirmed changes by impact, for example `3 new restaurants · 1 removed · 2 menus changed`.
- Its count represents unread public changes, not failing or stale sources.
- Opening the panel shows **Confirmed changes** first with before, after, checked time, explorer link, and official source.
- Technical fields such as hashes, fingerprints, source lifecycle state, and menu version IDs are never shown as diner-facing change details.
- **Data freshness** follows the change history as a collapsed disclosure.
- The freshness summary explains user impact in plain language. Detailed source rows remain available for users who want to inspect provenance.
- Unreviewed differences are not presented as confirmed changes.
- Availability that may be outdated is described beside availability results because it affects a booking decision.

## Vertical slices

### Slice 1: public event contract

Define the reviewed event kinds that belong in the visitor feed. Filter out `source_*` lifecycle events even when their internal delivery status is `published`. Preserve venue additions, venue removals, reviewed menu changes, reviewed T&C or FAQ clauses, and meaningful venue-detail corrections.

### Slice 2: useful summary and details

Generate an unread summary from the public feed. Keep the latest confirmed change visible after everything has been marked read. Filter technical comparison fields while retaining semantic before-and-after statements and official links.

### Slice 3: progressive freshness

Move source health below confirmed changes and collapse it by default. Translate operational states into visitor language. Keep freshness warnings contextual when they affect availability or another decision.

### Slice 4: evidence and deployment

Add focused regression coverage, run the full verifier, deploy the exact revision, then inspect the live update panel at 390 pixels.

## Plan critique

### Risk: hiding source health could create false confidence

Do not remove freshness. Put it behind **Data freshness**, and keep an inline warning wherever stale information changes a booking decision.

### Risk: `published` does not mean useful to a diner

Source recovery events are legitimately published for owner operations but are not public product changes. Require both `status === published` and an explicitly allowed decision-relevant kind.

### Risk: a menu alert can still expose technical noise

Reviewed menu events may contain both semantic changes and version hashes. Filter fields such as `Menu version`, SHA values, and fingerprints from the public comparison. If no semantic comparison remains, say that the official menu changed and link to it rather than displaying a hash.

### Risk: additions and removals can overstate causality

Use `Added to the checked listing` and `No longer on the checked listing`. Do not claim that a restaurant joined or left the programme for a reason the source did not provide.

### Risk: the panel can still become a dense admin dashboard on mobile

Lead with a compact summary and collapsed rows. Keep freshness collapsed, maintain 44-pixel targets, and verify the actual 390-pixel production journey.

## Non-goals

- Changing owner Telegram alert contents or delivery security.
- Suppressing source monitoring or review queues internally.
- Inferring why a venue disappeared.
- Publishing an unreviewed menu, T&C, or roster difference.
