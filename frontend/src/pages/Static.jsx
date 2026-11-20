import { useEffect, useState } from 'react'
import { apiGet } from '../api.js'
import { useApp } from '../context.jsx'
import { Loading } from '../components/Bits.jsx'

export function About() {
  const { t, pick, settings } = useApp()
  return (
    <section className="container py-5">
      <div className="row justify-content-center"><div className="col-lg-8">
        <h1 className="fw-bold mb-3">{t('about_title')}</h1>
        <p className="lead">{pick(settings.shop_name, settings.shop_name_hi)} {t('about_lead_sfx')}</p>
        <p className="text-muted">
          {t('about1')} {t('about2')}
        </p>
        <div className="row g-4 mt-3">
          <div className="col-md-6">
            <div className="card h-100"><div className="card-body">
              <h5 className="fw-bold"><i className="bi bi-people me-2 text-primary"></i>{t('who_we_serve')}</h5>
              <p className="small text-muted mb-0">{t('who_we_serve_d')}</p>
            </div></div>
          </div>
          <div className="col-md-6">
            <div className="card h-100"><div className="card-body">
              <h5 className="fw-bold"><i className="bi bi-info-circle me-2 text-primary"></i>{t('honest_disclaimer')}</h5>
              <p className="small text-muted mb-0">{pick(settings.footer_text, settings.footer_text_hi)}</p>
            </div></div>
          </div>
        </div>
      </div></div>
    </section>
  )
}

export function Contact() {
  const { t, settings } = useApp()
  return (
    <section className="container py-5">
      <div className="row justify-content-center"><div className="col-lg-8">
        <h1 className="fw-bold mb-4">{t('contact_title')}</h1>
        <div className="row g-4">
          {[
            ['bi-geo-alt', t('addr_label'), settings.shop_address],
            ['bi-telephone', t('phone_label'),
              <span key="p">
                <a href={`tel:+91${settings.shop_mobile}`}>{settings.shop_mobile}</a>
                {settings.shop_whatsapp && <> · <a href={`https://wa.me/91${settings.shop_whatsapp}`} target="_blank" rel="noopener">WhatsApp</a></>}
              </span>],
            ['bi-envelope', t('email_label'), <a key="e" href={`mailto:${settings.shop_email}`}>{settings.shop_email}</a>],
            ['bi-clock', t('hours_label'), settings.working_hours],
          ].map(([icon, label, value], i) => (
            <div className="col-md-6" key={i}>
              <div className="card h-100"><div className="card-body d-flex gap-3">
                <i className={`bi ${icon} fs-3 text-primary`}></i>
                <div>
                  <h6 className="fw-bold mb-1">{label}</h6>
                  <p className="small text-muted mb-0">{value}</p>
                </div>
              </div></div>
            </div>
          ))}
        </div>
        <div className="alert alert-info mt-4"><i className="bi bi-lightbulb me-1"></i>{t('contact_hint')}</div>
      </div></div>
    </section>
  )
}

export function Faq() {
  const { t } = useApp()
  const [open, setOpen] = useState(0)
  const faqs = [1, 2, 3, 4, 5, 6].map((n) => [t(`faq${n}_q`), t(`faq${n}_a`)])
  return (
    <section className="container py-5">
      <div className="row justify-content-center"><div className="col-lg-8">
        <h1 className="fw-bold mb-4">{t('faq_title')}</h1>
        <div className="accordion" id="faqPage">
          {faqs.map(([q, a], i) => (
            <div className="accordion-item" key={i}>
              <h2 className="accordion-header">
                <button className={`accordion-button ${open !== i ? 'collapsed' : ''}`} type="button"
                        onClick={() => setOpen(open === i ? -1 : i)}>
                  {q}
                </button>
              </h2>
              <div className={`accordion-collapse collapse ${open === i ? 'show' : ''}`}>
                <div className="accordion-body text-muted">{a}</div>
              </div>
            </div>
          ))}
        </div>
      </div></div>
    </section>
  )
}

export function Legal({ pageName }) {
  const { t, pick } = useApp()
  const [page, setPage] = useState(null)
  useEffect(() => {
    setPage(null)
    apiGet(`/api/pages/${pageName}`).then(setPage).catch(() => setPage({}))
  }, [pageName])
  if (!page) return <Loading />
  const title = page.body_en !== undefined ? pick(page.title_en, page.title_hi) : ''
  const body = pick(page.body_en, page.body_hi)
  return (
    <section className="container py-5">
      <div className="row justify-content-center"><div className="col-lg-8">
        <h1 className="fw-bold mb-3">{title}</h1>
        {body
          ? <div className="text-muted pre-wrap">{body}</div>
          : <div className="text-muted">{t('legal_empty')}</div>}
      </div></div>
    </section>
  )
}

export function NotFound() {
  const { t } = useApp()
  return (
    <section className="container py-5 text-center">
      <div className="display-4 text-primary mb-2"><i className="bi bi-emoji-frown"></i></div>
      <h1 className="h4 fw-bold">{t('not_found')}</h1>
      <p className="text-muted">{t('not_found_hint')}</p>
    </section>
  )
}
