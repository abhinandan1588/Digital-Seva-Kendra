import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiGet, apiPost, inr, rememberOrder } from '../api.js'
import { useApp } from '../context.jsx'
import { Loading, ErrorAlert } from '../components/Bits.jsx'

export default function Checkout() {
  const { t, pick } = useApp()
  const navigate = useNavigate()
  const [cart, setCart] = useState(null)
  const [profile, setProfile] = useState(null)
  const [token, setToken] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    apiGet('/api/cart').then((d) => {
      setCart(d)
      if ((d.items || []).length === 0) setError('cart_empty')
    }).catch((e) => setError(e.code || 'err_generic'))
    apiPost('/api/checkout/init').then((d) => setToken(d.checkout_token)).catch(() => {})
    // Contact details filled once on the unified form prefill checkout too.
    apiGet('/api/apply/common').then((d) => setProfile(d.profile || {})).catch(() => setProfile({}))
  }, [])

  const submit = async (e) => {
    e.preventDefault()
    setError(''); setBusy(true)
    const fd = new FormData(e.currentTarget)
    const payload = {
      name: fd.get('name') || '', mobile: fd.get('mobile') || '',
      email: fd.get('email') || '', address: fd.get('address') || '',
      consent: fd.get('consent') === 'on',
      checkout_token: token,
    }
    try {
      const res = await apiPost('/api/checkout', payload)
      if (res.duplicate) {
        navigate(`/track?order_number=${encodeURIComponent(res.order_number)}`)
        return
      }
      rememberOrder({
        order_number: res.order_number, token: res.tracking_token,
        pin: res.tracking_pin, total: res.total,
        created_at: new Date().toISOString(),
      })
      navigate(`/order/${res.order_number}?token=${encodeURIComponent(res.tracking_token)}`)
    } catch (err) {
      setError(err.data?.error || err.code || 'err_generic')
      window.scrollTo({ top: 0, behavior: 'smooth' })
      setBusy(false)
    }
  }

  if (!cart) return <Loading />
  if (cart.items.length === 0) {
    return <section className="container py-5"><ErrorAlert>{t('err_cart_empty')}</ErrorAlert></section>
  }
  const p = profile || {}

  return (
    <section className="container py-5">
      <h1 className="h3 fw-bold mb-4">{t('checkout_title')}</h1>
      <ErrorAlert>{error ? t('err_' + error) || t('err_generic') : ''}</ErrorAlert>
      <div className="row g-4">
        <div className="col-lg-7">
          <div className="card">
            <div className="card-body">
              <h5 className="fw-bold mb-3">{t('customer_details')}</h5>
              <form onSubmit={submit} key={profile === null ? 'loading' : 'ready'}>
                <div className="mb-3">
                  <label className="form-label fw-semibold" htmlFor="co-name">{t('full_name')} <span className="text-danger">*</span></label>
                  <input className="form-control" id="co-name" name="name" required minLength={2} defaultValue={p.name || ''} />
                </div>
                <div className="mb-3">
                  <label className="form-label fw-semibold" htmlFor="co-mobile">{t('mobile')} <span className="text-danger">*</span></label>
                  <input className="form-control" id="co-mobile" name="mobile" type="tel" inputMode="numeric"
                         pattern="[0-9 ]{10,13}" required defaultValue={p.mobile || ''} />
                </div>
                <div className="mb-3">
                  <label className="form-label fw-semibold" htmlFor="co-email">{t('email')}</label>
                  <input className="form-control" id="co-email" name="email" type="email" defaultValue={p.email || ''} />
                </div>
                <div className="mb-3">
                  <label className="form-label fw-semibold" htmlFor="co-address">{t('address')}</label>
                  <textarea className="form-control" id="co-address" name="address" rows={2} defaultValue={p.address || ''} />
                </div>
                <div className="form-check mb-3">
                  <input className="form-check-input" type="checkbox" id="co-consent" name="consent" required />
                  <label className="form-check-label small" htmlFor="co-consent">{t('consent')}</label>
                </div>
                <button className="btn btn-primary btn-lg w-100" disabled={busy || !token}>
                  {busy
                    ? <><span className="spinner-border spinner-border-sm me-2"></span>{t('placing')}</>
                    : <><i className="bi bi-bag-check me-1"></i>{t('place_order')} · {inr(cart.totals.total)}</>}
                </button>
              </form>
            </div>
          </div>
        </div>
        <div className="col-lg-5">
          <div className="card price-card">
            <div className="card-body">
              <h5 className="fw-bold mb-3">{t('order_summary')}</h5>
              <ul className="list-group list-group-flush mb-3">
                {cart.items.map((i) => (
                  <li className="list-group-item d-flex justify-content-between px-0 bg-transparent" key={i.key}>
                    <span>{pick(i.name_en, i.name_hi)}</span>
                    <span>{inr(i.line_total)}</span>
                  </li>
                ))}
              </ul>
              <div className="d-flex justify-content-between fw-bold fs-5">
                <span>{t('grand_total')}</span>
                <span className="text-primary">{inr(cart.totals.total)}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
