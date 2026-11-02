# Dark Pool Scanner

Off-exchange / dark pool flow tool. Starts on **FINRA's free public historical data**
(weekly, 2-4 week lag) while the Massive subscription decision is pending; switches to
Massive's live trades feed (`exchange==4`, `trf_id`) for the real scanner once that's
active (Stocks Developer, $79/mo - see project notes).

## Setup

```bash
uv sync
uv run python -m pytest -q
```

## One manual step: a free FINRA developer account

1. Register at [developer.finra.org](https://developer.finra.org) (free, no payment)
2. Create a **Public** app to get a Client ID and Client Secret
3. Copy `.env.example` to `.env` and paste them in:
   ```
   FINRA_CLIENT_ID=...
   FINRA_CLIENT_SECRET=...
   ```

## Run order

```bash
# 1. Confirm the real field names first - FINRA's docs don't publish them clearly
uv run python -m dark_pool.finra.collect --discover

# 2. Pull weekly off-exchange volume history for a watchlist (free, ~4 years back)
uv run python -m dark_pool.finra.collect --symbols JPM BAC GS XOM KO --years 4
```

Output: `data/finra_ats/<SYMBOL>.csv` - one row per week, off-exchange (ATS) and
non-ATS volume for that symbol.

## What this is (and isn't) yet

This is the free, weekly, delayed version - good for a "which stocks see the most
off-exchange volume, which weeks stand out" research angle. It is **not** the live
scanner from the tutorial (individual trades, intraday timing, live alerts) - that
needs Massive's trades feed and a paid plan. See the project's cost notes for the
$79/mo (15-min delayed) vs $199/mo (real-time) options.

## Structure

```
dark_pool/
  finra/
    client.py    - FINRA OAuth2 + query client (schema-discovering, not hardcoded)
    collect.py   - CLI: --discover the schema, then pull a watchlist's history
shared/
  config.py      - credentials, folders
```
