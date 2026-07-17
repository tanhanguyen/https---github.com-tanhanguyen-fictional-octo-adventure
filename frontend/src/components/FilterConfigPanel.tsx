import { useMemo, useState } from 'react'
import { api } from '../api/client'
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

export function FilterConfigPanel({ schema, config, onChanged }: Props) {
  const [pending, setPending] = useState<Record<string, boolean>>({})
  const root = schema.json_schema

  const filtersRootDef = useMemo(() => {
    const filtersProp = resolveRef(root, root.properties.filters)
    return filtersProp
  }, [root])

  const sortedMeta = useMemo(
    () => [...schema.metadata].sort((a, b) => a.ordinal - b.ordinal),
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
