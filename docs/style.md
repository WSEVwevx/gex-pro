# Style guide (the website): Meridian

Chosen 2026-11-21 in Phase 1 of the 2040 redesign (`docs/prompts/redesign-2040.md`; directions:
https://claude.ai/artifact/SzFNBPfhFKhy2tRskiMF6e; why: `JOURNAL.md`). This replaces "Quiet pro" (2026-11-19).

## The manifesto
Price is a bead on a vertical meridian, and the gamma field is the dial behind it. Walls are where the tone is
deepest. Zero gamma is where the total curve crosses its axis. Surfaces are planes of one material, night glass in
dark and porcelain in light, separated by lightness rather than borders. The page speaks in one plain sentence under
a watch-face price, built from fixed templates. It describes the market and never tells anyone what to trade.

The trading day sets the order of the Levels page:
- before the open: the plan and the paste;
- during the session: the field;
- after the close: how the levels held.

Trust is a material. A backup estimate sits on its own hatched plate and says so in words. Ageing numbers quiet their
ink, never below 4.5:1. A missing level is an empty row that says why.

All tokens live at the top of `dashboard/assets/terminal.css`. These tests keep the rules below true:
- `tests/test_design_tokens.py`: colour, contrast, space and radius;
- `tests/test_site_motion.py`: motion and type sizes;
- `tests/test_pine_static.py`: the colours shared with the indicator.

## Material (surfaces)
Dark is night glass, hue 260. Light is porcelain, hue 85, a warm paper rather than an inverted dark.

| Token | Dark | Light | Use |
|---|---|---|---|
| `--page` | `oklch(0.165 0.012 260)` | `oklch(0.972 0.006 85)` | the ground |
| `--panel` | `oklch(0.2 0.014 260)` | `oklch(0.995 0.003 85)` | a plane that stands apart (no border; light lifts it with `--card-shadow`) |
| `--panel2` | `oklch(0.235 0.015 260)` | `oklch(0.958 0.007 85)` | a well or control inside a plane |
| `--raise` | `oklch(0.275 0.016 260)` | `oklch(0.93 0.009 85)` | the selected or hovered item |

Depth is lightness: each step is a few points of L. Within a plane, divide with `--line` hairlines, never boxes.

## Ink
`--ink` is for numbers and headings, `--ink2` for body, `--ink3` for labels and ageing values, `--ink4` for hints.
Each is opaque and at least 4.5:1 on all four surfaces in both themes (tested). Ageing data uses `--ink3`: quieter,
never faded with opacity.

## Meaning (never decoration)
The eight level colours are shared with the TradingView indicator and stay hex so that the indicator test can compare
them:
- `--pos`: positive gamma and calls (blue);
- `--neg`: negative gamma and puts (orange);
- `--zg`: zero gamma and the flip;
- `--ag`: abs gamma;
- `--vol`: volume;
- `--oi`: open interest;
- `--mp`: max pain;
- `--em`: the expected move.

The states are OKLCH and each reads at 4.5:1 or better as text: `--good`, `--warn`, `--bad`, `--prompt`, `--bad-fg`
and `--high-fg`. A tint is `color-mix(in srgb,var(--pos) 12%,transparent)`. No hex, `rgb()`, `oklch()`, `hsl()` or
other colour appears outside the token blocks.

## Trust states
| State | Looks like | Always says |
|---|---|---|
| Fresh | full ink | its "as of" time |
| Ageing (past the freshness stated on Data health) | `--ink3` | its time, and "late" |
| Backup estimate | `--backup-bg` plate with a `--backup-hatch` hatch, `--backup-ink` text (4.5:1 or better) | "Backup estimate" and the source |
| Missing | an empty row or shape in `--ink3` | "unavailable" and why |
| Closed market | the phase label (from `data.calendar`) | which close the numbers are from |

Colour is never the only signal: every state has words.

## Type
- One face: the system's variable UI face, `--sans` (Segoe UI Variable, SF Pro, system-ui), with tabular figures
  on for the whole page. `--mono` is for code and aligned columns.
- The self-hosted Geist woff2 (open licence) planned in Phase 1 is on hold: downloading the font file needs the
  owner's OK. The system faces cost 0 KB.
- At most 8 sizes: `--fs-xs` .. `--fs-x3`. No raw pixel font sizes. Large numbers are light weight (300) with a
  slight negative tracking, set like a watch face.

## Space, radius, motion
- Space: `--sp-1` .. `--sp-8` = 4, 8, 12, 16, 20, 24, 32, 40 px.
- Radius:
  - `--r-1` (4 px): tags and small controls;
  - `--r-2` (7 px): buttons and inputs;
  - `--r-3` (12 px): planes;
  - circles (50%) and pills (999px) are shapes.
- Motion uses `--t-fast` (90 ms), `--t-std` (160 ms) and `--t-slow` (280 ms) with `--ease` and `--ease-out`. It
  only carries information:
  - a number that changed rolls briefly;
  - a level that moved glides once;
  - a page or control changes state.
- All motion is zero under `prefers-reduced-motion`.

## The sentence
It uses fixed templates only (Phase 4). It never contains buy, sell, should, target or will. Every number in it is
on the page in the same units, with its time. A historical tendency appears only with its sample size.

## Fixed palettes
The quote tape (`--tape-*`) and the indicator source (`--code-*`) stay dark in both themes on purpose.
