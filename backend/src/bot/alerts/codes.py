"""The alert catalogue (plan 13): every code the system may ever emit, and its level.

Keeping the catalogue in one module (rather than string literals at the call sites) buys
two things: `test_alert_codes_are_catalogued` can prove no runner invents a code the UI
has never heard of, and the Config UI can list the events a user is muting without
scraping the codebase.

Codes owned by plans that do not exist yet (broker execution, chart snapshots) are listed
here anyway, unemitted: the level/severity contract is a user decision from 2026-07-18,
and writing it down once is cheaper than rediscovering it per plan.
"""

from __future__ import annotations

from typing import Final, Literal

Level = Literal["INFO", "WARN", "ERROR", "CRITICAL"]

#: Severity order — used by the Telegram threshold and the UI's toast styling.
LEVEL_ORDER: Final[dict[str, int]] = {"INFO": 0, "WARN": 1, "ERROR": 2, "CRITICAL": 3}


def level_at_least(level: str, threshold: str) -> bool:
    """True when `level` is as severe as `threshold`. Unknown levels sort as INFO."""
    return LEVEL_ORDER.get(level, 0) >= LEVEL_ORDER.get(threshold, 0)


# --- the catalogue ---------------------------------------------------------------
# code -> (default level, Vietnamese one-liner for the UI legend)

ALERT_CATALOGUE: Final[dict[str, tuple[Level, str]]] = {
    # --- trade lifecycle (plan 07 live runner) ---
    "trade_opened": ("INFO", "Lệnh khớp (fill)"),
    "trade_pending": ("INFO", "Đặt lệnh chờ retest — mặc định không gửi Telegram"),
    "trade_cancelled": ("INFO", "Huỷ lệnh chờ"),
    "tp1_hit": ("INFO", "Chốt một phần tại TP1 + dời SL về BE"),
    "trade_closed": ("INFO", "Đóng lệnh (SL/TP/BE/time_stop/…)"),
    # --- account risk ---
    "daily_loss_limit": ("WARN", "Chạm giới hạn lệnh thua trong ngày"),
    "equity_multiplier": ("WARN", "Equity-curve filter đổi hệ số risk"),
    "drawdown_warn": ("WARN", "Drawdown từ đỉnh equity chạm ngưỡng cảnh báo"),
    "drawdown_critical": ("CRITICAL", "Drawdown chạm ngưỡng nguy hiểm"),
    # --- feed / process health (plan 07) ---
    "feed_degraded": ("WARN", "Mất dữ liệu live"),
    "feed_recovered": ("INFO", "Khôi phục dữ liệu live"),
    "runner_started": ("INFO", "Process live bắt đầu chạy"),
    "runner_stopped": ("WARN", "Process live dừng"),
    "runner_crashed": ("CRITICAL", "Process live crash"),
    "daily_summary": ("INFO", "Tổng kết cuối ngày"),
    # --- broker execution (plan 08) — catalogued now, emitted when plan 08 lands ---
    "order_error": ("ERROR", "Lỗi đặt/sửa lệnh broker"),
    "naked_position_closed": ("CRITICAL", "Đặt SL thất bại → đóng vị thế khẩn cấp"),
    "circuit_breaker": ("CRITICAL", "Lỗi API liên tiếp → tự về paper"),
    "desynced": ("CRITICAL", "Reconciliation lệch lúc boot"),
    # --- chart snapshot (plan 14) ---
    "snapshot_error": ("WARN", "Render ảnh chart lỗi"),
}

ALL_CODES: Final[frozenset[str]] = frozenset(ALERT_CATALOGUE)


def default_level(code: str) -> Level:
    """The catalogued level for `code`. Unknown codes are WARN, never silently INFO:
    an uncatalogued alert is itself a small bug, and hiding it under the quietest level
    is the wrong default."""
    entry = ALERT_CATALOGUE.get(code)
    return entry[0] if entry is not None else "WARN"
