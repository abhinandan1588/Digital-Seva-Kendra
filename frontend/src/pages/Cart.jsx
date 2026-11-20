import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { apiGet, apiPost, inr } from '../api.js'
import { useApp } from '../context.jsx'
import { Loading, ErrorAlert, InfoAlert, OkAlert, StickyActionBar, useOffscreen } from '../components/Bits.jsx'

export default function Cart() {
  const { t, pick, refreshCartCount } = useApp()
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState(null)
  const [busy, setBusy] = useState(false)
  // primary CTA lives below the list; a fixed bar keeps it reachable while
  // the user scrolls through a long list
  const fillBtnRef = useRef(null)
  const fillBtnOffscreen = useOffscreen(fillBtnRef, data)

  const load = useCallback(() => {
    apiGet('/api/cart').then(setData).catch((e) => setError(e.code || 'err_generic'))
  }, [])
  useEffect(() => { load(); refreshCartCount() }, [load, refreshCartCount])

  const removeItem = async (key) => {
    await apiPost('/api/cart/remove', { item_key: key }).catch(() => {})
    setNotice({ kind: 'info', text: t('removed') })
    load(); refreshCartCount()
  }

  const clearList = async () => {
    await apiPost('/api/cart/clear').catch(() => {})
    setNotice({ kind: 'info', text: t('cleared') })
    load(); refreshCartCount()
  }

  if (error) return <section className="container py-5"><ErrorAlert>{t('err_' + error) || t('err_generic')}</ErrorAlert></section>
  if (!data) return <Loading />

  const missingForms = data.items.some((i) => !i.form_filled)
  const hasUnavailable = (data.unavailable || []).length > 0
  const canCheckout = data.items.length > 0 && !missingForms && !hasUnavailable

  return (
    <section className="container py-5">
      <h1 className="h3 fw-bold mb-4">{t('cart_title')}</h1>
      <OkAlert>{notice?.kind === 'success' ? notice.text : ''}</OkAlert>
      <InfoAlert>{notice?.kind === 'info' ? notice.text : ''}</InfoAlert>
      {hasUnavailable && <ErrorAlert>{t('unavailable_warning')}</ErrorAlert>}

      {data.items.length === 0 ? (
        <div className="text-center py-5">
          <i className="bi bi-basket2 display-5 text-muted" aria-hidden="true"></i>
          <p className="text-muted mt-3">{t('cart_empty')}</p>
          <Link to="/services" className="btn btn-primary">
            <i className="bi bi-grid-3x3-gap me-1"></i>{t('browse_services')}
          </Link>
        </div>
      ) : (
        <div className="row g-4">
          <div className="col-lg-8">
            <div className="list-group">
              {data.items.map((item) => (
                <div className="list-group-item" key={item.key}>
                  <div className="d-flex justify-content-between align-items-center">
                    <div>
                      <Link to={`/services/${item.slug}`} className="fw-semibold text-decoration-none">
                        {pick(item.name_en, item.name_hi)}
                      </Link>
                      <div className="small text-muted">{inr(item.line_total)}</div>
                    </div>
                    <div className="d-flex align-items-center gap-2">
                      <span className={`badge ${item.form_filled ? 'bg-success-subtle text-success-emphasis' : 'bg-warning-subtle text-warning-emphasis'}`}>
                        {item.form_filled ? t('form_done') : t('form_pending')}
                      </span>
                      <button className="btn btn-sm btn-outline-danger" onClick={() => removeItem(item.key)}>
                        <i className="bi bi-trash me-1"></i>{t('remove')}
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
            <button className="btn btn-link btn-sm text-danger ps-0 mt-2" onClick={clearList}>
              <i className="bi bi-x-circle me-1"></i>{t('clear_list')}
            </button>
            <div ref={fillBtnRef} className="d-grid mt-4">
              <button className="btn btn-primary btn-lg" onClick={() => navigate('/apply')}>
                <i className="bi bi-pencil-square me-1"></i>
                {missingForms ? t('fill_all_forms') : t('edit_application')}
              </button>
              <div className="form-text text-center">{t('unified_note')}</div>
            </div>
          </div>

          <div className="col-lg-4">
            <div className="card price-card">
              <div className="card-body">
                <h5 className="fw-bold mb-3">{t('order_summary')}</h5>
                <table className="table table-sm mb-2">
                  <tbody>
                    <tr><td>{t('service_charge')}</td><td className="text-end">{inr(data.totals.service_charges_total)}</td></tr>
                    <tr><td>{t('official_fee')}</td><td className="text-end">{inr(data.totals.official_fees_total)}</td></tr>
                    <tr><td>{t('other_charge')}</td><td className="text-end">{inr(data.totals.other_charges_total)}</td></tr>
                  </tbody>
                  <tfoot>
                    <tr className="fw-bold"><td>{t('grand_total')}</td><td className="text-end text-primary">{inr(data.totals.total)}</td></tr>
                  </tfoot>
                </table>
                {missingForms && <div className="small text-warning-emphasis mb-2"><i className="bi bi-exclamation-triangle me-1"></i>{t('complete_forms_first')}</div>}
                <button className="btn btn-primary w-100" disabled={!canCheckout || busy}
                        onClick={() => navigate('/checkout')}>
                  {t('proceed_checkout')} <i className="bi bi-arrow-right"></i>
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      <StickyActionBar show={data.items.length > 0 && fillBtnOffscreen}>
        <button className="btn btn-primary btn-lg w-100" onClick={() => navigate('/apply')}>
          <i className="bi bi-pencil-square me-1"></i>
          {missingForms ? t('fill_all_forms') : t('edit_application')}
        </button>
      </StickyActionBar>
    </section>
  )
}
