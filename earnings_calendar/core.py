"""Compare the sources' reports and turn them into calendar events."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from . import ics
from .sources import (AFTER_CLOSE, BEFORE_OPEN, CONFIRMED, DURING_MARKET, ESTIMATED,
                      NOT_REPORTED, Report)

log = logging.getLogger("earnings_calendar")

CONFLICT = "conflict"  # the sources give different release timings for the same date

TIMING_TITLE = {
    BEFORE_OPEN: "before open",
    AFTER_CLOSE: "after close",
    DURING_MARKET: "during market hours",
    NOT_REPORTED: "time not reported",
    CONFLICT: "timing unclear",
}

# Reports for the same ticker this close together, with quarter labels that
# don't match, are treated as the same quarter (see pair_mismatched_labels).
PAIRING_WINDOW = timedelta(days=45)


@dataclass(frozen=True)
class Settings:
    source_names: tuple[str, ...]          # in display order, e.g. ("Finnhub", "Nasdaq")
    tz: str = "America/New_York"
    duration_minutes: int = 60
    default_start: dict | None = None      # timing -> "HH:MM"
    uid_domain: str = "earnings-calendar"
    ir_urls: dict | None = None

    def start_time(self, timing: str) -> time:
        defaults = {BEFORE_OPEN: "08:30", AFTER_CLOSE: "16:30",
                    DURING_MARKET: "12:00", NOT_REPORTED: "08:30"}
        defaults.update(self.default_start or {})
        hh, mm = defaults[BEFORE_OPEN if timing == CONFLICT else timing].split(":")
        return time(int(hh), int(mm))


def fmt_day(d: date) -> str:
    return f"{d:%a %b} {d.day}, {d.year}"


def fmt_clock(t: time) -> str:
    hour = t.hour % 12 or 12
    return f"{hour}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'}"


def join(names) -> str:
    names = list(names)
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def verb(names) -> str:
    return "does" if len(list(names)) == 1 else "do"


def quarter_key(r: Report):
    if r.fiscal_year is None or r.fiscal_quarter is None:
        return None
    return (r.fiscal_year, r.fiscal_quarter)


def group_by_quarter(reports: list[Report]) -> dict:
    """Group one ticker's reports by fiscal quarter.

    Reports without a quarter label join the labelled group nearest in date
    (within the pairing window); otherwise they stand alone, keyed by date.
    """
    groups: dict = defaultdict(list)
    unlabelled = []
    for r in reports:
        k = quarter_key(r)
        (groups[k].append(r) if k else unlabelled.append(r))
    for r in unlabelled:
        best = min(((min(abs(x.date - r.date) for x in rs), k) for k, rs in groups.items()
                    if isinstance(k, tuple)), default=None)
        if best and best[0] <= PAIRING_WINDOW:
            groups[best[1]].append(r)
        else:
            groups[("date", r.date)].append(r)
    return pair_mismatched_labels(dict(groups))


def pair_mismatched_labels(groups: dict) -> dict:
    """Merge two groups that are clearly one quarter labelled two ways.

    If one quarter group has reports from only source A and another has
    reports from only source B, close together in date, the sources almost
    certainly mean the same release and disagree only on the quarter label
    (for example a wrong fiscal_year_end_month in companies.toml). Merge them
    under Finnhub's label, which comes from the company's fiscal calendar.
    """
    changed = True
    while changed:
        changed = False
        keys = [k for k in groups if isinstance(k[0], int)]
        for a in keys:
            for b in keys:
                if a == b or a not in groups or b not in groups:
                    continue
                sa = {r.source for r in groups[a]}
                sb = {r.source for r in groups[b]}
                if len(sa) != 1 or len(sb) != 1 or sa == sb:
                    continue
                gap = min(abs(x.date - y.date) for x in groups[a] for y in groups[b])
                if gap > PAIRING_WINDOW:
                    continue
                keep, drop = (a, b) if "Finnhub" in sa else (b, a)
                t = groups[a][0].ticker
                log.warning("%s: %s says Q%d FY%d, %s says Q%d FY%d for nearby dates; "
                            "treating them as the same quarter (check companies.toml)",
                            t, join(sa), a[1], a[0], join(sb), b[1], b[0])
                groups[keep] += groups.pop(drop)
                changed = True
    return groups


def build_events(ticker: str, reports: list[Report], s: Settings) -> list[ics.Event]:
    events = []
    for key, rs in group_by_quarter(reports).items():
        by_date: dict[date, list[Report]] = defaultdict(list)
        for r in rs:
            by_date[r.date].append(r)
        disputed = len(by_date) > 1
        quarter = key if isinstance(key[0], int) else None
        for day, day_reports in sorted(by_date.items()):
            others = {d: x for d, x in by_date.items() if d != day}
            events.append(make_event(ticker, quarter, day, day_reports, others, rs, disputed, s))
    return events


def ordered_sources(reports, s: Settings) -> list[str]:
    present = {r.source for r in reports}
    return [n for n in s.source_names if n in present]


def make_event(ticker, quarter, day, day_reports, others, all_reports, disputed, s: Settings):
    known = {r.timing for r in day_reports if r.timing != NOT_REPORTED}
    timing = known.pop() if len(known) == 1 else (CONFLICT if known else NOT_REPORTED)

    if quarter:
        fy, q = quarter
        qlabel = f"Q{q} FY{fy % 100:02d}"
        uid = f"{ticker}-FY{fy}-Q{q}"
    else:
        qlabel = "quarter not reported"
        uid = f"{ticker}-{day:%Y%m%d}"
    if disputed and quarter:
        uid += f"-{day:%Y%m%d}"
    uid = f"{uid.lower()}@{s.uid_domain}"

    summary = f"{ticker} earnings, {qlabel}, {TIMING_TITLE[timing]}"
    if disputed:
        summary = "DISPUTED: " + summary

    start_t = s.start_time(timing)
    tz = ZoneInfo(s.tz)
    start = datetime.combine(day, start_t, tzinfo=tz).astimezone(timezone.utc)
    end = start + timedelta(minutes=s.duration_minutes)

    here = ordered_sources(day_reports, s)
    notes = []
    if disputed:
        notes.append("DISPUTED: the sources disagree on the date of this release.")
        notes.append(f"This date ({fmt_day(day)}) comes from {join(here)}.")
        for d, rs in sorted(others.items()):
            names = ordered_sources(rs, s)
            notes.append(f"{join(names)} {'reports' if len(names) == 1 else 'report'} {fmt_day(d)} instead "
                         "(listed as a separate DISPUTED event).")
    notes.append("Earnings release. The conference call is normally the same day, shortly "
                 "after the release; the exact call time is in the company's own announcement.")

    timing_bits = []
    for r in sorted(day_reports, key=lambda r: s.source_names.index(r.source)):
        timing_bits.append(f"{r.source}: {TIMING_TITLE[r.timing]}")
    notes.append("Release timing: " + "; ".join(timing_bits) + ".")
    tz_abbr = datetime.combine(day, start_t, tzinfo=tz).tzname()
    if timing in (BEFORE_OPEN, AFTER_CLOSE, DURING_MARKET):
        n = sum(1 for r in day_reports if r.timing == timing)
        gives = "the sources give" if n > 1 else "the source gives"
        notes.append(f"Start time approximate: {gives} only \"{TIMING_TITLE[timing]}\", "
                     f"with no clock time, so {fmt_clock(start_t)} {tz_abbr} is a default.")
    elif timing == CONFLICT:
        notes.append(f"Start time approximate: the sources give different release timings, so "
                     f"the event starts at the earlier default, {fmt_clock(start_t)} {tz_abbr}.")
    else:
        notes.append(f"Start time approximate: no source says whether the release is before "
                     f"open or after close, so {fmt_clock(start_t)} {tz_abbr} is a placeholder.")

    if not disputed:
        missing = [n for n in s.source_names if n not in here]
        if missing:
            notes.append(f"Date source: {join(here)} only ({join(missing)} "
                         f"{'has' if len(missing) == 1 else 'have'} no date for "
                         "this quarter).")
        else:
            notes.append(f"Date source: {join(here)} agree.")

    statuses = [(r.source, r.status) for r in day_reports if r.status in (CONFIRMED, ESTIMATED)]
    silent = [n for n in here if n not in {src for src, _ in statuses}]
    if statuses:
        status = "; ".join(f"{st} ({src})" for src, st in statuses)
        if silent:
            status += f". {join(silent)} {verb(silent)} not say whether the date is confirmed"
        notes.append(f"Status: {status}.")
    else:
        notes.append(f"Status: not reported ({join(here)} {verb(here)} not say whether the date is "
                     "confirmed or estimated).")

    ir = (s.ir_urls or {}).get(ticker)
    if ir:
        notes.append(f"Investor relations: {ir}")

    props = {
        "SUMMARY": ics.escape(summary),
        "DTSTART": start.strftime("%Y%m%dT%H%M%SZ"),
        "DTEND": end.strftime("%Y%m%dT%H%M%SZ"),
        "DESCRIPTION": ics.escape("\n".join(notes)),
    }
    if ir:
        props["URL"] = ir  # URI value type: not text-escaped
    return ics.Event(uid=uid, props=props)


def apply_previous(events: list[ics.Event], previous: dict[str, ics.Event], stamp: str):
    """Carry SEQUENCE/DTSTAMP from the previous file; bump on visible change."""
    for ev in events:
        prev = previous.get(ev.uid)
        if prev is None:
            ev.sequence, ev.dtstamp = 0, stamp
        elif prev.props == ev.props:
            ev.sequence, ev.dtstamp = prev.sequence, prev.dtstamp or stamp
        else:
            ev.sequence, ev.dtstamp = prev.sequence + 1, stamp
    return events


def sort_key(ev: ics.Event):
    return (ev.props["DTSTART"], ev.uid)
