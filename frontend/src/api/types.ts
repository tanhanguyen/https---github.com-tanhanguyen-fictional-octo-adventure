export interface AccountOut {
  run_id: number | null
  equity: number
  balance: number
  drawdown_pct: number
  open_trades: number
  current_risk_pct: number
  daily_loss_count: number
  daily_losses_remaining: number
  current_trading_day: string | null
  consecutive_wins: number
  consecutive_losses: number
  risk_multiplier: number
  bot_enabled: boolean
  blocked_reason: string | null
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
  status: string
  starting_equity: number
  created_at_utc: string
  is_playing: boolean
}

export interface RunStepOut {
  bar_ts: string
  reason: string
  stage: string
  trade_event_types: string[]
  closed_result: string | null
  equity: number
  exhausted: boolean
}
