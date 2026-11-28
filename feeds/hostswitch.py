"""One switch per outside host: GEX_OFF_HOSTS="api.nasdaq.com,other.host" keeps this computer off those hosts.

START.bat sets it for the local app; the hosted build (GitHub's servers) leaves it empty. A switched-off source reads
"unavailable: <host> is switched off on this computer" on the website and in Data health, never as a failure to retry.
"""
from __future__ import annotations

import os
import urllib.parse
from typing import Optional


def off_hosts() -> set:
    return {h.strip().lower() for h in os.environ.get("GEX_OFF_HOSTS", "").split(",") if h.strip()}


def why_off(url: str) -> Optional[str]:
    """The reason url may not be requested from here, or None."""
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    return f"{host} is switched off on this computer (GEX_OFF_HOSTS)" if host and host in off_hosts() else None


class HostOff(RuntimeError):
    pass


def check(url: str) -> None:
    why = why_off(url)
    if why:
        raise HostOff(why)
