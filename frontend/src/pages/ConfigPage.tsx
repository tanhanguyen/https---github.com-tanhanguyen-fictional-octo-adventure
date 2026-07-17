import { api } from '../api/client'
import { FilterConfigPanel } from '../components/FilterConfigPanel'
import { usePolling } from '../hooks/usePolling'

export function ConfigPage() {
  const { data: schema } = usePolling(() => api.getConfigSchema(), 60_000, false)
  const { data: config, refetch: refetchConfig } = usePolling(() => api.getConfig(), 60_000, false)
  const { data: versions, refetch: refetchVersions } = usePolling(
    () => api.listConfigVersions(),
    60_000,
    false,
    [config?.id],
  )

  function refreshAll() {
    void refetchConfig()
    void refetchVersions()
  }

  return (
    <div className="grid" style={{ gap: 16 }}>
      {schema && config ? (
        <FilterConfigPanel schema={schema} config={config} onChanged={refreshAll} />
      ) : (
        <p className="muted">Đang tải cấu hình...</p>
      )}

      <div className="card">
        <h2>Lịch sử phiên bản config</h2>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Version</th>
                <th>Active</th>
                <th>Created</th>
                <th>Note</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {(versions ?? []).map((v) => (
                <tr key={v.id}>
                  <td>v{v.version}</td>
                  <td>{v.is_active ? '✓' : ''}</td>
                  <td>{v.created_at_utc}</td>
                  <td>{v.note}</td>
                  <td>
                    {!v.is_active && (
                      <button
                        onClick={async () => {
                          await api.activateConfigVersion(v.id)
                          refreshAll()
                        }}
                      >
                        Activate
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
