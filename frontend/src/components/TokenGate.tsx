import { useEffect, useState } from 'react'
import { UNAUTHORIZED_EVENT, getApiToken, setApiToken } from '../api/client'

/** The API-token entry (plan 09 §2). A 🔑 button in the nav lets the operator set/replace
 * the token at any time; a 401 from the backend auto-opens the same dialog. The token is
 * stored in localStorage and attached to every request by the axios client. */
export function TokenGate() {
  const [open, setOpen] = useState(false)
  const [value, setValue] = useState('')

  useEffect(() => {
    const onUnauthorized = () => {
      setValue(getApiToken())
      setOpen(true)
    }
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
  }, [])

  function openDialog() {
    setValue(getApiToken())
    setOpen(true)
  }

  function save() {
    setApiToken(value)
    setOpen(false)
    // Simplest correct behavior: reload so every poller re-fetches with the new header.
    window.location.reload()
  }

  return (
    <>
      <button
        className="token-button"
        onClick={openDialog}
        title="Nhập API token"
        aria-label="Nhập API token"
      >
        🔑
      </button>
      {open && (
        <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="API token">
          <div className="modal">
            <h3>API token</h3>
            <p className="muted">
              Backend đang bật auth. Nhập token (được lưu trong trình duyệt này) để truy cập.
            </p>
            <input
              type="password"
              autoFocus
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder="Bearer token"
              style={{ width: '100%' }}
              onKeyDown={(e) => e.key === 'Enter' && save()}
            />
            <div className="toolbar">
              <button className="primary" onClick={save}>
                Lưu
              </button>
              <button onClick={() => setOpen(false)}>Đóng</button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
