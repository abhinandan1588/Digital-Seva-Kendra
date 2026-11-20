import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { apiGet } from '../api.js'
import { useApp } from '../context.jsx'
import ServiceCard from '../components/ServiceCard.jsx'
import { useFlash } from '../components/useFlash.jsx'
import { Loading } from '../components/Bits.jsx'

export default function Services() {
  const { t, pick, refreshCartCount } = useApp()
  const [searchParams, setSearchParams] = useSearchParams()
  const q = searchParams.get('q') || ''
  const category = searchParams.get('category') || ''
  const [data, setData] = useState(null)
  const [searchText, setSearchText] = useState(q)
  const [flash, flashMsg] = useFlash()

  useEffect(() => { setSearchText(q) }, [q])

  useEffect(() => {
    setData(null)
    const params = new URLSearchParams()
    if (q) params.set('q', q)
    if (category) params.set('category', category)
    apiGet(`/api/services?${params.toString()}`).then(setData).catch(() => setData({ services: [], categories: [] }))
  }, [q, category])

  const submitSearch = (e) => {
    e.preventDefault()
    const params = {}
    if (searchText.trim()) params.q = searchText.trim()
    if (category) params.category = category
    setSearchParams(params)
  }

  const setCategory = (slug) => {
    const params = {}
    if (q) params.q = q
    if (slug) params.category = slug
    setSearchParams(params)
  }

  return (
    <section className="container py-5">
      {flash}
      <h1 className="h3 fw-bold mb-4">{t('services_title')}</h1>

      <form className="d-flex gap-2 mb-3" onSubmit={submitSearch} role="search">
        <div className="input-group">
          <span className="input-group-text bg-white"><i className="bi bi-search"></i></span>
          <input className="form-control" type="search" value={searchText}
                 placeholder={t('search_placeholder')}
                 onChange={(e) => setSearchText(e.target.value)} />
          <button className="btn btn-primary" type="submit">{t('search_btn')}</button>
        </div>
      </form>

      <div className="d-flex flex-wrap gap-2 mb-4">
        <button className={`btn btn-sm ${!category ? 'btn-primary' : 'btn-outline-primary'}`}
                onClick={() => setCategory('')}>{t('all_categories')}</button>
        {(data?.categories || []).map((c) => (
          <button key={c.id}
                  className={`btn btn-sm ${category === c.slug ? 'btn-primary' : 'btn-outline-primary'}`}
                  onClick={() => setCategory(c.slug)}>
            <i className={`bi ${c.icon} me-1`}></i>{pick(c.name_en, c.name_hi)}
          </button>
        ))}
      </div>

      {data === null ? <Loading /> : data.services.length === 0 ? (
        <div className="text-center text-muted py-5">{t('no_services')}</div>
      ) : (
        <div className="row g-4">
          {data.services.map((s) => (
            <div className="col-12 col-md-6 col-lg-3" key={s.id}>
              <ServiceCard service={s} onAdded={() => { refreshCartCount(); flashMsg(t('added')) }} />
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
