"""Pull FINRA's free weekly off-exchange (ATS/dark pool) volume history.

IMPORTANT, confirmed against the real API: the historic dataset can only be
queried by week (weekStartDate/historicalWeek/historicalMonth) or tier - NOT by
symbol. FINRA's own error: "Only the following fields can be queried for this
historical dataset [weekStartDate, tierIdentifier, historicalMonth, historicalWeek]"

So each pull grabs one FULL WEEK across every symbol and firm, then we filter
client-side for summaryTypeCode == ATS_W_SMBL (ATS Weekly Symbol - security-level
dark pool rows, not firm-level or non-ATS rows) and whatever symbols we care about.
One week's pull covers the whole market, reusable for any symbol later - not
limited to a fixed watchlist.

    # 1. Confirm the schema first (undocumented publicly)
    uv run python -m dark_pool.finra.collect --discover

    # 2. Pull full weekly market data for a date range (ATS-only rows kept)
    uv run python -m dark_pool.finra.collect --weeks-back 104
"""

import argparse
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

import pandas as pd
import requests

from dark_pool.finra.client import FinraClient
from shared.config import DATA_DIR

FINRA_DIR = DATA_DIR / "finra_ats"
SYMBOL_FIELD = "issueSymbolIdentifier"
DATE_FIELD = "weekStartDate"  # confirmed: dataset's partition key, the only valid query field (besides tier)
ATS_SYMBOL_ROWS = "ATS_W_SMBL"  # confirmed via /metadata: security-level ATS (dark pool) rows specifically
# CONFIRMED BUG WORKAROUND: querying by weekStartDate alone silently returns ONLY
# Tier 2 rows - Tier 1 (S&P 500/Russell 1000, i.e. every mega-cap) is missing unless
# tierIdentifier is passed explicitly. Not documented anywhere; found by noticing
# AAPL/MSFT/JPM never appeared in any pulled week. Must query each tier separately.
TIERS = ["T1", "T2", "OTCE"]
# A small number of specific weeks (confirmed: 2025-07-14, 07-21, 08-18, 09-01,
# 09-15, 09-22) have ZERO ATS_W_SMBL rows for the T2 tier specifically, verified
# across three separate pull attempts (full bulk pull, a retry, and a targeted
# 100,000-row fetch that returned no matching rows at all). T1 and OTCE are fine
# for those same weeks. This looks like a genuine gap in FINRA's own data for that
# slice, not a bug on our end - not worth chasing further.

# Publication lag confirmed from FINRA docs: Tier 1 (S&P 500/Russell 1000) = 2 weeks,
# everything else = 4 weeks. Skip weeks too recent to be published yet.
PUBLISH_LAG_WEEKS = 4


def discover():
    meta = FinraClient().fields()
    print(json.dumps(meta, indent=2))
    fields = meta.get("fields", [])
    print(f"\n{len(fields)} fields found. Confirm {SYMBOL_FIELD!r} and {DATE_FIELD!r} above still match - edit if not.")


def mondays_back(weeks_back: int, anchor: str) -> list[str]:
    """The `weeks_back` Mondays on/before `anchor`, oldest first (weekStartDate
    values are always Mondays, so align to one even if anchor itself isn't)."""
    end = date.fromisoformat(anchor)
    end -= timedelta(days=end.weekday())  # snap back to that week's Monday
    return [(end - timedelta(weeks=i)).isoformat() for i in range(weeks_back)][::-1]


RANGE_MSG = re.compile(r"minDate=(\d{4}-\d{2}-\d{2})\s+maxDate=(\d{4}-\d{2}-\d{2})")


def allowed_range(client: FinraClient) -> tuple[str, str]:
    """The historic dataset's actual valid window, read from FINRA's own error
    message (it isn't published anywhere else) - confirmed it runs roughly a year
    behind present; the most recent year lives in the separate `weeklySummary`
    dataset instead, not this one."""
    try:
        client.query([{"compareType": "EQUAL", "fieldName": DATE_FIELD, "fieldValue": "1900-01-01"}])
    except requests.exceptions.HTTPError as e:
        match = RANGE_MSG.search(e.response.text)
        if match:
            return match.group(1), match.group(2)
    raise SystemExit("Could not determine the dataset's valid date range from FINRA's API.")


def pull_week(client: FinraClient, week_start: str) -> pd.DataFrame:
    """One week, every symbol in every tier (T1/T2/OTCE - see TIERS note above),
    ATS-only rows (client-side filtered - the API won't filter by summaryTypeCode
    server-side)."""
    frames = []
    for tier in TIERS:
        rows = client.query_all([
            {"compareType": "EQUAL", "fieldName": DATE_FIELD, "fieldValue": week_start},
            {"compareType": "EQUAL", "fieldName": "tierIdentifier", "fieldValue": tier},
        ])
        if rows:
            frames.append(pd.DataFrame(rows))
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    return df[df["summaryTypeCode"] == ATS_SYMBOL_ROWS] if "summaryTypeCode" in df.columns else df


def pull(weeks_back: int | None = None, workers: int = 24, explicit_weeks: list[str] | None = None, force: bool = False):
    """Pulls weeks CONCURRENTLY (each week is an independent request covering the
    whole market) - FINRA's documented limit is 1200 sync requests/minute/IP, but in
    practice their backend seems to degrade under sustained heavy parallel load
    (observed ~0% failures early in a run, ~25%+ later) - the client now retries
    5xx errors with backoff, and a lower worker count helps for a retry pass.
    Each week is still paginated internally by query_all()."""
    FINRA_DIR.mkdir(parents=True, exist_ok=True)
    client = FinraClient()

    if explicit_weeks:
        weeks = explicit_weeks
    else:
        min_date, max_date = allowed_range(client)
        print(f"Dataset's valid range right now: {min_date} to {max_date} "
              f"(the most recent ~year isn't in this dataset - that needs FINRA's live weeklySummary instead)")
        weeks = [w for w in mondays_back(weeks_back, anchor=max_date) if w >= min_date]

    todo = weeks if force else [w for w in weeks if not (FINRA_DIR / f"{w}.csv").exists()]
    already = len(weeks) - len(todo)
    print(f"{len(weeks)} weeks requested, {already} already saved, pulling {len(todo)} with {workers} workers...")

    ok, empty, failed = already, [], []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(pull_week, client, w): w for w in todo}
        for i, future in enumerate(as_completed(futures), 1):
            week = futures[future]
            try:
                df = future.result()
            except Exception as e:
                print(f"  [{i}/{len(todo)}] {week}: FAILED ({e})")
                failed.append(week)
                continue
            if df.empty:
                empty.append(week)
                print(f"  [{i}/{len(todo)}] {week}: empty/not published")
                continue
            df.to_csv(FINRA_DIR / f"{week}.csv", index=False)
            ok += 1
            print(f"  [{i}/{len(todo)}] {week}: {len(df):,} ATS symbol-rows saved")

    print(f"\n{ok} weeks saved total, {len(empty)} empty/not published, {len(failed)} failed -> {FINRA_DIR}")
    if failed:
        print("Failed (retry these):", ", ".join(failed))


def refresh(workers: int = 4) -> int:
    """Incremental update: pull only weeks newer than what's already saved, up to
    the dataset's current max_date. Meant to run on a schedule (e.g. 3x/day) - cheap
    and a no-op most days, since FINRA only publishes once a week. Returns how many
    new weeks were added."""
    FINRA_DIR.mkdir(parents=True, exist_ok=True)
    client = FinraClient()
    min_date, max_date = allowed_range(client)
    saved = sorted(p.stem for p in FINRA_DIR.glob("*.csv"))
    newest_saved = saved[-1] if saved else min_date
    candidates = [w for w in mondays_back(60, anchor=max_date) if newest_saved < w <= max_date]

    if not candidates:
        print(f"Up to date - newest saved week is {newest_saved}, dataset max is {max_date}.")
        return 0
    print(f"{len(candidates)} new week(s) available since {newest_saved}: {', '.join(candidates)}")
    before = len(list(FINRA_DIR.glob("*.csv")))
    pull(workers=workers, explicit_weeks=candidates)
    after = len(list(FINRA_DIR.glob("*.csv")))
    return after - before


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--discover", action="store_true", help="Print the dataset's real field schema and stop")
    parser.add_argument("--weeks-back", type=int, help="How many published weeks to pull, newest-first range")
    parser.add_argument("--all", action="store_true", help="Pull the dataset's ENTIRE available range (~209 weeks)")
    parser.add_argument("--weeks", nargs="+", help="Retry specific weeks (yyyy-MM-dd Mondays), e.g. failed ones from a prior run")
    parser.add_argument("--refresh", action="store_true", help="Pull only new weeks since the last run (for scheduling, e.g. 3x/day)")
    parser.add_argument("--workers", type=int, default=24, help="Concurrent week-pulls (lower this for a retry pass - the backend seems to strain under sustained heavy load)")
    parser.add_argument("--force", action="store_true", help="Re-pull weeks even if already saved (e.g. to backfill the T1-tier fix)")
    args = parser.parse_args()

    if args.discover:
        discover()
        return
    if args.refresh:
        refresh(workers=args.workers)
        return
    if args.weeks:
        pull(workers=args.workers, explicit_weeks=args.weeks, force=args.force)
        return
    if args.all:
        min_date, max_date = allowed_range(FinraClient())
        weeks_back = (date.fromisoformat(max_date) - date.fromisoformat(min_date)).days // 7 + 1
        print(f"--all: pulling the full available range ({weeks_back} weeks, {min_date} to {max_date})")
    elif args.weeks_back:
        weeks_back = args.weeks_back
    else:
        parser.error("--weeks-back N, --all, --weeks, or --discover is required")
    pull(weeks_back, workers=args.workers, force=args.force)


if __name__ == "__main__":
    main()
