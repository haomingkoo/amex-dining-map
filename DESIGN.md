# Design: Unofficial Platinum Experience

Inherits the kooexperience design core (`~/.agent-memory/design/DESIGN-core.md`). This file only records what is specific to this app. Amex Explorer is the core's reference app, so refine it; don't restyle it.

## Audience and job
Singapore Amex Platinum cardholders, mostly on phones, checking where a dining or hotel benefit applies and whether a Table for Two table is open. One job per tab: find a venue on the map and follow the official source.

## Mood
A concierge's ledger: deep navy, warm ivory text, a little gold. Calm and premium, never promotional, never urgent.

## Tokens (in `web/styles.css`)
- Ground `--bg #070d16`. Text `--text #f0ebe2`, secondary `--text-secondary #8a9aaa`, tertiary `--text-dim #7f90a4` (passes 4.5:1 on every panel).
- Accent: gold `--gold #c9a55a` marks selection, active state and focus. Teal `--teal #4db8a6` means bookable or live and nothing else.
- Structure comes from the 1px warm hairline `--border`. Shadows only on floating layers (map sheet, popups).
- Type: Cormorant Garamond for display and panel headings, Figtree for UI. Labels are at least 11px. Tabular numerals in counts.
- Focus: one ring everywhere, 2px solid `--focus-color` with a 2px offset (darker gold in the light theme).

## Copy
- Plain words for data provenance: "checked 25 Oct, 7:29 am", "Amex list", "Amex booking system". Never "cached", "snapshot", "roster", "fallback", project codes or record counts.
- Counts come from the loaded data at render time and use `toLocaleString("en-SG")`. No hard-coded totals in copy.
- "Removed" means absent from the latest checked listing; never guess a reason.
- No em dashes. Telegram and email replies follow the same rules and say "Table for Two", not "TFT".

## States
- Loading: "Loading restaurants..." in each panel. Empty filters: one sentence plus a Clear filters button. Load failure: one sentence plus Reload.
- Table for Two live check failure shows the previous check and says so.
- What's new: full breakdown on desktop, "N unread changes" on phones; the panel holds the detail.

## Chrome
Header: wordmark, route breadcrumb, GitHub icon, theme toggle, Guide. Footer is the shared core footer plus the "Unofficial fan site, not affiliated with American Express" line, on the map and both legal pages.

## Not done yet
Token sprawl (17 gold alphas, unused accent hues), pill radius on most controls, glass blur on static panels and the uppercase focus-card kickers are left from the incumbent design.
