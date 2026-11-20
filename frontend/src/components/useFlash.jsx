import { useState, useCallback } from 'react'

/** Tiny self-dismissing flash message. Returns [node, show]. */
export function useFlash(timeout = 2600) {
  const [msg, setMsg] = useState(null)
  const show = useCallback((text, kind = 'success') => {
    setMsg({ text, kind })
    window.clearTimeout(show._t)
    show._t = window.setTimeout(() => setMsg(null), timeout)
  }, [timeout])
  const node = msg ? (
    <div className={`alert alert-${msg.kind} flash-toast shadow-sm d-flex gap-2 align-items-center`}>
      <i className={`bi ${msg.kind === 'success' ? 'bi-check-circle-fill' : 'bi-exclamation-triangle-fill'}`}></i>
      <div>{msg.text}</div>
    </div>
  ) : null
  return [node, show]
}
