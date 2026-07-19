import axios from 'axios'
import type {
  AccountOut,
  BarOut,
  ConfigOut,
  ConfigSchemaOut,
  ConfigVersionOut,
  DatasetOut,
  DecisionDetailOut,
  DecisionOut,
  DecisionStatsOut,
  EquityPointOut,
  FilterRowOut,
  RunCompareOut,
  RunOut,
  RunReportOut,
  RunStepOut,
  RunSummaryOut,
  SymbolOut,
  TradeDetailOut,
  TradeOut,
} from './types'

const http = axios.create({ baseURL: '/api' })

/** FastAPI puts the human-readable message in `detail`; fall back to the raw error. */
export function errorDetail(err: unknown): string {
  const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
  return detail ?? String(err)
}

export const api = {
  health: () => http.get<{ status: string }>('/health').then((r) => r.data),

  getAccount: () => http.get<AccountOut>('/account').then((r) => r.data),

  getConfig: () => http.get<ConfigOut>('/config').then((r) => r.data),
  patchConfig: (patch: Record<string, unknown>) =>
    http.patch<ConfigOut>('/config', patch).then((r) => r.data),
  getConfigSchema: () => http.get<ConfigSchemaOut>('/config/schema').then((r) => r.data),
  listConfigVersions: () =>
    http.get<ConfigVersionOut[]>('/config/versions').then((r) => r.data),
  activateConfigVersion: (id: number) =>
    http.post<ConfigOut>(`/config/versions/${id}/activate`).then((r) => r.data),

  listFilters: () => http.get<FilterRowOut[]>('/filters').then((r) => r.data),

  listTrades: (status?: string) =>
    http
      .get<TradeOut[]>('/trades', { params: status ? { status } : {} })
      .then((r) => r.data),
  getTrade: (id: number) => http.get<TradeDetailOut>(`/trades/${id}`).then((r) => r.data),

  listDecisions: (params: { limit?: number; reason?: string; outcome?: string } = {}) =>
    http.get<DecisionOut[]>('/decisions', { params }).then((r) => r.data),
  getDecision: (id: number) =>
    http.get<DecisionDetailOut>(`/decisions/${id}`).then((r) => r.data),
  getDecisionStats: () => http.get<DecisionStatsOut>('/decisions/stats').then((r) => r.data),

  getEquity: (limit = 500) =>
    http.get<EquityPointOut[]>('/equity', { params: { limit } }).then((r) => r.data),
  getSymbols: () => http.get<SymbolOut[]>('/symbols').then((r) => r.data),

  listDatasets: () => http.get<DatasetOut[]>('/datasets').then((r) => r.data),
  createDataset: (seed: number, bars: number) =>
    http.post<DatasetOut>('/datasets', { seed, bars }).then((r) => r.data),
  importCsv: (path: string, symbol: string, nativeTf: string) =>
    http
      .post<DatasetOut>('/datasets/import', { path, symbol, native_tf: nativeTf })
      .then((r) => r.data),

  getRun: () => http.get<RunOut | null>('/run').then((r) => r.data),
  createRun: (seed: number, bars: number, datasetId?: string) =>
    http
      .post<RunOut>('/run', { seed, bars, dataset_id: datasetId ?? null })
      .then((r) => r.data),
  step: () => http.post<RunStepOut>('/run/step').then((r) => r.data),

  listRuns: () => http.get<RunSummaryOut[]>('/runs').then((r) => r.data),
  getRunReport: (id: number) =>
    http.get<RunReportOut>(`/runs/${id}/report`).then((r) => r.data),
  compareRuns: (a: number, b: number) =>
    http.get<RunCompareOut>('/runs/compare', { params: { a, b } }).then((r) => r.data),
  deleteRun: (id: number) =>
    http.delete<{ status: string }>(`/runs/${id}`).then((r) => r.data),
  getRunEquity: (id: number, limit = 100000) =>
    http.get<EquityPointOut[]>(`/runs/${id}/equity`, { params: { limit } }).then((r) => r.data),
  getRunBars: (id: number, tf: string, from?: string, to?: string) =>
    http
      .get<BarOut[]>(`/runs/${id}/bars`, { params: { tf, from, to } })
      .then((r) => r.data),
  getRunTrades: (id: number, status?: string) =>
    http
      .get<TradeOut[]>(`/runs/${id}/trades`, { params: status ? { status } : {} })
      .then((r) => r.data),
  play: (intervalMs = 200) =>
    http.post<RunOut>('/run/play', { interval_ms: intervalMs }).then((r) => r.data),
  pause: () => http.post<RunOut | null>('/run/pause').then((r) => r.data),
  reset: () => http.post<{ status: string }>('/run/reset').then((r) => r.data),
}
