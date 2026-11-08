"""What other components read from the GEX and feeds components: the briefings snapshot and the
track record's pre-open levels.

This is the only place that knows both sides, so feature packages stay independent of each other.
Shape: see briefings/compose.py.
"""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone

from feeds import weekinfo
from gexsys import bias, export, marketcal, session
from trackrecord import prices


def _p(v):
    return v.get("price") if isinstance(v, dict) else v


def market_snapshot(w) -> dict | None:
    r = w.result
    if not r or r["summary"].get("status") == "UNAVAILABLE":
        return None
    s = r["summary"]
    L = r.get("mapped") or s                          # futures prices when mapped, else index prices
    X = L.get("extras") or {}
    em, near, b = X.get("expected_move") or {}, X.get("nearest") or {}, r.get("bias")
    return {
        "market": w.cfg.market, "price": L.get("futures_equiv_of_ref") or s.get("ref_price"),
        "asof": s.get("asof"), "quality": s.get("ref_quality"),
        "options": (s.get("options_source") or w.cfg.source) + ("+" + s["etf"] if s.get("etf") else ""),
        "regime": s.get("regime"), "net": s.get("net"),
        "zero_gamma": _p(L.get("zero_gamma")), "call_wall": _p(L.get("call_wall")),
        "put_wall": _p(L.get("put_wall")), "abs_gamma": _p(L.get("abs_gamma")),
        "nearest": {"label": near.get("label"), "zero_gamma": _p(near.get("zero_gamma")),
                    "call_wall": _p(near.get("call_wall")), "put_wall": _p(near.get("put_wall"))},
        "em": {"anchor": em.get("anchor_fut", em.get("anchor")), "daily": em.get("daily_points_fut", em.get("daily_points")),
               "weekly": em.get("weekly_points_fut", em.get("weekly_points")), "weekly_expiry": em.get("weekly_expiry")},
        "bias": {k: b.get(k) for k in ("bias", "confidence", "day_type", "target", "range", "summary")} if b else None,
        "delta": r.get("delta"),
    }


def snapshot(gex, feeds) -> dict:
    """gex: GexComponent (its workers), feeds: FeedsComponent."""
    markets = [m for m in (market_snapshot(w) for w in gex.workers.values()) if m]
    try:
        events = feeds.calendar.get().get("events", [])
    except Exception:
        events = []
    try:
        posts = feeds.posts.get().get("posts", [])
    except Exception:
        posts = []
    return {"now": datetime.now(timezone.utc).isoformat(), "markets": markets, "events": events, "posts": posts}


# ---------------------------------------------------------------- the weekly recap's prices
WEEK_INDEXES = {"S&P 500": "^GSPC", "Nasdaq-100": "^NDX", "Dow": "^DJI", "Russell 2000": "^RUT", "VIX": "^VIX"}
WEEK_MARKETS = {"10-year yield": "^TNX", "dollar": "DX-Y.NYB", "oil": "CL=F"}
WEEK_SECTORS = {"Technology": "XLK", "Communication": "XLC", "Consumer Discretionary": "XLY", "Consumer Staples": "XLP", "Financials": "XLF",
                "Health Care": "XLV", "Industrials": "XLI", "Energy": "XLE", "Materials": "XLB", "Real Estate": "XLRE", "Utilities": "XLU"}


def week_data(feeds, end: date) -> dict:
    """Everything the weekly recap reads for the week ending `end` (see briefings/weekly.py). Each source may fail on its own."""
    bars = lambda table: {name: prices.yahoo_daily(sym) for name, sym in table.items()}
    try:
        w = feeds.screener.weights()
    except Exception:
        w = {}
    weights = {"S&P 500": w.get("ES") or {}, "Nasdaq-100": w.get("NQ") or {}}
    monday = end - timedelta(days=end.weekday())
    try:
        held = feeds.positioning.get().get("markets") or {}
    except Exception:
        held = {}
    return {"positioning": held, "indexes": bars(WEEK_INDEXES), "markets": bars(WEEK_MARKETS), "sectors": bars(WEEK_SECTORS), "weights": weights,
            "closes": weekinfo.closes(sorted({s for t in weights.values() for s in t})),
            "earnings": weekinfo.earnings(monday - timedelta(days=3), end), "economy": weekinfo.economy(monday, end),
            "headlines": weekinfo.headlines}


# ---------------------------------------------------------------- track record: the levels known before an open
PRE_OPEN_WINDOW = timedelta(hours=30)          # the plan must come from the evening before or later


def plan_input(market: str, s: dict, bias: dict | None) -> dict:
    """A stored summary (index points) in the shape the track record freezes (see trackrecord/score.py)."""
    X = s.get("extras") or {}
    em = X.get("expected_move") or {}
    return {"market": market, "underlying": s.get("underlying"), "asof": s.get("asof"), "ref": s.get("ref_price"),
            "em": em.get("daily_points"), "em_iv": em.get("daily_iv"), "regime": s.get("regime"), "net": s.get("net"),
            "zg": _p(s.get("zero_gamma")), "cw": _p(s.get("call_wall")), "pw": _p(s.get("put_wall")),
            "ag": _p(s.get("abs_gamma")), "bias": bias}


def open_paste(w, s: dict, d: date, open_: datetime) -> str | None:
    """The TradingView paste as it stood at d's 09:30 open, for backtesting: built from the same snapshot as the
    plan, marked bt=yyyymmdd (the indicator then labels it a backtest instead of stale and stays silent), with the
    closing levels of the sessions before it (H). No futures factor: the chart maps it live, like any paste."""
    try:
        p = export.pine_payload(s, w.cfg.market, w.cfg.source, w.cfg.method, provider=s.get("provider", ""))
    except (KeyError, TypeError, ValueError):
        return None
    prior = session.prior_levels(w.store.root / w.key, open_)
    return export.add_tokens(p, {"bt": f"{d:%Y%m%d}", "H": session.history_token(prior)})


def pre_open(gex, d: date) -> dict:
    """{market: plan input or None} from the last saved calculation timestamped before d's 09:30 ET open.

    Reads the snapshot files every worker saves, so it works the same in the local app and in the hosted
    build, and for a session that has already started. The bias is recomputed for that open."""
    open_ = datetime.combine(d, time(9, 30), marketcal.NY)
    lo = open_ - PRE_OPEN_WINDOW
    out: dict = {}
    for w in gex.workers.values():
        m = w.cfg.market
        if out.get(m):
            continue
        base = w.store.root / w.key
        best = None
        for day in {lo.astimezone(timezone.utc).date() + timedelta(days=i) for i in range(3)}:
            for f in sorted((base / day.strftime("%Y%m%d")).glob("*.json")):
                if f.name.endswith(".chain.json"):
                    continue
                try:
                    s = json.loads(f.read_text(encoding="utf-8"))
                    t = datetime.fromisoformat(s["asof"])
                except (OSError, ValueError, KeyError):
                    continue
                usable = s.get("status") != "UNAVAILABLE" and ((s.get("extras") or {}).get("expected_move") or {}).get("daily_points")
                if lo <= t < open_ and usable and (best is None or t > best[0]):
                    best = (t, s)
        if best:
            s = best[1]
            out[m] = dict(plan_input(m, s, bias.compute(s, open_ - timedelta(minutes=1))), paste=open_paste(w, s, d, open_))
        else:
            out.setdefault(m, None)
    return out
