"""CSV chain adapter - the integration path for any licensed source without a
built-in adapter, notably CME ES/NQ futures options (e.g. Databento GLBX.MDP3
definitions + statistics + quotes, or CME DataMine), exported to this schema.

Required columns: root, type (C|P), strike, expiration (YYYY-MM-DD), multiplier,
open_interest
Optional columns: symbol, expiration_time (ISO with offset), bid, ask, last,
quote_time (ISO), iv, gamma, delta, volume, underlying_price, underlying_time (ISO)

The user must declare quality labels in config (quote_quality, greeks_quality);
they default to the most conservative honest labels.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .. import marketcal
from ..mapping import SOURCES
from ..models import ChainSnapshot, OptionContract, OptionType, Quality
from .base import Provider, ProviderError

REQUIRED = {"root", "type", "strike", "expiration", "multiplier", "open_interest"}


def _f(x) -> Optional[float]:
    if x is None or str(x).strip() == "":
        return None
    try:
        return float(x)
    except ValueError:
        return None


def _dt(x) -> Optional[datetime]:
    if not x or not str(x).strip():
        return None
    d = datetime.fromisoformat(str(x).strip().replace("Z", "+00:00"))
    if d.tzinfo is None:
        raise ProviderError(f"timestamp without timezone: {x!r}")
    return d


class CsvProvider(Provider):
    name = "csv"

    def __init__(self, path: str, quote_quality: str = "DL", greeks_quality: str = "PROV",
                 spot_quality: str = "DL", rate: float = 0.04, div_yield: float = 0.0):
        self.path = Path(path)
        self.quote_quality = Quality(quote_quality)
        self.greeks_quality = Quality(greeks_quality)
        self.spot_quality = Quality(spot_quality)
        self.rate, self.div_yield = rate, div_yield

    def fetch_snapshot(self, source_key: str, max_dte: float = 1e9, include_0dte: bool = True) -> ChainSnapshot:
        src = SOURCES[source_key]
        if not self.path.exists():
            raise ProviderError(f"chain file not found: {self.path}")
        contracts, spot, spot_time, bad = [], None, None, 0
        with self.path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            missing = REQUIRED - set(reader.fieldnames or [])
            if missing:
                raise ProviderError(f"CSV missing required columns: {sorted(missing)}")
            for row in reader:
                try:
                    root = row["root"].strip()
                    exp = _dt(row.get("expiration_time")) or marketcal.option_expiry_time(
                        datetime.strptime(row["expiration"].strip(), "%Y-%m-%d").date(), root)
                    gamma = _f(row.get("gamma"))
                    c = OptionContract(
                        symbol=(row.get("symbol") or "").strip() or f"{root}-{row['expiration']}-{row['type']}-{row['strike']}",
                        root=root, underlying=src.vendor_symbol, option_type=OptionType(row["type"].strip().upper()),
                        strike=float(row["strike"]), expiration=exp, multiplier=float(row["multiplier"]),
                        open_interest=_f(row.get("open_interest")), volume=_f(row.get("volume")),
                        bid=_f(row.get("bid")), ask=_f(row.get("ask")), last=_f(row.get("last")),
                        last_time=_dt(row.get("quote_time")), iv=_f(row.get("iv")), gamma=gamma,
                        delta=_f(row.get("delta")), quote_quality=self.quote_quality, oi_quality=Quality.EOD,
                        greeks_quality=self.greeks_quality if gamma is not None else Quality.MISSING,
                        exercise_style=src.exercise)
                except (ValueError, KeyError, ProviderError):
                    bad += 1
                    continue
                contracts.append(c)
                up, ut = _f(row.get("underlying_price")), _dt(row.get("underlying_time"))
                if up and (spot_time is None or (ut and ut > spot_time)):
                    spot, spot_time = up, ut
        warnings = [f"CSV quality labels declared by user: quotes={self.quote_quality.value}, "
                    f"greeks={self.greeks_quality.value}"]
        if bad:
            warnings.append(f"csv: {bad} unparseable rows skipped")
        return ChainSnapshot(underlying=src.vendor_symbol, source_kind=src.kind, spot=spot, spot_time=spot_time,
                             spot_quality=self.spot_quality if spot else Quality.MISSING, contracts=contracts,
                             source=f"csv:{self.path.name}", fetched_at=datetime.now(timezone.utc),
                             rate=self.rate, div_yield=self.div_yield, warnings=warnings)
