import { Link, NavLink, Outlet } from 'react-router-dom'
import { useApp } from '../context.jsx'

export default function Layout() {
  const { t, pick, settings, lang, setLang, cartCount } = useApp()
  const brand = pick(settings.shop_name, settings.shop_name_hi) || t('brand')
  const year = new Date().getFullYear()

  return (
    <div className="d-flex flex-column min-vh-100">
      <nav className="navbar navbar-expand-lg navbar-dark main-nav sticky-top">
        <div className="container">
          <Link className="navbar-brand fw-bold" to="/">
            <i className="bi bi-hexagon-fill me-2" aria-hidden="true"></i>{brand}
          </Link>
          <div className="d-flex align-items-center order-lg-2 gap-2">
            <button
              className="btn btn-sm btn-outline-light lang-btn"
              onClick={() => setLang(lang === 'hi' ? 'en' : 'hi')}
              title="Language">
              {lang === 'hi' ? 'English' : 'हिंदी'}
            </button>
            <Link to="/cart" className="btn btn-sm btn-light position-relative" title={t('nav_cart')}>
              <i className="bi bi-basket2" aria-hidden="true"></i>
              {cartCount > 0 && (
                <span className="position-absolute top-0 start-100 translate-middle badge rounded-pill bg-danger">
                  {cartCount}
                </span>
              )}
            </Link>
          </div>
          <div className="collapse navbar-collapse order-lg-1" id="nav">
            <ul className="navbar-nav ms-auto mb-2 mb-lg-0">
              {[
                ['/', t('nav_home')], ['/services', t('nav_services')],
                ['/track', t('nav_track')], ['/about', t('nav_about')],
                ['/contact', t('nav_contact')], ['/faq', t('nav_faq')],
              ].map(([to, label]) => (
                <li className="nav-item" key={to}>
                  <NavLink to={to} end={to === '/'} className={({ isActive }) =>
                    'nav-link' + (isActive ? ' active fw-semibold' : '')}>{label}</NavLink>
                </li>
              ))}
              <li className="nav-item">
                <a href="/admin/login" className="nav-link nav-admin">{t('nav_admin')} <i className="bi bi-box-arrow-in-right small"></i></a>
              </li>
            </ul>
          </div>
        </div>
      </nav>

      <main className="flex-grow-1">
        <Outlet />
      </main>

      <footer className="site-footer mt-5">
        <div className="container py-4">
          <div className="row g-4">
            <div className="col-lg-4">
              <div className="fw-bold mb-2">{brand}</div>
              <p className="small text-muted mb-0">
                {pick(settings.footer_text, settings.footer_text_hi)}
              </p>
            </div>
            <div className="col-6 col-lg-2">
              <h6 className="fw-bold">{t('nav_services')}</h6>
              <ul className="list-unstyled small mb-0 footer-links">
                <li><Link to="/services">{t('nav_home')}</Link></li>
                <li><Link to="/track">{t('nav_track')}</Link></li>
                <li><Link to="/faq">{t('nav_faq')}</Link></li>
                <li><Link to="/privacy">{t('privacy_title')}</Link></li>
                <li><Link to="/terms">{t('terms_title')}</Link></li>
              </ul>
            </div>
            <div className="col-lg-3">
              <h6 className="fw-bold">{t('contact_title')}</h6>
              <ul className="list-unstyled small text-muted mb-0">
                <li><i className="bi bi-geo-alt me-1"></i>{settings.shop_address}</li>
                <li><i className="bi bi-telephone me-1"></i>{settings.shop_mobile}</li>
                <li><i className="bi bi-envelope me-1"></i>{settings.shop_email}</li>
                <li><i className="bi bi-clock me-1"></i>{settings.working_hours}</li>
              </ul>
            </div>
            <div className="col-lg-3">
              <h6 className="fw-bold">{t('contact_title')}</h6>
              <div className="d-flex gap-3 fs-5">
                {settings.shop_whatsapp && <a href={`https://wa.me/91${settings.shop_whatsapp}`} target="_blank" rel="noopener" aria-label="WhatsApp"><i className="bi bi-whatsapp"></i></a>}
                {settings.shop_email && <a href={`mailto:${settings.shop_email}`} aria-label="Email"><i className="bi bi-envelope"></i></a>}
                {settings.social_facebook && <a href={settings.social_facebook} target="_blank" rel="noopener" aria-label="Facebook"><i className="bi bi-facebook"></i></a>}
                {settings.social_instagram && <a href={settings.social_instagram} target="_blank" rel="noopener" aria-label="Instagram"><i className="bi bi-instagram"></i></a>}
                {settings.social_youtube && <a href={settings.social_youtube} target="_blank" rel="noopener" aria-label="YouTube"><i className="bi bi-youtube"></i></a>}
              </div>
            </div>
          </div>
          <hr className="mt-4" />
          <div className="d-flex flex-wrap justify-content-between small text-muted">
            <span>© {year} {brand}</span>
            <span><a href="/admin/login" className="text-muted">{t('nav_admin')}</a></span>
          </div>
        </div>
      </footer>
    </div>
  )
}
