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


def render_with_companies(tmp, watchlist, companies_toml, *events):
    (tmp / "w.txt").write_text(watchlist)
    (tmp / "c.toml").write_text(companies_toml)
    data = ics.render(list(events), "Test", "America/New_York")
    rows = site.rows_from_ics(data, today=NOW)
    comps = site.load_companies(tmp / "w.txt", tmp / "c.toml", rows)
    return comps, site.render(rows, NOW, None, comps)


class CompaniesTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, self.tmp)

    def test_lists_every_watchlist_company_alphabetically_with_next_dates(self):
        comps, page = render_with_companies(
            self.tmp, "ZZZ\n# comment\nAAA\nBBB  # trailing\n",
            '[AAA]\nname = "Alpha Co"\nir_url = "https://ir.alpha.example/"\n[ZZZ]\nname = "Zed Corp"\n',
            event("a@x", "AAA earnings, Q3 FY27, before open", "20261117T133000Z"))
        self.assertEqual([c.ticker for c in comps], ["AAA", "BBB", "ZZZ"])
        self.assertIn("Companies covered (3)", page)
        self.assertIn("Next: Nov 17", page)
        self.assertEqual(page.count("No date yet"), 2)
        self.assertIn('href="https://ir.alpha.example/"', page)
        self.assertLess(page.index(">AAA<"), page.index(">ZZZ<"))

    def test_disputed_company_shows_both_dates(self):
        comps, page = render_with_companies(
            self.tmp, "AAA\n", '[AAA]\nname = "Alpha"\n',
            event("a1@x", "DISPUTED: AAA earnings, Q3 FY27, after close", "20261209T213000Z"),
            event("a2@x", "DISPUTED: AAA earnings, Q3 FY27, after close", "20261214T213000Z"))
        self.assertEqual(comps[0].dates, ["Dec 9", "Dec 14"])
        self.assertIn("Next: Dec 9 or Dec 14", page)

    def test_company_without_name_or_link_still_listed_and_escaped(self):
        _, page = render_with_companies(
            self.tmp, "AAA\nBBB\n",
            '[BBB]\nname = "<b>Bad</b> & Co"\nir_url = "javascript:alert(1)"\n')
        self.assertIn(">AAA<", page)
        self.assertNotIn("<b>Bad</b>", page)
        self.assertNotIn("javascript:", page)

    def test_section_absent_when_no_companies_given(self):
        self.assertNotIn("Companies covered", render())

    def test_real_watchlist_is_fully_named(self):
        root = Path(__file__).resolve().parent.parent
        comps = site.load_companies(root / "watchlist.txt", root / "companies.toml", [])
        self.assertEqual(len(comps), 50)
        self.assertEqual([c.ticker for c in comps if not c.name], [])


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
