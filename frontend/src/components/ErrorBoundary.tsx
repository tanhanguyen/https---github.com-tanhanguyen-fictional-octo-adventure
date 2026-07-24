import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children: ReactNode
}

interface State {
  error: Error | null
}

/** Catches render-time errors in a page subtree so a single broken component shows a
 * recoverable message instead of a blank white app (plan 09 §3). One instance wraps each
 * routed page, so an error on one page never takes down the nav or the other routes. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Leaves a breadcrumb in the browser console for debugging; the UI stays usable.
    console.error('Page crashed:', error, info.componentStack)
  }

  private reset = () => this.setState({ error: null })

  render(): ReactNode {
    if (this.state.error !== null) {
      return (
        <div className="card error-fallback" role="alert">
          <h2>Trang gặp lỗi</h2>
          <p className="muted">{this.state.error.message}</p>
          <div className="toolbar">
            <button className="primary" onClick={this.reset}>
              Thử lại
            </button>
            <button onClick={() => window.location.reload()}>Tải lại trang</button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}
