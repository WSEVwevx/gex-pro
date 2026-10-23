from datetime import datetime, timedelta, timezone

from gexsys.models import ChainSnapshot, OptionContract, OptionType, Quality, SourceKind

ASOF = datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc)   # Tue 11:00 ET


def contract(k, typ="C", oi=1000.0, gamma=None, iv=0.2, days=7.0, mult=100.0, root="TST",
             bid=None, ask=None, asof=ASOF, exp=None, symbol=None):
    exp = exp or (asof + timedelta(days=days))
    return OptionContract(symbol=symbol or f"{root}-{k}-{typ}-{exp:%Y%m%d}", root=root, underlying="TST",
                          option_type=OptionType(typ), strike=float(k), expiration=exp, multiplier=mult,
                          open_interest=oi, iv=iv, gamma=gamma, bid=bid, ask=ask,
                          quote_quality=Quality.SYNTHETIC, oi_quality=Quality.SYNTHETIC,
                          greeks_quality=Quality.SYNTHETIC if gamma is not None else Quality.MISSING)


def chain(contracts, spot=100.0, kind=SourceKind.INDEX, spot_time=ASOF, rate=0.0, q=0.0):
    return ChainSnapshot(underlying="TST", source_kind=kind, spot=spot, spot_time=spot_time,
                         spot_quality=Quality.SYNTHETIC, contracts=list(contracts), source="test",
                         fetched_at=ASOF, rate=rate, div_yield=q)
