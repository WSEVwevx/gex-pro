"""Market configuration loading and strict validation.

Unknown keys are rejected so that a typo can never silently fall back to a
default and produce plausible-looking but wrong levels.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Optional

from .alerts import AlertConfig
from .engine import ConfigError, EngineConfig
from .levels import LevelConfig
from .mapping import FUTURES, SOURCES
from .marketcal import RefreshPolicy
from .publish import PublishConfig

TOP_KEYS = {"market", "source", "provider", "engine", "levels", "mapping", "futures_ref", "refresh",
            "alerts", "storage", "description", "publish"}
PROVIDERS = {"tradier", "csv", "synthetic", "cboe"}
FREE_INDEX_SOURCES = {"SPX", "NDX", "SPY", "QQQ"}


def _build(cls, data: dict, section: str):
    names = {f.name for f in fields(cls)}
    bad = set(data) - names
    if bad:
        raise ConfigError(f"[{section}] unknown keys: {sorted(bad)} (valid: {sorted(names)})")
    return cls(**data)


@dataclass
class MarketConfig:
    market: str
    source: str
    provider: dict
    engine: EngineConfig = field(default_factory=EngineConfig)
    levels: LevelConfig = field(default_factory=LevelConfig)
    mapping: dict = field(default_factory=dict)
    futures_ref: dict = field(default_factory=lambda: {"mode": "none"})
    refresh: RefreshPolicy = field(default_factory=RefreshPolicy)
    alerts: AlertConfig = field(default_factory=AlertConfig)
    storage: dict = field(default_factory=lambda: {"root": "data/snapshots", "store_raw": False})
    description: str = ""
    publish: PublishConfig = field(default_factory=PublishConfig)

    @property
    def method(self) -> str:
        return self.mapping.get("method") or SOURCES[self.source].default_method

    def validate(self) -> "MarketConfig":
        if self.market not in FUTURES:
            raise ConfigError(f"market must be one of {sorted(FUTURES)}")
        if self.source not in SOURCES:
            raise ConfigError(f"source must be one of {sorted(SOURCES)}")
        src, fut = SOURCES[self.source], FUTURES[self.market]
        if src.tracks != fut.full_size_root:
            raise ConfigError(f"source {self.source} tracks {src.tracks}; it cannot drive {self.market}")
        if self.method not in src.allowed_methods:
            raise ConfigError(f"mapping.method {self.method!r} not allowed for {self.source}: {src.allowed_methods}")
        bad = set(self.mapping) - {"method", "max_skew_s", "calendar_spread"}
        if bad:
            raise ConfigError(f"[mapping] unknown keys: {sorted(bad)}")
        name = self.provider.get("name")
        if name not in PROVIDERS:
            raise ConfigError(f"provider.name must be one of {sorted(PROVIDERS)}")
        if name == "tradier" and src.kind.value == "FUT":
            raise ConfigError("Tradier has no CME futures options; use provider 'csv' for NQ_FOP/ES_FOP")
        if name == "csv" and not self.provider.get("path"):
            raise ConfigError("csv provider requires provider.path")
        if name == "cboe" and self.source not in FREE_INDEX_SOURCES:
            raise ConfigError(f"{name} provider supports sources {sorted(FREE_INDEX_SOURCES)}")
        mode = self.futures_ref.get("mode", "none")
        if mode not in ("none", "manual", "synthetic_basis", "carry"):
            raise ConfigError("futures_ref.mode must be none | manual | synthetic_basis | carry")
        if mode == "synthetic_basis" and name != "synthetic":
            raise ConfigError("futures_ref.mode synthetic_basis is only allowed with the synthetic provider")
        if mode == "carry" and src.kind.value != "INDEX":
            raise ConfigError("futures_ref.mode carry needs a cash-index source (SPX or NDX)")
        self.engine.validate()
        self.publish.validate()
        return self


def load(path: str | Path) -> MarketConfig:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return from_dict(raw)


def from_dict(raw: dict) -> MarketConfig:
    bad = set(raw) - TOP_KEYS
    if bad:
        raise ConfigError(f"unknown top-level keys: {sorted(bad)}")
    for req in ("market", "source", "provider"):
        if req not in raw:
            raise ConfigError(f"missing required key {req!r}")
    cfg = MarketConfig(
        market=raw["market"], source=raw["source"], provider=raw["provider"],
        engine=_build(EngineConfig, raw.get("engine", {}), "engine"),
        levels=_build(LevelConfig, raw.get("levels", {}), "levels"),
        mapping=raw.get("mapping", {}), futures_ref=raw.get("futures_ref", {"mode": "none"}),
        refresh=_build(RefreshPolicy, raw.get("refresh", {}), "refresh"),
        alerts=_build(AlertConfig, raw.get("alerts", {}), "alerts"),
        storage=raw.get("storage", {"root": "data/snapshots", "store_raw": False}),
        description=raw.get("description", ""),
        publish=_build(PublishConfig, raw.get("publish", {}), "publish"),
    )
    return cfg.validate()


def make_provider(cfg: MarketConfig):
    p = dict(cfg.provider)
    name = p.pop("name")
    if name == "tradier":
        from .providers.tradier import TradierProvider
        return TradierProvider(requests_per_minute=float(p.get("requests_per_minute", 60)))
    if name == "csv":
        from .providers.csvfile import CsvProvider
        return CsvProvider(**p)
    if name == "cboe":
        from .providers.cboe import CboeProvider
        return CboeProvider(**p)
    from .providers.synthetic import SyntheticProvider
    return SyntheticProvider(**p)


def load_dotenv(path: Optional[str] = ".env") -> None:
    """Minimal .env loader (KEY=VALUE lines); existing environment variables win."""
    import os
    if not path or not Path(path).exists():
        return
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
