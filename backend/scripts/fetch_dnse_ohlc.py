"""Download OHLC history from the DNSE OpenAPI into this repo's standard CSV schema
(`open_ts,open,high,low,close,volume`, UTC ISO-8601) so it can be imported as a backtest
dataset with `python -m bot.cli import-csv`.

Covers everything DNSE serves: cổ phiếu (`--type STOCK`), phái sinh (`--type
DERIVATIVE`, e.g. VN30F1M) and chỉ số (`--type INDEX`, e.g. VNINDEX / VN30).

This is the *dataset preparation* counterpart to `bot.data.dnse_feed`, which serves the
same endpoint to the live runner — both go through `DnseOhlcFeed`, so the prices written
here are on exactly the same grid and in exactly the same units as the live feed
produces (stock prices scaled from thousand-VND to VND, daily bars anchored at 09:00
ICT). That equality is the point: a backtest on this CSV and a live run see one series.

Credentials come from the environment:

    export DNSE_API_KEY=...
    export DNSE_API_SECRET=...

Usage:
    python -m scripts.fetch_dnse_ohlc --symbol HPG --type STOCK --resolution 1D \\
        --from 2019-01-01 --out data/csv/HPG_1D.csv
    python -m scripts.fetch_dnse_ohlc --symbol VN30F1M --type DERIVATIVE \\
        --resolution 1D --from 2018-01-01 --out data/csv/VN30F1M_1D.csv

Note on VN30F1M: the venue's `VN30F1M` is the rolling front-month alias, so the series
contains a price jump at every roll. For backtests prefer stitching the individual
contracts with `scripts/stitch_vn30f.py` (back-adjusted); use this script's VN30F1M
output when you want the raw, un-adjusted series.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from bot.data.dnse_feed import RESOLUTION_BY_TIMEFRAME, VALID_MARKET_TYPES, DnseOhlcFeed

_COLUMNS = ["open_ts", "open", "high", "low", "close", "volume"]

#: DNSE resolution -> the repo timeframe vocabulary `DnseOhlcFeed` speaks.
_TIMEFRAME_BY_RESOLUTION = {res: tf for tf, res in RESOLUTION_BY_TIMEFRAME.items()}


def _parse_day(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def fetch(
    symbol: str,
    market_type: str,
    resolution: str,
    start: datetime,
    end: datetime,
    out_path: Path,
) -> None:
    timeframe = _TIMEFRAME_BY_RESOLUTION[resolution]
    feed = DnseOhlcFeed(symbol, timeframe, market_type)
    # `backfill` pages backwards from `end`; ask for the whole span in bars, generously
    # over-counted, then trim to the requested window.
    span_bars = int((end - start) / feed.duration) + 2
    df = feed.backfill(end, bars=span_bars)
    if df.empty:
        raise SystemExit(f"no bars returned for {symbol} {market_type} {resolution}")
    df = df[df.index >= start]
    if df.empty:
        raise SystemExit(f"no bars in requested window for {symbol} (earliest available is later)")
    out = df.reset_index()
    out["open_ts"] = out["open_ts"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    out = out[_COLUMNS]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False)
    print(
        f"wrote {len(out)} bars -> {out_path} "
        f"({out['open_ts'].iloc[0]} -> {out['open_ts'].iloc[-1]})"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fetch_dnse_ohlc")
    parser.add_argument("--symbol", required=True, help="e.g. HPG, FPT, VN30F1M, VNINDEX")
    parser.add_argument("--type", dest="market_type", required=True, choices=VALID_MARKET_TYPES)
    parser.add_argument(
        "--resolution",
        default="1D",
        choices=sorted(_TIMEFRAME_BY_RESOLUTION),
        help="DNSE resolution (the VN profile trades 1D)",
    )
    parser.add_argument("--from", dest="start", required=True, help="YYYY-MM-DD (inclusive)")
    parser.add_argument("--to", dest="end", default=None, help="YYYY-MM-DD (default: now)")
    parser.add_argument("--out", required=True)

    args = parser.parse_args(argv)
    end = _parse_day(args.end) if args.end else datetime.now(timezone.utc)
    fetch(
        args.symbol,
        args.market_type,
        args.resolution,
        _parse_day(args.start),
        end,
        Path(args.out),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
