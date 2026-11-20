import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { apiGet, apiPost, inr, fmtDateTime, rememberOrder, savedOrders } from '../api.js'
import { useApp } from '../context.jsx'
import { Loading, ErrorAlert, StatusBadge } from '../components/Bits.jsx'

export default function Track() {
  const { t, pick, lang } = useApp()
  const [search] = useSearchParams()
  const [orderNumber, setOrderNumber] = useState(search.get('order_number') || '')
  const [code, setCode] = useState(search.get('code') || '')
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const recent = savedOrders()

  const doTrack = async (num, tok) => {
    const n = (num || orderNumber).trim().toUpperCase()
    const c = (tok || code).trim()
    if (!n || !c) return
    setBusy(true); setError('')
    try {
      const res = await apiGet(`/api/track?order_number=${encodeURIComponent(n)}&token=${encodeURIComponent(c)}`)
      setResult(res)
      rememberOrder({ order_number: n, token: c, pin: '', total: res.amounts?.total, created_at: new Date().toISOString() })
    } catch (e) {
      setResult(null)
      setError(e.data?.error || 'invalid_credentials')
    }
    setBusy(false)
  }

  // Auto-track when arriving from a confirmation/pay link (?order_number=&code=)
  useEffect(() => {
    const n = search.get('order_number'); const tok = search.get('code') || search.get('token')
    if (n && tok) doTrack(n, tok)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <section className="container py-5">
      <div className="row justify-content-center">
        <div className="col-lg-9">
          <h1 className="h3 fw-bold mb-4">{t('track_title')}</h1>

          <form className="row g-2 align-items-end mb-3" onSubmit={(e) => { e.preventDefault(); doTrack() }}>
            <div className="col-md-4">
              <label className="form-label fw-semibold small" htmlFor="tr-num">{t('order_number')}</label>
              <input className="form-control" id="tr-num" value={orderNumber}
                     placeholder="DSK-2026-000123"
                     onChange={(e) => setOrderNumber(e.target.value)} />
            </div>
            <div className="col-md-4">
              <label className="form-label fw-semibold small" htmlFor="tr-code">{t('code_or_pin')}</label>
              <input className="form-control" id="tr-code" value={code}
                     onChange={(e) => setCode(e.target.value)} />
            </div>
            <div className="col-md-3">
              <button className="btn btn-primary w-100" disabled={busy}>
                {busy ? <span className="spinner-border spinner-border-sm"></span> : <><i className="bi bi-search me-1"></i>{t('track_btn')}</>}
              </button>
            </div>
          </form>

          {recent.length > 0 && !result && (
            <div className="mb-4">
              <div className="small text-muted mb-1">{t('saved_orders')}</div>
              <div className="d-flex flex-wrap gap-2">
                {recent.map((o) => (
                  <button key={o.order_number} className="btn btn-sm btn-outline-secondary"
                          onClick={() => { setOrderNumber(o.order_number); setCode(o.token || o.pin || ''); doTrack(o.order_number, o.token || o.pin || '') }}>
                    {o.order_number}
                  </button>
                ))}
              </div>
            </div>
          )}

          <ErrorAlert>{error ? t('err_' + error) || t('err_generic') : ''}</ErrorAlert>

          {result && <TrackResult result={result} />}
        </div>
      </div>
    </section>
  )
}

function TrackResult({ result }) {
  const { t, pick, lang } = useApp()
  return (
    <div className="card mt-3">
      <div className="card-body">
        <div className="d-flex flex-wrap justify-content-between align-items-start mb-3">
          <div>
            <div className="fw-bold fs-5">{result.order_number}</div>
            <div className="small text-muted">
              {t('submitted_on')}: {fmtDateTime(result.submitted_at, lang)}
            </div>
          </div>
          <div className="text-end">
            <div>{t('status')}: <StatusBadge kind="order" value={result.status} /></div>
            <div className="mt-1">{t('payment_status')}: <StatusBadge kind="payment" value={result.payment_status} /></div>
          </div>
        </div>

        {result.payment_status === 'awaiting_payment' && (
          <div className="alert alert-warning d-flex justify-content-between align-items-center">
            <span>{t('pay_pending_cta')}</span>
            <Link className="btn btn-sm btn-primary" to={`/pay/${result.order_number}?token=${encodeURIComponent(result.token)}`}>
              {t('pay_now')}
            </Link>
          </div>
        )}

        <h6 className="fw-bold mt-2">{t('items')}</h6>
        <div className="table-responsive">
          <table className="table table-sm align-middle">
            <thead>
              <tr>
                <th>{t('application')}</th><th>{t('service')}</th>
                <th className="text-end">{t('amount')}</th><th>{t('status')}</th>
              </tr>
            </thead>
            <tbody>
              {result.items.map((i, idx) => (
                <tr key={idx}>
                  <td className="small">{i.application_number}</td>
                  <td>{i.service_name}</td>
                  <td className="text-end">{inr(i.line_total)}</td>
                  <td>{i.application_status ? <StatusBadge kind="application" value={i.application_status} /> : '—'}</td>
                </tr>
              ))}
              <tr className="fw-bold">
                <td colSpan={2}>{t('grand_total')}</td>
                <td className="text-end text-primary">{inr(result.amounts.total)}</td>
                <td></td>
              </tr>
            </tbody>
          </table>
        </div>

        <h6 className="fw-bold mt-3">{t('timeline')}</h6>
        {result.history.length === 0 ? (
          <div className="text-muted small">{t('no_updates')}</div>
        ) : (
          <ul className="timeline list-unstyled">
            {result.history.map((h, idx) => (
              <li key={idx} className="timeline-item">
                <div className="d-flex justify-content-between flex-wrap">
                  <strong><StatusBadge kind={h.entity_type} value={h.new_status} /></strong>
                  <span className="small text-muted">{fmtDateTime(h.created_at, lang)}</span>
                </div>
                {h.customer_remark && <div className="small text-muted">{h.customer_remark}</div>}
              </li>
            ))}
          </ul>
        )}

        <h6 className="fw-bold mt-3">{t('output_documents')}</h6>
        {result.output_documents.length === 0 ? (
          <div className="text-muted small">{t('no_documents')}</div>
        ) : (
          <ul className="list-group">
            {result.output_documents.map((d) => (
              <li className="list-group-item d-flex justify-content-between align-items-center" key={d.id}>
                <span className="small"><i className="bi bi-file-earmark-arrow-down me-2"></i>{d.original_name}</span>
                <a className="btn btn-sm btn-outline-primary" href={d.download_url}>
                  <i className="bi bi-download me-1"></i>{t('download')}
                </a>
              </li>
            ))}
          </ul>
        )}

        <a className="btn btn-outline-secondary btn-sm mt-3" href={result.receipt_url} target="_blank" rel="noopener">
          <i className="bi bi-file-earmark-pdf me-1"></i>{t('receipt')}
        </a>
      </div>
    </div>
  )
}
