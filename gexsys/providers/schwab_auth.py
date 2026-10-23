"""Schwab Trader API OAuth (authorization-code flow) with token storage and refresh.

From the schwab-py source and docs (checked 2026-10-21):
  authorize: https://api.schwabapi.com/v1/oauth/authorize   (client_id, redirect_uri, response_type=code)
  token:     https://api.schwabapi.com/v1/oauth/token        (HTTP Basic app_key:app_secret;
             grant_type=authorization_code | refresh_token)
  callback must EXACTLY match the app's registered URL; host 127.0.0.1, https, port > 1024
  (recommended https://127.0.0.1:8182).  Access token lives 30 minutes, refresh token 7 days;
  after that the user must log in again.

Tokens are stored OUTSIDE the project folder (which OneDrive syncs):
  %LOCALAPPDATA%/gexsys/schwab_token.json
Credentials come from the environment / .env: SCHWAB_APP_KEY, SCHWAB_APP_SECRET, SCHWAB_CALLBACK_URL.
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from .base import AuthError, ProviderError

AUTH_URL = "https://api.schwabapi.com/v1/oauth/authorize"
TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"
DEFAULT_CALLBACK = "https://127.0.0.1:8182"
REFRESH_LIFETIME_S = 7 * 86400
LEEWAY_S = 300


def _local_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or str(Path.home())) / "gexsys"


def token_path() -> Path:
    return Path(os.environ.get("SCHWAB_TOKEN_PATH") or _local_dir() / "schwab_token.json")


def local_env_path() -> Path:
    """Per-PC settings file for secrets (not inside the OneDrive-synced project folder)."""
    return _local_dir() / ".env"


def credentials() -> tuple[str, str, str]:
    key, secret = os.environ.get("SCHWAB_APP_KEY", ""), os.environ.get("SCHWAB_APP_SECRET", "")
    if not key or not secret or "replace" in key.lower():
        raise AuthError("SCHWAB_APP_KEY / SCHWAB_APP_SECRET are not set - see docs/SCHWAB_SETUP.md")
    return key, secret, os.environ.get("SCHWAB_CALLBACK_URL", DEFAULT_CALLBACK)


def authorize_url(app_key: str, callback: str, state: Optional[str] = None) -> tuple[str, str]:
    state = state or secrets.token_urlsafe(16)
    q = urllib.parse.urlencode({"response_type": "code", "client_id": app_key, "redirect_uri": callback, "state": state})
    return f"{AUTH_URL}?{q}", state


def code_from_redirect(url: str, expected_state: Optional[str] = None) -> str:
    """Pull the authorization code out of the URL the browser was redirected to.
    parse_qs percent-decodes it (Schwab codes end in an encoded '@')."""
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url.strip()).query)
    if "error" in q:
        raise AuthError(f"Schwab login refused: {q['error'][0]}")
    if expected_state and q.get("state", [expected_state])[0] != expected_state:
        raise AuthError("login state mismatch - start the login again")
    code = (q.get("code") or [""])[0]
    if not code:
        raise AuthError("no ?code= in that URL - copy the FULL address from the browser bar after logging in")
    return code


def _post_token(form: dict, app_key: str, app_secret: str, opener: Callable = urllib.request.urlopen) -> dict:
    basic = base64.b64encode(f"{app_key}:{app_secret}".encode()).decode()
    req = urllib.request.Request(TOKEN_URL, data=urllib.parse.urlencode(form).encode(), method="POST",
                                 headers={"Authorization": f"Basic {basic}",
                                          "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with opener(req, timeout=20) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode()[:200]
        except Exception:
            pass
        if e.code in (400, 401):
            raise AuthError(f"Schwab token request rejected (HTTP {e.code}) {detail} - run SCHWAB_LOGIN.bat again") from e
        raise ProviderError(f"Schwab token endpoint HTTP {e.code}") from e
    except (urllib.error.URLError, OSError) as e:
        raise ProviderError(f"Schwab token endpoint unreachable: {e}") from e


class TokenStore:
    def __init__(self, path: Optional[Path] = None, clock: Callable[[], float] = time.time,
                 opener: Callable = urllib.request.urlopen):
        self.path = path or token_path()
        self.clock, self.opener = clock, opener

    def load(self) -> Optional[dict]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def save(self, tok: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(tok), encoding="utf-8")
        os.replace(tmp, self.path)

    def _stamp(self, resp: dict, refresh_issued: Optional[float]) -> dict:
        now = self.clock()
        if not resp.get("access_token"):
            raise AuthError("Schwab token response had no access_token")
        return {"access_token": resp["access_token"],
                "refresh_token": resp.get("refresh_token"),
                "expires_at": now + float(resp.get("expires_in", 1800)),
                "refresh_issued_at": refresh_issued if refresh_issued is not None else now}

    def exchange_code(self, code: str) -> dict:
        key, secret, cb = credentials()
        tok = self._stamp(_post_token({"grant_type": "authorization_code", "code": code, "redirect_uri": cb},
                                      key, secret, self.opener), None)
        self.save(tok)
        return tok

    def status(self) -> dict:
        t = self.load()
        if not t:
            return {"logged_in": False, "reason": "no token - run SCHWAB_LOGIN.bat"}
        left = t["refresh_issued_at"] + REFRESH_LIFETIME_S - self.clock()
        return {"logged_in": left > 0, "refresh_days_left": round(left / 86400, 2),
                "reason": "" if left > 0 else "7-day login expired - run SCHWAB_LOGIN.bat"}

    def access_token(self) -> str:
        t = self.load()
        if not t:
            raise AuthError("not logged in to Schwab - run SCHWAB_LOGIN.bat")
        if t["refresh_issued_at"] + REFRESH_LIFETIME_S <= self.clock():
            raise AuthError("Schwab's 7-day login expired - run SCHWAB_LOGIN.bat")
        if t["expires_at"] - LEEWAY_S > self.clock():
            return t["access_token"]
        key, secret, _ = credentials()
        resp = _post_token({"grant_type": "refresh_token", "refresh_token": t["refresh_token"]}, key, secret, self.opener)
        new = self._stamp(resp, t["refresh_issued_at"])          # the 7-day clock does not restart on refresh
        new["refresh_token"] = new["refresh_token"] or t["refresh_token"]
        self.save(new)
        return new["access_token"]
