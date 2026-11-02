"""The Dark Pool Scanner.

Two implementations live in this file:

  1. THE REAL ONE (commented out below) - follows Massive's own tutorial exactly:
     https://massive.com/blog/dark-pool-scanner-with-massive
     Live trades, filtered to off-exchange prints (exchange==4, trf_id present),
     above a notional threshold. Needs a paid Massive plan (Stocks Developer $79/mo
     for 15-min delayed, or Advanced $199/mo for real-time) - uncomment and set
     MASSIVE_API_KEY in .env once that's active.

  2. THE FREE ONE (active now) - reads FINRA's free weekly ATS data we've already
     pulled (dark_pool/finra/collect.py) instead of live trades. Weekly, 2-4 week
     delayed, not per-trade - but free and working today. See collect.py's and this
     project's README for what this trades off against the real scanner.

    uv run python -m dark_pool.scanner --week 2025-10-13
    uv run python -m dark_pool.scanner --latest
"""

# ============================================================================
# THE REAL SCANNER (Massive's tutorial, live trades) - commented out until the
# Stocks Developer/Advanced subscription is active. This is adapted directly from
# https://massive.com/blog/dark-pool-scanner-with-massive, not rewritten.
# ============================================================================
#
# import argparse
# from datetime import datetime
# from zoneinfo import ZoneInfo
#
# from massive import WebSocketClient
# from massive.websocket.models import EquityTrade, Feed, Market
#
# from shared.config import api_key
#
# EASTERN = ZoneInfo("America/New_York")
# TRF_NAMES = {201: "FINRA/NYSE TRF", 202: "FINRA/NASDAQ TRF Carteret", 203: "FINRA/NASDAQ TRF Chicago"}
#
#
# def fmt_time(ts_ms: int) -> str:
#     return datetime.fromtimestamp(ts_ms / 1000, tz=EASTERN).strftime("%H:%M:%S")
#
#
# def show_trade(trade: EquityTrade):
#     notional = trade.price * trade.size
#     print(
#         f"{fmt_time(trade.sip_timestamp)}  {trade.symbol:6}  "
#         f"${trade.price:.2f} x {trade.size:,} = ${notional:,.0f}  "
#         f"{TRF_NAMES.get(trade.trf_id, 'TRF ' + str(trade.trf_id))}"
#     )
#
#
# def main():
#     parser = argparse.ArgumentParser()
#     parser.add_argument("--min-notional", type=float, default=100_000)
#     parser.add_argument("--ticker", nargs="+")
#     args = parser.parse_args()
#
#     subs = [f"T.{t.upper()}" for t in args.ticker] if args.ticker else ["T.*"]
#     client = WebSocketClient(api_key=api_key(), feed=Feed.RealTime, market=Market.Stocks, subscriptions=subs)
#
#     def handler(msgs):
#         for m in msgs:
#             if not isinstance(m, EquityTrade) or m.exchange != 4 or not m.trf_id:
#                 continue  # exchange==4 + trf_id present = off-exchange/dark pool print
#             if m.price * m.size < args.min_notional:
#                 continue
#             show_trade(m)
#
#     print(f"Dark pool scanner (live, Massive) - {', '.join(subs)}")
#     client.run(handle_msg=handler)
#
#
# if __name__ == "__main__":
#     main()

# ============================================================================
# THE FREE SCANNER (active) - FINRA's weekly ATS data instead of live trades.
# ============================================================================

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
