import axios from 'axios'
import type {
  AccountOut,
  ConfigOut,
  ConfigSchemaOut,
  ConfigVersionOut,
  DatasetOut,
  DecisionDetailOut,
  DecisionOut,
  DecisionStatsOut,
  EquityPointOut,
  FilterRowOut,
  RunOut,
  RunStepOut,
  SymbolOut,
  TradeDetailOut,
  TradeOut,
} from './types'

const http = axios.create({ baseURL: '/api' })

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

  getRun: () => http.get<RunOut | null>('/run').then((r) => r.data),
  createRun: (seed: number, bars: number) =>
    http.post<RunOut>('/run', { seed, bars }).then((r) => r.data),
  step: () => http.post<RunStepOut>('/run/step').then((r) => r.data),
  play: (intervalMs = 200) =>
    http.post<RunOut>('/run/play', { interval_ms: intervalMs }).then((r) => r.data),
  pause: () => http.post<RunOut | null>('/run/pause').then((r) => r.data),
  reset: () => http.post<{ status: string }>('/run/reset').then((r) => r.data),
}
