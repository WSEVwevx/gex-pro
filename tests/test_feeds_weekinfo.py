"""The weekly recap's sources: Yahoo closes, Nasdaq earnings and economic data, Google News headlines."""
import json
import unittest

from feeds import weekinfo


class TestParsers(unittest.TestCase):
    def test_spark_keeps_real_closes_by_new_york_date(self):
        raw = json.dumps({"spark": {"result": [
            {"symbol": "AAA", "response": [{"timestamp": [1793367000, 1793453400], "indicators": {"quote": [{"close": [10.5, None]}]}}]},
            {"symbol": "BAD", "response": []}]}}).encode()
        self.assertEqual(weekinfo.parse_spark(raw), {"AAA": {"2026-10-30": 10.5}})

    def test_earnings_rows(self):
        raw = json.dumps({"data": {"rows": [{"symbol": "BRK.B", "surprise": "-5.97", "time": "time-after-hours"},
                                            {"symbol": "AMZN", "surprise": "N/A", "time": "time-not-supplied"}]}}).encode()
        self.assertEqual(weekinfo.parse_earnings(raw, "2026-10-29"), [
            {"date": "2026-10-29", "symbol": "BRK-B", "time": "time-after-hours", "surprise": -5.97},
            {"date": "2026-10-29", "symbol": "AMZN", "time": "time-not-supplied", "surprise": None}])

    def test_economy_keeps_big_us_results_only(self):
        rows = [{"country": "United States", "eventName": "CPI (YoY)", "actual": "3.1%", "consensus": "2.9%"},
                {"country": "United States", "eventName": "Nonfarm Payrolls", "actual": "&nbsp;", "consensus": "150K"},     # no result yet
                {"country": "United States", "eventName": "Baker Hughes Rig Count", "actual": "580", "consensus": ""},
                {"country": "United States", "eventName": "Atlanta Fed GDPNow", "actual": "3.4%", "consensus": "3.5%"},           # an estimate, not a release
                {"country": "Germany", "eventName": "CPI (YoY)", "actual": "2.1%", "consensus": "2.0%"}]
        raw = json.dumps({"data": {"rows": rows}}).encode()
        self.assertEqual(weekinfo.parse_economy(raw, "2026-10-30"),
                         [{"date": "2026-10-30", "title": "CPI (YoY)", "rank": 2, "actual": "3.1%", "consensus": "2.9%"}])

    def test_news_splits_title_and_source(self):
        raw = (b"<rss><channel><title>feed</title><item><title>Stocks &amp;amp; bonds slide - The Wire - Wire News</title>"
               b"<link>https://news.google.com/a?x=1&amp;y=2</link></item><item><title>Second - Other</title><link>https://b</link></item></channel></rss>")
        got = weekinfo.parse_news(raw, "2026-10-30", 1)
        self.assertEqual(got, [{"day": "2026-10-30", "title": "Stocks & bonds slide - The Wire", "source": "Wire News", "url": "https://news.google.com/a?x=1&y=2"}])


if __name__ == "__main__":
    unittest.main()
