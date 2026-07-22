export interface AccountOut {
  run_id: number | null
  equity: number
  balance: number
  drawdown_pct: number
  open_trades: number
  open_trades_by_symbol: Record<string, number>
  current_risk_pct: number
  daily_loss_count: number
  daily_losses_remaining: number
  current_trading_day: string | null
  consecutive_wins: number
  consecutive_losses: number
  risk_multiplier: number
  bot_enabled: boolean
  blocked_reason: string | null
  open_risk_pct_total: number
  max_total_open_risk_pct: number | null
}

export interface ConfigOut {
  id: number
  version: number
  is_active: boolean
  created_at_utc: string
  note: string
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  config: Record<string, any>
}

export interface ConfigVersionOut {
  id: number
  version: number
  is_active: boolean
  created_at_utc: string
  note: string
}

export interface FieldMetaOut {
  field: string
  label_vi: string
  group: string
  ordinal: number
  kind: string | null
  locked: boolean
  spec_ref: string
  min: number | null
  max: number | null
  step: number | null
}

export interface ConfigSchemaOut {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  json_schema: Record<string, any>
  metadata: FieldMetaOut[]
}

export interface FilterLastEvaluation {
  enabled: boolean
  evaluated: boolean
  passed: boolean | null
  blocking: boolean
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  values: Record<string, any>
  detail: string | null
}

export interface FilterRowOut {
  id: string
  label_vi: string
  kind: string
  enabled: boolean
  locked: boolean
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  params: Record<string, any>
  last_evaluation: FilterLastEvaluation | null
}

export interface TradeOut {
  id: number
  run_id: number
  symbol: string
  strategy: string
  direction: string
  status: string
  entry_price: number | null
  sl_price: number | null
  tp1_price: number | null
  tp2_price: number | null
  lot_size: number | null
  opened_at_utc: string | null
  closed_at_utc: string | null
  trading_day: string | null
  result: string | null
  pnl_amount: number | null
  pnl_r: number | null
  decision_id: number | null
}

export interface TradeEventOut {
  id: number
  event_type: string
  ts_utc: string
  price: number | null
  detail: string | null
}

export interface TradeDetailOut extends TradeOut {
  trade_events: TradeEventOut[]
}

export interface DecisionOut {
  id: number
  run_id: number
  bar_ts_utc: string
  reason: string
  stage: string
  detail: string | null
  strategy: string | null
  direction: string | null
  trade_id: number | null
  symbol: string | null
}

export interface DecisionFilterOut {
  id: number
  filter_id: string
  kind: string
  enabled: boolean
  evaluated: boolean
  passed: boolean | null
  blocking: boolean
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  values: Record<string, any>
  detail: string | null
}

export interface DecisionDetailOut extends DecisionOut {
  filters: DecisionFilterOut[]
}

export interface DecisionStatsOut {
  histogram: Record<string, number>
}

export interface EquityPointOut {
  bar_ts_utc: string
  equity: number
  balance: number
}

export interface SymbolOut {
  symbol: string
  symbol_type: string
}

export interface NewsEventOut {
  id: number
  ts_utc: string
  currency: string
  impact: string
  title: string
}

export interface NewsImportOut {
  file_sha256: string
  row_count: number
  inserted_count: number
  duplicate_count: number
}

export interface DatasetOut {
  id: string
  kind: string
  created_at_utc: string
  seed: number | null
  n_candles_15m: number | null
  symbol: string | null
  native_tf: string | null
  source_path: string | null
  file_sha256: string | null
  start_ts: string | null
  end_ts: string | null
  bar_count: number | null
  gap_count: number | null
}

export interface RunOut {
  id: number
  dataset_id: string
  config_version_id: number
  symbol: string
  symbols: string[]
  status: string
  starting_equity: number
  created_at_utc: string
  is_playing: boolean
}

export interface RunSummaryOut {
  id: number
  dataset_id: string
  config_version_id: number
  config_version: number
  symbol: string
  status: string
  starting_equity: number
  created_at_utc: string
  bars_processed: number
  final_equity: number | null
  closed_trades: number
  is_active: boolean
}

export interface HistogramBinOut {
  label: string
  lo: number | null
  hi: number | null
  count: number
}

export interface TradeStatsOut {
  n_total: number
  n_by_strategy: Record<string, number>
  n_by_direction: Record<string, number>
  n_win: number
  n_loss: number
  n_breakeven: number
  win_rate: number | null
  profit_factor: number | null
  expectancy_r: number | null
  avg_win: number | null
  max_win: number | null
  avg_loss: number | null
  max_loss: number | null
  avg_holding_hours: number | null
  r_histogram: HistogramBinOut[]
}

export interface SeriesStatsOut {
  final_equity: number
  total_return_pct: number
  max_drawdown_abs: number
  max_drawdown_pct: number
  longest_drawdown_bars: number
  sharpe: number | null
  n_bars: number
}

export interface RunReportOut {
  run_id: number
  overall: TradeStatsOut
  per_strategy: Record<string, TradeStatsOut>
  series: SeriesStatsOut
  reason_histogram: Record<string, number>
  filter_block_counts: Record<string, number>
}

export interface MetricDiffOut {
  a: number | null
  b: number | null
  delta: number | null
}

export interface HistCountDiffOut {
  a: number
  b: number
  delta: number
}

export interface RunCompareOut {
  run_a: number
  run_b: number
  dataset_a: string
  dataset_b: string
  config_version_a: number
  config_version_b: number
  same_dataset: boolean
  same_config_version: boolean
  metrics: Record<string, MetricDiffOut>
  reason_histogram: Record<string, HistCountDiffOut>
}

export interface BarOut {
  ts_utc: string
  open: number
  high: number
  low: number
  close: number
}

export interface RunStepOut {
  bar_ts: string
  symbol: string
  reason: string
  stage: string
  trade_event_types: string[]
  closed_result: string | null
  equity: number
  exhausted: boolean
}
