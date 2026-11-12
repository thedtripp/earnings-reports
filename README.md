# Earnings calendar

Keeps earnings dates for a watchlist in a standard calendar file, `earnings.ics`,
that Google Calendar (or any calendar app) can subscribe to.

- **Generator** (`generate.py`): fetches dates from Finnhub, Nasdaq and Alpha
  Vantage, compares them, and writes `earnings.ics`. Python 3.11+, standard
  library only, no GitHub-specific code.
- **Runtime**: a GitHub Actions job runs daily (10:41 UTC), runs the tests, runs
  the generator, and commits `earnings.ics` if it changed.
- **Subscribe** to the raw file URL, then set one reminder for the whole
  calendar in your calendar app:
  `https://raw.githubusercontent.com/<owner>/<repo>/main/earnings.ics`

## Events

- One event per ticker per fiscal quarter, for dates up to 45 days out. Past
  that, only Finnhub has dates, with no cross-check.
- Title: `NVDA earnings, Q3 FY27, after close`. The event is the earnings
  **release**. Exact call times and webcast links are not tracked.
- Start times are defaults, because no source gives a clock time: 8:30 AM ET
  before open, 4:30 PM ET after close. The notes say "start time approximate".
  Each event lasts 1 hour.
- Notes list the sources behind the date, confirmed or estimated status, and the
  investor-relations link.
- **Sources agree:** one event.
- **Sources disagree on the date:** one event per date, prefixed `DISPUTED: `,
  each naming its sources and the other date. No source is treated as the winner.
- **Status:** only Nasdaq says whether a date is confirmed.
- **UIDs:** `nvda-fy2027-q3@earnings-calendar`, or
  `avgo-fy2026-q4-20261209@earnings-calendar` when disputed. The generator reads
  the previous `earnings.ics` (the only state) and raises `SEQUENCE` only when a
  visible field changes, so calendars update events instead of duplicating them.
  An unchanged run gives a byte-identical file.

## Earnings call listener (planning)

A separate, not-yet-built pipeline for transcribing and analyzing calls. A
proof of concept, `call_schedule_poc.py`, looks up call times and webcast links
for reports in the next 7 days. It reads `earnings.ics` and never changes it.
See [`docs/earnings-call-plan.md`](docs/earnings-call-plan.md).

## Failure behavior

If any source fails (network error, bad or unrecognized response, rate limit,
missing key), nothing is written. The previous `earnings.ics` stays untouched,
the run exits `1`, and the Actions run fails visibly.

## Configuration

| File | Purpose |
| --- | --- |
| `watchlist.txt` | One ticker per line. |
| `companies.toml` | Per ticker: fiscal-year-end month (labels Nasdaq and Alpha Vantage quarters) and investor-relations URL. Add an entry for each new ticker, or it is assumed to have a December year-end. |
| `config.toml` | Horizon, event duration, default start times, time zone. |
| `earnings.ics` | Output and only state. Don't edit by hand. |

The job needs two repository secrets: `FINNHUB_API_KEY` and
`ALPHAVANTAGE_API_KEY` (both free tiers). Never commit keys.

## Running locally

```sh
export FINNHUB_API_KEY=... ALPHAVANTAGE_API_KEY=...
python3 generate.py                          # writes earnings.ics
python3 generate.py --today 2026-11-06 -v    # fixed date, verbose
python3 -m unittest discover -s tests        # offline tests
python3 call_schedule_poc.py --days 7        # call-time lookup (needs FINNHUB_API_KEY)
```

Exit codes: `0` success, `1` a source was unavailable, `2` configuration error.

## Sources

- **Finnhub** `/calendar/earnings`, per ticker. Gives fiscal quarter and
  timing, not confirmed status.
- **Nasdaq** `api.nasdaq.com`, unofficial and keyless. Gives confirmed or
  estimated status, timing and fiscal period end. It can change format or block
  traffic without notice, which fails the run.
- **Alpha Vantage** `EARNINGS_CALENDAR`: one request covers all tickers (the
  free tier allows 25 per day). Gives timing and fiscal period end. Rate-limit
  notices arrive as normal responses and are treated as failures.
- A ticker with no date in any source (often new listings and foreign filers)
  simply has no event until one appears.

## Limits

- Nasdaq sometimes blocks GitHub's servers (HTTP 403). The generator retries
  with growing waits; if Nasdaq stays blocked it publishes without it: events
  already in `earnings.ics` are kept exactly as they were (so "confirmed" is
  never lost), new events from Finnhub and Alpha Vantage are added, and the
  log shows a warning. If Finnhub or Alpha Vantage fail, nothing is published.
- Calendar apps refresh subscriptions about once a day. Subscribed events are
  read-only, and this is not a last-minute alert system.
- GitHub pauses scheduled workflows in a public repo after 60 days without
  activity. Daily commits normally count, but if the workflow is ever disabled,
  re-enable it in the Actions tab.
