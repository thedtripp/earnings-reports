"""Acceptance tests from spec v1.1, run offline against fake source responses.

Run: python3 -m unittest discover -s tests
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from earnings_calendar import cli, ics  # noqa: E402
from earnings_calendar.sources import fiscal_quarter_from_period_end, period_end_month  # noqa: E402

TODAY = "2026-11-06"


def nasdaq_text(day: str, confirmed=True, timing="after market close", period="Oct 2026"):
    if confirmed:
        return (f"Example Corp is expected* to report earnings on  {day} {timing}.  "
                f"The report will be for the fiscal Quarter ending {period}.")
    return (f"Example Corp is estimated to report earnings on  {day}. The upcoming earnings "
            "date is derived from an algorithm based on a company's historical reporting dates.")


NO_DATE = "Our vendor, Zacks Investment Research, hasn't provided us with the upcoming earnings report date."


class FakeWeb:
    """Canned Finnhub and Nasdaq responses keyed by ticker.

    finnhub: ticker -> list of earningsCalendar rows
    nasdaq:  ticker -> (reportText, calendar row or None)
    """

    def __init__(self, finnhub=None, nasdaq=None, alpha=None, fail=None, alpha_body=None):
        self.finnhub = finnhub or {}
        self.nasdaq = nasdaq or {}
        self.alpha = alpha or []  # list of CSV rows (dicts)
        self.alpha_body = alpha_body  # raw body override, e.g. a rate-limit notice
        self.fail = fail  # a source name: that source's requests error out

    def __call__(self, url, headers):
        if "alphavantage.co" in url:
            if self.fail == "Alpha Vantage":
                raise OSError("timed out")
            if self.alpha_body is not None:
                return 200, self.alpha_body
            cols = ["symbol", "name", "reportDate", "fiscalDateEnding", "estimate",
                    "currency", "timeOfTheDay"]
            lines = [",".join(cols)] + [
                ",".join(str(r.get(c, "")) for c in cols) for r in self.alpha]
            return 200, ("\r\n".join(lines) + "\r\n").encode()
        if "finnhub.io" in url:
            if self.fail == "Finnhub":
                raise OSError("connection refused")
            sym = re.search(r"symbol=([A-Z.]+)", url).group(1)
            return 200, json.dumps({"earningsCalendar": self.finnhub.get(sym, [])}).encode()
        if self.fail == "Nasdaq":
            return 503, b"Service Unavailable"
        if self.fail == "Nasdaq403":
            return 403, b"Forbidden"
        if self.fail == "Nasdaq403-once" and not getattr(self, "_blocked", False):
            self._blocked = True
            return 403, b"Forbidden"
        m = re.search(r"/analyst/([A-Z.]+)/earnings-date", url)
        if m:
            text = self.nasdaq.get(m.group(1), (NO_DATE, None))[0]
            return 200, json.dumps({"data": {"reportText": text}, "status": {"rCode": 200}}).encode()
        day = re.search(r"date=(\d{4}-\d{2}-\d{2})", url).group(1)
        rows = []
        for sym, (text, row) in self.nasdaq.items():
            if row and row.get("_date") == day:
                rows.append({k: v for k, v in row.items() if k != "_date"} | {"symbol": sym})
        return 200, json.dumps({"data": {"rows": rows or None}}).encode()


def fh(sym, day, hour="amc", q=3, y=2027):
    return {"symbol": sym, "date": day, "hour": hour, "quarter": q, "year": y,
            "epsEstimate": None, "epsActual": None, "revenueEstimate": None, "revenueActual": None}


def nq_row(day, time="time-after-hours", period="Oct/2026"):
    return {"_date": day, "time": time, "fiscalQuarterEnding": period}


def av(sym, day, period_end="2026-10-31", timing="post-market"):
    return {"symbol": sym, "name": "Example", "reportDate": day,
            "fiscalDateEnding": period_end, "currency": "USD", "timeOfTheDay": timing}


def nvda_web(**kw):
    return FakeWeb(
        finnhub={"NVDA": [fh("NVDA", "2026-11-25")]},
        nasdaq={"NVDA": (nasdaq_text("11/25/2026"), nq_row("2026-11-25"))},
        alpha=[av("NVDA", "2026-11-25")], **kw)


KEYS = {"FINNHUB_API_KEY": "test-key", "ALPHAVANTAGE_API_KEY": "test-key"}


class Workspace:
    """A temp copy of the config, with a chosen watchlist."""

    def __init__(self, tickers):
        self.dir = Path(tempfile.mkdtemp())
        shutil.copy(ROOT / "config.toml", self.dir)
        shutil.copy(ROOT / "companies.toml", self.dir)
        (self.dir / "watchlist.txt").write_text("\n".join(tickers) + "\n")
        self.ics = self.dir / "earnings.ics"

    def run(self, web, today=TODAY, env=None):
        env = KEYS if env is None else env
        return cli.main(["--config", str(self.dir / "config.toml"), "--today", today],
                        http_get=web, env=env)

    def events(self):
        return ics.parse(self.ics.read_bytes())

    def cleanup(self):
        shutil.rmtree(self.dir)


def summary(ev):
    return ev.props["SUMMARY"].replace("\\,", ",")


def description(ev):
    return ev.props["DESCRIPTION"].replace("\\n", "\n").replace("\\,", ",").replace("\\;", ";")


class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        # Retries back off with real sleeps; keep the failure tests fast.
        from earnings_calendar import sources
        self._sleep = sources.time.sleep
        sources.time.sleep = lambda s: None

    def tearDown(self):
        from earnings_calendar import sources
        sources.time.sleep = self._sleep

    def ws(self, tickers):
        w = Workspace(tickers)
        self.addCleanup(w.cleanup)
        return w

    # 1. NVDA produces an event on Nov 25, 2026.
    def test_1_nvda_event_on_reported_date(self):
        w = self.ws(["NVDA"])
        self.assertEqual(w.run(nvda_web()), 0)
        events = list(w.events().values())
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(summary(ev), "NVDA earnings, Q3 FY27, after close")
        # 4:30 PM EST on Nov 25 is 21:30 UTC.
        self.assertEqual(ev.props["DTSTART"], "20261125T213000Z")
        self.assertEqual(ev.props["DTEND"], "20261125T223000Z")
        notes = description(ev)
        self.assertIn("Start time approximate", notes)
        self.assertIn("Date source: Finnhub, Nasdaq and Alpha Vantage agree.", notes)
        self.assertIn("confirmed (Nasdaq)", notes)
        self.assertIn("https://investor.nvidia.com", notes)

    # 2. Disagreeing sources produce two DISPUTED events, each naming its source.
    def test_2_disputed_dates(self):
        w = self.ws(["AVGO"])
        web = FakeWeb(
            finnhub={"AVGO": [fh("AVGO", "2026-12-09", q=4, y=2026)]},
            nasdaq={"AVGO": (nasdaq_text("12/10/2026", confirmed=False),
                             nq_row("2026-12-10", time="time-not-supplied"))})
        self.assertEqual(w.run(web), 0)
        events = sorted(w.events().values(), key=lambda e: e.props["DTSTART"])
        self.assertEqual(len(events), 2)
        a, b = events
        self.assertTrue(summary(a).startswith("DISPUTED: AVGO earnings, Q4 FY26"))
        self.assertTrue(summary(b).startswith("DISPUTED: AVGO earnings, Q4 FY26"))
        self.assertNotEqual(a.uid, b.uid)
        self.assertIn("20261209", a.uid)
        self.assertIn("20261210", b.uid)
        self.assertIn("comes from Finnhub", description(a))
        self.assertIn("Nasdaq reports Thu Dec 10, 2026 instead", description(a))
        self.assertIn("comes from Nasdaq", description(b))
        self.assertIn("Finnhub reports Wed Dec 9, 2026 instead", description(b))
        self.assertIn("estimated (Nasdaq)", description(b))

    # 3. A changed date updates the same event (same UID, higher SEQUENCE).
    def test_3_changed_date_updates_existing_event(self):
        w = self.ws(["NVDA"])
        self.assertEqual(w.run(nvda_web()), 0)
        (uid, first), = w.events().items()
        self.assertEqual(first.sequence, 0)

        # Rerun with nothing changed: no new SEQUENCE, file byte-identical.
        before = w.ics.read_bytes()
        self.assertEqual(w.run(nvda_web(), today="2026-11-07"), 0)
        self.assertEqual(w.ics.read_bytes(), before)

        moved = FakeWeb(
            finnhub={"NVDA": [fh("NVDA", "2026-11-19")]},
            nasdaq={"NVDA": (nasdaq_text("11/19/2026"), nq_row("2026-11-19"))})
        self.assertEqual(w.run(moved, today="2026-11-08"), 0)
        events = w.events()
        self.assertEqual(list(events), [uid])
        self.assertEqual(events[uid].sequence, 1)
        self.assertEqual(events[uid].props["DTSTART"], "20261119T213000Z")
        self.assertEqual(events[uid].dtstamp, "20261108T000000Z")

    # 4. Running locally, outside GitHub Actions, produces the same file.
    def test_4_same_output_locally_and_in_actions(self):
        outputs = []
        for env_extra in ({}, {"GITHUB_ACTIONS": "true", "CI": "true"}):
            w = self.ws(["NVDA", "AVGO"])
            # Run as a real subprocess from another working directory, through
            # a tiny wrapper that injects the fake web.
            script = w.dir / "run_fake.py"
            script.write_text(
                "import sys\n"
                f"sys.path.insert(0, {str(ROOT)!r}); sys.path.insert(0, {str(Path(__file__).parent)!r})\n"
                "import test_generator as t\n"
                "from earnings_calendar import cli, sources\n"
                "sources.time.sleep = lambda s: None\n"
                "sys.exit(cli.main(sys.argv[1:], http_get=t.nvda_web()))\n")
            env = {k: v for k, v in os.environ.items() if k not in ("GITHUB_ACTIONS", "CI")}
            env.update(env_extra, **KEYS, TZ="Asia/Tokyo" if env_extra else "UTC")
            subprocess.run([sys.executable, str(script), "--config", str(w.dir / "config.toml"),
                            "--today", TODAY], cwd=tempfile.gettempdir(), env=env, check=True,
                           capture_output=True)
            outputs.append(w.ics.read_bytes())
        self.assertEqual(outputs[0], outputs[1])

    # 5. With a source failing, the published file is untouched and exit is nonzero.
    def test_5_failed_source_publishes_nothing(self):
        for failing in ("Finnhub", "Alpha Vantage"):
            with self.subTest(failing=failing):
                w = self.ws(["NVDA"])
                self.assertEqual(w.run(nvda_web()), 0)
                before = w.ics.read_bytes()
                code = w.run(nvda_web(fail=failing), today="2026-11-07")
                self.assertNotEqual(code, 0)
                self.assertEqual(w.ics.read_bytes(), before)
                self.assertFalse((w.dir / "earnings.ics.tmp").exists())

    def test_5a_nasdaq_403_is_retried(self):
        w = self.ws(["NVDA"])
        self.assertEqual(w.run(nvda_web(fail="Nasdaq403-once")), 0)
        self.assertIn("confirmed (Nasdaq)", description(next(iter(w.events().values()))))

    def test_5d_nasdaq_blocked_keeps_published_events_and_adds_new_ones(self):
        w = self.ws(["NVDA"])
        self.assertEqual(w.run(nvda_web()), 0)
        (uid, first), = w.events().items()
        # Blocked run, same data from Finnhub and Alpha Vantage: nothing changes.
        before = w.ics.read_bytes()
        self.assertEqual(w.run(nvda_web(fail="Nasdaq403"), today="2026-11-07"), 0)
        self.assertEqual(w.ics.read_bytes(), before)
        # Finnhub now disagrees on the date: the published event is not downgraded.
        moved = nvda_web(fail="Nasdaq403")
        moved.finnhub = {"NVDA": [fh("NVDA", "2026-11-26")]}
        self.assertEqual(w.run(moved, today="2026-11-07"), 0)
        kept = w.events()[uid]  # the other sources now disagree, so DISPUTED events are added
        self.assertEqual(kept.props, first.props)
        self.assertIn("confirmed (Nasdaq)", description(kept))

    def test_5e_nasdaq_blocked_still_publishes_a_new_ticker(self):
        w = self.ws(["NVDA"])
        self.assertEqual(w.run(nvda_web()), 0)
        w.dir.joinpath("watchlist.txt").write_text("NVDA\nAVGO\n")
        web = FakeWeb(finnhub={"NVDA": [fh("NVDA", "2026-11-25")],
                               "AVGO": [fh("AVGO", "2026-12-09", q=4, y=2026)]},
                      alpha=[av("NVDA", "2026-11-25")], fail="Nasdaq403")
        self.assertEqual(w.run(web, today="2026-11-07"), 0)
        events = w.events().values()
        self.assertEqual(len(events), 2)
        avgo = next(e for e in events if summary(e).startswith("AVGO"))
        self.assertNotIn("Nasdaq", description(avgo))

    def test_5b_missing_api_key_is_a_failure_not_an_empty_source(self):
        w = self.ws(["NVDA"])
        self.assertEqual(w.run(nvda_web()), 0)
        before = w.ics.read_bytes()
        for env in ({}, {"FINNHUB_API_KEY": "k"}, {"ALPHAVANTAGE_API_KEY": "k"}):
            self.assertNotEqual(w.run(nvda_web(), env=env), 0)
            self.assertEqual(w.ics.read_bytes(), before)

    def test_5c_alpha_vantage_rate_limit_notice_is_a_failure(self):
        # Alpha Vantage reports rate limits as JSON with HTTP 200.
        w = self.ws(["NVDA"])
        self.assertEqual(w.run(nvda_web()), 0)
        before = w.ics.read_bytes()
        notice = b'{"Information": "We have detected your API key and our standard API rate limit is 25 requests per day."}'
        self.assertNotEqual(w.run(nvda_web(alpha_body=notice), today="2026-11-07"), 0)
        self.assertEqual(w.ics.read_bytes(), before)

    def test_2b_three_sources_two_dates(self):
        w = self.ws(["MU"])
        web = FakeWeb(
            finnhub={"MU": [fh("MU", "2026-12-15", q=1, y=2027)]},
            nasdaq={"MU": (nasdaq_text("12/16/2026", confirmed=False),
                           nq_row("2026-12-16", time="time-not-supplied", period="Nov/2026"))},
            # Micron's quarter ends on a Thursday near month end; Sep 3 style
            # dates must still map to the right quarter.
            alpha=[av("MU", "2026-12-16", period_end="2026-11-30", timing="")])
        self.assertEqual(w.run(web), 0)
        events = sorted(w.events().values(), key=lambda e: e.props["DTSTART"])
        self.assertEqual([summary(e) for e in events],
                         ["DISPUTED: MU earnings, Q1 FY27, after close",
                          "DISPUTED: MU earnings, Q1 FY27, time not reported"])
        self.assertIn("comes from Finnhub.", description(events[0]))
        self.assertIn("Nasdaq and Alpha Vantage report Wed Dec 16, 2026 instead", description(events[0]))
        self.assertIn("comes from Nasdaq and Alpha Vantage.", description(events[1]))


class BehaviourTests(unittest.TestCase):
    def ws(self, tickers):
        w = Workspace(tickers)
        self.addCleanup(w.cleanup)
        return w

    def test_past_events_dropped_and_horizon_respected(self):
        w = self.ws(["NVDA", "MSFT"])
        web = FakeWeb(finnhub={"NVDA": [fh("NVDA", "2026-11-25")],
                               "MSFT": [fh("MSFT", "2027-03-01", q=3, y=2027)]})
        self.assertEqual(w.run(web), 0)
        self.assertEqual([summary(e) for e in w.events().values()],
                         ["NVDA earnings, Q3 FY27, after close"])
        self.assertEqual(w.run(web, today="2026-11-26"), 0)
        self.assertEqual(w.events(), {})

    def test_single_source_and_unknown_timing(self):
        w = self.ws(["AAPL"])
        web = FakeWeb(finnhub={"AAPL": [fh("AAPL", "2026-12-01", hour="", q=1, y=2027)]})
        self.assertEqual(w.run(web), 0)
        ev, = w.events().values()
        self.assertEqual(summary(ev), "AAPL earnings, Q1 FY27, time not reported")
        self.assertEqual(ev.props["DTSTART"], "20261201T133000Z")  # 8:30 AM EST
        self.assertIn("Finnhub only (Nasdaq and Alpha Vantage have no date", description(ev))
        self.assertIn("Start time approximate", description(ev))

    def test_daylight_saving_before_open(self):
        w = self.ws(["TSM"])
        web = FakeWeb(finnhub={"TSM": [fh("TSM", "2027-01-14", hour="bmo", q=4, y=2026)]})
        self.assertEqual(w.run(web, today="2027-01-01"), 0)
        ev, = w.events().values()
        self.assertEqual(ev.props["DTSTART"], "20270114T133000Z")

    def test_fiscal_quarter_mapping(self):
        self.assertEqual(fiscal_quarter_from_period_end(10, 2026, 1), (2027, 3))   # NVDA
        self.assertEqual(fiscal_quarter_from_period_end(12, 2026, 9), (2027, 1))   # AAPL
        self.assertEqual(fiscal_quarter_from_period_end(12, 2026, 6), (2027, 2))   # MSFT
        self.assertEqual(fiscal_quarter_from_period_end(9, 2026, 12), (2026, 3))   # calendar FY
        self.assertEqual(fiscal_quarter_from_period_end(10, 2026, 10), (2026, 4))  # AVGO
        self.assertEqual(fiscal_quarter_from_period_end(11, 2026, 8), (2027, 1))   # MU
        from datetime import date
        self.assertEqual(period_end_month(date(2026, 11, 1)), (10, 2026))  # AVGO's Nov 1 end
        self.assertEqual(period_end_month(date(2026, 9, 3)), (8, 2026))    # MU's Sep 3 end
        self.assertEqual(period_end_month(date(2027, 1, 2)), (12, 2026))
        self.assertEqual(period_end_month(date(2026, 10, 31)), (10, 2026))

    def test_unrecognized_nasdaq_text_is_a_failure(self):
        w = self.ws(["NVDA"])
        web = FakeWeb(finnhub={"NVDA": [fh("NVDA", "2026-11-25")]},
                      nasdaq={"NVDA": ("Something new and unexpected.", None)})
        self.assertNotEqual(w.run(web), 0)
        self.assertFalse(w.ics.exists())

    def test_output_is_valid_ics_lines(self):
        w = self.ws(["NVDA"])
        self.assertEqual(w.run(nvda_web()), 0)
        data = w.ics.read_bytes()
        self.assertTrue(data.endswith(b"\r\n"))
        for line in data.split(b"\r\n"):
            self.assertLessEqual(len(line), 75)


if __name__ == "__main__":
    unittest.main()
