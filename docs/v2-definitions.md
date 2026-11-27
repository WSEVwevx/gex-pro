# v2 Levels: definitions table

Direction: racing form / Swiss print (owner pick, 23 Nov 2026; decision 001). Implemented by
`dashboard/v2/core.js` (`levelsModel`), tested by `tests/test_v2.py`.

Every number on the v2 Levels first screen and ladder. Source = `data/all.json`, worker `w` for the market
(`w.market` = NQ or ES); `m` = `w.result.mapped`, `s` = `w.result.session`, `mp` = `m.mapping`.
Prices are futures points unless marked. v2 is built against this table; a number not in it does not ship.

| # | Name on screen | Unit | Value field | As-of field (shown ET) | When missing |
|---|---|---|---|---|---|
| 1 | Price | futures pts, 2 dp | `mp.futures_ref` | `mp.futures_time` | "Price unavailable: no futures quote" and the hero, nearer wall and ladder distances show "unavailable" |
| 2 | Distance to zero gamma (hero) | pts, unsigned, 2 dp, plus "above"/"below" | `abs(#1 - #3)`; word from the sign of `#1 - #3` | later of `mp.futures_time`, `m.asof` | "unavailable" plus the reason from #1 or #3 |
| 3 | Zero gamma | futures pts | `m.zero_gamma.price` | `m.asof` | "No zero gamma in this reading" (`m.zero_gamma` null); `m.zero_gamma_status` = ESTIMATE shows "(modelled)" |
| 4 | Call wall | futures pts | `m.call_wall.price` | `m.asof` | "unavailable" row in the ladder |
| 5 | Put wall | futures pts | `m.put_wall.price` | `m.asof` | "unavailable" row |
| 6 | Nearer wall + distance | name, pts unsigned + word | the smaller of `abs(#4-#1)`, `abs(#5-#1)` | as #2 | if one wall is missing, the other with "(only wall in this reading)"; both missing: "unavailable" |
| 7 | C1 | futures pts | `s.levels.C1` | `m.asof` | "not in this reading" |
| 8 | P1 | futures pts | `s.levels.P1` | `m.asof` | "not in this reading" |
| 9 | Ab1 | futures pts | `m.abs_gamma.price` | `m.asof` | "not in this reading" |
| 10 | Regime | word | `m.regime` (POSITIVE / NEGATIVE / INDETERMINATE) | `m.asof` | "unavailable" |
| 11 | Levels as of | ET time and day | `m.asof` | itself | never missing if the worker exists; else the whole page says "no reading for <market>" |
| 12 | Minutes since levels | min | `now - m.asof`, with `now` = page clock | `all.json.now` (build time) shown beside it | n/a |
| 13 | 1σ high / 1σ low | futures pts | `#1 ± m.expected_move.one_sigma_points_fut`, label "exp <m.expected_move.expiration>" | `m.asof` | rows hidden, "1σ move unavailable" |
| 14 | Source line | words | `m.provider`, `m.source`, `m.backup`, `m.warnings[]` verbatim | `m.asof` | — |
| 15 | Backup flag | highlight | true when `m.provider` != "CBOE" or `m.backup` is set | — | — |
| 16 | Paste time | ET | `w.published.published_at`, slot `w.published.slot_et` | itself | "No paste published yet" |
| 17 | Paste age | "N d N h" | `now - w.published.published_at` | `all.json.now` | — |
| 18 | Paste on hold | highlight | while the reading is the backup estimate (backup estimates are not pasted); next slot `w.health.next_publish_et` | `all.json.now` | — |
| 19 | Paste zero gamma | futures pts | `w.published.zero_gamma` (space = `w.published.space`) | `published_at` | omitted |

## Open points (engine side: v2 shows the engine's values and computes none)
1. **Mapping time.** `CLAUDE.md` says levels on futures use the mapping frozen with the plan at 09:30. The backup
   reading's `mp.futures_ref_mode` reads "measured NQ=F / ^NDX basis (15-minute median to 11-23 12:29 ET)", so the
   mapping in `m` is not the 09:30 one. v2 must show the engine's `m` values (no recomputing on the page); whether the
   engine's mapping follows the 09:30 rule is an engine question, logged here, not changed by v2.
2. **1σ band centre.** v2 shows the engine's 1σ move to the nearest expiry (`one_sigma_points_fut`) around price,
   labelled with its expiry. The prior-close daily band (`daily_points`, centred on the prior close in RTH) and its
   `spot_sigma` note (decision 001, C1) stay on v1; whether v2 adds them is an owner question.
3. **Two 1σ figures in the paste** (NQ 339 vs `daily_points` 881, `export.py:58,144`): unresolved, engine side.
4. **Paste zero gamma** (resolved): `w.published.zero_gamma` is in futures space (`space` = futures); the payload's
   `zg` is the index value. NQ 19 Nov 16:30: 27,691.15 x 1.002938 = 27,772.50 on the 0.25 tick.

## Invariants v2 tests (no v1 facts)
- No horizontal scroll at 375 and 1366, dark and light, NQ and ES.
- Every number in this table renders with its as-of time or sits under a heading that carries it.
- Every "When missing" text appears when its field is null (one test per row).
- Level mark colours equal the Pine `input.color` defaults and `themed()` light shades.
- No layout jump: first-screen boxes keep their size from first paint to data.
