# Prompt for the ui-auditor agent

Paste this as the agent's task. Replace `<URL>` (default: https://wsevwevx.github.io/gex-pro/).

---

Audit <URL> like a picky trader who opens it on a phone at 09:25 and a QA lead who has to sign off on it.
Read only: change no code, files or site settings, and send nothing anywhere.

## Coverage (do every cell; do not sample, do not stop early)
- Pages: every `button[data-p]` in the site's own nav (today 13).
- Markets: NQ and ES. Widths: 1366x900 and the mobile preset (375x812). Themes: dark and light.
  That is 13 x 2 x 2 x 2 = 104 cells. Keep a coverage table as you go; a cell counts only if its data loaded.
- On every page, also open every closed `<details>` (on Levels: "More numbers" `#lvMore` and "Level history"
  `#lvHist`) and audit what is inside. Close them again afterwards.

## On every cell, measure (javascript_tool)
1. Sideways scroll: `document.documentElement.scrollWidth - innerWidth > 1`.
2. Anything visible past the right edge, or clipped by an `overflow:hidden` parent.
3. Text overlapping: for visible text boxes and SVG `<text>`, any two `getBoundingClientRect()`s that intersect.
   On phones, anything under the fixed copy bar (`#copyAll`) at first paint.
4. A number, price, date, time or range that wraps onto two lines (its box is taller than one line height).
5. "NaN", "undefined", "null", "[object Object]", "Infinity", "-0" or an empty value in the page text.
6. An empty or half-empty card; a `.skeleton` still showing after 5 s; a spinner that never ends.
7. Layout shift: record the positions of the cards at 0.5 s and at 5 s after the page opens; anything that moved more
   than 4 px is a shift (a 0 CLS only counts if the page actually painted).
8. Script errors: listen for `error` and `unhandledrejection` before the sweep; read the console at the end.
9. Text contrast below 4.5:1 for any visible text (compute from the colours actually used, including opacity).

## On every cell, look (take a screenshot and actually read it)
Look at the first screen of every cell, and of every opened fold, and write one line on what is wrong or "clean".
Look for things a script misses: misaligned columns, a label on the wrong line, cramped or uneven spacing, a chart
with labels outside its box, an icon or tag that collides with a number, an empty-looking area, a light-theme
colour that disappears, a font that changes size or weight for no reason.

## Honesty and data (this site's own rules)
- Every number shows its "as of" time; every statistic shows its sample size. Flag any that does not.
- Missing data must say "unavailable" and why. Flag a blank, a dash with no reason, or an old number shown as current.
- While Cboe refuses requests, the site runs on the OCC backup: every page with levels must say "Backup estimate".
  The backup itself is expected and is not a defect; a page that hides it is.
- Compare times with the Data health page: anything older than its stated freshness is a defect.
- Cross-check: the same level (zero gamma, call wall, put wall) must show the same price on Levels, the level map,
  the paste text and the Live table, for the same market. Report any mismatch with both values.
- Switching NQ <-> ES must change every number on the page. A number that stays the same is a defect.

## Interactions (once per market, at both widths)
- Every "?" help button opens help that fits on screen and closes.
- The copy button copies the paste (read it back from the page or the clipboard event; do not paste it anywhere).
- The theme and market choices survive a reload.
- The nav row on phones scrolls so the open tab is visible.

## Report
1. Coverage table: 104 cells, each "ok", "defect" or "not checked (why)".
2. Defects, worst first. One line each:
   severity (high = wrong or misleading data, broken page; medium = hard to read or use; low = cosmetic) |
   market | width | theme | page | what you saw | the measured value | screenshot path.
   Group repeats of the same defect into one line that lists every cell it appears in.
3. Totals: cells checked, defects by severity, script errors.
4. What you could not check and why.
Every defect needs a measured value or a screenshot. Never write "looks fine" for a cell you did not open, and never
report a check that did not run. If it is all clean, say so with the totals.
