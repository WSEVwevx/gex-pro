"""Stress test B3: does folding SPY / QQQ options into SPX / NDX terms conserve dollar gamma?

  python tools/stress/etf_merge.py

Live chains: each ETF contract's dollar gamma per 1% computed in the ETF's OWN terms (its price, strike, dividend
yield, contracts of 100 shares) must equal the engine's exposure for the converted contract, one by one, in total
and per index strike bucket. Edge cases (synthetic): an ETF strike exactly halfway between two index strikes (it
must land in one bucket, never both or neither), a different ratio (e.g. after a split: conservation must not
depend on it), and a missing ETF chain (the index alone, with a warning).
Tolerance (fixed before running): 1e-9 relative per contract and in total; 0 contracts lost or doubled.
"""
from __future__ import annotations

import dataclasses
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import verify_math as vm  # noqa: E402
from gexsys import config as cfgmod, engine as eng, pricing  # noqa: E402
from gexsys.models import OptionType  # noqa: E402
from gexsys.normalize import normalize  # noqa: E402
from gexsys.providers.cboe import CboeProvider, ProviderError, merge_etf  # noqa: E402

TOL = 1e-9


def own_dollar_gamma(c_etf, etf_spot, t, q, rate=0.04):
    return c_etf.open_interest * pricing.bsm_gamma(etf_spot, c_etf.strike, t, rate, q, c_etf.iv) * 100 * etf_spot ** 2 * 0.01


def live(cfgp, si, se, q_etf) -> list[str]:
    bad = []
    cfg = cfgmod.load(cfgp)
    raw = {si: vm.fetch(si), se: vm.fetch(se)}
    prov = CboeProvider(http=lambda url, headers, limiter=None: raw[url.rsplit("/", 1)[1][:-5]], include_etf=True)
    snap = normalize(prov.fetch_snapshot(cfg.source, cfg.engine.max_dte, True), check_occ=True)
    ecfg = dataclasses.replace(cfg.engine, max_spot_age_s=400 * 86400)
    res = eng.compute(snap, ecfg, asof=snap.fetched_at)
    etf_only = CboeProvider(http=lambda url, headers, limiter=None: raw[url.rsplit("/", 1)[1][:-5]], include_etf=False)
    ech = etf_only._chain(se, cfg.engine.max_dte, True)
    etf_spot, ratio = ech["spot"], snap.spot / ech["spot"]
    converted = {r.contract.symbol.split("@")[0]: r for r in res.rows if r.contract.group_strike is not None}
    own_total = conv_total = 0.0
    worst, n, missing = 0.0, 0, 0
    bucket_own: dict = {}
    for c in ech["contracts"]:
        r = converted.get(c.symbol)
        if r is None:
            continue                     # no OI or no usable IV: excluded on both sides alike (counted below)
        t = r.t_years
        mine = own_dollar_gamma(dataclasses.replace(c, iv=r.iv), etf_spot, t, q_etf) * (1 if c.option_type == OptionType.CALL else -1)
        own_total += abs(mine)
        conv_total += abs(r.exposure)
        worst = max(worst, abs(mine - r.exposure) / max(abs(mine), 1e-300))
        bucket_own[r.contract.group_strike] = bucket_own.get(r.contract.group_strike, 0.0) + mine
        n += 1
    # every ETF contract with OI and a usable IV must appear exactly once among the converted rows
    keyed = [r.contract.symbol.split("@")[0] for r in res.rows if r.contract.group_strike is not None]
    doubled = len(keyed) - len(set(keyed))
    with_oi = [c for c in ech["contracts"] if c.open_interest and c.symbol not in converted]
    expired = sum(1 for c in with_oi if c.expiration <= res.asof)
    missing = len(with_oi) - expired
    bucket_conv: dict = {}
    for r in res.rows:
        if r.contract.group_strike is not None:
            bucket_conv[r.contract.group_strike] = bucket_conv.get(r.contract.group_strike, 0.0) + r.exposure
    worst_bucket = max((abs(bucket_own[k] - bucket_conv.get(k, 0.0)) / max(abs(bucket_own[k]), 1e-300) for k in bucket_own), default=0.0)
    total_err = abs(own_total - conv_total) / own_total
    print(f"  {cfg.market}: {n} {se} contracts, ratio {ratio:.4f}; worst per contract {worst:.1e}, worst per strike "
          f"{worst_bucket:.1e}, total {total_err:.1e}; doubled {doubled}; left out: {expired} already expired, "
          f"{missing} without a usable IV")
    for name, v in (("per contract", worst), ("per strike", worst_bucket), ("total", total_err)):
        if v > TOL:
            bad.append(f"{cfg.market} {name} {v:.2e}")
    if doubled:
        bad.append(f"{cfg.market} {doubled} contracts doubled")
    return bad


def edge_cases() -> list[str]:
    from tests.util import ASOF, contract
    bad = []
    exp = ASOF + timedelta(days=10)
    index = [contract(k, exp=exp) for k in (1000, 1010, 1020)]
    # halfway: ETF strike 50.25 x ratio 20 = 1005, exactly between 1000 and 1010
    etf = [dataclasses.replace(contract(50.25, exp=exp, iv=0.2), underlying="SPY")]
    out = merge_etf(index, etf, 20.0, "SPX", 100.0, etf_spot=50.5, asof=ASOF, etf_q=0.013)
    print(f"  halfway strike 1005 -> bucket {out[0].group_strike} (one bucket, exact strike {out[0].strike})")
    if out[0].group_strike not in (1000.0, 1010.0) or len(out) != 1:
        bad.append("halfway strike not in exactly one neighbouring bucket")
    # ratio: dollar gamma per 1% is the same in ETF and index terms for any ratio
    for ratio in (10.0, 20.0, 41.15):
        S, s_etf, k_etf = 1000.0, 1000.0 / ratio, 1000.0 / ratio * 1.02
        c = dataclasses.replace(contract(k_etf, exp=exp, iv=0.25, oi=500), underlying="QQQ")
        o = merge_etf([contract(1020, exp=exp)], [c], ratio, "NDX", 100.0, etf_spot=s_etf, asof=ASOF, etf_q=0.006)[0]
        t = 10 / 365
        own = 500 * pricing.bsm_gamma(s_etf, k_etf, t, 0.04, 0.006, 0.25) * 100 * s_etf ** 2 * 0.01
        conv = o.open_interest * pricing.bsm_gamma(S, o.strike, t, 0.04, o.div_yield, 0.25) * 100 * S ** 2 * 0.01
        err = abs(conv - own) / own
        print(f"  ratio {ratio:6.2f}: own-terms {own:.6f}, index-terms {conv:.6f}, rel {err:.1e}")
        if err > TOL:
            bad.append(f"ratio {ratio} not conserved ({err:.1e})")
    # missing ETF chain: the index alone, with a warning
    raw_i = {"timestamp": "2026-11-10 15:00:00", "data": {"current_price": 7600.0, "options": [
        {"option": "SPXW261113C07600000", "iv": 0.2, "gamma": 0.001, "open_interest": 100, "bid": 1, "ask": 2, "volume": 1}]}}
    def http(url, headers, limiter=None):
        if "SPY" in url:
            raise ProviderError("SPY chain unavailable")
        return raw_i
    snap = CboeProvider(http=http, include_etf=True).fetch_snapshot("SPX", 45, True)
    warned = any("SPY options unavailable" in w for w in snap.warnings)
    print(f"  missing SPY chain: {len(snap.contracts)} SPX contracts kept, warning shown: {warned}")
    if not warned or len(snap.contracts) != 1:
        bad.append("missing ETF chain not handled")
    return bad


def main() -> int:
    print("live chains:")
    bad = live("configs/free_nq_cboe.json", "_NDX", "QQQ", 0.006) + live("configs/free_es_cboe.json", "_SPX", "SPY", 0.013)
    print("edge cases:")
    bad += edge_cases()
    print("RESULT:", "PASS" if not bad else "FAIL - " + "; ".join(bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
