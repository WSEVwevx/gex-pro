"""Stress test B2: how far zero gamma moves when the inputs move a little (live Cboe chains, NQ and ES).

  python tools/stress/zero_gamma_sensitivity.py

Perturbations: every IV +/-1 vol point; the reference price +/-0.25%; open interest x(1 +/- 5%) uniformly and
randomly per contract (3 seeds); the price-grid step halved and doubled. Zero gamma is a property of the
market's positioning, so none of these small changes should move it much.
Tolerance (fixed before running): a move of more than 0.1 daily expected moves (sigma) is numerically unstable.
"""
from __future__ import annotations

import dataclasses
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import verify_math as vm  # noqa: E402
from gexsys import config as cfgmod, engine as eng  # noqa: E402
from gexsys.extras import compute_extras  # noqa: E402
from gexsys.normalize import normalize  # noqa: E402
from gexsys.providers.cboe import CboeProvider  # noqa: E402

TOL_SIGMA = 0.1


def snapshot(cfg, raw):
    prov = CboeProvider(http=lambda url, headers, limiter=None: raw[url.rsplit("/", 1)[1][:-5]], include_etf=True)
    return normalize(prov.fetch_snapshot(cfg.source, cfg.engine.max_dte, cfg.engine.include_0dte), check_occ=True)


def zg(snap, ecfg):
    res = eng.compute(snap, ecfg, asof=snap.fetched_at)
    return res.zero_gamma, res


def main() -> int:
    fails = 0
    for cfgp, si, se in (("configs/free_nq_cboe.json", "_NDX", "QQQ"), ("configs/free_es_cboe.json", "_SPX", "SPY")):
        cfg = cfgmod.load(cfgp)
        raw = {si: vm.fetch(si), se: vm.fetch(se)}
        snap = snapshot(cfg, raw)
        ecfg = dataclasses.replace(cfg.engine, max_spot_age_s=400 * 86400)
        base, res = zg(snap, ecfg)
        em = compute_extras(snap, ecfg, res)["expected_move"]["daily_points"]
        print(f"\n{cfg.market}: zero gamma {base:.2f}, daily expected move {em:.1f} pts, tolerance {TOL_SIGMA * em:.1f} pts")
        cases = []
        for d in (+0.01, -0.01):
            cs = [dataclasses.replace(c, iv=c.iv + d) if c.iv else c for c in snap.contracts]
            cases.append((f"every IV {d * 100:+.0f} vol pt", dataclasses.replace(snap, contracts=cs), ecfg))
        for f in (1.0025, 0.9975):
            cases.append((f"reference price {(f - 1) * 100:+.2f}%", dataclasses.replace(snap, spot=snap.spot * f), ecfg))
        for f in (1.05, 0.95):
            cs = [dataclasses.replace(c, open_interest=c.open_interest * f) if c.open_interest else c for c in snap.contracts]
            cases.append((f"all open interest x{f}", dataclasses.replace(snap, contracts=cs), ecfg))
        for seed in (1, 2, 3):
            rng = random.Random(seed)
            cs = [dataclasses.replace(c, open_interest=c.open_interest * rng.uniform(0.95, 1.05)) if c.open_interest else c
                  for c in snap.contracts]
            cases.append((f"open interest +/-5% at random (seed {seed})", dataclasses.replace(snap, contracts=cs), ecfg))
        for steps, name in ((401, "grid step halved"), (101, "grid step doubled")):
            cases.append((name, snap, dataclasses.replace(ecfg, grid_steps=steps)))
        for name, s2, e2 in cases:
            z, _ = zg(s2, e2)
            if z is None or base is None:
                ok, txt = (z is None) == (base is None), f"{z}"
            else:
                move = abs(z - base)
                ok, txt = move <= TOL_SIGMA * em, f"{z:.2f}  moved {move:6.2f} pts = {move / em:.3f} sigma"
            fails += not ok
            print(f"  {'PASS' if ok else 'FAIL'}  {name:40s} {txt}")
    print(f"\n{'ALL PASS' if not fails else f'{fails} unstable'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
