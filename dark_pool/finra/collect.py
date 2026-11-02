"""Pull FINRA's free weekly ATS/off-exchange volume history for a watchlist.

Step 1 - run this FIRST, once, to see the dataset's real field names (undocumented
publicly, so don't guess):
    uv run python -m dark_pool.finra.collect --discover

Step 2 - once you've confirmed the symbol/date field names from step 1 (edit the
constants below if they differ), pull history for a watchlist:
    uv run python -m dark_pool.finra.collect --symbols JPM BAC GS XOM KO --years 4
"""

import argparse
import json

import pandas as pd

from dark_pool.finra.client import FinraClient
from shared.config import DATA_DIR

FINRA_DIR = DATA_DIR / "finra_ats"

# Best-guess field names from FINRA's public docs for this dataset family - CONFIRM
# with --discover before trusting these for a real pull.
SYMBOL_FIELD = "issueSymbolIdentifier"
DATE_FIELD = "weekStartDate"


def discover():
    fields = FinraClient().fields()
    print(json.dumps(fields, indent=2))
    print(f"\n{len(fields)} fields found. Confirm the symbol and week-date field names above")
    print(f"match SYMBOL_FIELD={SYMBOL_FIELD!r} and DATE_FIELD={DATE_FIELD!r} in this file - edit if not.")


def pull(symbols: list[str]):
    FINRA_DIR.mkdir(parents=True, exist_ok=True)
    client = FinraClient()
    ok, failed = 0, []
    for sym in symbols:
        try:
            rows = client.query_all([{"compareType": "EQUAL", "fieldName": SYMBOL_FIELD, "fieldValue": sym}])
            if not rows:
                failed.append(sym)
                continue
            pd.DataFrame(rows).to_csv(FINRA_DIR / f"{sym}.csv", index=False)
            ok += 1
            print(f"{sym}: {len(rows)} weekly rows")
        except Exception as e:
            print(f"{sym}: failed ({e})")
            failed.append(sym)
    print(f"\n{ok} succeeded, {len(failed)} failed -> {FINRA_DIR}")
    if failed:
        print("Failed:", ", ".join(failed))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--discover", action="store_true", help="Print the dataset's real field schema and stop")
    parser.add_argument("--symbols", nargs="+", help="Symbols to pull (e.g. JPM BAC GS)")
    args = parser.parse_args()

    if args.discover:
        discover()
        return
    if not args.symbols:
        parser.error("--symbols is required unless using --discover")
    pull([s.upper() for s in args.symbols])


if __name__ == "__main__":
    main()
