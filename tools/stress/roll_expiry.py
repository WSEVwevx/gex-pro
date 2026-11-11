"""Stress test C2: the quarterly roll week, triple-witching Friday, the Sunday open and the daily 17:00-18:00 halt.

  python tools/stress/roll_expiry.py

A synthetic SPX-style chain (the AM-settled monthly at 09:30 on the third Friday, PM-settled dailies at 16:00) is
evaluated at each step of December 2026's expiry week. At every timestamp it checks:
  futures contract  the contract the website's carry model prices, against the one a continuous chart (NQ1!,
                    Yahoo NQ=F) shows: those switch on the Monday after expiry (measured on Yahoo's daily closes,
                    Dec 2025 - Sep 2026: the basis jumps ~0.8% on that Monday every quarter), not on the roll date
  mapping factor    the carry fair value's time to expiry is positive and belongs to that contract
  EM anchor         previous close in RTH, the last price outside it
  daily band        runs to the session's close outside RTH; in RTH the forward variance to the next session's close
  0DTE selection    the first expiration the levels use, and the expiration the daily band's variance runs to
Tolerance (fixed before running): exact - every item must equal the expected value at every timestamp.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from gexsys import basis, engine as eng, marketcal  # noqa: E402
from gexsys.extras import compute_extras  # noqa: E402
from gexsys.models import ChainSnapshot, OptionContract, OptionType, Quality, SourceKind  # noqa: E402

NY = marketcal.NY


def at(d: date, hh: int, mm: int = 0) -> datetime:
    return datetime.combine(d, time(hh, mm), NY)


def chart_contract(root: str, on: datetime) -> str:
    """What a continuous chart (NQ1!, NQ=F) shows: the quarterly until its 09:30 settlement on expiry day, then the next.
    (Yahoo prints the switch on the next session's bar; the expiring contract has no price after 09:30.)"""
    d = on.date()
    y, m = d.year, ((d.month - 1) // 3 + 1) * 3
    for _ in range(3):
        exp = datetime.combine(marketcal.quarterly_expiry(y, m), time(9, 30), NY)
        if on < exp:
            return f"{root}{marketcal.QUARTER_CODES[m]}{y % 10}"
        m += 3
        if m > 12:
            m, y = 3, y + 1
    raise RuntimeError("unreachable")


def chain_at(asof: datetime) -> ChainSnapshot:
    first = date(2026, 12, 7)
    cs = []
    for i in range(40):
        d = first + timedelta(days=i)
        if not marketcal.is_trading_day(d):
            continue
        exps = [("SPXW", datetime.combine(d, marketcal.rth_close(d), NY))]
        if d == marketcal.third_friday(2026, 12):
            exps.append(("SPX", datetime.combine(d, time(9, 30), NY)))
        for root, e in exps:
            for k in range(90, 111, 5):
                for typ in (OptionType.CALL, OptionType.PUT):
                    cs.append(OptionContract(symbol=f"{root}{e:%y%m%d%H}{typ.value}{k}", root=root, underlying="SPX",
                                             option_type=typ, strike=float(k), expiration=e, multiplier=100.0,
                                             open_interest=1000.0, iv=0.2 if root == "SPXW" else 0.3,
                                             quote_quality=Quality.DELAYED, oi_quality=Quality.EOD,
                                             greeks_quality=Quality.MISSING))
    return ChainSnapshot(underlying="SPX", source_kind=SourceKind.INDEX, spot=100.0, spot_time=asof,
                         spot_quality=Quality.DELAYED, contracts=cs, source="test", fetched_at=asof,
                         rate=0.04, div_yield=0.013, prev_close=99.0)


def expected(asof: datetime) -> dict:
    """The right answers, written out from the exchange rules (not from the code under test)."""
    d, clock = asof.date(), asof.time()
    rth = marketcal.is_trading_day(d) and time(9, 30) <= clock < marketcal.rth_close(d)
    # the session the levels and the band are for: today until its close, else the next trading day
    s = d
    if not (marketcal.is_trading_day(d) and clock < marketcal.rth_close(d)):
        s = d + timedelta(days=1)
        while not marketcal.is_trading_day(s):
            s += timedelta(days=1)
    pm_close = datetime.combine(s, marketcal.rth_close(s), NY)
    am = datetime.combine(s, time(9, 30), NY)
    # the daily band: outside RTH the variance to the session's own close; in RTH (anchored at the previous
    # close, for a full session) the forward variance from today's close to the next session's
    nxt = s + timedelta(days=1)
    while not marketcal.is_trading_day(nxt):
        nxt += timedelta(days=1)
    first = am if (s == marketcal.third_friday(2026, 12) and asof < am) else pm_close
    return {"contract": chart_contract("ES", asof), "anchor": 99.0 if rth else 100.0,
            "first_expiry": first.date().isoformat(), "first_is_am": first == am,
            "label": "0DTE" if first.date() == d else f"next {first.date().isoformat()[5:]}",
            "band_to": (nxt if rth else s).isoformat()}


STEPS = [
    ("Thu roll date, 12:00", at(date(2026, 12, 10), 12)),
    ("Fri before expiry week, 15:00", at(date(2026, 12, 11), 15)),
    ("Mon expiry week, 10:00", at(date(2026, 12, 14), 10)),
    ("Thu before triple witching, 17:30 halt", at(date(2026, 12, 17), 17, 30)),
    ("Thu evening session, 18:05", at(date(2026, 12, 17), 18, 5)),
    ("Triple witching, 09:00 pre-open", at(date(2026, 12, 18), 9)),
    ("Triple witching, 09:31 after AM settlement", at(date(2026, 12, 18), 9, 31)),
    ("Triple witching, 15:59", at(date(2026, 12, 18), 15, 59)),
    ("Triple witching, 16:30", at(date(2026, 12, 18), 16, 30)),
    ("Sunday 17:59, before the open", at(date(2026, 12, 20), 17, 59)),
    ("Sunday open, 18:05", at(date(2026, 12, 20), 18, 5)),
    ("Monday after expiry, 09:45", at(date(2026, 12, 21), 9, 45)),
    ("Monday 17:30 halt", at(date(2026, 12, 21), 17, 30)),
]


def main() -> int:
    wrong = []
    cfg = eng.EngineConfig(max_spot_age_s=400 * 86400)
    print(f"{'step':45s} {'state':7s} contract  first expiry      label        band to     anchor")
    for name, asof in STEPS:
        exp = expected(asof)
        snap = chain_at(asof)
        res = eng.compute(snap, cfg, asof=asof)
        ex = compute_extras(snap, cfg, res)
        em, near = ex["expected_move"] or {}, ex["nearest"] or {}
        code, settle = basis.futures_expiry("ES", asof)
        first_exp = min((c.expiration for c in snap.contracts if c.expiration.date().isoformat() == res.basket[0]
                         and c.expiration > asof), default=None)
        got = {"contract": code, "anchor": em.get("anchor"), "first_expiry": res.basket[0],
               "first_is_am": bool(first_exp and first_exp.time() == time(9, 30)),
               "label": near.get("label"), "band_to": em.get("daily_iv_expiry")}
        bad = [k for k in exp if got[k] != exp[k]]
        if settle <= asof:
            bad.append("carry time to expiry <= 0")
        print(f"{name:45s} {marketcal.session_state(asof):7s} {code:9s} {got['first_expiry']}{' AM' if got['first_is_am'] else '   '}  "
              f"{str(got['label']):12s} {str(got['band_to']):11s} {got['anchor']}  {'OK' if not bad else 'WRONG: ' + ', '.join(f'{k} {got[k]} (should be {exp[k]})' if k in exp else k for k in bad)}")
        for k in bad:
            wrong.append(f"{asof:%Y-%m-%d %H:%M} ET {name}: {k}")
    print("\nRESULT:", "PASS" if not wrong else f"FAIL - {len(wrong)} wrong:\n  " + "\n  ".join(wrong))
    return 1 if wrong else 0


if __name__ == "__main__":
    sys.exit(main())
