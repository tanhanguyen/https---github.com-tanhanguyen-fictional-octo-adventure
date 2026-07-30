"""Per-SYMBOL_TYPE profile defaults (plan 05).

A *profile* is a config patch applied between the global config and a symbol's own
`overrides` (see `effective_config_for_symbol`): global < profile < per-symbol override.
It exists because the VN market rules are properties of the market, not preferences --
a user who set `timeframe: 15m` globally for forex must not accidentally run HPG on 15m
bars. Per-symbol `overrides` still win, so a deliberate VN experiment stays possible.

FOREX/CRYPTO have NO profile patch: their behavior (and every golden hash) is untouched.

Sources: D9 (sessions), D10 (2 concurrent trades, no daily-loss limit), D11 (ALLOW_SHORT),
user decisions 2026-07-18 (H4/D1 timeframes, time-stop off above H1) and 2026-07-22
(D1 only for VN, VND account, T+2.5 modelled).
"""

from __future__ import annotations

from typing import Any

# Trading day for stock VN is the Asia/Ho_Chi_Minh CALENDAR day -- NOT the 17:00 NY
# rollover of C3 (D10). Expressed as a midnight rollover in that tz, which
# `bot.core.timeframes.trading_day` handles explicitly.
VN_ROLLOVER_TZ = "Asia/Ho_Chi_Minh"
VN_ROLLOVER_TIME = "00:00"

#: HOSE T+2.5: shares bought on day T are sellable from the AFTERNOON session of the
#: second trading day after T. Counted in trading days actually present in the data
#: (so exchange holidays, which simply have no bar, are handled for free).
VN_CASH_SETTLEMENT_TRADING_DAYS = 2
VN_CASH_SETTLEMENT_RELEASE_TIME = "13:00"  # local Asia/Ho_Chi_Minh, start of afternoon


def _vn_common() -> dict[str, Any]:
    return {
        # User decision 2026-07-22: D1 only. H4 on a ~4.5h VN session would need a
        # 09:00 ICT resample origin; deliberately not built (see docs/decisions.md).
        "timeframe": "1D",
        "trading_day_rollover_tz": VN_ROLLOVER_TZ,
        "trading_day_rollover_time": VN_ROLLOVER_TIME,
        # spec_v2 §3 sizes the range window by timeframe: 30 bars on M15/H1, 12-15 on H4.
        # D1 is not in that table; taking the higher-timeframe row's upper bound (15 ≈ 3
        # trading weeks) is an inference, flagged in docs/decisions.md. Without it the VN
        # D1 profile would inherit the M15/H1 default of 30 bars ≈ 6 weeks of range.
        "strategies": {"breakout": {"range_period": 15}},
        "filters": {
            # D10: 2 concurrent trades; daily-loss limit OFF (a D1 strategy can never
            # take 3 losses in one day). `daily_loss_limit_enabled=false` is still
            # reported in the decision row for transparency.
            "account_risk": {
                "max_concurrent_trades": 2,
                "daily_loss_limit_enabled": False,
            },
            # User decision 2026-07-18: TF > H1 -> time stop off, trades may be held
            # over the weekend.
            "time_stop": {"enabled": False},
            # §6.6 DXY is a forex construct; meaningless for VN equities.
            "dxy": {"enabled": False},
        },
    }


def _cash_profile() -> dict[str, Any]:
    profile = _vn_common()
    # D11 / deviation #12: HOSE cash has no short side.
    profile["risk"] = {"allow_short": False}
    return profile


def _deriv_profile() -> dict[str, Any]:
    profile = _vn_common()
    profile["risk"] = {"allow_short": True}  # VN30F1M trades both directions
    return profile


def profile_patch(symbol_type: str) -> dict[str, Any]:
    """Config patch for `symbol_type` ({} for FOREX/CRYPTO -- no profile)."""
    if symbol_type == "STOCK_VN_CASH":
        return _cash_profile()
    if symbol_type == "STOCK_VN_DERIV":
        return _deriv_profile()
    return {}


def is_stock_vn(symbol_type: str) -> bool:
    return symbol_type.startswith("STOCK_VN")
