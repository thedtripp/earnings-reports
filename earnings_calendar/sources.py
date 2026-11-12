"""The earnings-date sources: Finnhub, Nasdaq and Alpha Vantage.

Each source returns a list of Report records for one ticker, or raises
SourceUnavailable. A source that fails is unavailable, never empty: callers
must not treat a failure as "no earnings dates".
"""

from __future__ import annotations

import csv
import io
import json
import logging
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable

# Release timing values, shared by both sources.
BEFORE_OPEN = "before_open"
AFTER_CLOSE = "after_close"
DURING_MARKET = "during_market"
NOT_REPORTED = "not_reported"

# Date status values.
CONFIRMED = "confirmed"
ESTIMATED = "estimated"
STATUS_NOT_REPORTED = "not_reported"


class SourceUnavailable(Exception):
    """A source could not be read this run (network, bad response, rate limit)."""

    def __init__(self, source: str, message: str):
        super().__init__(f"{source}: {message}")
        self.source = source


@dataclass(frozen=True)
class Report:
    source: str
    ticker: str
    date: date
    timing: str
    fiscal_year: int | None
    fiscal_quarter: int | None
    status: str


# An HTTP getter takes (url, headers) and returns (status_code, body_bytes).
# It raises OSError (including urllib.error.URLError) on network failure.
HttpGet = Callable[[str, dict], tuple[int, bytes]]


def urllib_get(url: str, headers: dict, timeout: float = 30.0) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read() or b""


class SourceBlocked(SourceUnavailable):
    """The source kept refusing or failing after every retry (block, throttle, outage).

    Unlike a bad response shape, this says nothing about the data itself, so a
    caller may choose to carry on without the source.
    """


def get_json(source: str, http_get: HttpGet, url: str, headers: dict, **kw):
    """GET a JSON document, retrying transient failures, else SourceUnavailable."""
    return get(source, http_get, url, headers, parse=json.loads, **kw)


def get(source: str, http_get: HttpGet, url: str, headers: dict, parse,
        retries: int = 3, backoff: float = 2.0, retry_statuses: tuple = (429,),
        sleep: Callable[[float], None] | None = None):
    """GET and parse a document, retrying transient failures, else SourceUnavailable."""
    last = "no attempt made"
    for attempt in range(retries):
        if attempt:
            delay = backoff * 2 ** (attempt - 1)
            (sleep or time.sleep)(delay + random.uniform(0, delay / 2))
        try:
            status, body = http_get(url, headers)
        except OSError as e:
            last = f"network error: {e}"
            continue
        if status in retry_statuses:
            last = f"refused (HTTP {status})"
            continue
        if status >= 500:
            last = f"server error (HTTP {status})"
            continue
        if status != 200:
            # 401/403/404 and friends will not fix themselves on retry.
            raise SourceUnavailable(source, f"HTTP {status} for {redact(url)}")
        try:
            return parse(body)
        except ValueError as e:
            last = f"bad response: {e}"
            continue
    raise SourceBlocked(source, f"{last} for {redact(url)}")


def redact(url: str) -> str:
    return re.sub(r"((?:token|apikey)=)[^&]+", r"\1***", url)


# ---------------------------------------------------------------- Finnhub

FINNHUB_TIMING = {
    "bmo": BEFORE_OPEN,
    "amc": AFTER_CLOSE,
    "dmh": DURING_MARKET,
    "": NOT_REPORTED,
    None: NOT_REPORTED,
}


class Finnhub:
    """Finnhub earnings calendar (free tier, API key).

    Queried per ticker: the unfiltered calendar is capped at 1,500 rows and
    would silently drop dates. Finnhub reports fiscal quarter and year, but
    not whether a date is confirmed.
    """

    name = "Finnhub"
    url = "https://finnhub.io/api/v1/calendar/earnings"

    def __init__(self, api_key: str | None, http_get: HttpGet = urllib_get, **kw):
        self.api_key = api_key
        self.http_get = http_get
        self.kw = kw

    def fetch(self, ticker: str, start: date, end: date) -> list[Report]:
        if not self.api_key:
            raise SourceUnavailable(self.name, "FINNHUB_API_KEY is not set")
        query = urllib.parse.urlencode(
            {"from": start.isoformat(), "to": end.isoformat(), "symbol": ticker})
        # Key goes in a header, not the URL, so it never shows up in logs.
        data = get_json(self.name, self.http_get, f"{self.url}?{query}",
                        {"X-Finnhub-Token": self.api_key, "Accept": "application/json"},
                        **self.kw)
        if not isinstance(data, dict) or not isinstance(data.get("earningsCalendar"), list):
            raise SourceUnavailable(self.name, f"unexpected response shape for {ticker}")
        reports = []
        for row in data["earningsCalendar"]:
            if not isinstance(row, dict) or row.get("symbol", "").upper() != ticker:
                continue
            try:
                day = date.fromisoformat(row["date"])
            except (KeyError, TypeError, ValueError):
                raise SourceUnavailable(self.name, f"bad date in row for {ticker}: {row!r}")
            hour = row.get("hour")
            if hour not in FINNHUB_TIMING:
                raise SourceUnavailable(self.name, f"unknown hour {hour!r} for {ticker}")
            q, y = row.get("quarter"), row.get("year")
            labelled = isinstance(q, int) and isinstance(y, int) and 1 <= q <= 4
            reports.append(Report(
                source=self.name, ticker=ticker, date=day, timing=FINNHUB_TIMING[hour],
                fiscal_year=y if labelled else None,
                fiscal_quarter=q if labelled else None,
                status=STATUS_NOT_REPORTED))
        return reports


# ----------------------------------------------------------------- Nasdaq

NASDAQ_TIMING = {
    "time-pre-market": BEFORE_OPEN,
    "time-after-hours": AFTER_CLOSE,
    "time-not-supplied": NOT_REPORTED,
    "": NOT_REPORTED,
    None: NOT_REPORTED,
}

# Nasdaq's per-ticker text, from its vendor Zacks. "expected*" marks a date
# the company has confirmed; "estimated" marks one derived from an algorithm.
_DATE_RE = re.compile(
    r"is\s+(expected\*?|estimated)\s+to\s+report\s+earnings\s+on\s+(\d{2}/\d{2}/\d{4})"
    r"(?:\s+(before market open|after market close))?", re.I)
_NO_DATE_RE = re.compile(r"hasn't provided us with the upcoming earnings report date", re.I)
_QTR_END_RE = re.compile(r"fiscal Quarter ending ([A-Z][a-z]{2}) (\d{4})")
_TEXT_TIMING = {"before market open": BEFORE_OPEN, "after market close": AFTER_CLOSE}

NASDAQ_HEADERS = {
    # Nasdaq's public API rejects or stalls requests without browser-like headers.
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.nasdaq.com",
    "Referer": "https://www.nasdaq.com/",
}


def fiscal_quarter_from_period_end(month: int, year: int, fye_month: int) -> tuple[int, int]:
    """Map a fiscal-quarter end month/year to (fiscal_year, quarter).

    Example: NVDA's fiscal year ends in January, so the quarter ending
    Oct 2026 is Q3 FY2027.
    """
    quarter = ((month - fye_month - 1) % 12) // 3 + 1
    fiscal_year = year if month <= fye_month else year + 1
    return fiscal_year, quarter


class Nasdaq:
    """Nasdaq public earnings endpoints (no key, unofficial).

    Per ticker: the analyst earnings-date endpoint gives the next date and
    whether it is confirmed; the calendar for that date gives the structured
    release timing and fiscal quarter ending.
    """

    name = "Nasdaq"
    date_url = "https://api.nasdaq.com/api/analyst/{ticker}/earnings-date"
    calendar_url = "https://api.nasdaq.com/api/calendar/earnings?date={day}"

    def __init__(self, fye_months: dict[str, int], http_get: HttpGet = urllib_get, **kw):
        self.fye_months = fye_months
        self.http_get = http_get
        self.kw = kw
        self._calendar_cache: dict[date, list] = {}

    def _get(self, url: str):
        # Nasdaq blocks some datacenter IPs with a 403 that is often gone minutes
        # later, so unlike other sources a 403 is retried, with longer waits.
        opts = {"retries": 4, "backoff": 5.0, "retry_statuses": (403, 429), **self.kw}
        data = get_json(self.name, self.http_get, url, NASDAQ_HEADERS, **opts)
        if not isinstance(data, dict) or "data" not in data:
            raise SourceUnavailable(self.name, f"unexpected response shape from {url}")
        return data

    def _calendar_rows(self, day: date) -> list:
        if day not in self._calendar_cache:
            data = self._get(self.calendar_url.format(day=day.isoformat()))
            rows = (data.get("data") or {}).get("rows") or []
            if not isinstance(rows, list):
                raise SourceUnavailable(self.name, f"unexpected calendar rows for {day}")
            self._calendar_cache[day] = rows
        return self._calendar_cache[day]

    def fetch(self, ticker: str, start: date, end: date) -> list[Report]:
        data = self._get(self.date_url.format(ticker=urllib.parse.quote(ticker)))
        info = data.get("data")
        if not isinstance(info, dict) or not isinstance(info.get("reportText"), str):
            raise SourceUnavailable(self.name, f"no reportText for {ticker}")
        text = info["reportText"]
        m = _DATE_RE.search(text)
        if not m:
            if _NO_DATE_RE.search(text):
                return []  # Nasdaq genuinely has no upcoming date for this ticker.
            raise SourceUnavailable(self.name, f"unrecognized reportText for {ticker}: {text[:120]!r}")
        status = CONFIRMED if m.group(1).lower().startswith("expected") else ESTIMATED
        day = datetime.strptime(m.group(2), "%m/%d/%Y").date()
        if not (start <= day <= end):
            return []
        timing = _TEXT_TIMING.get((m.group(3) or "").lower(), NOT_REPORTED)
        period = None
        qm = _QTR_END_RE.search(text)
        if qm:
            period = f"{qm.group(1)}/{qm.group(2)}"

        row = next((r for r in self._calendar_rows(day)
                    if isinstance(r, dict) and r.get("symbol", "").upper() == ticker), None)
        if row is not None:
            row_timing = row.get("time")
            if row_timing not in NASDAQ_TIMING:
                raise SourceUnavailable(self.name, f"unknown time {row_timing!r} for {ticker}")
            if NASDAQ_TIMING[row_timing] != NOT_REPORTED:
                timing = NASDAQ_TIMING[row_timing]
            period = row.get("fiscalQuarterEnding") or period

        fy = fq = None
        if period:
            try:
                pe = datetime.strptime(period, "%b/%Y")
            except ValueError:
                raise SourceUnavailable(self.name, f"bad fiscal quarter ending {period!r} for {ticker}")
            fy, fq = fiscal_quarter_from_period_end(
                pe.month, pe.year, self.fye_months.get(ticker, 12))
        return [Report(source=self.name, ticker=ticker, date=day, timing=timing,
                       fiscal_year=fy, fiscal_quarter=fq, status=status)]


# ---------------------------------------------------------- Alpha Vantage

log = logging.getLogger("earnings_calendar")

ALPHA_VANTAGE_TIMING = {
    "pre-market": BEFORE_OPEN,
    "post-market": AFTER_CLOSE,
    "": NOT_REPORTED,
}
_AV_COLUMNS = ["symbol", "name", "reportDate", "fiscalDateEnding"]


def period_end_month(day: date) -> tuple[int, int]:
    """The month a fiscal period "ends in", for quarter labelling.

    Some companies end quarters on a weekday near the month boundary (Broadcom
    on ~Nov 1, Micron on ~Sep 3). An end date in the first week of a month
    belongs to the previous month, as Nasdaq labels it.
    """
    if day.day <= 7:
        prev = day.replace(day=1) - timedelta(days=1)
        return prev.month, prev.year
    return day.month, day.year


def parse_alpha_vantage_csv(body: bytes) -> list[dict]:
    text = body.decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text)))
    header = list(rows[0].keys()) if rows else text.splitlines()[:1]
    if not rows and text.strip().split(",")[:4] == _AV_COLUMNS:
        return []  # a valid file with no rows
    if not rows or header[:4] != _AV_COLUMNS:
        # Errors and rate-limit notices come back as JSON with HTTP 200.
        raise ValueError(f"not an earnings calendar CSV: {text[:200]!r}")
    return rows


class AlphaVantage:
    """Alpha Vantage EARNINGS_CALENDAR (free tier, API key).

    One request returns every company for the next three months, so a run
    costs one of the free tier's 25 daily requests. Reports fiscal period end
    and release timing, but not whether a date is confirmed.
    """

    name = "Alpha Vantage"
    url = "https://www.alphavantage.co/query"

    def __init__(self, api_key: str | None, fye_months: dict[str, int],
                 http_get: HttpGet = urllib_get, **kw):
        self.api_key = api_key
        self.fye_months = fye_months
        self.http_get = http_get
        self.kw = kw
        self._rows: dict[str, list[dict]] | None = None

    def _load(self):
        if self._rows is None:
            if not self.api_key:
                raise SourceUnavailable(self.name, "ALPHAVANTAGE_API_KEY is not set")
            # Alpha Vantage only accepts the key as a query parameter.
            query = urllib.parse.urlencode({"function": "EARNINGS_CALENDAR",
                                            "horizon": "3month", "apikey": self.api_key})
            rows = get(self.name, self.http_get, f"{self.url}?{query}", {},
                       parse=parse_alpha_vantage_csv, **self.kw)
            self._rows = {}
            for row in rows:
                self._rows.setdefault((row.get("symbol") or "").upper(), []).append(row)
        return self._rows

    def fetch(self, ticker: str, start: date, end: date) -> list[Report]:
        reports = []
        for row in self._load().get(ticker, []):
            try:
                day = date.fromisoformat(row["reportDate"])
            except (KeyError, TypeError, ValueError):
                raise SourceUnavailable(self.name, f"bad reportDate for {ticker}: {row!r}")
            if not (start <= day <= end):
                continue
            raw_timing = (row.get("timeOfTheDay") or "").strip()
            timing = ALPHA_VANTAGE_TIMING.get(raw_timing)
            if timing is None:
                log.warning("%s: unknown timeOfTheDay %r for %s; treating as not reported",
                            self.name, raw_timing, ticker)
                timing = NOT_REPORTED
            fy = fq = None
            if row.get("fiscalDateEnding"):
                try:
                    m, y = period_end_month(date.fromisoformat(row["fiscalDateEnding"]))
                except ValueError:
                    raise SourceUnavailable(self.name, f"bad fiscalDateEnding for {ticker}: {row!r}")
                fy, fq = fiscal_quarter_from_period_end(m, y, self.fye_months.get(ticker, 12))
            reports.append(Report(source=self.name, ticker=ticker, date=day, timing=timing,
                                  fiscal_year=fy, fiscal_quarter=fq, status=STATUS_NOT_REPORTED))
        return reports
