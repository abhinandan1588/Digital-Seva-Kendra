import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiGet } from '../api.js'
import { useApp } from '../context.jsx'
import ServiceCard from '../components/ServiceCard.jsx'
import { useFlash } from '../components/useFlash.jsx'
import { Loading } from '../components/Bits.jsx'

export default function Home() {
  const { t, pick, settings, categories, refreshCartCount } = useApp()
  const [featured, setFeatured] = useState(null)
  const [flash, flashMsg] = useFlash()

  useEffect(() => {
    apiGet('/api/site').then((d) => setFeatured(d.featured_services || [])).catch(() => setFeatured([]))
  }, [])

  const steps = [
    ['bi-grid-3x3-gap', 'how1_t', 'how1_d'],
    ['bi-pencil-square', 'how2_t', 'how2_d'],
    ['bi-qr-code', 'how3_t', 'how3_d'],
    ['bi-search', 'how4_t', 'how4_d'],
  ]

  return (
    <div>
      {flash}
      {/* Hero */}
      <section className="hero-section text-white py-5">
        <div className="container py-4">
          <div className="row align-items-center g-4">
            <div className="col-lg-8">
              <h1 className="display-6 fw-bold">
                {pick(settings.homepage_banner_title, settings.homepage_banner_title_hi)}
              </h1>
              <p className="lead mb-4">
                {pick(settings.homepage_banner_subtitle, settings.homepage_banner_subtitle_hi)}
              </p>
              <div className="d-flex flex-wrap gap-2">
                <Link to="/services" className="btn btn-light btn-lg px-4 fw-semibold">
                  <i className="bi bi-grid-3x3-gap me-1"></i>{t('explore_services')}
                </Link>
                <Link to="/track" className="btn btn-outline-light btn-lg px-4 fw-semibold">
                  <i className="bi bi-search me-1"></i>{t('track_app')}
                </Link>
              </div>
            </div>
            <div className="col-lg-4 text-center hero-icon-wrap">
              <i className="bi bi-phone-fill hero-icon" aria-hidden="true"></i>
            </div>
          </div>
        </div>
      </section>

      {/* Featured services */}
      <section className="container py-5">
        <div className="d-flex justify-content-between align-items-center mb-4">
          <h2 className="h3 fw-bold mb-0">{t('featured')}</h2>
          <Link to="/services" className="text-decoration-none">{t('view_all')} <i className="bi bi-arrow-right"></i></Link>
        </div>
        {featured === null ? <Loading /> : featured.length === 0 ? (
          <div className="text-center text-muted py-4">{t('empty_featured')}</div>
        ) : (
          <div className="row g-4">
            {featured.map((s) => (
              <div className="col-12 col-md-6 col-lg-3" key={s.id}>
                <ServiceCard service={s} onAdded={() => { refreshCartCount(); flashMsg(t('added')) }} />
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Categories */}
      <section className="bg-light py-5">
        <div className="container">
          <h2 className="h3 fw-bold mb-4">{t('popular_categories')}</h2>
          {categories.length === 0 ? (
            <div className="text-center text-muted py-4">{t('empty_featured')}</div>
          ) : (
            <div className="row g-3">
              {categories.map((c) => (
                <div className="col-6 col-md-4 col-lg-3" key={c.id}>
                  <Link to={`/services?category=${encodeURIComponent(c.slug)}`} className="text-decoration-none">
                    <div className="card category-card h-100 text-center p-3">
                      <i className={`bi ${c.icon} category-icon`} aria-hidden="true"></i>
                      <div className="fw-semibold mt-2 text-dark">{pick(c.name_en, c.name_hi)}</div>
                      <div className="small text-muted">{c.service_count} {t('services_count')}</div>
                    </div>
                  </Link>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>

      {/* How it works */}
      <section className="container py-5">
        <h2 className="h3 fw-bold mb-4 text-center">{t('how_title')}</h2>
        <div className="row g-4">
          {steps.map(([icon, titleKey, descKey], i) => (
            <div className="col-6 col-lg-3" key={i}>
              <div className="card how-card h-100 text-center p-3">
                <div className="how-step">{i + 1}</div>
                <i className={`bi ${icon} fs-3 text-primary`} aria-hidden="true"></i>
                <h6 className="fw-bold mt-2">{t(titleKey)}</h6>
                <p className="small text-muted mb-0">{t(descKey)}</p>
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}
