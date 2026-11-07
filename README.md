# Earnings calendar

Keeps earnings dates for a watchlist in Google Calendar, automatically.

- **Generator** (`generate.py`): fetches dates from Finnhub, Nasdaq and
  Alpha Vantage, compares them, and writes one standard calendar file, `earnings.ics`. That's all it does.
- **Loader**: none in v1. Google Calendar subscribes to the published
  `earnings.ics` and loads it itself.
- **Runtime**: a GitHub Actions job runs the generator daily and commits
  `earnings.ics` when it changes. The generator is a plain Python script
  (standard library only, Python 3.11+), so it runs the same way anywhere.

Events track the earnings **release**. The conference call is normally the same
day, shortly after. No source gives clock times, so start times are defaults
(8:30 AM ET before open, 4:30 PM ET after close) and the notes say
"start time approximate".

## Setup checklist (still to do)

The code, tests, workflow and a first `earnings.ics` are already in the repo.
These steps are left, in this order. Each is done once, in a web browser.

### 1. Rename the branch to `main`

Right now the repo's only branch is `claude/friendly-hopper-ng9fkq`. GitHub
made it the default because it was pushed first. Scheduled workflows only run
on the default branch, and the subscription URL names the branch, so give it a
permanent name before anything else depends on it.

- github.com/thedtripp/earnings-reports → **Settings** → **General** →
  **Default branch** → the pencil icon next to the branch name → rename it to
  `main` → **Rename branch**.

### 2. Make sure the repo is public

Google Calendar can only subscribe to a URL anyone can open.

- **Settings** → **General** → scroll to **Danger Zone** → **Change repository
  visibility**. If it says "Change to private", the repo is already public and
  there's nothing to do.

### 3. Get the two API keys

Both are free.

- **Finnhub:** sign up at finnhub.io. The key is on the dashboard.
- **Alpha Vantage:** alphavantage.co → **Get free API key**. If you posted an
  earlier key anywhere (a chat, a screenshot), request a fresh one and use that.

### 4. Add the keys as repository secrets

- **Settings** → **Secrets and variables** → **Actions** → **New repository
  secret**. Add two secrets, with exactly these names:

  | Name | Value |
  | --- | --- |
  | `FINNHUB_API_KEY` | your Finnhub key |
  | `ALPHAVANTAGE_API_KEY` | your Alpha Vantage key |

Secrets are hidden from the public. Never put a key in a file in this repo,
because the repo is public.

### 5. Run the workflow once by hand

- **Actions** tab → if GitHub asks, click **I understand my workflows, go
  ahead and enable them** → **Update earnings calendar** → **Run workflow** →
  branch `main` → **Run workflow**.
- Wait for the green check (about 2 minutes, mostly Nasdaq).
  - **Red at "Generate earnings.ics"**: open the log. "FINNHUB_API_KEY is not
    set" or "ALPHAVANTAGE_API_KEY is not set" means a secret name is wrong.
    "HTTP 401" or "HTTP 403" from Finnhub means a bad key. A Nasdaq failure
    may mean Nasdaq is blocking GitHub's servers (see "Notes on the sources").
    In every failure case, the published calendar is left unchanged.
  - **Red at "Commit if changed"** with "Permission denied" or "403": go to
    **Settings** → **Actions** → **General** → **Workflow permissions** →
    choose **Read and write permissions** → **Save**, then run it again.

From then on it runs by itself every day at 10:41 UTC.

### 6. Subscribe in Google Calendar

This step needs a computer. The Google Calendar phone app can't add a
calendar by URL.

- calendar.google.com → in the left sidebar, **Other calendars** → **+** →
  **From URL** → paste:

  ```
  https://raw.githubusercontent.com/thedtripp/earnings-reports/main/earnings.ics
  ```

  → **Add calendar**. Events can take a few hours to appear the first time.
- To check the URL works, open it in a browser. You should see text that
  starts with `BEGIN:VCALENDAR`.

### 7. Set reminders

Subscribed calendars can't have per-event reminders, so set one for the
whole calendar.

- calendar.google.com → **Settings** (gear icon) → under **Settings for other
  calendars**, click **Earnings calendar** → **Event notifications** → **Add
  notification** (for example, 1 day before).

Then it's done. The calendar appears on your phone too, once the subscription
syncs.

### Known limits (accepted for v1)

- Google refreshes subscriptions roughly once a day, so a moved date can take
  up to a day longer to show.
- Subscribed events are read-only.
- This is not a last-minute alert system.
- GitHub pauses scheduled workflows in a public repo after 60 days with no
  activity. The daily commits normally count as activity, but if the Actions
  tab ever shows the workflow disabled, click **Enable workflow**.
- If a source fails, the Actions run fails and GitHub emails you. The
  calendar keeps its last good version until a run succeeds.

## One-off manual import (no subscription)

To get the dates into Google Calendar before the setup above is finished:

1. Get a fresh `earnings.ics`: run the generator (see "Running locally"), or
   download the one in this repo.
2. On a computer: calendar.google.com → **Other calendars** → **+** → **Create
   new calendar**, and name it something like "Earnings (manual import)".
3. **Settings** (gear icon) → **Import & export** → **Import** → choose
   `earnings.ics` → **Add to calendar**: the new calendar → **Import**.

Imported events are a one-time copy. They don't update when a date moves, and
past events stay. Importing into a separate calendar lets you delete it in one
step once the subscription is set up, so you don't see every event twice.

## Running locally

```sh
export FINNHUB_API_KEY=your-key
export ALPHAVANTAGE_API_KEY=your-key
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
| `config.toml` | Horizon (45 days), event duration (60 min), default start times, time zone. |
| `earnings.ics` | The output and the only state. Don't edit it by hand. |

## How it decides

- **Per ticker per fiscal quarter.** Finnhub reports the fiscal quarter
  directly. Nasdaq reports the fiscal quarter's end month (for example
  "Oct/2026"), which `companies.toml` converts (NVDA's FY ends in January, so
  Oct 2026 is Q3 FY27). Alpha Vantage's period-end date is converted the same way. If two sources label nearby dates with different
  quarters, they're treated as the same quarter and a warning is logged (the
  usual cause is a wrong `fiscal_year_end_month`).
- **All three sources are equal.** Alpha Vantage is not a tiebreaker: if any
  dates differ, every date becomes its own DISPUTED event. The notes say which
  sources back each date (for example "Nasdaq and Alpha Vantage" against
  "Finnhub"), so you can see the majority, but nothing is dropped.
- **Agree:** one event, notes say the sources agree.
- **Disagree on the date:** one event per date, title prefixed `DISPUTED: `,
  notes name the sources behind that date and the other dates reported. Neither
  date is picked as the winner.
- **Some sources have no date:** one event, notes say which sources have it.
- **Status:** Nasdaq says whether a date is confirmed by the company or
  estimated by an algorithm. Finnhub and Alpha Vantage don't say, and the notes state that.
- **UIDs:** `nvda-fy2027-q3@earnings-calendar`. A disputed event adds the
  date: `avgo-fy2026-q4-20261209@earnings-calendar`. On each run the
  generator reads the previous `earnings.ics` and bumps `SEQUENCE` only when the
  title, time, notes or URL changed, so Google updates the event instead of
  adding a duplicate. Unchanged runs give a byte-identical file, so the job
  commits only on real changes.
- **Failures:** if any source fails (network error, bad or unrecognized
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
- **Alpha Vantage** (`EARNINGS_CALENDAR`, free tier, key): one request
  returns every company for the next three months as CSV, so a run uses 1 of
  the free tier's 25 requests per day. It gives fiscal period end and
  pre-/post-market timing, but no confirmed status. Rate-limit notices come
  back as JSON with HTTP 200; the generator treats those as a failure. The key
  has to go in the URL (`apikey=`). Logs redact it.
- Coverage gaps are normal: a company with no date yet in any source (often
  a foreign filer like TSM or ASML until it announces) simply has no event.

## Roadmap (not built)

Disagreement notifications; a Google Calendar API loader with per-event
reminders.
