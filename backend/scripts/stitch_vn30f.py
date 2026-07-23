"""Stitch per-contract VN30F files into ONE back-adjusted continuous series
(plan 05, user decision 2026-07-22: roll handling lives outside the engine).

Why outside the engine: a futures roll is a data-preparation step, not a trading rule.
Keeping it here means the engine still sees exactly what it sees for every other
symbol -- one dataset, one continuous price series -- and the backtest stays
deterministic and free of contract-switching special cases.

Back-adjustment (the "difference" / panama method): walking BACKWARD from the newest
contract, every older contract's OHLC is shifted by the price gap observed at its roll
date, so the seam is continuous and the most recent prices are the real, untouched ones.
Absolute levels of old bars are therefore NOT tradeable prices -- but every price
DIFFERENCE (which is all the strategy uses: ranges, ATR, SL distance, R multiples) is
faithful. Ratio adjustment is deliberately not offered: it distorts point distances,
and VN30F P&L is linear in points (100,000 VND per point).

Input: one standard OHLCV CSV per contract (`open_ts,open,high,low,close,volume`, the
schema `scripts/convert_csv.py` emits), plus a roll schedule mapping each contract to
the LAST timestamp at which it is the front month.

Roll schedule CSV: `contract,last_ts` -- e.g.

    contract,last_ts
    VN30F2401,2024-01-18T02:00:00Z
    VN30F2402,2024-02-15T02:00:00Z

`contract` must match the input file's stem. Typically the expiry bar itself
(`bot.core.timeframes.vn30f_expiry` gives the 3rd Thursday) or the session before it,
if you prefer rolling a day early.

Usage:
    python -m scripts.stitch_vn30f \\
        --glob "data/examples/vn30f/VN30F24*.csv" \\
        --rolls data/examples/vn30f/rolls.csv \\
        --out data/csv/VN30F1M_continuous_1D.csv
"""

from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

import pandas as pd

_OHLC = ["open", "high", "low", "close"]
_COLUMNS = ["open_ts", *_OHLC, "volume"]


def _read_contract(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["open_ts"])
    missing = [c for c in _COLUMNS if c not in df.columns]
    if missing:
        raise SystemExit(f"{path}: missing column(s) {missing}")
    df["open_ts"] = pd.to_datetime(df["open_ts"], utc=True)
    return df[_COLUMNS].drop_duplicates(subset="open_ts").sort_values("open_ts")


def read_rolls(path: Path) -> list[tuple[str, pd.Timestamp]]:
    raw = pd.read_csv(path)
    for col in ("contract", "last_ts"):
        if col not in raw.columns:
            raise SystemExit(f"{path}: roll schedule needs columns contract,last_ts")
    rolls = [
        (str(r.contract), pd.to_datetime(r.last_ts, utc=True)) for r in raw.itertuples()
    ]
    rolls.sort(key=lambda pair: pair[1])
    return rolls


def stitch(
    contracts: dict[str, pd.DataFrame], rolls: list[tuple[str, pd.Timestamp]]
) -> pd.DataFrame:
    """Slice each contract to its front-month window, then back-adjust older segments.

    Segment k covers (rolls[k-1].last_ts, rolls[k].last_ts]; the newest contract keeps
    every bar after the last listed roll, so a schedule can end at the still-active
    front month.
    """
    missing = [name for name, _ in rolls if name not in contracts]
    if missing:
        raise SystemExit(f"roll schedule names contracts with no input file: {missing}")

    segments: list[pd.DataFrame] = []
    prev_end: pd.Timestamp | None = None
    for name, last_ts in rolls:
        df = contracts[name]
        window = df["open_ts"] <= last_ts
        if prev_end is not None:
            window &= df["open_ts"] > prev_end
        seg = df.loc[window].copy()
        if seg.empty:
            raise SystemExit(
                f"contract {name} contributes no bars for window "
                f"({prev_end}, {last_ts}] -- check the roll schedule against the data"
            )
        seg["contract"] = name
        segments.append(seg)
        prev_end = last_ts

    # Tail: the front month after the final scheduled roll (may legitimately be empty
    # when the schedule ends exactly at the last bar of the data).
    newest = rolls[-1][0]
    tail = contracts[newest].loc[contracts[newest]["open_ts"] > rolls[-1][1]].copy()
    if not tail.empty:
        tail["contract"] = newest
        segments.append(tail)

    # Back-adjust from the newest segment backwards: at each seam the offset is the
    # close of the NEW contract's first bar minus the close of the OLD contract's last
    # bar, measured on the same session where both are quoted.
    cumulative = 0.0
    for i in range(len(segments) - 2, -1, -1):
        older, newer = segments[i], segments[i + 1]
        old_name = str(older["contract"].iloc[0])
        old_last_ts = older["open_ts"].iloc[-1]
        overlap = contracts[str(newer["contract"].iloc[0])]
        same_session = overlap.loc[overlap["open_ts"] == old_last_ts, "close"]
        if same_session.empty:
            raise SystemExit(
                f"no overlapping bar at {old_last_ts} between {old_name} and "
                f"{newer['contract'].iloc[0]} -- both contracts must quote the roll "
                "session for a difference adjustment to be computable"
            )
        gap = float(same_session.iloc[0]) - float(older["close"].iloc[-1])
        cumulative += gap
        segments[i] = older.assign(**{c: older[c] + cumulative for c in _OHLC})

    out = pd.concat(segments, ignore_index=True).sort_values("open_ts")
    if out["open_ts"].duplicated().any():
        dup = out.loc[out["open_ts"].duplicated(), "open_ts"].iloc[0]
        raise SystemExit(f"stitched series has a duplicate timestamp at {dup}")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stitch_vn30f")
    parser.add_argument("--glob", action="append", required=True, dest="patterns")
    parser.add_argument("--rolls", type=str, required=True)
    parser.add_argument("--out", type=str, required=True)
    args = parser.parse_args(argv)

    paths = sorted(p for pattern in args.patterns for p in glob.glob(pattern))
    if not paths:
        raise SystemExit(f"no files matched: {args.patterns}")
    contracts = {Path(p).stem: _read_contract(Path(p)) for p in paths}

    out = stitch(contracts, read_rolls(Path(args.rolls)))
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out[_COLUMNS].to_csv(out_path, index=False)
    print(
        f"wrote {len(out)} back-adjusted bars -> {out_path} "
        f"({out['open_ts'].iloc[0]} -> {out['open_ts'].iloc[-1]})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
