"""Convert common third-party OHLCV export formats into the standard schema
`open_ts,open,high,low,close,volume` (UTC ISO-8601) that `bot.data.csv_feed.load_csv`
expects (plan 02: user downloads files themselves, this script just normalizes them).

Supported source formats:
  binance   - Binance klines CSV export (data.binance.vision), columns:
              open_time,open,high,low,close,volume,close_time,quote_volume,count,
              taker_buy_volume,taker_buy_quote_volume,ignore -- open_time in epoch ms.
              Accepts multiple monthly files (glob) for one symbol/interval; merges,
              dedups, and sorts them into one output file.
  mt        - MetaTrader/Dukascopy-style tab-separated CSV, no header:
              "YYYY-MM-DD HH:MM\topen\thigh\tlow\tclose\tvolume". Timestamps are
              assumed to already be UTC (no timezone info in the source) -- if your
              broker export uses a different server timezone, convert before import.
  vnstock   - TradingView/vnstock-style bar JSON: {"t": [...], "o": [...], "h": [...],
              "l": [...], "c": [...], "v": [...]}, t in epoch seconds. Accepts multiple
              date-range files (glob) for one symbol/resolution; merges, dedups, sorts.

Usage:
    python -m scripts.convert_csv binance \\
        --glob "data/examples/crypto/BTCUSDT-1h-*.csv" --out data/csv/BTCUSDT_1h.csv
    python -m scripts.convert_csv mt \\
        --path "data/examples/forex/EURUSD15.csv" --out data/csv/EURUSD_real_15m.csv
    python -m scripts.convert_csv vnstock \\
        --glob "data/examples/phai sinh vnstock/*VN30F1M*.json" --out data/csv/VN30F1M_1D.csv
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

import pandas as pd

_COLUMNS = ["open_ts", "open", "high", "low", "close", "volume"]


def _write_standard(df: pd.DataFrame, out_path: Path) -> None:
    df = df[_COLUMNS].drop_duplicates(subset="open_ts").sort_values("open_ts")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    span = f"{df['open_ts'].iloc[0]} -> {df['open_ts'].iloc[-1]}"
    print(f"wrote {len(df)} bars -> {out_path} ({span})")


def convert_binance(patterns: list[str], out_path: Path) -> None:
    paths = sorted(p for pattern in patterns for p in glob.glob(pattern))
    if not paths:
        raise SystemExit(f"no files matched: {patterns}")
    frames = []
    for p in paths:
        raw = pd.read_csv(p)
        frames.append(
            pd.DataFrame(
                {
                    "open_ts": pd.to_datetime(raw["open_time"], unit="ms", utc=True),
                    "open": raw["open"],
                    "high": raw["high"],
                    "low": raw["low"],
                    "close": raw["close"],
                    "volume": raw["volume"],
                }
            )
        )
    _write_standard(pd.concat(frames, ignore_index=True), out_path)


def convert_mt(path: Path, out_path: Path) -> None:
    raw = pd.read_csv(
        path, sep="\t", header=None, names=["dt", "open", "high", "low", "close", "volume"]
    )
    df = pd.DataFrame(
        {
            "open_ts": pd.to_datetime(raw["dt"], utc=True),
            "open": raw["open"],
            "high": raw["high"],
            "low": raw["low"],
            "close": raw["close"],
            "volume": raw["volume"],
        }
    )
    _write_standard(df, out_path)


def convert_vnstock(patterns: list[str], out_path: Path) -> None:
    paths = sorted(p for pattern in patterns for p in glob.glob(pattern))
    if not paths:
        raise SystemExit(f"no files matched: {patterns}")
    frames = []
    for p in paths:
        data = json.loads(Path(p).read_text(encoding="utf-8"))
        if not data.get("t"):
            continue
        frames.append(
            pd.DataFrame(
                {
                    "open_ts": pd.to_datetime(data["t"], unit="s", utc=True),
                    "open": data["o"],
                    "high": data["h"],
                    "low": data["l"],
                    "close": data["c"],
                    "volume": data["v"],
                }
            )
        )
    if not frames:
        raise SystemExit(f"no bars found in: {patterns}")
    _write_standard(pd.concat(frames, ignore_index=True), out_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="convert_csv")
    sub = parser.add_subparsers(dest="format", required=True)

    binance = sub.add_parser("binance", help="Binance klines CSV export(s)")
    binance.add_argument("--glob", action="append", required=True, dest="patterns")
    binance.add_argument("--out", type=str, required=True)

    mt = sub.add_parser("mt", help="MetaTrader/Dukascopy-style tab-separated CSV")
    mt.add_argument("--path", type=str, required=True)
    mt.add_argument("--out", type=str, required=True)

    vnstock = sub.add_parser("vnstock", help="TradingView/vnstock-style bar JSON export(s)")
    vnstock.add_argument("--glob", action="append", required=True, dest="patterns")
    vnstock.add_argument("--out", type=str, required=True)

    args = parser.parse_args(argv)
    if args.format == "binance":
        convert_binance(args.patterns, Path(args.out))
    elif args.format == "mt":
        convert_mt(Path(args.path), Path(args.out))
    elif args.format == "vnstock":
        convert_vnstock(args.patterns, Path(args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
