import { useState } from 'react'
import { Link } from 'react-router-dom'
import { apiPost, inr } from '../api.js'
import { useApp } from '../context.jsx'

export default function ServiceCard({ service, onAdded }) {
  const { t, pick } = useApp()
  const [busy, setBusy] = useState(false)
  const catIcon = service.category?.icon || 'bi-file-earmark-text'

  const add = async () => {
    setBusy(true)
    try {
      await apiPost('/api/cart/add', { service_id: service.id })
      onAdded?.()
    } catch { /* card stays; parent shows message */ }
    setBusy(false)
  }

  return (
    <div className="card h-100 service-card">
      {service.image_url && (
        <img src={service.image_url} className="card-img-top service-img" alt=""
             loading="lazy" />
      )}
      <div className="card-body d-flex flex-column">
        <div className="service-icon mb-2"><i className={`bi ${catIcon}`} aria-hidden="true"></i></div>
        <h5 className="card-title">{pick(service.name_en, service.name_hi)}</h5>
        <p className="card-text small text-muted flex-grow-1">
          {(pick(service.description_en, service.description_hi) || '').slice(0, 110)}
        </p>
        <div className="d-flex justify-content-between align-items-center mt-2">
          <span className="fw-bold text-primary">{inr(service.total_price)}</span>
          <div className="d-flex gap-2">
            <Link to={`/services/${service.slug}`} className="btn btn-sm btn-outline-secondary">{t('view_all')}</Link>
            <button className="btn btn-sm btn-primary" onClick={add} disabled={busy}>
              {t('add_to_list')} <i className="bi bi-plus-lg"></i>
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
