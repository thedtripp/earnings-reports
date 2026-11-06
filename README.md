# Earnings calendar

Keeps earnings dates for a watchlist in Google Calendar, automatically.

- **Generator** (`generate.py`): fetches dates from Finnhub and Nasdaq, compares
  them, and writes one standard calendar file, `earnings.ics`. That's all it does.
- **Loader**: none in v1. Google Calendar subscribes to the published
  `earnings.ics` and loads it itself.
- **Runtime**: a GitHub Actions job runs the generator daily and commits
  `earnings.ics` when it changes. The generator is a plain Python script
  (standard library only, Python 3.11+), so it runs the same way anywhere.

Events track the earnings **release**. The conference call is normally the same
day, shortly after. No source gives clock times, so start times are defaults
(8:30 AM ET before open, 4:30 PM ET after close) and the notes say
"start time approximate".

## Setup

1. **Finnhub key.** Get a free API key at finnhub.io. In the GitHub repo, go to
   Settings → Secrets and variables → Actions → New repository secret, name it
   `FINNHUB_API_KEY`, and paste the key. Never commit the key.
2. **Default branch.** Scheduled workflows only run on the default branch. Merge
   this branch into it (or make it the default) so the daily job runs there.
3. **Public repo.** Google can subscribe only to a public URL, so the repo
   must be public.
4. **First run.** Actions tab → "Update earnings calendar" → Run workflow. Make
   sure it goes green.
5. **Subscribe in Google Calendar.** On a computer: Other calendars → **+** → From URL,
   and paste:

   ```
   https://raw.githubusercontent.com/thedtripp/earnings-reports/<default-branch>/earnings.ics
   ```

6. **Reminders.** Google Calendar settings → the subscribed calendar → set a
   default notification (for example, 1 day before). Subscribed calendars
   can't have per-event reminders.

Known limits (accepted for v1): Google refreshes subscriptions roughly once a
day, subscribed events are read-only, and this is not a last-minute alert system.

## Running locally

```sh
export FINNHUB_API_KEY=your-key
python3 generate.py            # writes earnings.ics next to config.toml
python3 generate.py --today 2026-11-06 -v   # pretend date, verbose log
python3 -m unittest discover -s tests       # offline acceptance tests
```

Exit codes: `0` success, `1` a source was unavailable (nothing written),
`2` configuration error.

## Files

| File | Purpose |
| --- | --- |
| `watchlist.txt` | One ticker per line. Edit by hand. |
| `companies.toml` | Per ticker: fiscal-year-end month and investor-relations URL. Add an entry when you add a ticker. |
| `config.toml` | Horizon (90 days), event duration (60 min), default start times, time zone. |
| `earnings.ics` | The output and the only state. Don't edit it by hand. |

## How it decides

- **Per ticker per fiscal quarter.** Finnhub reports the fiscal quarter
  directly. Nasdaq reports the fiscal quarter's end month (for example
  "Oct/2026"), which `companies.toml` converts (NVDA's FY ends in January, so
  Oct 2026 is Q3 FY27). If the two sources label nearby dates with different
  quarters, they're treated as the same quarter and a warning is logged (the
  usual cause is a wrong `fiscal_year_end_month`).
- **Agree:** one event, notes say both sources agree.
- **Disagree on the date:** one event per date, title prefixed `DISPUTED: `,
  notes name the source behind that date and the other source's date. Neither
  date is picked as the winner.
- **Only one source has a date:** one event, notes say which source.
- **Status:** Nasdaq says whether a date is confirmed by the company or
  estimated by an algorithm. Finnhub doesn't say, and the notes state that.
- **UIDs:** `nvda-fy2027-q3@earnings-calendar`. A disputed event adds the
  date: `avgo-fy2026-q4-20261209@earnings-calendar`. On each run the
  generator reads the previous `earnings.ics` and bumps `SEQUENCE` only when the
  title, time, notes or URL changed, so Google updates the event instead of
  adding a duplicate. Unchanged runs give a byte-identical file, so the job
  commits only on real changes.
- **Failures:** if either source fails (network error, bad or unrecognized
  response, rate limit, missing key), the generator writes nothing, leaves the
  previous `earnings.ics` byte-identical, and exits `1`. The Actions run then
  fails visibly instead of quietly deleting real events.

## Notes on the sources

- **Finnhub** (`/calendar/earnings`) is queried per ticker. The unfiltered
  calendar caps at 1,500 rows and would silently drop dates. 20 tickers fit
  well inside the free tier's 60 calls/minute.
- **Nasdaq** (`api.nasdaq.com`, unofficial, no key): the per-ticker
  `earnings-date` endpoint gives the next date and its confirmed/estimated
  status. The calendar for that day gives the release timing and fiscal
  quarter. Being unofficial, it can change format or block traffic from some
  networks. Either one fails the run, which is the intended loud failure.
- Coverage gaps are normal: a company with no date yet in either source (often
  a foreign filer like TSM or ASML until it announces) simply has no event.

## Roadmap (not built)

Disagreement notifications; a Google Calendar API loader with per-event
reminders; a third source as tiebreaker.
