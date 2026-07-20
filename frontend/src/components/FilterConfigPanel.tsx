import { useMemo, useState } from 'react'
import { api, errorDetail } from '../api/client'
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type JsonSchema = Record<string, any>
import type { ConfigOut, ConfigSchemaOut } from '../api/types'

interface Props {
  schema: ConfigSchemaOut
  config: ConfigOut
  onChanged: () => void
}

function resolveRef(root: JsonSchema, node: JsonSchema): JsonSchema {
  if (node && typeof node === 'object' && '$ref' in node) {
    const path = String(node['$ref']).replace('#/', '').split('/')
    let cur: JsonSchema = root
    for (const p of path) cur = cur[p]
    return cur
  }
  return node
}

function scalarFields(root: JsonSchema, filterDef: JsonSchema): [string, JsonSchema][] {
  const props: Record<string, JsonSchema> = filterDef.properties ?? {}
  return Object.entries(props).filter(([key, def]) => {
    if (key === 'enabled' || key === 'locked') return false
    const resolved = resolveRef(root, def)
    const type = resolved.type ?? (resolved.anyOf ? resolved.anyOf[0]?.type : undefined)
    return type === 'number' || type === 'integer' || type === 'string' || type === 'boolean'
  })
}

/** Plan 04: `symbols` has no per-item FieldMeta (it's a nested list of objects) --
 * schema-driven rendering falls back to a raw JSON editor, validated server-side by
 * PATCH /api/config (client-side JSON.parse just catches typos early). */
function SymbolsJsonEditor({ config, onChanged }: { config: ConfigOut; onChanged: () => void }) {
  const initial = JSON.stringify(config.config.symbols ?? [], null, 2)
  const [text, setText] = useState(initial)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function save() {
    setError(null)
    let parsed: unknown
    try {
      parsed = JSON.parse(text)
    } catch (e) {
      setError(`JSON không hợp lệ: ${String(e)}`)
      return
    }
    setBusy(true)
    try {
      await api.patchConfig({ symbols: parsed })
      onChanged()
    } catch (e) {
      setError(errorDetail(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="filter-row">
      <div className="filter-name">
        <span>0. Danh sách symbol (portfolio / whitelist)</span>
      </div>
      <div className="filter-params" style={{ flexDirection: 'column', alignItems: 'stretch' }}>
        <textarea
          rows={10}
          style={{ fontFamily: 'monospace', width: '100%' }}
          value={text}
          disabled={busy}
          onChange={(e) => setText(e.target.value)}
        />
        <div className="toolbar">
          <button disabled={busy} onClick={() => void save()}>
            Lưu symbols
          </button>
          <button disabled={busy} onClick={() => setText(initial)}>
            Hoàn tác
          </button>
        </div>
        {error && <span style={{ color: 'var(--danger, red)' }}>{error}</span>}
        <span className="muted">
          Mỗi entry: symbol, symbol_type, enabled, dataset_seed, overrides (chỉ
          filters/strategies/timeframe/risk.allow_short/risk.max_risk_per_trade_pct).
        </span>
      </div>
    </div>
  )
}

export function FilterConfigPanel({ schema, config, onChanged }: Props) {
  const [pending, setPending] = useState<Record<string, boolean>>({})
  const root = schema.json_schema

  const filtersRootDef = useMemo(() => {
    const filtersProp = resolveRef(root, root.properties.filters)
    return filtersProp
  }, [root])

  const sortedMeta = useMemo(
    () => [...schema.metadata].sort((a, b) => a.ordinal - b.ordinal).filter((m) => m.kind),
    [schema.metadata],
  )

  async function patchFilter(id: string, patch: Record<string, unknown>) {
    setPending((p) => ({ ...p, [id]: true }))
    try {
      await api.patchConfig({ filters: { [id]: patch } })
      onChanged()
    } finally {
      setPending((p) => ({ ...p, [id]: false }))
    }
  }

  return (
    <div className="card">
      <h2>Cấu hình bộ lọc ({sortedMeta.length})</h2>
      <p className="muted">
        Render trực tiếp từ <code>/api/config/schema</code> — thêm filter mới không cần sửa
        frontend.
      </p>
      <div className="filter-group">
        <SymbolsJsonEditor config={config} onChanged={onChanged} />
        {sortedMeta.map((m) => {
          const id = m.field.replace('filters.', '')
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          const filterCfg: Record<string, any> = config.config.filters?.[id] ?? {}
          const filterDefRef = filtersRootDef.properties?.[id]
          const filterDef = filterDefRef ? resolveRef(root, filterDefRef) : { properties: {} }
          const fields = scalarFields(root, filterDef)
          const busy = pending[id]

          return (
            <div className="filter-row" key={id}>
              <div className="filter-name">
                <input
                  type="checkbox"
                  checked={Boolean(filterCfg.enabled)}
                  disabled={busy || m.locked}
                  onChange={(e) => patchFilter(id, { enabled: e.target.checked })}
                />
                <span>
                  {m.ordinal}. {m.label_vi}
                  {m.locked && ' 🔒'}
                </span>
                <span className="muted">[{m.kind}]</span>
              </div>
              <div className="filter-params">
                {fields.map(([key, def]) => {
                  const resolved = resolveRef(root, def)
                  const type = resolved.type ?? resolved.anyOf?.[0]?.type
                  const value = filterCfg[key]
                  if (type === 'boolean') {
                    return (
                      <label key={key}>
                        {key}
                        <input
                          type="checkbox"
                          checked={Boolean(value)}
                          disabled={busy || m.locked}
                          onChange={(e) => patchFilter(id, { [key]: e.target.checked })}
                        />
                      </label>
                    )
                  }
                  if (type === 'number' || type === 'integer') {
                    return (
                      <label key={key}>
                        {key}
                        <input
                          type="number"
                          value={value ?? ''}
                          disabled={busy || m.locked}
                          step={type === 'integer' ? 1 : 'any'}
                          onChange={(e) => {
                            const n =
                              type === 'integer'
                                ? parseInt(e.target.value, 10)
                                : parseFloat(e.target.value)
                            if (!Number.isNaN(n)) patchFilter(id, { [key]: n })
                          }}
                        />
                      </label>
                    )
                  }
                  return null
                })}
                {m.spec_ref && <span className="muted">{m.spec_ref}</span>}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
