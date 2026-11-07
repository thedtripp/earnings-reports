"""Pull the call time, dial-in and webcast link out of an announcement's text."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

TZ = {
    "ET": "America/New_York", "EST": "America/New_York", "EDT": "America/New_York", "EASTERN": "America/New_York",
    "CT": "America/Chicago", "CST": "America/Chicago", "CDT": "America/Chicago", "CENTRAL": "America/Chicago",
    "MT": "America/Denver", "MST": "America/Denver", "MDT": "America/Denver", "MOUNTAIN": "America/Denver",
    "PT": "America/Los_Angeles", "PST": "America/Los_Angeles", "PDT": "America/Los_Angeles", "PACIFIC": "America/Los_Angeles",
}
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

_DATE = re.compile(
    r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sept?(?:ember)?|"
    r"Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\b", re.I)
_TIME = re.compile(
    r"\b(\d{1,2})(?::(\d{2}))?\s*([ap])\.?\s?m\.?"
    r"(?:\s*[\(/,]?\s*(E[SD]?T|P[SD]?T|C[SD]?T|M[SD]?T|Eastern|Pacific|Central|Mountain)\b)?", re.I)
_URL = re.compile(r"https?://[^\s)\]>\"']+")
_PHONE = re.compile(r"\(?\b\d{3}\)?[-\s.]\d{3}[-.]\d{4}\b")


@dataclass(frozen=True)
class CallInfo:
    start: datetime            # timezone-aware
    date_from_text: bool       # False if the date came from the calendar, not the text
    tz_label: str
    webcast_url: str | None
    dial_in: str | None


def dates_in(text: str, near: date) -> list[date]:
    """Dates written in the text. A date with no year takes the year that puts
    it closest to `near` (press releases often say just "November 17")."""
    out = []
    for m in _DATE.finditer(text):
        month, dom = MONTHS[m.group(1)[:3].lower()], int(m.group(2))
        years = [int(m.group(3))] if m.group(3) else [near.year - 1, near.year, near.year + 1]
        cands = []
        for y in years:
            try:
                cands.append(date(y, month, dom))
            except ValueError:
                pass
        if cands:
            out.append(min(cands, key=lambda d: abs((d - near).days)))
    return out


def parse_announcement(text: str, expected: date) -> CallInfo | None:
    """Return the call details if the text announces a call near `expected`.

    `expected` is the earnings date from the calendar. A text with no clock
    time is not an announcement of a call time, so it returns None.
    """
    # Replay times come after the call time; never read them as the call.
    head = re.split(r"\breplay\b", text, maxsplit=1, flags=re.I)[0]
    times = []
    for m in _TIME.finditer(head):
        hour, minute = int(m.group(1)), int(m.group(2) or 0)
        if not (1 <= hour <= 12 and minute < 60):
            continue
        hour = hour % 12 + (12 if m.group(3).lower() == "p" else 0)
        times.append((time(hour, minute), (m.group(4) or "").upper()))
    if not times:
        return None
    # Prefer a time quoted in Eastern, else the first one that names a zone.
    pick = next((t for t in times if t[1] in ("ET", "EST", "EDT", "EASTERN")), None) \
        or next((t for t in times if t[1]), None)
    if pick is None:
        return None  # a bare time with no zone is not safe to schedule on
    near = [d for d in dates_in(head, expected) if abs((d - expected).days) <= 2]
    day = near[-1] if near else None
    if day is None:
        return None  # the text is about some other date
    tz = ZoneInfo(TZ[pick[1]])
    url = next((u.rstrip(".,;") for u in _URL.findall(text)), None)
    phone = _PHONE.search(text)
    return CallInfo(start=datetime.combine(day, pick[0], tzinfo=tz), date_from_text=True,
                    tz_label=pick[1], webcast_url=url, dial_in=phone.group(0) if phone else None)
