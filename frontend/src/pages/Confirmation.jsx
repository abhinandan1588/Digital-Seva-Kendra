import { Link, useParams, useSearchParams } from 'react-router-dom'
import { findSavedOrder, inr } from '../api.js'
import { useApp } from '../context.jsx'
import { InfoAlert } from '../components/Bits.jsx'

export default function Confirmation() {
  const { orderNumber } = useParams()
  const [search] = useSearchParams()
  const { t } = useApp()
  const token = search.get('token') || ''
  const saved = findSavedOrder(orderNumber)

  return (
    <section className="container py-5">
      <div className="row justify-content-center">
        <div className="col-lg-7 text-center">
          <div className="text-success display-4 mb-2"><i className="bi bi-check-circle-fill"></i></div>
          <h1 className="h3 fw-bold">{t('order_created')}</h1>
          <p className="text-muted">DSK · {orderNumber}</p>

          <div className="card text-start my-4">
            <div className="card-body">
              <div className="mb-3">
                <div className="small text-muted">{t('order_no')}</div>
                <div className="fs-4 fw-bold">{orderNumber}</div>
              </div>
              <div className="mb-3">
                <div className="small text-muted">{t('tracking_code')}</div>
                <div className="fs-6 font-monospace text-break user-select-all">{token || saved?.token || ''}</div>
              </div>
              {saved?.pin && (
                <div className="mb-1">
                  <div className="small text-muted">{t('tracking_pin')}</div>
                  <div className="fs-4 fw-bold font-monospace user-select-all">{saved.pin}</div>
                </div>
              )}
              <div className="alert alert-warning small mt-3 mb-0">
                <i className="bi bi-exclamation-triangle-fill me-1"></i>{t('pin_warning')}
              </div>
            </div>
          </div>

          {!saved && <InfoAlert>{t('duplicate_note')}</InfoAlert>}

          <div className="d-flex flex-wrap justify-content-center gap-2 mt-4">
            <Link className="btn btn-primary btn-lg" to={`/pay/${orderNumber}?token=${encodeURIComponent(token || saved?.token || '')}`}>
              <i className="bi bi-qr-code me-1"></i>{t('pay_now')}
            </Link>
            <Link className="btn btn-outline-secondary" to={`/track?order_number=${encodeURIComponent(orderNumber)}&code=${encodeURIComponent(token || saved?.token || '')}`}>
              <i className="bi bi-search me-1"></i>{t('track_now')}
            </Link>
            <a className="btn btn-outline-secondary"
               href={`/order/${orderNumber}/receipt.pdf?token=${encodeURIComponent(token || saved?.token || '')}`}
               target="_blank" rel="noopener">
              <i className="bi bi-file-earmark-pdf me-1"></i>{t('download_receipt')}
            </a>
          </div>
          {saved?.total && <p className="text-muted small mt-3">{t('grand_total')}: {inr(saved.total)}</p>}
        </div>
      </div>
    </section>
  )
}
