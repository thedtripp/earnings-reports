#!/usr/bin/env python3
"""Look up earnings call times and webcast links for reports in the next N days.

    FINNHUB_API_KEY=... python3 call_schedule_poc.py [--days 7] [--json out.json]

Reads earnings.ics (from the calendar generator). Does not modify it.
"""
import argparse
import json
import logging
import os
import sys
import tomllib
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from earnings_calendar.sources import SourceUnavailable
from call_schedule.lookup import lookup, render


def main(argv=None, http_get=None, env=None) -> int:
    env = os.environ if env is None else env
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=7, help="look this many days ahead (default 7)")
    p.add_argument("--ics", default="earnings.ics")
    p.add_argument("--companies", default="companies.toml")
    p.add_argument("--today", help="pretend today is YYYY-MM-DD")
    p.add_argument("--json", help="also write the results to this file")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stderr)
    key = env.get("FINNHUB_API_KEY")
    if not key:
        logging.error("FINNHUB_API_KEY is not set")
        return 1
    today = date.fromisoformat(args.today) if args.today else datetime.now(ZoneInfo("America/New_York")).date()
    companies = tomllib.loads(Path(args.companies).read_text()) if Path(args.companies).exists() else {}
    ir = {t: c["ir_url"] for t, c in companies.items() if "ir_url" in c}
    kw = {"http_get": http_get} if http_get else {}
    try:
        rows = lookup(Path(args.ics), today, args.days, key, ir, **kw)
    except SourceUnavailable as e:
        logging.error("source unavailable: %s", e)
        return 1
    print(render(rows))
    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
