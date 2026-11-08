"""The free dark pool scanner - reads FINRA's free weekly ATS data we've already
pulled (dark_pool/finra/collect.py) instead of live trades. Weekly, 2-4 week
delayed, not per-trade - but free and needs no subscription.

For live, per-trade dark pool prints (needs the paid Massive subscription), see
dark_pool/live.py instead.

    uv run python -m dark_pool.scanner --week 2025-10-13
    uv run python -m dark_pool.scanner --latest
"""

import argparse

import pandas as pd

from dark_pool.finra.collect import FINRA_DIR


def available_weeks() -> list[str]:
    return sorted(p.stem for p in FINRA_DIR.glob("*.csv"))


def load_week(week: str) -> pd.DataFrame:
    path = FINRA_DIR / f"{week}.csv"
    if not path.exists():
        raise SystemExit(f"No data for week {week}. Available: {available_weeks()[:5]} ... "
                          f"({len(available_weeks())} total). Run dark_pool.finra.collect first.")
    return pd.read_csv(path)


def top_symbols(week: str, top_n: int = 20) -> pd.DataFrame:
    """Which symbols had the heaviest off-exchange (ATS/dark pool) volume that week,
    summed across every reporting ATS. This is the free scanner's headline read -
    the closest free equivalent to 'who's trading heavy in the dark this week.'"""
    df = load_week(week)
    totals = (
        df.groupby("issueSymbolIdentifier")
        .agg(ats_shares=("totalWeeklyShareQuantity", "sum"), ats_trades=("totalWeeklyTradeCount", "sum"))
        .sort_values("ats_shares", ascending=False)
        .head(top_n)
    )
    return totals.reset_index().rename(columns={"issueSymbolIdentifier": "symbol"})


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--week", help="A specific week (yyyy-MM-dd Monday)")
    parser.add_argument("--latest", action="store_true", help="Use the most recent pulled week")
    parser.add_argument("--top", type=int, default=20)
    args = parser.parse_args()

    weeks = available_weeks()
    if not weeks:
        raise SystemExit("No FINRA data pulled yet. Run: uv run python -m dark_pool.finra.collect --all")
    week = args.week or (weeks[-1] if args.latest else weeks[-1])

    print(f"Top {args.top} symbols by off-exchange (ATS) volume - week of {week}\n")
    result = top_symbols(week, args.top)
    for i, row in result.iterrows():
        print(f"  {i + 1:>2}. {row['symbol']:6}  {row['ats_shares']:>14,.0f} shares  {row['ats_trades']:>8,.0f} trades")


if __name__ == "__main__":
    main()
