"""Recent Donald Trump posts (Truth Social), for the website's News tab.

Primary: Truth Social's public, Mastodon-compatible API for the @realDonaldTrump account
  GET https://truthsocial.com/api/v1/accounts/107780257626128497/statuses?limit=20&exclude_replies=true
Fallback: the public RSS feed of trumpstruth.org, an archive of the same posts
  GET https://www.trumpstruth.org/feed
(Both checked 2026-10-21.) Fetched at most every `ttl_s` (default 5 min); the last good copy is kept in
memory and on disk (%LOCALAPPDATA%/gexsys/truth_posts.json). Personal use; text is shown as plain text.

Posts mentioning market-moving topics (tariffs, the Fed, China, ...) are flagged so they stand out, and
tagged bullish or bearish when their keywords clearly lean one way (see market_tone).
"""
from __future__ import annotations

import html
import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger("feeds.truthsocial")
API_URL = "https://truthsocial.com/api/v1/accounts/107780257626128497/statuses?limit=20&exclude_replies=true"
RSS_URL = "https://www.trumpstruth.org/feed"
UA = {"User-Agent": "Mozilla/5.0 (gexsys personal use)", "Accept": "application/json, application/xml, */*"}
MARKET_WORDS = ("tariff", "fed", "powell", "rate", "interest", "inflation", "china", "trade", "deal", "sanction",
                "oil", "stock", "market", "dollar", "economy", "tax", "debt", "shutdown", "war", "nvidia", "apple",
                "chip", "semiconductor", "crypto", "bitcoin", "jobs", "recession", "treasury", "bond")
_WORD_RE = re.compile(r"\b(" + "|".join(MARKET_WORDS) + r")s?\b", re.I)


class _Text(HTMLParser):
    """HTML -> plain text: paragraphs and <br> become line breaks; quote-link spans are dropped."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        cls = dict(attrs).get("class") or ""
        if self._skip or (tag == "span" and "quote-inline" in cls):
            self._skip += 1
        elif tag == "br":
            self.out.append("\n")

    def handle_endtag(self, tag):
        if self._skip:
            self._skip -= 1
        elif tag == "p":
            self.out.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.out.append(data)


def html_to_text(s: str) -> str:
    p = _Text()
    p.feed(s or "")
    return re.sub(r"\n{3,}", "\n\n", "".join(p.out)).strip()


def market_words(text: str) -> list[str]:
    return sorted({m.group(1).lower() for m in _WORD_RE.finditer(text or "")})


# Rough read of what a post means for US stocks: keyword phrases, each with a weight. A post gets a tone
# only when it already mentions a market topic and the weights clearly lean one way. A keyword guess,
# not a forecast: negation and sarcasm are not understood.
_BULL = [(re.compile(p, re.I), w) for p, w in (
    (r"\b(trade )?deals?\b|\bagreements?\b|\bframework\b", 1),
    (r"\bceasefire\b|\bpeace\b|\btruce\b", 1),
    (r"\brate cuts?\b|\bcut(ting)? (interest )?rates\b|\blower (interest )?rates\b", 1),
    (r"\btax cuts?\b|\bstimulus\b|\brebate", 1),
    (r"\b(record|all[- ]time) highs?\b|\bboom\w*|\bsoar\w*|\bsurg\w*|\brally\w*", 1),
    (r"\b(paus\w*|lift\w*|remov\w*|suspend\w*|reduc\w*|lower\w*|delay\w*|exempt\w*)\s+(\w+\s+){0,2}tariffs?\b"
     r"|\btariffs?\s+(pause|relief|exemptions?|reduction)", 2),
)]
_BEAR = [(re.compile(p, re.I), w) for p, w in (
    (r"\b(new|impos\w*|rais\w*|increas\w*|hik\w*|higher|additional|massive|big|\d+\s?%)\s+tariffs?\b"
     r"|\btariffs?\s+(on|against)\b", 1),
    (r"\bsanctions?\b|\bembargo", 1),
    (r"\bwar\b|\battack\w*|\bstrikes?\b|\bmissiles?\b|\binvasion\b", 1),
    (r"\bshutdown\b|\brecession\b|\bdefault\b|\bcrash\w*|\bcollaps\w*", 1),
    (r"\bretaliat\w*|\bban(s|ned|ning)?\b|\bterminat\w*|\bcancel\w*", 1),
    (r"\bend(ed|ing)? (all )?(trade|talks|negotiations)\b|\bno deal\b", 2),
)]


def market_tone(text: str) -> Optional[str]:
    """'bullish' / 'bearish' for posts on market topics that lean clearly one way, else None."""
    if not market_words(text):
        return None
    bull = sum(w for p, w in _BULL if p.search(text))   # each group counts once, so repetition can't tip it
    bear = sum(w for p, w in _BEAR if p.search(text))
    if "no deal" in text.lower():
        bull -= 1                                       # "no deal" also matched "deal" above
    if bull > bear:
        return "bullish"
    if bear > bull:
        return "bearish"
    return None


def _https(u) -> Optional[str]:
    return u if isinstance(u, str) and u.startswith("https://") else None


def from_api(statuses) -> list[dict]:
    out = []
    for s in statuses if isinstance(statuses, list) else []:
        try:
            t = datetime.fromisoformat(str(s["created_at"]).replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        rb = s.get("reblog") or None
        src = rb or s
        text = html_to_text(src.get("content", ""))
        kind = "retruth" if rb else ("quote" if s.get("quote_id") or "quote-inline" in (s.get("content") or "") else "post")
        media = [{"type": m.get("type", "image"), "preview": _https(m.get("preview_url") or m.get("url"))}
                 for m in (src.get("media_attachments") or []) if _https(m.get("preview_url") or m.get("url"))][:1]
        card = src.get("card") or {}
        out.append({"id": str(s.get("id")), "time": t.astimezone(timezone.utc).isoformat(), "kind": kind,
                    "author": ((rb or {}).get("account") or {}).get("acct") if rb else None,
                    "text": text, "media": media, "url": _https(s.get("url")),
                    "link": {"title": card.get("title"), "url": _https(card.get("url"))} if card.get("url") else None,
                    "counts": {"replies": s.get("replies_count"), "retruths": s.get("reblogs_count"), "likes": s.get("favourites_count")}
                    if not rb else None,
                    "market_words": market_words(text), "tone": market_tone(text)})
    return out


def from_rss(xml_bytes: bytes) -> list[dict]:
    out = []
    root = ET.fromstring(xml_bytes)
    for it in root.iter("item"):
        try:
            t = parsedate_to_datetime(it.findtext("pubDate"))
        except (TypeError, ValueError):
            continue
        desc = html_to_text(html.unescape(it.findtext("description") or ""))
        title = (it.findtext("title") or "").strip()
        text = desc or ("" if title.lower().startswith(("image post", "video post")) else title)
        media = []
        for el in it:
            if el.tag.endswith("content") or el.tag.endswith("thumbnail"):
                u = _https(el.attrib.get("url"))
                if u:
                    media.append({"type": "image", "preview": u})
        out.append({"id": it.findtext("guid") or it.findtext("link") or t.isoformat(), "time": t.astimezone(timezone.utc).isoformat(),
                    "kind": "retruth" if text.startswith("RT ") else "post", "author": None, "text": text,
                    "media": media[:1], "url": _https(it.findtext("link")), "link": None, "counts": None,
                    "market_words": market_words(text), "tone": market_tone(text)})
    return out


def _cache_path() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or str(Path.home())) / "gexsys" / "truth_posts.json"


class Posts:
    def __init__(self, ttl_s: float = 300.0, opener: Callable = urllib.request.urlopen,
                 clock: Callable[[], float] = time.time, cache_path: Optional[Path] = None, limit: int = 15):
        self.ttl_s, self.opener, self.clock, self.limit = ttl_s, opener, clock, limit
        self.cache_path = cache_path or _cache_path()
        self._lock = threading.Lock()
        self._data: Optional[dict] = None
        self._last_try = -1e18
        try:
            self._data = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass

    def get(self) -> dict:
        with self._lock:
            if self.clock() - self._last_try >= self.ttl_s:
                self._last_try = self.clock()
                self._refresh()
            return dict(self._data or {"posts": [], "fetched_at": None, "source": None})

    def _fetch(self, url: str) -> bytes:
        with self.opener(urllib.request.Request(url, headers=UA), timeout=20) as r:
            return r.read()

    def _refresh(self) -> None:
        errors = []
        for name, url, parse in (("Truth Social", API_URL, lambda b: from_api(json.loads(b.decode("utf-8")))),
                                 ("trumpstruth.org archive", RSS_URL, from_rss)):
            try:
                posts = parse(self._fetch(url))
            except (urllib.error.URLError, OSError, ValueError, ET.ParseError) as e:
                errors.append(f"{name}: {e}")
                continue
            if posts:
                posts.sort(key=lambda p: p["time"], reverse=True)
                self._data = {"posts": posts[: self.limit], "fetched_at": datetime.now(timezone.utc).isoformat(), "source": name}
                try:
                    self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                    self.cache_path.write_text(json.dumps(self._data), encoding="utf-8")
                except OSError:
                    pass
                return
            errors.append(f"{name}: no posts in the response")
        log.warning("posts refresh failed: %s", "; ".join(errors))
        if self._data is not None:
            self._data["error"] = "latest refresh failed; showing the copy from " + str(self._data.get("fetched_at"))
        else:
            self._data = {"posts": [], "fetched_at": None, "source": None, "error": "; ".join(errors)}
