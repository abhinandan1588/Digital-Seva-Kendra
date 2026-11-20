import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { apiGet, apiPost, inr } from '../api.js'
import { useApp } from '../context.jsx'
import { useFlash } from '../components/useFlash.jsx'
import { Loading, ErrorAlert } from '../components/Bits.jsx'

export default function ServiceDetail() {
  const { t, pick, refreshCartCount } = useApp()
  const { slug } = useParams()
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [flash, flashMsg] = useFlash()

  useEffect(() => {
    setData(null); setError('')
    apiGet(`/api/services/${encodeURIComponent(slug)}`)
      .then(setData)
      .catch((e) => setError(e.code === 'not_found' ? t('not_found') : t('err_generic')))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug])

  const addToCart = async () => {
    setBusy(true)
    try {
      await apiPost('/api/cart/add', { service_id: data.service.id })
      refreshCartCount()
      flashMsg(`${t('added')} `)
    } catch (e) {
      flashMsg(t('err_generic'), 'danger')
    }
    setBusy(false)
  }

  if (error) return <section className="container py-5"><ErrorAlert>{error}</ErrorAlert></section>
  if (!data) return <Loading />

  const s = data.service
  const catIcon = s.category?.icon || 'bi-file-earmark-text'

  return (
    <section className="container py-5">
      {flash}
      <div className="mb-3 small">
        <Link to="/services" className="text-decoration-none">
          <i className="bi bi-arrow-left me-1"></i>{t('services_title')}
        </Link>
        {s.category && <span className="text-muted"> / {pick(s.category.name_en, s.category.name_hi)}</span>}
      </div>

      <div className="row g-4">
        <div className="col-lg-8">
          <div className="d-flex align-items-center gap-3 mb-2">
            <div className="service-icon"><i className={`bi ${catIcon}`} aria-hidden="true"></i></div>
            <h1 className="h3 fw-bold mb-0">{pick(s.name_en, s.name_hi)}</h1>
          </div>
          {s.image_url && <img src={s.image_url} alt="" className="img-fluid rounded mb-3 service-img-lg" />}
          <p className="text-muted">{pick(s.description_en, s.description_hi)}</p>

          {pick(s.processing_time_en, s.processing_time_hi) && (
            <p className="mb-2"><i className="bi bi-clock-history me-1 text-primary"></i>
              <strong>{t('processing_time')}:</strong> {pick(s.processing_time_en, s.processing_time_hi)}
            </p>
          )}
          {pick(s.instructions_en, s.instructions_hi) && (
            <div className="alert alert-light border">
              <strong><i className="bi bi-info-circle me-1"></i>{t('instructions')}:</strong>
              <div className="pre-wrap">{pick(s.instructions_en, s.instructions_hi)}</div>
            </div>
          )}

          {data.form_fields.length > 0 && (
            <>
              <h5 className="fw-bold mt-4">{t('form_fields')}</h5>
              <ul className="list-group">
                {data.form_fields.map((f) => (
                  <li className="list-group-item d-flex justify-content-between align-items-center" key={f.id}>
                    <span>{pick(f.label_en, f.label_hi)}</span>
                    <span className={`badge ${f.is_required ? 'bg-danger-subtle text-danger-emphasis' : 'bg-secondary-subtle text-secondary-emphasis'}`}>
                      {f.is_required ? t('required') : t('optional')}
                    </span>
                  </li>
                ))}
              </ul>
            </>
          )}

          {data.document_requirements.length > 0 && (
            <>
              <h5 className="fw-bold mt-4">{t('docs_required')}</h5>
              <ul className="list-group">
                {data.document_requirements.map((r) => (
                  <li className="list-group-item" key={r.id}>
                    <div className="d-flex justify-content-between align-items-center">
                      <span>{pick(r.label_en, r.label_hi)}</span>
                      <span className={`badge ${r.is_required ? 'bg-danger-subtle text-danger-emphasis' : 'bg-secondary-subtle text-secondary-emphasis'}`}>
                        {r.is_required ? t('required') : t('optional')}
                      </span>
                    </div>
                    <div className="form-text mb-0">
                      {pick(r.description_en, r.description_hi)}
                      {r.description_en || r.description_hi ? ' · ' : ''}
                      {t('ext_hint')}: {r.allowed_extensions.join(', ')} · {t('max_size')}: {r.max_file_mb} MB
                    </div>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>

        <div className="col-lg-4">
          <div className="card price-card sticky-top-price">
            <div className="card-body">
              <h5 className="fw-bold mb-3">{t('price_breakdown')}</h5>
              <table className="table table-sm mb-2">
                <tbody>
                  <tr><td>{t('service_charge')}</td><td className="text-end">{inr(s.service_charge)}</td></tr>
                  <tr><td>{t('official_fee')}</td><td className="text-end">{inr(s.official_fee)}</td></tr>
                  <tr><td>{t('other_charge')}</td><td className="text-end">{inr(s.other_charge)}</td></tr>
                </tbody>
                <tfoot>
                  <tr className="fw-bold"><td>{t('total')}</td><td className="text-end text-primary">{inr(s.total_price)}</td></tr>
                </tfoot>
              </table>
              <button className="btn btn-primary w-100 mt-2" onClick={addToCart} disabled={busy}>
                <i className="bi bi-plus-lg me-1"></i>{t('add_to_list')}
              </button>
              <Link to="/cart" className="btn btn-outline-secondary w-100 mt-2">
                <i className="bi bi-basket2 me-1"></i>{t('cart_title')}
              </Link>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
