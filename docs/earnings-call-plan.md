# Earnings call listener: plan

Status: **planning, one proof of concept built.** Written 2026-11-07. Nothing
here is a final design. Items marked *open* are undecided.

## Goal

Listen to and transcribe an earnings call, and analyze it in real time next to
market moves, for the stocks on the watchlist.

## Principles

- A **separate pipeline** from the calendar generator. The calendar's
  `earnings.ics` is the contract: new pipelines read it and never change it.
- Same failure rule as the generator: a failed source is "unavailable", never
  "empty".
- Each stage works and is tested alone before the next one starts.

## Stages

| # | Stage | Status |
| --- | --- | --- |
| 1 | **Call schedule**: call time and webcast link for reports in the next N days | POC built (below) |
| 2 | **Audio or transcript source**: where the live call comes from | *open*, needs a decision |
| 3 | **Speech-to-text** (only if stage 2 gives audio) | not started |
| 4 | **Live price and volume feed** | not started |
| 5 | **Analysis**: transcript windows next to price moves, using Claude | not started |
| 6 | **Output**: live view, alerts, post-call summary | *open* |

## Stage 1: call schedule (POC)

Run: `FINNHUB_API_KEY=... python3 call_schedule_poc.py --days 7`

How it works: read `earnings.ics` for reports in the next N days, pull each
ticker's recent company news from Finnhub (existing key, no new source), find
the announcement ("X to host conference call..."), and parse the call time,
dial-in and webcast link. A ticker with no announcement yet is "not announced
yet", not an error. A Finnhub failure exits nonzero.

Result on 2026-11-07, reports within 12 days:

| Found | Not found by the POC |
| --- | --- |
| TTWO, AMAT, CSCO, HD, PANW: call time found | NVDA, DIS, WMT |

Known gaps:

- **Finnhub misses some announcements.** NVIDIA announced its Nov 17 call
  (2 p.m. PT, webcast on its IR site) and the POC did not find it. NVDA has
  heavy news volume and Finnhub caps a query at about 250 items, newest first,
  so busy tickers can push the announcement out of the window. Narrow date
  windows would help but cost more API calls (free tier: 60 per minute).
- **Summaries are cut at about 500 characters.** The call time is usually
  inside that, but webcast links often are not. Where the link is missing, the
  output falls back to the company's investor-relations page and says so. The
  full text sits behind a redirect to a third-party site, which the POC does
  not scrape.
- **Some companies announce late.** Walmart announced its 2025 Q3 call a week
  before the call, so a 7-day lookahead is borderline for companies like it.
  Announcements seen so far came 1 to 3 weeks ahead.
- Not every announcement states a time zone or a year. The parser skips a bare
  time with no zone, and infers the year when it is missing.

Next experiments for stage 1 (*open*): fetch the press-release wires or the
companies' own IR pages directly for full text; SEC filings; narrow-window
news queries for busy tickers.

## Stage 2: where the audio or transcript comes from (*open*)

Findings from vendor pages and comparison sites. Prices and limits are
unverified; check each vendor's own pages before relying on them.

- **Live transcript vendors** (no audio capture or speech-to-text to build):
  [Quartr](https://quartr.com/docs/datasets/live-earnings-call-transcripts)
  (JSON Lines stream, webhooks), [Benzinga](https://prnewswire.com/news-releases/benzinga-unveils-a-live-conference-call-transcript-api-to-enhance-earnings-information-accessibility-302196494.html)
  (WebSocket, sentence-level, mock mode),
  [FactSet](https://platform.softwareone.com/product/documents-distributor-near-real-time-transcripts-api/PCP-9120-3234)
  (near-real-time, institutional). Pricing not found.
- **Post-call transcripts only:** Finnhub and
  [Financial Modeling Prep](https://site.financialmodelingprep.com/developer/docs/earning-call-transcript-api)
  transcripts appear to be paid tiers.
- **Do it ourselves:** capture webcast audio, then stream to speech-to-text.
  Reported streaming prices are small per call (about $0.15 to $0.46 per hour
  across [AssemblyAI](https://www.assemblyai.com/blog/speech-to-text-api-pricing)
  and [Deepgram](https://www.happyrobot.ai/hub/deepgram-pricing) sources, which
  disagree). The hard part is the audio itself: every company uses a different
  webcast platform, many need registration, and terms of use may restrict
  recording. Checking those terms is required before building this route.

Decision needed: buy a live transcript feed, or capture audio ourselves. Stage 1
supplies the webcast links either way.

## Stages 3 to 6: notes

- **Price feed** (*open*): Finnhub and
  [Alpaca](https://alpaca.markets/learn/the-top-3-differences-between-polygon-and-alpaca-data-plans/)
  look like the free real-time options; sources disagree on limits, and one
  reports Finnhub's WebSocket dropping connections, so reconnect handling is
  needed. Polygon's free tier looks poor for this.
- **Analysis**: Claude reads the transcript in rolling windows with price and
  volume moves around them, and flags what was said near each move.
- **Where it runs**: live capture needs a process that stays up for the whole
  call, so a local machine or a small server, not a GitHub Actions job. *open*
- **Not investment advice.** The output is for the owner's own research; the
  analysis can be wrong, and transcripts, especially auto-generated ones, can
  contain errors.

## Open questions

1. Live transcript vendor or own audio capture?
2. Which lookahead for stage 1? 7 days is the target; some companies announce
   about a week before.
3. What output matters most: live view, alerts, or post-call summary?
4. Where does the listener run?
5. Budget ceiling for any paid feed?
