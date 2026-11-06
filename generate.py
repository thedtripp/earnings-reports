#!/usr/bin/env python3
"""Generate earnings.ics. Usage: FINNHUB_API_KEY=... python3 generate.py"""
import sys

from earnings_calendar.cli import main

if __name__ == "__main__":
    sys.exit(main())
