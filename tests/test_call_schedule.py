"""Offline tests for the call-schedule POC, using real announcement wording."""

import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import call_schedule_poc  # noqa: E402
from call_schedule.parse import parse_announcement  # noqa: E402
from earnings_calendar import ics  # noqa: E402

AMAT = ("Applied Materials to Report Fourth Quarter and Fiscal 2026 Results on Nov. 12, 2026. "
        "SANTA CLARA, Calif., Oct. 22, 2026 (GLOBE NEWSWIRE) -- Applied Materials, Inc. today announced "
        "that it will hold its fourth quarter and fiscal 2026 earnings conference call on Thursday, "
        "Nov. 12, 2026, at 4:30 p.m. ET / 1:30 p.m. PT. The call will be webcast live at: "
        "https://ir.appliedmaterials.com. A replay will be available on the same day by 8:00 p.m. ET / 5:00 p.m. PT.")
CSCO = ("Cisco Schedules Conference Call for Q1 Fiscal Year 2027 Financial Results. Cisco (NASDAQ: CSCO) has "
        "scheduled a conference call for Thursday, Nov 12, 2026, at 1:30 PM (PT); 4:30 PM (ET) to announce its "
        "first quarter fiscal year 2027 financial results for the period ending Saturday, October 24, 2026.")
TTWO = ("Take-Two Interactive Software, Inc. to Report Second Quarter Fiscal Year 2027 Results on Monday, Nov 9. "
        "NEW YORK, October 13, 2026--Take-Two Interactive Software, Inc. (NASDAQ: TTWO) today announced that it "
        "plans to report financial results for its second quarter of fiscal year 2027, ended September 30, 2026, "
        "after the market close on Monday, November 9, 2026. The Company plans to hold a conference call to "
        "discuss its results at 4:30 p.m. Eastern Time, which can be accessed by dialing (833) 461-5787 "
        "(Meeting ID: 112-490-011). A live, listen-only webcast and a replay of the call will be available a")


HD = ("The Home Depot to Host Third Quarter Earnings Conference Call on November 17. The Home Depot, the "
      "world's largest home improvement retailer, announced today that it will hold its Third Quarter Earnings "
      "Conference Call on Tuesday, November 17, at 9 a.m. ET.")


class ParseTests(unittest.TestCase):
    def test_hd_date_without_a_year(self):
        c = parse_announcement(HD, date(2026, 11, 17))
        self.assertEqual(c.start.isoformat(), "2026-11-17T09:00:00-05:00")

    def test_yearless_date_across_new_year(self):
        c = parse_announcement("The call is on January 5 at 8:30 a.m. ET.", date(2027, 1, 5))
        self.assertEqual(c.start.isoformat(), "2027-01-05T08:30:00-05:00")

    def test_words_that_only_look_like_months_are_ignored(self):
        self.assertIsNone(parse_announcement("A decision 5 at 4:30 p.m. ET.", date(2026, 12, 5)))

    def test_amat_uses_call_time_not_replay_time(self):
        c = parse_announcement(AMAT, date(2026, 11, 12))
        self.assertEqual(c.start.isoformat(), "2026-11-12T16:30:00-05:00")
        self.assertEqual(c.webcast_url, "https://ir.appliedmaterials.com")

    def test_csco_prefers_eastern_and_has_no_link(self):
        c = parse_announcement(CSCO, date(2026, 11, 12))
        self.assertEqual(c.start.isoformat(), "2026-11-12T16:30:00-05:00")
        self.assertIsNone(c.webcast_url)

    def test_ttwo_dial_in_and_truncated_link(self):
        c = parse_announcement(TTWO, date(2026, 11, 9))
        self.assertEqual(c.start.isoformat(), "2026-11-09T16:30:00-05:00")
        self.assertEqual(c.dial_in, "(833) 461-5787")
        self.assertIsNone(c.webcast_url)

    def test_only_pacific_is_converted_to_the_right_instant(self):
        c = parse_announcement("The call is on Nov 12, 2026 at 1:30 p.m. PT.", date(2026, 11, 12))
        self.assertEqual(c.start.isoformat(), "2026-11-12T13:30:00-08:00")

    def test_rejects_text_without_zone_or_for_another_date(self):
        self.assertIsNone(parse_announcement("The call is on Nov 12, 2026 at 4:30 p.m.", date(2026, 11, 12)))
        self.assertIsNone(parse_announcement(AMAT, date(2026, 12, 20)))
        self.assertIsNone(parse_announcement("Gears up to report Q3 earnings: buy or hold?", date(2026, 11, 12)))


class LookupTests(unittest.TestCase):
    def setUp(self):
        from earnings_calendar import sources
        self._sleep = sources.time.sleep
        sources.time.sleep = lambda s: None
        self.addCleanup(setattr, sources.time, "sleep", self._sleep)

    def run_poc(self, news_by_symbol, fail=False):
        d = Path(tempfile.mkdtemp())
        events = [ics.Event(uid=f"{t.lower()}-fy2027-q1@earnings-calendar",
                            props={"SUMMARY": f"{t} earnings\\, Q1 FY27\\, after close",
                                   "DTSTART": "20261112T213000Z", "DTEND": "20261112T223000Z"}, dtstamp="20261107T000000Z")
                  for t in news_by_symbol]
        (d / "earnings.ics").write_bytes(ics.render(events, "t", "America/New_York"))

        def http(url, headers):
            if fail:
                raise OSError("down")
            sym = url.split("symbol=")[1].split("&")[0]
            return 200, json.dumps(news_by_symbol[sym]).encode()
        out = d / "out.json"
        code = call_schedule_poc.main(["--today", "2026-11-07", "--ics", str(d / "earnings.ics"),
                                       "--companies", str(d / "none.toml"), "--json", str(out)],
                                      http_get=http, env={"FINNHUB_API_KEY": "k"})
        return code, (json.loads(out.read_text()) if out.exists() else None)

    def test_found_and_not_announced(self):
        code, rows = self.run_poc({
            "AMAT": [{"datetime": 1793000000, "headline": "Applied Materials to Report Fourth Quarter", "summary": AMAT}],
            "ZZZ": [{"datetime": 1793000000, "headline": "Analyst blog: gears up to report", "summary": "Buy or hold?"}]})
        self.assertEqual(code, 0)
        by = {r["ticker"]: r for r in rows}
        self.assertEqual(by["AMAT"]["status"], "found")
        self.assertEqual(by["AMAT"]["call_start_utc"], "2026-11-12T21:30:00Z")
        self.assertEqual(by["ZZZ"]["status"], "not announced yet")

    def test_source_failure_is_nonzero_and_writes_nothing(self):
        code, rows = self.run_poc({"AMAT": []}, fail=True)
        self.assertNotEqual(code, 0)
        self.assertIsNone(rows)


if __name__ == "__main__":
    unittest.main()
