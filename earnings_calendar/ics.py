"""Minimal RFC 5545 writer and reader for the calendar file.

The output is deterministic: the same events and the same previous file give
byte-identical output, wherever it runs.
"""

from __future__ import annotations

from dataclasses import dataclass

# Properties a person can see in Google Calendar. SEQUENCE goes up only when
# one of these changes.
VISIBLE = ("SUMMARY", "DTSTART", "DTEND", "DESCRIPTION", "URL")


@dataclass
class Event:
    uid: str
    props: dict[str, str]  # property name -> already-escaped value, in VISIBLE order
    sequence: int = 0
    dtstamp: str = ""


def escape(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(";", "\\;")
            .replace(",", "\\,").replace("\n", "\\n"))


def fold(line: str) -> list[str]:
    """Fold a content line at 75 octets without splitting UTF-8 characters."""
    out, cur, size = [], "", 0
    limit = 75
    for ch in line:
        n = len(ch.encode("utf-8"))
        if size + n > limit:
            out.append(cur)
            cur, size, limit = " ", 1, 75
        cur += ch
        size += n
    out.append(cur)
    return out


def render(events: list[Event], cal_name: str, tz_name: str) -> bytes:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//earnings-calendar//generator v1//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{escape(cal_name)}",
        f"X-WR-TIMEZONE:{tz_name}",
        "REFRESH-INTERVAL;VALUE=DURATION:PT12H",
        "X-PUBLISHED-TTL:PT12H",
    ]
    for ev in events:
        lines += ["BEGIN:VEVENT", f"UID:{ev.uid}", f"DTSTAMP:{ev.dtstamp}",
                  f"SEQUENCE:{ev.sequence}"]
        lines += [f"{k}:{ev.props[k]}" for k in VISIBLE if k in ev.props]
        lines += ["TRANSP:TRANSPARENT", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    folded = [part for line in lines for part in fold(line)]
    return ("\r\n".join(folded) + "\r\n").encode("utf-8")


def parse(data: bytes) -> dict[str, Event]:
    """Read events from a previous run's file, keyed by UID."""
    text = data.decode("utf-8", errors="replace").replace("\r\n", "\n")
    unfolded: list[str] = []
    for raw in text.split("\n"):
        if raw[:1] in (" ", "\t") and unfolded:
            unfolded[-1] += raw[1:]
        elif raw:
            unfolded.append(raw)
    events: dict[str, Event] = {}
    cur: dict[str, str] | None = None
    for line in unfolded:
        if line == "BEGIN:VEVENT":
            cur = {}
        elif line == "END:VEVENT":
            if cur is not None and "UID" in cur:
                try:
                    seq = int(cur.get("SEQUENCE", "0"))
                except ValueError:
                    seq = 0
                events[cur["UID"]] = Event(
                    uid=cur["UID"], props={k: cur[k] for k in VISIBLE if k in cur},
                    sequence=seq, dtstamp=cur.get("DTSTAMP", ""))
            cur = None
        elif cur is not None and ":" in line:
            name, value = line.split(":", 1)
            cur[name.split(";", 1)[0].upper()] = value
    return events
