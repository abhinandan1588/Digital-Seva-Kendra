import { useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { apiGet, apiPost, inr } from '../api.js'
import { useApp } from '../context.jsx'
import { Loading, ErrorAlert, OkAlert, InfoAlert } from '../components/Bits.jsx'
import { StatusBadge } from '../components/Bits.jsx'

export default function Pay() {
  const { orderNumber } = useParams()
  const [search] = useSearchParams()
  const { t, pick } = useApp()
  const token = search.get('token') || ''
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [okMsg, setOkMsg] = useState('')
  const [pendingNote, setPendingNote] = useState(false)

  const load = () => {
    apiGet(`/api/pay/${encodeURIComponent(orderNumber)}?token=${encodeURIComponent(token)}`)
      .then(setData)
      .catch((e) => setError(e.data?.error || e.code || 'err_generic'))
  }
  useEffect(load, [orderNumber, token])

  const submit = async (e) => {
    e.preventDefault()
    setError(''); setBusy(true); setOkMsg('')
    try {
      const fd = new FormData(e.currentTarget)
      fd.set('token', token)
      const res = await apiPost(`/api/pay/${encodeURIComponent(orderNumber)}/proof`, fd)
      setOkMsg(res.upload_pending ? 'upload_pending' : 'proof_ok')
      setPendingNote(res.upload_pending)
      load()
      window.scrollTo({ top: 0, behavior: 'smooth' })
    } catch (err) {
      setError(err.data?.error || err.code || 'err_generic')
    }
    setBusy(false)
  }

  if (error && !data) {
    return <section className="container py-5"><ErrorAlert>{t('err_' + error) || t('err_generic')}</ErrorAlert></section>
  }
  if (!data) return <Loading />

  const verified = data.payment_status === 'verified'
  const refunded = data.payment_status === 'refunded'

  return (
    <section className="container py-5">
      <div className="row justify-content-center">
        <div className="col-lg-8">
          <h1 className="h3 fw-bold mb-1">{t('payment_for')} · {data.order_number}</h1>
          <p className="text-muted">
            {t('payment_status')}: <StatusBadge kind="payment" value={data.payment_status} />
          </p>

          <OkAlert>{okMsg === 'proof_ok' ? t('proof_ok') : ''}</OkAlert>
          <InfoAlert>{okMsg === 'upload_pending' ? t('upload_pending') : ''}</InfoAlert>
          <ErrorAlert>{error ? t('err_' + error) || t('err_generic') : ''}</ErrorAlert>

          {verified && (
            <div className="alert alert-success d-flex gap-2 align-items-center">
              <i className="bi bi-check-circle-fill"></i>
              <div>{t('already_verified')}</div>
            </div>
          )}
          {refunded && <ErrorAlert>{t('refunded')}</ErrorAlert>}

          {!verified && !refunded && (
            <div className="row g-4 mt-1">
              <div className="col-md-6">
                <div className="card h-100 text-center">
                  <div className="card-body">
                    <h5 className="fw-bold">{t('scan_qr')}</h5>
                    <div className="fw-bold fs-3 text-primary my-2">{inr(data.total)}</div>
                    <img src={data.qr_url} alt="UPI QR" className="img-fluid qr-img" />
                    <div className="small text-muted mt-2">{t('upi_id_label')}: {data.upi_id}</div>
                    <a href={data.upi_intent} className="btn btn-sm btn-outline-primary mt-2">
                      <i className="bi bi-phone me-1"></i>{t('open_upi')}
                    </a>
                  </div>
                </div>
              </div>
              <div className="col-md-6">
                <div className="alert alert-info small">
                  <strong>{t('payment_instructions')}:</strong>
                  <div className="pre-wrap">{pick(data.instructions_en, data.instructions_hi)}</div>
                </div>
                <form onSubmit={submit} encType="multipart/form-data">
                  <div className="mb-3">
                    <label className="form-label fw-semibold" htmlFor="utr">{t('utr_label')} <span className="text-danger">*</span></label>
                    <input className="form-control" id="utr" name="utr" minLength={8} maxLength={60} required />
                    <div className="form-text">{t('utr_hint')}</div>
                  </div>
                  <div className="mb-3">
                    <label className="form-label fw-semibold" htmlFor="screenshot">{t('screenshot_label')} <span className="text-danger">*</span></label>
                    <input className="form-control" id="screenshot" name="screenshot" type="file"
                           accept=".jpg,.jpeg,.png,.pdf" required />
                  </div>
                  <div className="mb-3">
                    <label className="form-label fw-semibold" htmlFor="remarks">{t('remarks')}</label>
                    <input className="form-control" id="remarks" name="remarks" maxLength={200} />
                  </div>
                  <button className="btn btn-primary w-100" disabled={busy}>
                    {busy
                      ? <><span className="spinner-border spinner-border-sm me-2"></span>{t('submitting')}</>
                      : <><i className="bi bi-send me-1"></i>{t('submit_proof')}</>}
                  </button>
                </form>
              </div>
            </div>
          )}

          <div className="small text-muted mt-4">
            {pick(data.support_info_en, data.support_info_hi)}
          </div>
          <Link className="btn btn-outline-secondary mt-3"
                to={`/track?order_number=${encodeURIComponent(data.order_number)}&code=${encodeURIComponent(token)}`}>
            <i className="bi bi-search me-1"></i>{t('track_now')}
          </Link>
        </div>
      </div>
    </section>
  )
}
