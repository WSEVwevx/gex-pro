"""Scheduled publishing of TradingView payloads.

Pine cannot pull data, so "levels that update every hour" is implemented as:
the service recalculates continuously, and at fixed ET publish times it freezes
a payload, notifies the user (Windows toast and/or webhook), and exposes it at
/api/pine?market=X&which=published and on the dashboard's Copy button.
The user pastes it into the indicator (about 10 seconds).

Publish slots are ET wall-clock times on trading days. Default: every hour on the hour, around
the clock (all_day=True), since the futures trade overnight. With all_day=False, slots at or after
the cash close (16:00, or an early close) are skipped. Weekends and holidays have no slots: the
options data doesn't change then. zoneinfo handles DST.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Optional

from . import marketcal
from .engine import ConfigError

log = logging.getLogger("gexsys.publish")


@dataclass
class PublishConfig:
    times_et: list[str] = field(default_factory=lambda: [f"{h:02d}:00" for h in range(24)])
    all_day: bool = True             # False: only slots before the cash close (16:00 / early close)
    desktop_notify: bool = True
    webhook_format: str = "json"     # json | discord | none

    def slots(self) -> list[time]:
        out = []
        for t in self.times_et:
            try:
                hh, mm = t.split(":")
                out.append(time(int(hh), int(mm)))
            except (ValueError, TypeError) as e:
                raise ConfigError(f"publish.times_et entry {t!r} is not HH:MM") from e
        return sorted(out)

    def validate(self) -> None:
        self.slots()
        if self.webhook_format not in ("json", "discord", "none"):
            raise ConfigError("publish.webhook_format must be json | discord | none")


def _day_slots(d, cfg: PublishConfig) -> list[datetime]:
    if not marketcal.is_trading_day(d):
        return []
    close = marketcal.rth_close(d)
    return [datetime.combine(d, s, marketcal.NY) for s in cfg.slots() if cfg.all_day or s < close]


def latest_slot(now: datetime, cfg: PublishConfig) -> Optional[datetime]:
    """Most recent publish slot at or before `now` (looks back up to 10 days)."""
    d = now.astimezone(marketcal.NY).date()
    for back in range(11):
        past = [s for s in _day_slots(d - timedelta(days=back), cfg) if s <= now]
        if past:
            return past[-1]
    return None


def next_slot(now: datetime, cfg: PublishConfig) -> Optional[datetime]:
    d = now.astimezone(marketcal.NY).date()
    for ahead in range(11):
        fut = [s for s in _day_slots(d + timedelta(days=ahead), cfg) if s > now]
        if fut:
            return fut[0]
    return None


def due(last_published_slot: Optional[datetime], now: datetime, cfg: PublishConfig) -> Optional[datetime]:
    """Return the slot to publish now, or None if the latest slot was already published."""
    s = latest_slot(now, cfg)
    if s is None or (last_published_slot is not None and last_published_slot >= s):
        return None
    return s


def notify_desktop(title: str, body: str) -> bool:
    """Best-effort Windows toast via PowerShell WinRT (no extra modules). Text passed via env vars."""
    if sys.platform != "win32":
        log.info("NOTIFY %s: %s", title, body)
        return False
    script = (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null;"
        "$t=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
        "$n=$t.GetElementsByTagName('text');"
        "$n.Item(0).AppendChild($t.CreateTextNode($env:GEX_TOAST_TITLE)) > $null;"
        "$n.Item(1).AppendChild($t.CreateTextNode($env:GEX_TOAST_BODY)) > $null;"
        "$id='{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe';"
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($id).Show([Windows.UI.Notifications.ToastNotification]::new($t))"
    )
    env = dict(os.environ, GEX_TOAST_TITLE=title[:120], GEX_TOAST_BODY=body[:250])
    try:
        subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script], env=env,
                       timeout=20, capture_output=True, check=False)
        return True
    except (OSError, subprocess.SubprocessError) as e:
        log.error("desktop notification failed: %s", e)
        return False


def webhook_body(fmt: str, market: str, payload: str, info: dict) -> dict:
    if fmt == "discord":
        head = (f"**{market} GEX update** ({info.get('slot_et', '')} ET) - regime {info.get('regime')}, "
                f"zero gamma {info.get('zero_gamma')}. Paste into the TradingView indicator:\n")
        return {"content": (head + "```" + payload + "```")[:1990]}
    return {"type": "publish", "market": market, "payload": payload, **info}


def send_webhook(url: str, body: dict) -> bool:
    try:
        req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "User-Agent": "gexsys"})
        urllib.request.urlopen(req, timeout=10).close()
        return True
    except OSError as e:
        log.error("publish webhook failed: %s", e)
        return False
