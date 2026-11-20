import { useEffect, useState } from 'react'
import { STATUS_LABELS } from '../i18n.js'
import { useApp } from '../context.jsx'

export function StatusBadge({ kind, value }) {
  const { pick } = useApp()
  const colors = {
    draft: 'secondary', submitted: 'secondary', awaiting_payment: 'warning text-dark',
    payment_verification: 'info text-dark', confirmed: 'primary', partially_completed: 'primary',
    completed: 'success', cancelled: 'danger', rejected: 'danger', refunded: 'dark',
    under_processing: 'primary', documents_required: 'warning text-dark',
    resubmission_required: 'warning text-dark', payment_verified: 'success',
    pending_verification: 'info text-dark', verified: 'success',
  }
  const pair = STATUS_LABELS[kind]?.[value]
  const label = pair ? pick(pair[0], pair[1]) : (value || '').replace(/_/g, ' ')
  return <span className={`badge ${colors[value] || 'secondary'}`}>{label}</span>
}

export function Loading({ label }) {
  const { t } = useApp()
  return (
    <div className="text-center text-muted py-5">
      <div className="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></div>
      {label || t('loading')}
    </div>
  )
}

export function ErrorAlert({ children }) {
  if (!children) return null
  return <div className="alert alert-danger d-flex gap-2 align-items-center">
    <i className="bi bi-exclamation-triangle-fill" aria-hidden="true"></i><div>{children}</div>
  </div>
}

export function OkAlert({ children }) {
  if (!children) return null
  return <div className="alert alert-success d-flex gap-2 align-items-center">
    <i className="bi bi-check-circle-fill" aria-hidden="true"></i><div>{children}</div>
  </div>
}

export function InfoAlert({ children }) {
  if (!children) return null
  return <div className="alert alert-info d-flex gap-2 align-items-center">
    <i className="bi bi-info-circle" aria-hidden="true"></i><div>{children}</div>
  </div>
}

/** True while the referenced element is scrolled out of the viewport.
 *  `dep` re-arms the observer after conditional content mounts. */
export function useOffscreen(ref, dep) {
  const [offscreen, setOffscreen] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!el || typeof IntersectionObserver === 'undefined') return undefined
    const io = new IntersectionObserver(([entry]) => setOffscreen(!entry.isIntersecting))
    io.observe(el)
    return () => io.disconnect()
  }, [ref, dep]) // eslint-disable-line react-hooks/exhaustive-deps -- dep is a render value
  return offscreen
}

/** Fixed bar at the bottom of the screen, shown while the in-flow action
 *  button is offscreen, so the primary action never disappears below the
 *  fold on long pages. */
export function StickyActionBar({ show, children }) {
  if (!show) return null
  return (
    <div className="sticky-action-bar">
      <div className="container">{children}</div>
    </div>
  )
}
