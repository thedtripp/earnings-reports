"""Command line entry point: fetch, compare, write one .ics file."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import tomllib
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import core, ics
from .sources import AlphaVantage, Finnhub, Nasdaq, SourceBlocked, SourceUnavailable, urllib_get

log = logging.getLogger("earnings_calendar")

EXIT_OK = 0
EXIT_SOURCE_UNAVAILABLE = 1
EXIT_CONFIG = 2

# Sources the calendar can be published without. Nasdaq alone: it is unofficial
# and blocks some datacenter IPs, and the two keyed sources failing means a
# broken key or quota that someone should fix.
OPTIONAL_SOURCES = {"Nasdaq"}


def read_watchlist(path: Path) -> list[str]:
    tickers = []
    for line in path.read_text(encoding="utf-8").splitlines():
        t = line.split("#", 1)[0].strip().upper()
        if t and t not in tickers:
            tickers.append(t)
    return tickers


def load_config(path: Path) -> dict:
    with path.open("rb") as f:
        cfg = tomllib.load(f)
    base = path.parent
    cfg["_base"] = base
    return cfg


def main(argv=None, http_get=urllib_get, env=None, sources=None) -> int:
    env = os.environ if env is None else env
    p = argparse.ArgumentParser(description="Generate the earnings calendar .ics file.")
    p.add_argument("--config", default="config.toml", help="config file (default: config.toml)")
    p.add_argument("--output", help="override the output .ics path")
    p.add_argument("--previous", help="previous .ics to read state from (default: the output)")
    p.add_argument("--today", help="pretend today is YYYY-MM-DD (default: today in the config time zone)")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(message)s", stream=sys.stderr, force=True)

    try:
        cfg = load_config(Path(args.config))
        base = cfg["_base"]
        tz = cfg.get("timezone", "America/New_York")
        tickers = read_watchlist(base / cfg.get("watchlist", "watchlist.txt"))
        companies_path = base / cfg.get("companies", "companies.toml")
        companies = tomllib.loads(companies_path.read_text(encoding="utf-8")) \
            if companies_path.exists() else {}
        output = Path(args.output) if args.output else base / cfg.get("output", "earnings.ics")
        previous_path = Path(args.previous) if args.previous else output
        today = date.fromisoformat(args.today) if args.today else datetime.now(ZoneInfo(tz)).date()
    except (OSError, ValueError, KeyError, tomllib.TOMLDecodeError) as e:
        log.error("configuration error: %s", e)
        return EXIT_CONFIG
    if not tickers:
        log.error("configuration error: the watchlist is empty")
        return EXIT_CONFIG

    horizon_end = today + timedelta(days=int(cfg.get("horizon_days", 90)))
    fye = {t: int(c["fiscal_year_end_month"]) for t, c in companies.items()
           if "fiscal_year_end_month" in c}
    for t in tickers:
        if t not in fye:
            log.warning("%s: no fiscal_year_end_month in companies.toml; assuming December", t)

    if sources is None:
        sources = [Finnhub(env.get("FINNHUB_API_KEY"), http_get=http_get),
                   Nasdaq(fye, http_get=http_get),
                   AlphaVantage(env.get("ALPHAVANTAGE_API_KEY"), fye, http_get=http_get)]

    reports = {t: [] for t in tickers}
    failed, skipped = [], []
    for src in sources:
        try:
            for t in tickers:
                got = [r for r in src.fetch(t, today, horizon_end) if today <= r.date <= horizon_end]
                log.debug("%s %s: %s", src.name, t, got)
                reports[t] += got
        except SourceBlocked as e:
            if src.name in OPTIONAL_SOURCES:
                log.warning("source blocked, carrying on without it: %s", e)
                skipped.append(src.name)
            else:
                log.error("source unavailable: %s", e)
                failed.append(src.name)
        except SourceUnavailable as e:
            log.error("source unavailable: %s", e)
            failed.append(src.name)

    if failed:
        log.error("%s unavailable: leaving %s untouched, publishing nothing",
                  " and ".join(failed), output)
        return EXIT_SOURCE_UNAVAILABLE

    if skipped:
        # Drop whatever a skipped source returned before it failed: a partial
        # set would make some tickers look different from the rest.
        reports = {t: [r for r in rs if r.source not in skipped] for t, rs in reports.items()}
    settings = core.Settings(
        source_names=tuple(s.name for s in sources if s.name not in skipped), tz=tz,
        duration_minutes=int(cfg.get("duration_minutes", 60)),
        default_start=cfg.get("default_start"),
        uid_domain=cfg.get("calendar", {}).get("uid_domain", "earnings-calendar"),
        ir_urls={t: c["ir_url"] for t, c in companies.items() if "ir_url" in c})

    events = []
    for t in tickers:
        events += core.build_events(t, reports[t], settings)
    previous = ics.parse(previous_path.read_bytes()) if previous_path.exists() else {}
    if skipped:
        events = core.keep_previous(events, previous, today)
        log.warning("%s unavailable: published new dates only; events already in %s are "
                    "kept as they were", " and ".join(skipped), previous_path)
    core.apply_previous(events, previous, stamp=f"{today:%Y%m%d}T000000Z")
    events.sort(key=core.sort_key)
    data = ics.render(events, cfg.get("calendar", {}).get("name", "Earnings calendar"), tz)

    disputed = sum(1 for e in events if e.props["SUMMARY"].startswith("DISPUTED"))
    changed = sum(1 for e in events if e.uid in previous and e.sequence != previous[e.uid].sequence)
    added = sum(1 for e in events if e.uid not in previous)
    removed = len(set(previous) - {e.uid for e in events})
    log.info("%d events (%d disputed): %d new, %d updated, %d removed",
             len(events), disputed, added, changed, removed)

    if output.exists() and output.read_bytes() == data:
        log.info("%s unchanged", output)
        return EXIT_OK
    tmp = output.with_name(output.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, output)  # atomic: readers never see a half-written file
    log.info("wrote %s", output)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
