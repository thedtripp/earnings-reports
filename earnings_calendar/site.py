"""Render the demo page: a plain HTML list of the upcoming events in earnings.ics.

Standard library only. The page is built from the same file people subscribe to,
so it can never disagree with the calendar.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from . import ics

SUBSCRIBE_URL = "https://raw.githubusercontent.com/thedtripp/earnings-reports/main/earnings.ics"
REPO_URL = "https://github.com/thedtripp/earnings-reports"
HOME_URL = "https://www.ddtripp.com/"

_SUMMARY = re.compile(r"^(DISPUTED: )?([^ ]+) earnings, (.+?), ([^,]+)$")
_STATUS = re.compile(r"Status: (confirmed|estimated|not reported)")


@dataclass
class Row:
    day: str          # e.g. "Tue Nov 17, 2026"
    sort_key: str     # ISO date for ordering
    ticker: str
    quarter: str
    timing: str
    status: str       # confirmed / estimated / not reported
    disputed: bool
    url: str


def unescape(text: str) -> str:
    out, i = [], 0
    while i < len(text):
        c = text[i]
        if c == "\\" and i + 1 < len(text):
            n = text[i + 1]
            out.append("\n" if n in "nN" else n)
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def rows_from_ics(data: bytes, tz: str = "America/New_York",
                  today: datetime | None = None) -> list[Row]:
    zone = ZoneInfo(tz)
    now = (today or datetime.now(timezone.utc)).astimezone(zone).date()
    rows = []
    for ev in ics.parse(data).values():
        summary = unescape(ev.props.get("SUMMARY", ""))
        m = _SUMMARY.match(summary)
        if not m:
            continue
        start = datetime.strptime(ev.props["DTSTART"], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        local = start.astimezone(zone)
        if local.date() < now:
            continue
        s = _STATUS.search(unescape(ev.props.get("DESCRIPTION", "")))
        rows.append(Row(
            day=f"{local:%a %b} {local.day}, {local.year}", sort_key=local.date().isoformat(),
            ticker=m.group(2), quarter=m.group(3), timing=m.group(4),
            status=s.group(1) if s else "not reported", disputed=bool(m.group(1)),
            url=ev.props.get("URL", "")))
    rows.sort(key=lambda r: (r.sort_key, r.ticker))
    return rows


_STATUS_LABEL = {"confirmed": "Confirmed", "estimated": "Estimated", "not reported": "Unconfirmed"}


def render(rows: list[Row], built_at: datetime, cover: str | None = "cover.png") -> str:
    e = html.escape
    items = []
    for r in rows:
        badges = f'<span class="badge {r.status.replace(" ", "-")}">{_STATUS_LABEL[r.status]}</span>'
        if r.disputed:
            badges += '<span class="badge disputed">Sources disagree</span>'
        link = (f'<a href="{e(r.url, quote=True)}" rel="noopener">Investor relations</a>'
                if r.url.startswith("https://") else "")
        items.append(
            f'<li><div class="date">{e(r.day)}</div>'
            f'<div class="main"><strong>{e(r.ticker)}</strong> '
            f'<span class="muted">{e(r.quarter)} · {e(r.timing)}</span></div>'
            f'<div class="side">{badges}{link}</div></li>')
    body = ("<ul class=\"events\">" + "".join(items) + "</ul>") if items else \
        '<p class="empty">No upcoming earnings dates right now.</p>'
    hero = f'<img class="cover" src="{e(cover, quote=True)}" alt="">' if cover else ""
    gcal = "https://calendar.google.com/calendar/r?cid=" + SUBSCRIBE_URL.replace("https://", "webcal://")
    stamp = f"{built_at:%b} {built_at.day}, {built_at.year} {built_at:%H:%M} UTC"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Earnings calendar</title>
<meta name="description" content="Earnings dates for large-cap tech, cross-checked across three sources and published as a calendar you can subscribe to.">
<meta property="og:type" content="website">
<meta property="og:title" content="Earnings calendar">
<meta property="og:description" content="Earnings dates for large-cap tech, cross-checked across three sources and published as a calendar you can subscribe to.">
<meta property="og:url" content="https://www.ddtripp.com/earnings-reports/">
<meta property="og:image" content="https://www.ddtripp.com/earnings-reports/og.png">
<meta name="twitter:card" content="summary_large_image">
<style>
:root{{color-scheme:dark;--bg:#12101a;--card:#1b1826;--fg:#ece9f5;--muted:#a19db2;--line:#2c2839;--accent:#a78bfa;--ok:#5eead4;--warn:#fbbf24;--bad:#c4b5fd}}
*{{box-sizing:border-box}}.home{{position:absolute;top:14px;left:16px;z-index:2;padding:7px 14px;border-radius:999px;background:rgba(18,16,26,.62);border:1px solid rgba(236,233,245,.22);color:#ece9f5;text-decoration:none;font-weight:600;font-size:.8rem;letter-spacing:.14em;text-transform:uppercase;backdrop-filter:blur(6px)}}.home:hover{{background:rgba(18,16,26,.85);border-color:var(--accent)}}.home:focus-visible,.btn:focus-visible{{outline:2px solid var(--accent);outline-offset:2px}}body{{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}}
main{{max-width:760px;margin:0 auto;padding:0 16px 48px}}
.cover{{display:block;width:100%;height:auto;max-height:260px;object-fit:cover;object-position:center;border-radius:0 0 14px 14px;margin:0 0 20px}}
h1{{font-size:1.9rem;line-height:1.2;margin:8px 0 6px}}p.lede{{color:var(--muted);margin:0 0 18px}}
.actions{{display:flex;flex-wrap:wrap;gap:10px;margin:0 0 28px}}
.btn{{display:inline-block;padding:9px 16px;border-radius:9px;border:1px solid var(--line);background:var(--card);color:var(--fg);text-decoration:none;font-weight:600;font-size:.95rem;cursor:pointer}}
.btn.primary{{background:var(--accent);border-color:var(--accent);color:#12101a}}
code.url{{display:block;margin:0 0 28px;padding:10px 12px;border:1px dashed var(--line);border-radius:9px;color:var(--muted);font-size:.8rem;overflow-wrap:anywhere}}
h2{{font-size:1.1rem;margin:0 0 10px}}
.events{{list-style:none;margin:0;padding:0;background:var(--card);border:1px solid var(--line);border-radius:12px}}
.events li{{display:grid;grid-template-columns:130px 1fr auto;gap:8px 14px;align-items:center;padding:12px 16px;border-top:1px solid var(--line)}}
.events li:first-child{{border-top:0}}.date{{font-weight:600;font-size:.92rem}}.muted{{color:var(--muted);font-size:.92rem}}
.side{{display:flex;flex-wrap:wrap;gap:6px;justify-content:flex-end;align-items:center;font-size:.85rem}}.side a{{color:var(--accent)}}
.badge{{padding:2px 9px;border-radius:999px;font-size:.75rem;font-weight:600;border:1px solid currentColor}}
.confirmed{{color:var(--ok)}}.estimated{{color:var(--warn)}}.not-reported{{color:var(--muted)}}.disputed{{color:var(--bad)}}
@media (max-width:560px){{.events li{{grid-template-columns:1fr}}.side{{justify-content:flex-start}}}}
.empty{{color:var(--muted)}}footer{{margin-top:28px;color:var(--muted);font-size:.85rem}}footer a{{color:var(--accent)}}
</style></head><body>
<a class="home" href="{e(HOME_URL, quote=True)}" aria-label="Back to ddtripp.com">&larr; DDTRIPP</a>
{hero}<main>
<h1>Earnings calendar</h1>
<p class="lede">Earnings dates for large-cap tech, cross-checked across three sources and published as a calendar you can subscribe to. Updated daily.</p>
<div class="actions"><a class="btn primary" href="{e(gcal, quote=True)}">Add to Google Calendar</a>
<button class="btn" id="copy" type="button">Copy calendar URL</button>
<a class="btn" href="{e(REPO_URL, quote=True)}">View source</a></div>
<code class="url" id="url">{e(SUBSCRIBE_URL)}</code>
<h2>Upcoming</h2>
{body}
<footer>Built {e(stamp)}. Dates come from Finnhub, Nasdaq and Alpha Vantage; only Nasdaq says whether a date is confirmed. Start times are approximate defaults. <a href="{e(REPO_URL, quote=True)}">How it works</a>. <a href="{e(HOME_URL, quote=True)}">Back to ddtripp.com</a>.</footer>
</main>
<script>document.getElementById("copy").addEventListener("click",function(){{var b=this,t=document.getElementById("url").textContent;(navigator.clipboard?navigator.clipboard.writeText(t):Promise.reject()).then(function(){{b.textContent="Copied"}},function(){{b.textContent="Select the URL below"}})}});</script>
</body></html>
"""
