"""The weekly recap's sources: Yahoo closes, Nasdaq earnings and economic data, Google News headlines."""
import json
import unittest
from datetime import date, timedelta
from unittest import mock

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

    def test_economy_one_name_two_figures(self):
        # Nasdaq's own rows for 17 Nov 2026 (Retail Sales) and 14 Oct 2026 (CPI)
        us = lambda n, a, c: {"country": "United States", "eventName": n, "actual": a, "consensus": c}
        raw = json.dumps({"data": {"rows": [us("Retail Sales", "6.82%", " "), us("Retail Sales", "0.2%", "0.1%"), us("Retail Sales Ex Gas/Autos", "0.5%", " "),
                                            us("CPI", "0.6%", "0.6%"), us("CPI", "3.7%", "3.6%"), us("CPI, n.s.a", "0.59%", " ")]}}).encode()
        self.assertEqual([(e["title"], e["actual"]) for e in weekinfo.parse_economy(raw, "x")], [("Retail Sales", "0.2%"), ("CPI", "0.6%"), ("CPI", "3.7%")])

    def test_economy_leaves_out_parts_and_lookalikes(self):
        names = ("Private Nonfarm Payrolls", "U6 Unemployment Rate", "NFIB Small Business Optimism", "IBD/TIPP Economic Optimism", "PPI ex. Food/Energy/Transport",
                 "ISM Manufacturing Employment", "ISM Non-Manufacturing New Orders", "ISM Manufacturing Prices", "ISM Non-Manufacturing Business Activity")
        keep = ("Nonfarm Payrolls", "Unemployment Rate", "ISM Manufacturing PMI", "ISM Non-Manufacturing PMI", "PPI", "Core CPI", "GDP", "Core PCE Price Index")
        raw = json.dumps({"data": {"rows": [{"country": "United States", "eventName": n, "actual": "1", "consensus": "2"} for n in names + keep]}}).encode()
        self.assertEqual([e["title"] for e in weekinfo.parse_economy(raw, "x")], list(keep))

    def test_economy_reads_the_day_after_and_dates_the_day(self):
        # the payrolls of Friday 2 Oct 2026 are in Nasdaq's page for Saturday 3 Oct
        page = json.dumps({"data": {"rows": [{"country": "United States", "eventName": "Nonfarm Payrolls", "actual": "29K", "consensus": "89K"}]}}).encode()
        asked = []

        def get(url):
            asked.append(url[-10:])
            return page if url.endswith("2026-10-03") else None
        with mock.patch.object(weekinfo, "_get", get):
            got = weekinfo.economy(date(2026, 9, 28), date(2026, 10, 2))
        self.assertEqual([(e["date"], e["title"], e["actual"]) for e in got], [("2026-10-02", "Nonfarm Payrolls", "29K")])
        self.assertEqual(asked, ["2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02", "2026-10-03"])

    def test_economy_is_left_out_when_the_calendar_dates_change(self):
        us = lambda n: {"country": "United States", "eventName": n, "actual": "1", "consensus": "2"}
        week = {1: ["Redbook", "CPI"], 2: ["MBA Mortgage Applications"], 3: ["Initial Jobless Claims"]}          # the real weekdays

        def run(shift, holiday=False):
            def get(url):
                wd = (date.fromisoformat(url[-10:]) - timedelta(days=shift)).weekday()
                names = list(week.get(wd, []))
                if holiday and wd == 2:
                    names.append("Initial Jobless Claims")                                                       # claims a day early
                return json.dumps({"data": {"rows": [us(n) for n in names]}}).encode()
            with mock.patch.object(weekinfo, "_get", get):
                return [(e["date"], e["title"]) for e in weekinfo.economy(date(2026, 11, 9), date(2026, 11, 13))]
        self.assertEqual(run(1), [("2026-11-10", "CPI")])
        self.assertEqual(run(1, holiday=True), [("2026-11-10", "CPI")])
        with self.assertLogs("feeds.weekinfo", "WARNING"):
            self.assertEqual(run(0), [])                                                                         # filed on the day itself

    def test_news_splits_title_and_source(self):
        raw = (b"<rss><channel><title>feed</title><item><title>Stocks &amp;amp; bonds slide - The Wire - Wire News</title>"
               b"<link>https://news.google.com/a?x=1&amp;y=2</link></item><item><title>Second - Other</title><link>https://b</link></item></channel></rss>")
        got = weekinfo.parse_news(raw, "2026-10-30", 1)
        self.assertEqual(got, [{"day": "2026-10-30", "title": "Stocks & bonds slide - The Wire", "source": "Wire News", "url": "https://news.google.com/a?x=1&y=2"}])


if __name__ == "__main__":
    unittest.main()
