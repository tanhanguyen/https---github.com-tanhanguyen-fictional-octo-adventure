import type { ConfigOut, ConfigSchemaOut } from '../api/types'

/** Minimal config-schema fixture: just the two regime filters, each with `enabled` plus
 * one scalar param, enough to drive FilterConfigPanel's schema-driven rendering. */
export const schemaFixture: ConfigSchemaOut = {
  json_schema: {
    properties: {
      filters: {
        properties: {
          adx_filter: {
            properties: {
              enabled: { type: 'boolean' },
              threshold_trend: { type: 'number' },
            },
          },
          er_filter: {
            properties: {
              enabled: { type: 'boolean' },
              threshold: { type: 'number' },
            },
          },
        },
      },
    },
  },
  metadata: [
    {
      field: 'filters.adx_filter',
      label_vi: 'Cường độ xu hướng (ADX)',
      group: 'regime',
      ordinal: 2,
      kind: 'regime',
      locked: false,
      spec_ref: '§2#2',
      min: null,
      max: null,
      step: null,
    },
    {
      field: 'filters.er_filter',
      label_vi: 'Độ mượt xu hướng (ER)',
      group: 'regime',
      ordinal: 3,
      kind: 'regime',
      locked: false,
      spec_ref: '§2#3',
      min: null,
      max: null,
      step: null,
    },
  ],
}

/** Build a ConfigOut with the two regime filters enabled/disabled as requested. */
export function configFixture(adxEnabled: boolean, erEnabled: boolean): ConfigOut {
  return {
    id: 1,
    version: 1,
    is_active: true,
    created_at_utc: '2026-07-24T00:00:00Z',
    note: '',
    config: {
      symbols: [],
      filters: {
        adx_filter: { enabled: adxEnabled, threshold_trend: 20 },
        er_filter: { enabled: erEnabled, threshold: 0.3 },
      },
    },
  }
}
