"""Pydantic v2 config models. Pure — no I/O (loader.py does YAML/merge; this is schema only).

D2: single parameter set (no per-asset-type table). D3: 16 independent filter toggles
(mapping in docs/decisions.md). D9: session windows per SYMBOL_TYPE. D11: 4 symbol types.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from bot.core.types import FilterKind


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


# ---------------------------------------------------------------------------
# Strategy toggles
# ---------------------------------------------------------------------------


class BreakoutConfig(StrictModel):
    enabled: bool = True
    range_period: int = 20
    tp1_r: float = 1.5
    tp2_r: float = 3.0
    partial_fraction: float = 0.5


class MeanReversionConfig(StrictModel):
    enabled: bool = True
    rsi_period: int = 14
    rsi_overbought: float = 70.0
    rsi_oversold: float = 30.0
    mr_sl_atr_period: int = 5
    mr_sl_atr_mult: float = 1.0


class StrategiesConfig(StrictModel):
    breakout: BreakoutConfig = Field(default_factory=BreakoutConfig)
    mean_reversion: MeanReversionConfig = Field(default_factory=MeanReversionConfig)


# ---------------------------------------------------------------------------
# Filter params (one model per filter id — kind is fixed metadata, see metadata.py)
# ---------------------------------------------------------------------------


class FilterToggle(StrictModel):
    """Base: every filter has enabled + kind is implied by the field name (metadata.py)."""

    enabled: bool = True


class TrendFilterConfig(FilterToggle):
    ema_fast: int = 34
    ema_slow: int = 89


class AdxFilterConfig(FilterToggle):
    period: int = 14
    # Trend threshold 25 (was 30): breakout-retest fires at the START of a trend, when
    # ADX (a lagging indicator) is still climbing — 30 was rarely reached inside the
    # 5-bar retest window, starving the strategy of trades.
    threshold_trend: float = 25.0
    threshold_range: float = 23.0


class ErFilterConfig(FilterToggle):
    period: int = 10
    # 0.35 (was 0.6): ER > 0.6 over 10 bars is a near-perfect straight line and almost
    # never coincides with ADX-trend + channel alignment; the AND-gate starved trades.
    threshold_trend: float = 0.35
    threshold_range: float = 0.30


class AtrRefConfig(FilterToggle):
    enabled: bool = True
    locked: bool = True
    period14: int = 14
    period5: int = 5


class AtrZscoreConfig(FilterToggle):
    window: int = 100
    z_off_low: float = -1.5
    z_breakout_only: float = 2.0
    z_mid_low: float = 1.0
    sl_scale_high: float = 1.5
    sl_scale_mid: float = 1.2  # was 1.5 == sl_scale_high, making the mid band pointless
    sl_scale_normal: float = 1.0


class VolumeFilterConfig(FilterToggle):
    enabled: bool = False  # off for FOREX per plan
    period: int = 20
    multiplier: float = 1.5


class SessionWindow(StrictModel):
    tz: str
    start: str
    end: str


class SessionFilterConfig(FilterToggle):
    # D9: windows keyed by symbol_type; engine picks the right set for `symbol_type`.
    forex_crypto: list[SessionWindow] = Field(
        default_factory=lambda: [
            SessionWindow(tz="Europe/London", start="08:00", end="17:00"),
            SessionWindow(tz="America/New_York", start="08:00", end="17:00"),
        ]
    )
    stock_vn: list[SessionWindow] = Field(
        default_factory=lambda: [
            SessionWindow(tz="Asia/Ho_Chi_Minh", start="09:00", end="11:30"),
            SessionWindow(tz="Asia/Ho_Chi_Minh", start="13:00", end="14:30"),
        ]
    )


class MtfFilterConfig(FilterToggle):
    block_on_neutral: bool = False


class DxyFilterConfig(FilterToggle):
    change_threshold_pct: float = 0.2
    lookback_hours: int = 1
    # Plan 02: links a real DXY CSV dataset by id (kind='csv', symbol='DXY').
    # None -> synthetic DXY bundled with the price dataset (unchanged behavior).
    dataset_id: str | None = None


class ConfirmationLagFilterConfig(FilterToggle):
    enabled: bool = True


class EquityCurveFilterConfig(FilterToggle):
    win_streak_trigger: int = 3
    loss_streak_trigger: int = 2
    win_reduce_to: float = 0.5
    loss_reduce_to: float = 0.3


class TimeStopFilterConfig(FilterToggle):
    # When `bars` is set it takes precedence: the effective wall-clock budget is
    # bars x timeframe duration. A fixed hours=8 was timeframe-hostile — on 4H it
    # closed every trade after 2 bars, on 1D after the first bar.
    bars: int | None = 16
    hours: float = 8.0  # fallback when bars is None
    after_tp1: bool = False  # C5: disabled after TP1


class RangeWidthFilterConfig(FilterToggle):
    atr_mult: float = 1.5


class AccountRiskFilterConfig(FilterToggle):
    max_concurrent_trades: int = 3
    daily_max_losses: int = 3
    daily_loss_limit_enabled: bool = True
    one_trade_per_symbol: bool = True  # Phase 1/2 default gap table


class WickFilterConfig(FilterToggle):
    min_ratio: float = 0.33  # was 0.5: a half-range wick is a rare pin-bar, starved trades


class NewsFilterConfig(FilterToggle):
    enabled: bool = False
    blacklist_utc: list[str] = Field(default_factory=list)  # ISO ranges "start/end"


class FiltersConfig(StrictModel):
    trend: TrendFilterConfig = Field(default_factory=TrendFilterConfig)
    adx_filter: AdxFilterConfig = Field(default_factory=AdxFilterConfig)
    er_filter: ErFilterConfig = Field(default_factory=ErFilterConfig)
    atr_ref: AtrRefConfig = Field(default_factory=AtrRefConfig)
    atr_zscore: AtrZscoreConfig = Field(default_factory=AtrZscoreConfig)
    volume: VolumeFilterConfig = Field(default_factory=VolumeFilterConfig)
    session: SessionFilterConfig = Field(default_factory=SessionFilterConfig)
    mtf: MtfFilterConfig = Field(default_factory=MtfFilterConfig)
    dxy: DxyFilterConfig = Field(default_factory=DxyFilterConfig)
    confirmation_lag: ConfirmationLagFilterConfig = Field(
        default_factory=ConfirmationLagFilterConfig
    )
    equity_curve: EquityCurveFilterConfig = Field(default_factory=EquityCurveFilterConfig)
    time_stop: TimeStopFilterConfig = Field(default_factory=TimeStopFilterConfig)
    range_width: RangeWidthFilterConfig = Field(default_factory=RangeWidthFilterConfig)
    account_risk: AccountRiskFilterConfig = Field(default_factory=AccountRiskFilterConfig)
    wick: WickFilterConfig = Field(default_factory=WickFilterConfig)
    news: NewsFilterConfig = Field(default_factory=NewsFilterConfig)

    def kind_of(self, filter_id: str) -> FilterKind:
        return _FILTER_KIND[filter_id]

    def all_ids(self) -> list[str]:
        return list(_FILTER_KIND.keys())


_FILTER_KIND: dict[str, FilterKind] = {
    "trend": FilterKind.REGIME,
    "adx_filter": FilterKind.REGIME,
    "er_filter": FilterKind.REGIME,
    "atr_ref": FilterKind.INPUT,
    "atr_zscore": FilterKind.MODIFIER,
    "volume": FilterKind.GATE,
    "session": FilterKind.GATE,
    "mtf": FilterKind.GATE,
    "dxy": FilterKind.GATE,
    "confirmation_lag": FilterKind.GATE,
    "equity_curve": FilterKind.MODIFIER,
    "time_stop": FilterKind.EXIT,
    "range_width": FilterKind.GATE,
    "account_risk": FilterKind.GATE,
    "wick": FilterKind.GATE,
    "news": FilterKind.GATE,
}


# ---------------------------------------------------------------------------
# Top level config
# ---------------------------------------------------------------------------


SymbolTypeLiteral = Literal["FOREX", "CRYPTO", "STOCK_VN_CASH", "STOCK_VN_DERIV"]
TimeframeLiteral = Literal["15m", "1H", "4H", "1D", "1W"]


class ExecutionCostsConfig(StrictModel):
    """§10: applied only in order_engine.py at fill/close. All zero by default so
    `test_replay_golden` is untouched (D6/D-costs, plans/02-real-data.md)."""

    spread_pips: float = 0.0
    commission_per_lot: float = 0.0
    slippage_pips: float = 0.0


class ExecutionConfig(StrictModel):
    costs: ExecutionCostsConfig = Field(default_factory=ExecutionCostsConfig)


class RiskConfig(StrictModel):
    max_risk_per_trade_pct: float = 1.0  # C7: base %, multiplied by risk_multiplier
    retest_tolerance_mode: Literal["atr", "percent"] = "atr"
    retest_tolerance_atr_mult: float = 0.25
    retest_tolerance_percent: float = 0.003
    retest_max_bars: int = 5  # C6
    intrabar_priority: Literal["sl_first", "path"] = "sl_first"
    cancel_if_open_beyond_sl: bool = True
    allow_short: bool = True  # D11: false for STOCK_VN_CASH


class BotConfig(StrictModel):
    symbol: str = "EURUSD"
    symbol_type: SymbolTypeLiteral = "FOREX"
    timeframe: TimeframeLiteral = "1H"
    starting_equity: float = 10_000.0
    trading_day_rollover_tz: str = "America/New_York"  # C3
    trading_day_rollover_time: str = "17:00"
    risk: RiskConfig = Field(default_factory=RiskConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    strategies: StrategiesConfig = Field(default_factory=StrategiesConfig)
    filters: FiltersConfig = Field(default_factory=FiltersConfig)


class ConfigVersion(StrictModel):
    """Immutable versioned snapshot stored in DB (plan: config_version table)."""

    version: int
    config: BotConfig
    is_active: bool = True
    created_at_utc: str | None = None
    note: str = ""
