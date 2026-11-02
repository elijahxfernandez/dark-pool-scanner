# Dark Pool Scanner

Off-exchange / dark pool flow tool. Runs today on **FINRA's free public historical
data** (weekly, security-level ATS volume); switches to Massive's live trades feed
(`exchange==4`, `trf_id`) for the real tutorial scanner once that subscription is
active (Stocks Developer $79/mo for 15-min delayed, Advanced $199/mo for real-time -
see `dark_pool/scanner.py`'s commented-out real implementation, ready to uncomment).

## Setup

```bash
uv sync
uv run python -m pytest -q
```

## One manual step: a free FINRA developer account

1. Sign in / register at [FINRA Gateway](https://gateway.finra.org) (free, individual account, no payment)
2. Open the **API Console** → **My Credentials** → **Add API Credential**, type **Public**
3. Copy `.env.example` to `.env` and paste the Client ID/Secret in:
   ```
   FINRA_CLIENT_ID=...
   FINRA_CLIENT_SECRET=...
   ```

## How the data actually works (confirmed against the real API, not just docs)

- The historic dataset (`otcMarket/weeklySummaryHistoric`) can **only** be queried by
  week (`weekStartDate`) or tier - **not by symbol**. Each pull grabs one full week,
  every symbol and firm (5,000-row pages, often 6,000-7,000+ ATS-symbol rows/week),
  filtered client-side down to `summaryTypeCode == ATS_W_SMBL` (security-level dark
  pool rows).
- The historic dataset's window is rolling and lags present day by about a year
  (confirmed live: as of Nov 2026 it covers 2021-11-02 to 2025-11-01). The most
  recent ~year lives in FINRA's separate, non-historic `weeklySummary` dataset -
  not yet wired in here.
- FINRA's backend seems to degrade under heavy sustained parallel load (observed
  ~0% failures early in a 24-worker bulk pull, 25%+ later). `client.py` retries
  5xx errors automatically (backoff); a lower `--workers` count helps too.

## Run order

```bash
# 1. Confirm the real field schema (FINRA's docs don't publish it clearly)
uv run python -m dark_pool.finra.collect --discover

# 2. Pull the dataset's entire available history (~209 weeks, whole market each week)
uv run python -m dark_pool.finra.collect --all --workers 24

# 3. Retry any that failed (lower workers = fewer failures)
uv run python -m dark_pool.finra.collect --weeks 2024-03-11 2024-03-18 ... --workers 6

# 4. From here on, just pull what's new (safe to run anytime, no-ops if nothing new)
uv run python -m dark_pool.finra.collect --refresh
```

Output: `data/finra_ats/<week>.csv` - one file per week, every symbol's ATS volume that week.

## Scheduled updates

A Windows Scheduled Task, **`DarkPoolScannerRefresh`**, runs `--refresh` three times a
day (9:30 AM, 12:30 PM, 4:00 PM ET - open/mid-day/close) so the dataset stays current
within a day or two of each new weekly FINRA release, no manual effort needed. It's a
machine-level task (`schtasks`/Task Scheduler), not part of this repo - check/manage it
with:
```powershell
Get-ScheduledTask -TaskName DarkPoolScannerRefresh
```

## Using the data: the scanner

```bash
uv run python -m dark_pool.scanner --latest --top 20   # heaviest off-exchange volume, most recent pulled week
uv run python -m dark_pool.scanner --week 2025-10-13    # a specific week
```

## Structure

```
dark_pool/
  scanner.py        - the real Massive scanner (commented, tutorial-accurate) +
                       the working free scanner (FINRA weekly data)
  finra/
    client.py        - FINRA OAuth2 + query client (schema-discovering, retries 5xx)
    collect.py        - CLI: --discover, --all, --weeks, --refresh
shared/
  config.py          - credentials, folders
```
