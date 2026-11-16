"""Tests for the demo page. Run: python3 -m unittest discover -s tests"""

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from earnings_calendar import ics, site  # noqa: E402

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)


def event(uid, summary, start, status="confirmed (Nasdaq)", url="https://ir.example.com/"):
    desc = ics.escape(f"Earnings release.\nStatus: {status}.")
    return ics.Event(uid=uid, props={
        "SUMMARY": ics.escape(summary), "DTSTART": start, "DTEND": start,
        "DESCRIPTION": desc, "URL": url}, sequence=0, dtstamp="20261101T000000Z")


def render(*events, cover="cover.png"):
    data = ics.render(list(events), "Test", "America/New_York")
    return site.render(site.rows_from_ics(data, today=NOW), NOW, cover)


class SiteTests(unittest.TestCase):
    def test_sorted_and_past_events_dropped(self):
        page = render(
            event("b@x", "ZZZ earnings, Q3 FY27, after close", "20261201T213000Z"),
            event("a@x", "AAA earnings, Q3 FY27, before open", "20261117T133000Z"),
            event("old@x", "OLD earnings, Q3 FY27, before open", "20261101T133000Z"))
        self.assertNotIn("OLD", page)
        self.assertLess(page.index("AAA"), page.index("ZZZ"))

    def test_status_and_disputed_badges(self):
        page = render(
            event("a@x", "AAA earnings, Q3 FY27, before open", "20261117T133000Z", "estimated (Nasdaq)"),
            event("b@x", "DISPUTED: BBB earnings, Q3 FY27, after close", "20261118T213000Z"))
        self.assertIn("Estimated", page)
        self.assertIn("Sources disagree", page)

    def test_html_is_escaped_and_only_https_links(self):
        page = render(event("a@x", "A<B earnings, Q3 FY27, before open", "20261117T133000Z",
                            url="javascript:alert(1)"))
        self.assertNotIn("A<B", page)
        self.assertNotIn("javascript:", page)

    def test_link_preview_tags(self):
        page = render()
        self.assertIn('property="og:image" content="https://www.ddtripp.com/earnings-reports/og.png"', page)
        self.assertIn('name="twitter:card" content="summary_large_image"', page)

    def test_empty_calendar_message_and_subscribe_url(self):
        page = render()
        self.assertIn("No upcoming earnings dates", page)
        self.assertIn(site.SUBSCRIBE_URL, page)

    def test_links_back_to_home(self):
        page = render()
        self.assertIn(f'href="{site.HOME_URL}"', page)
        self.assertIn("DDTRIPP", page)

    def test_no_cover_means_no_image(self):
        self.assertNotIn("<img", render(cover=None))


if __name__ == "__main__":
    unittest.main()
