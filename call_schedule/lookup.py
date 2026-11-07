"""Find each upcoming report's call time and webcast link.

Reads earnings.ics (the contract with the calendar generator), asks Finnhub's
company news for each ticker's recent announcements, and parses the call time
and link. A ticker with no announcement yet is "not announced", not an error.
A Finnhub failure raises SourceUnavailable, same as the generator.
"""

from __future__ import annotations

import json
import re
import urllib.parse
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from earnings_calendar import ics
from earnings_calendar.sources import SourceUnavailable, get_json, urllib_get

from .parse import parse_announcement

NEWS_URL = "https://finnhub.io/api/v1/company-news"
LOOKBACK_DAYS = 60
_ANNOUNCEMENT_WORDS = re.compile(r"conference call|webcast|earnings call", re.I)


@dataclass
class Upcoming:
    ticker: str
    earnings_date: date
    summary: str


def upcoming_reports(ics_path: Path, today: date, days: int) -> list[Upcoming]:
    out = []
    for ev in ics.parse(ics_path.read_bytes()).values():
        d = ev.props["DTSTART"]
        day = date(int(d[:4]), int(d[4:6]), int(d[6:8]))
        if today <= day <= today + timedelta(days=days):
            summary = ev.props["SUMMARY"].replace("\\,", ",")
            out.append(Upcoming(ev.uid.split("-")[0].upper(), day, summary))
    return sorted(out, key=lambda u: (u.earnings_date, u.ticker))


def find_call(ticker: str, expected: date, today: date, api_key: str, http_get=urllib_get, **kw):
    query = urllib.parse.urlencode({"symbol": ticker, "from": (today - timedelta(days=LOOKBACK_DAYS)).isoformat(),
                                    "to": today.isoformat()})
    news = get_json("Finnhub", http_get, f"{NEWS_URL}?{query}",
                    {"X-Finnhub-Token": api_key, "Accept": "application/json"}, **kw)
    if not isinstance(news, list):
        raise SourceUnavailable("Finnhub", f"unexpected company-news shape for {ticker}")
    for item in sorted(news, key=lambda n: n.get("datetime", 0), reverse=True):
        text = f'{item.get("headline", "")}. {item.get("summary", "")}'
        if not _ANNOUNCEMENT_WORDS.search(text):
            continue
        info = parse_announcement(text, expected)
        if info:
            return item, info
    return None, None


def lookup(ics_path: Path, today: date, days: int, api_key: str, ir_urls: dict[str, str],
           http_get=urllib_get, **kw) -> list[dict]:
    rows = []
    for up in upcoming_reports(ics_path, today, days):
        item, info = find_call(up.ticker, up.earnings_date, today, api_key, http_get, **kw)
        row = {"ticker": up.ticker, "earnings_date": up.earnings_date.isoformat(),
               "calendar_event": up.summary}
        if info is None:
            row.update(status="not announced yet", call_start=None, webcast_url=None,
                       webcast_kind=None, dial_in=None, ir_page=ir_urls.get(up.ticker))
        else:
            kind = "from announcement" if info.webcast_url else "none in announcement"
            row.update(status="found", call_start=info.start.isoformat(),
                       call_start_utc=info.start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                       webcast_url=info.webcast_url, webcast_kind=kind, dial_in=info.dial_in,
                       ir_page=ir_urls.get(up.ticker),
                       announced=datetime.fromtimestamp(item["datetime"], timezone.utc).strftime("%Y-%m-%d"),
                       headline=item.get("headline"))
        rows.append(row)
    return rows


def render(rows: list[dict]) -> str:
    lines = [f'{"Ticker":6} {"Earnings":10} {"Call start (ET)":17} {"Webcast / where to listen"}']
    from zoneinfo import ZoneInfo
    for r in rows:
        if r["status"] != "found":
            lines.append(f'{r["ticker"]:6} {r["earnings_date"]:10} {"not announced yet":17} IR page: {r["ir_page"] or "-"}')
            continue
        et = datetime.fromisoformat(r["call_start"]).astimezone(ZoneInfo("America/New_York"))
        where = r["webcast_url"] or f'{r["ir_page"] or "-"} (IR page; announcement gave no link)'
        if r["dial_in"]:
            where += f' | dial-in {r["dial_in"]}'
        lines.append(f'{r["ticker"]:6} {r["earnings_date"]:10} {et:%a %b %d %-I:%M %p}   {where}')
    return "\n".join(lines)
