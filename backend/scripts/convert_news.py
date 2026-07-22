"""Convert a ForexFactory economic-calendar CSV export into the standard schema
`ts_utc,currency,impact,title` that `bot.data.news.import_news_csv`
(`python -m bot.cli import-news`) expects (plan 06: user downloads/exports the calendar
themselves -- KHÔNG scrape/gọi API -- this script just normalizes it).

ForexFactory export columns (as downloaded from the calendar page):
    Date, Time, Currency, Impact, Event, Actual, Forecast, Previous
`Date`+`Time` are in the export's own timezone (passed via --tz, default
"America/New_York" -- ForexFactory's own default); `Impact` is one of
Low/Medium/High/Holiday (Holiday rows are dropped -- not a tradable event).

Usage:
    python -m scripts.convert_news --path data/examples/news/forexfactory.csv \\
        --out data/news/calendar_2024.csv --tz America/New_York
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

_OUT_COLUMNS = ["ts_utc", "currency", "impact", "title"]
_IMPACT_MAP = {"low": "low", "medium": "medium", "high": "high"}


def convert_forexfactory(path: Path, out_path: Path, tz: str) -> None:
    raw = pd.read_csv(path)
    required = {"Date", "Time", "Currency", "Impact", "Event"}
    missing = required - set(raw.columns)
    if missing:
        raise SystemExit(f"{path}: missing columns {sorted(missing)}")

    raw = raw[raw["Impact"].astype(str).str.strip().str.lower() != "holiday"]
    raw = raw[raw["Time"].astype(str).str.strip() != ""]  # all-day rows have no time

    local_ts = pd.to_datetime(
        raw["Date"].astype(str).str.strip() + " " + raw["Time"].astype(str).str.strip(),
        errors="coerce",
    )
    valid = local_ts.notna()
    raw, local_ts = raw[valid], local_ts[valid]
    ts_utc = local_ts.dt.tz_localize(tz, ambiguous="NaT", nonexistent="NaT").dt.tz_convert("UTC")

    impact_raw = raw["Impact"].astype(str).str.strip().str.lower()
    unknown = sorted(set(impact_raw) - set(_IMPACT_MAP))
    if unknown:
        raise SystemExit(f"{path}: unknown Impact values {unknown} (expected Low/Medium/High)")

    df = pd.DataFrame(
        {
            "ts_utc": ts_utc.map(lambda t: t.isoformat() if pd.notna(t) else None),
            "currency": raw["Currency"].astype(str).str.strip().str.upper(),
            "impact": impact_raw.map(_IMPACT_MAP),
            "title": raw["Event"].astype(str).str.strip(),
        }
    )
    df = df.dropna(subset=["ts_utc"])
    df = df[_OUT_COLUMNS].drop_duplicates().sort_values("ts_utc")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    span = f"{df['ts_utc'].iloc[0]} -> {df['ts_utc'].iloc[-1]}" if len(df) else "(empty)"
    print(f"wrote {len(df)} events -> {out_path} ({span})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="convert_news")
    parser.add_argument("--path", type=str, required=True, help="ForexFactory export CSV")
    parser.add_argument("--out", type=str, required=True)
    parser.add_argument(
        "--tz", type=str, default="America/New_York", help="Timezone of Date/Time in the export"
    )
    args = parser.parse_args(argv)
    convert_forexfactory(Path(args.path), Path(args.out), args.tz)
    return 0


if __name__ == "__main__":
    sys.exit(main())
