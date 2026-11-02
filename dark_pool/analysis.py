"""The financial-analysis layer on top of the raw FINRA pull - same two-part
approach used for the NOI tool's price-impact/reversal split:

  Part A' - Participation rate: a raw ATS share count means nothing without
  context. Divide it by the stock's own total weekly volume (lit + dark, from the
  S&P 500 reference data) to get what fraction of normal trading happened off-
  exchange - comparable across stocks and across time. Then z-score it against the
  stock's own trailing average, so "unusual this week, for this stock" is explicit
  rather than eyeballed.

  Part B' - Does an unusually heavy dark-pool week predict the FOLLOWING week's
  return? Same OLS-from-the-math approach as noi_tool's reversal_test.py:

      Next-Week Return[s, t+1] = alpha + beta * z-score(Participation %)[s, t] + e

  beta < 0 -> reversal, beta > 0 -> follow-through. Reports "not enough data yet"
  rather than fitting noise on a small sample - same honesty rule as the NOI tool.

    uv run python -m dark_pool.analysis --symbol JPM
    uv run python -m dark_pool.analysis --test
"""

import argparse

import numpy as np
import pandas as pd

from dark_pool.finra.collect import FINRA_DIR
from dark_pool.scanner import available_weeks

REF_DIR = FINRA_DIR.parent.parent / "reference_data" / "daily"
MIN_ROWS_FOR_TEST = 30  # rough floor - below this, beta is noise, not a finding
Z_WINDOW = 12  # weeks of trailing history to judge "unusual" against


def weekly_total_volume(symbol: str) -> pd.Series:
    """That symbol's total (lit + dark) volume, summed Mon-Fri per week, indexed by
    the week's Monday - the denominator for participation rate."""
    path = REF_DIR / f"{symbol.upper()}.csv"
    if not path.exists():
        raise SystemExit(f"No reference price/volume data for {symbol}.")
    df = pd.read_csv(path, parse_dates=["date"])
    df["week"] = (df["date"] - pd.to_timedelta(df["date"].dt.weekday, unit="D")).dt.strftime("%Y-%m-%d")
    return df.groupby("week")["volume"].sum()


def weekly_next_return(symbol: str) -> pd.Series:
    """That symbol's return from this week's close to NEXT week's close, indexed by
    THIS week's Monday - the Part B' outcome variable."""
    path = REF_DIR / f"{symbol.upper()}.csv"
    df = pd.read_csv(path, parse_dates=["date"]).sort_values("date")
    df["week"] = (df["date"] - pd.to_timedelta(df["date"].dt.weekday, unit="D")).dt.strftime("%Y-%m-%d")
    weekly_close = df.groupby("week")["close"].last().sort_index()
    return (weekly_close.shift(-1) / weekly_close - 1) * 100


def participation_series(symbol: str) -> pd.DataFrame:
    """One row per pulled FINRA week for this symbol: ATS shares, total volume,
    participation %, and a z-score of that % against the trailing Z_WINDOW weeks."""
    rows = []
    for week in available_weeks():
        df = pd.read_csv(FINRA_DIR / f"{week}.csv")
        match = df[df["issueSymbolIdentifier"] == symbol.upper()]
        if not match.empty:
            rows.append({"week": week, "ats_shares": match["totalWeeklyShareQuantity"].sum()})
    if not rows:
        raise SystemExit(f"No FINRA ATS data found for {symbol} in any pulled week.")
    ats = pd.DataFrame(rows).set_index("week").sort_index()

    volume = weekly_total_volume(symbol)
    df = ats.join(volume.rename("total_volume"), how="inner")
    df = df[df["total_volume"] > 0]
    df["participation_pct"] = df["ats_shares"] / df["total_volume"] * 100

    roll = df["participation_pct"].rolling(Z_WINDOW, min_periods=6)
    df["z_score"] = (df["participation_pct"] - roll.mean()) / roll.std()
    return df.reset_index()


def fit_beta(df: pd.DataFrame) -> dict:
    """OLS via the normal equations - same from-the-math approach as the NOI
    tool's reversal_test.py, not sklearn."""
    x, y = df["z_score"].to_numpy(float), df["next_week_return_pct"].to_numpy(float)
    X = np.column_stack([np.ones_like(x), x])
    alpha, beta = np.linalg.lstsq(X, y, rcond=None)[0]
    resid = y - X @ [alpha, beta]
    se_beta = np.sqrt(np.sum(resid**2) / (len(y) - 2) / np.sum((x - x.mean()) ** 2))
    return {"alpha": float(alpha), "beta": float(beta), "se_beta": float(se_beta),
            "t_stat": float(beta / se_beta) if se_beta > 0 else float("nan"), "n": len(y)}


def predict_this_week(symbol: str) -> dict | None:
    """Fits beta on history, then applies it to the MOST RECENT pulled week's
    z-score to project THIS week's return/price - the concrete, usable output,
    same role as the NOI tool's model_predicted_final_price. Returns None (and
    prints why) if there isn't enough history to fit a trustworthy beta yet."""
    part_a = participation_series(symbol).dropna(subset=["z_score"])
    next_ret = weekly_next_return(symbol).rename("next_week_return_pct")
    train = part_a.join(next_ret, on="week").dropna(subset=["next_week_return_pct"])

    if len(train) < MIN_ROWS_FOR_TEST:
        print(f"{symbol.upper()}: only {len(train)} historical weeks with a known outcome "
              f"(need {MIN_ROWS_FOR_TEST}+) - not enough data to predict yet.")
        return None

    fit = fit_beta(train)
    latest = part_a.iloc[-1]  # this week's actual z-score, outcome not known yet
    pred_return_pct = fit["alpha"] + fit["beta"] * latest["z_score"]

    path = REF_DIR / f"{symbol.upper()}.csv"
    last_close = pd.read_csv(path, parse_dates=["date"]).sort_values("date")["close"].iloc[-1]
    pred_price = last_close * (1 + pred_return_pct / 100)

    return {
        "symbol": symbol.upper(), "as_of_week": latest["week"],
        "participation_pct": round(latest["participation_pct"], 3), "z_score": round(latest["z_score"], 2),
        "beta": round(fit["beta"], 4), "t_stat": round(fit["t_stat"], 2), "n_weeks_fit": fit["n"],
        "predicted_return_pct": round(pred_return_pct, 3),
        "last_close": round(float(last_close), 2), "predicted_price": round(float(pred_price), 2),
        "reliable": abs(fit["t_stat"]) >= 2,
    }


def reversal_test(symbol: str) -> None:
    part_a = participation_series(symbol).dropna(subset=["z_score"])
    next_ret = weekly_next_return(symbol).rename("next_week_return_pct")
    df = part_a.join(next_ret, on="week").dropna(subset=["next_week_return_pct"])

    print(f"{symbol.upper()}: {len(df)} weeks with both a participation z-score and a real next-week return")
    if len(df) < MIN_ROWS_FOR_TEST:
        print(f"Below the {MIN_ROWS_FOR_TEST}-row floor - not enough data yet for beta to mean anything.")
        return
    result = fit_beta(df)
    direction = "reversal" if result["beta"] < 0 else "follow-through"
    print(f"beta = {result['beta']:+.4f} ({direction}), t-stat {result['t_stat']:+.2f}, n={result['n']}")
    print("A |t-stat| below ~2 means this isn't distinguishable from no effect yet.")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--symbol", help="Show the participation-rate series for one symbol")
    parser.add_argument("--test", action="store_true", help="Run the Part B' reversal/follow-through test for --symbol")
    parser.add_argument("--predict", action="store_true", help="Predict this week's return/price from the latest z-score")
    args = parser.parse_args()
    if not args.symbol:
        parser.error("--symbol is required")
    if args.predict:
        result = predict_this_week(args.symbol)
        if result:
            flag = "" if result["reliable"] else "  (NOT statistically reliable yet - |t| < 2)"
            print(f"{result['symbol']} as of week {result['as_of_week']}:")
            print(f"  Participation {result['participation_pct']}% of volume (z={result['z_score']})")
            print(f"  Fitted on {result['n_weeks_fit']} weeks, beta={result['beta']}, t-stat={result['t_stat']}{flag}")
            print(f"  Predicted this week's return: {result['predicted_return_pct']:+.2f}%")
            print(f"  Last close ${result['last_close']} -> predicted ${result['predicted_price']}")
    elif args.test:
        reversal_test(args.symbol)
    else:
        df = participation_series(args.symbol)
        print(df.tail(12).to_string(index=False))


if __name__ == "__main__":
    main()
