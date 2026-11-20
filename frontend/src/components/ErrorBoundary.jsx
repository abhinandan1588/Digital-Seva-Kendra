import { Component } from 'react'

/** Catches render errors so a bug shows a message instead of a blank page. */
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    console.error('UI error:', error, info?.componentStack)
  }

  render() {
    if (this.state.error) {
      return (
        <div className="container py-5 text-center">
          <div className="alert alert-danger d-inline-block text-start">
            <strong><i className="bi bi-exclamation-triangle-fill me-1"></i>
              Something went wrong. / कुछ गड़बड़ हो गई।</strong>
            <div className="small text-muted font-monospace mt-2 text-break">
              {String(this.state.error)}
            </div>
          </div>
          <div>
            <button className="btn btn-primary mt-2" onClick={() => window.location.reload()}>
              <i className="bi bi-arrow-clockwise me-1"></i>Reload / पुनः लोड करें
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}
