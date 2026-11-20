# Style guide (the website)

Chosen 2026-11-19 by the owner: direction **A, "Quiet pro"**, with **B's level map** as the Levels page's hero
(mockups: https://claude.ai/artifact/WUxFg3UWGowYyUWwbZHz33). Calm and exact: space and hairlines group things, the
key numbers are the largest thing on the screen, and colour means something or is absent.

All tokens live at the top of `dashboard/assets/terminal.css`; `tests/test_design_tokens.py` and
`tests/test_site_motion.py` keep the rules below true.

## Surfaces
| Token | Use |
|---|---|
| `--page` | the page background |
| `--panel` | a card: a group that needs to stand apart (no border; in light mode `--card-shadow` lifts it) |
| `--panel2` | a control or a well inside a card (segmented switches, the clock, expiry tiles) |
| `--raise` | the selected or hovered item |

Cards have no border. Use a card only where grouping needs it; inside a card, divide with `--line` hairlines.

## Text
`--ink` (numbers and headings), `--ink2` (body), `--ink3` (labels), `--ink4` (hints). Each is at least 4.5:1 on
`--panel` in both themes. Prose and labels use `--sans`; numbers that align use `--mono` (tabular figures are on
for the whole page).

## Meaning (never decoration)
`--pos` calls / positive gamma (blue), `--neg` puts / negative gamma (orange), `--zg` zero gamma / the flip,
`--warn` warnings and estimates, `--bad` failures, `--good` healthy. A tint is
`color-mix(in srgb,var(--pos) 12%,transparent)`, so light mode tints follow the light palette. No other hex or
rgba colour appears outside the token blocks.

## Size
- Type: the 8 steps `--fs-xs` .. `--fs-x3`; no raw pixel font sizes.
- Space: `--sp-1` .. `--sp-8` = 4, 8, 12, 16, 20, 24, 32, 40 px.
- Radius: `--r-1` 4 px (tags, small controls), `--r-2` 7 px (buttons, inputs), `--r-3` 12 px (cards); circles
  (50%) and pills (999px) are shapes.
- Motion: `--t-fast` / `--t-std` / `--t-slow` with `--ease` / `--ease-out`, all zero under reduced motion.

## Fixed palettes
The quote tape (`--tape-*`) and the indicator source (`--code-*`) stay dark in both themes on purpose.
