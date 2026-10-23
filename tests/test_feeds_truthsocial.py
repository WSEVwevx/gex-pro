"""Trump posts feed: Truth Social API parsing, RSS fallback, HTML -> text, market-word flags, caching."""
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path

from feeds.truthsocial import Posts, from_api, from_rss, html_to_text, market_tone, market_words

API = [
    {"id": "1", "created_at": "2026-10-21T20:43:03.502Z", "content": "<p></p>", "reblog": None, "quote_id": None,
     "media_attachments": [{"type": "image", "preview_url": "https://static-assets-1.truthsocial.com/a.jpg"}],
     "url": "https://truthsocial.com/@realDonaldTrump/1", "replies_count": 5, "reblogs_count": 6, "favourites_count": 7, "card": None},
    {"id": "2", "created_at": "2026-10-21T17:20:53.024Z", "content": "<p>Big TARIFFS on China start Monday!<br/>Markets will love it.</p>",
     "reblog": None, "media_attachments": [], "url": "https://truthsocial.com/@realDonaldTrump/2", "card": None,
     "replies_count": 1, "reblogs_count": 2, "favourites_count": 3},
    {"id": "3", "created_at": "2026-10-21T17:20:00Z", "content": "<p>RT ...</p>", "url": "https://truthsocial.com/@realDonaldTrump/3",
     "reblog": {"content": "<p>The Fed must cut rates &amp; fast</p>", "account": {"acct": "someone"}, "media_attachments": []}},
    {"id": "4", "created_at": "2026-10-21T14:43:58Z", "quote_id": "9", "url": "javascript:alert(1)",
     "content": '<p><span class="quote-inline"><br/>RT: https://truthsocial.com/x</span>Look at this</p>', "media_attachments": []},
    {"id": "bad", "created_at": "not a time"},
]

RSS = b"""<?xml version="1.0"?><rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/"><channel>
<item><title>Image post from October 21, 2026</title><link>https://www.trumpstruth.org/statuses/42556</link>
<description></description><pubDate>Wed, 21 Oct 2026 20:43:03 +0000</pubDate><guid>42556</guid>
<media:content url="https://static-assets-1.truthsocial.com/a.jpg" medium="image"/></item>
<item><title>Post</title><link>https://www.trumpstruth.org/statuses/42555</link>
<description>&lt;p&gt;Oil prices are coming DOWN&lt;/p&gt;</description><pubDate>Wed, 21 Oct 2026 17:20:53 +0000</pubDate><guid>42555</guid></item>
</channel></rss>"""


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestParsing(unittest.TestCase):
    def test_api(self):
        p = from_api(API)
        self.assertEqual([x["id"] for x in p], ["1", "2", "3", "4"])                 # bad row dropped
        self.assertEqual((p[0]["text"], p[0]["media"][0]["type"], p[0]["counts"]["likes"]), ("", "image", 7))
        self.assertEqual(p[1]["text"], "Big TARIFFS on China start Monday!\nMarkets will love it.")
        self.assertEqual(p[1]["market_words"], ["china", "market", "tariff"])
        self.assertEqual((p[2]["kind"], p[2]["author"], p[2]["text"]), ("retruth", "someone", "The Fed must cut rates & fast"))
        self.assertEqual((p[3]["kind"], p[3]["text"]), ("quote", "Look at this"))     # quote-link span removed
        self.assertIsNone(p[3]["url"])                                                # only https links are kept

    def test_rss_fallback(self):
        p = from_rss(RSS)
        self.assertEqual(p[0]["text"], "")                                            # "Image post from ..." is not text
        self.assertEqual(p[0]["media"][0]["preview"], "https://static-assets-1.truthsocial.com/a.jpg")
        self.assertEqual((p[1]["text"], p[1]["market_words"]), ("Oil prices are coming DOWN", ["oil"]))
        self.assertEqual(p[1]["time"], "2026-10-21T17:20:53+00:00")

    def test_text_helpers(self):
        self.assertEqual(html_to_text("<p>a</p><p>b &amp; c</p>"), "a\nb & c")
        self.assertEqual(market_words("Fed, rates and stocks"), ["fed", "rate", "stock"])
        self.assertEqual(market_words("federal holiday"), [])                         # whole words only

    def test_tone(self):
        self.assertEqual(market_tone("Big TARIFFS on China start Monday!"), "bearish")
        self.assertEqual(market_tone("We will PAUSE the tariffs on China for 90 days"), "bullish")
        self.assertEqual(market_tone("Great trade deal signed with Japan, stocks at record highs"), "bullish")
        self.assertEqual(market_tone("No deal. We are ending all trade talks with Canada"), "bearish")
        self.assertEqual(market_tone("The Fed must cut rates"), "bullish")
        self.assertIsNone(market_tone("Sanctions were avoided because of a great deal"))  # mixed -> no label
        self.assertIsNone(market_tone("A ceasefire at the family dinner"))               # no market topic
        self.assertEqual(from_api(API)[1]["tone"], "bearish")


class TestFeed(unittest.TestCase):
    def test_falls_back_to_rss_then_caches_and_keeps_last_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            t, calls = [0.0], []

            def opener(req, timeout=None):
                calls.append(req.full_url)
                if "truthsocial" in req.full_url:
                    raise urllib.error.URLError("403 blocked")
                if len(calls) > 2:
                    raise urllib.error.URLError("down")
                return _Resp(RSS)
            feed = Posts(opener=opener, clock=lambda: t[0], cache_path=Path(tmp) / "p.json")
            d = feed.get()
            self.assertEqual((d["source"], len(d["posts"])), ("trumpstruth.org archive", 2))
            feed.get()
            self.assertEqual(len(calls), 2)                                           # cached within 5 minutes
            t[0] += 301
            d = feed.get()                                                            # both fail -> last copy kept
            self.assertEqual(len(d["posts"]), 2)
            self.assertIn("failed", d["error"])

    def test_api_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            feed = Posts(opener=lambda req, timeout=None: _Resp(json.dumps(API).encode()), cache_path=Path(tmp) / "p.json")
            d = feed.get()
            self.assertEqual((d["source"], d["posts"][0]["id"]), ("Truth Social", "1"))  # newest first


if __name__ == "__main__":
    unittest.main()
