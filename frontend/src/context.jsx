import { createContext, useContext, useEffect, useMemo, useState, useCallback } from 'react'
import { apiGet, apiPost } from './api.js'
import { STRINGS } from './i18n.js'

const AppCtx = createContext(null)

export function AppProvider({ children }) {
  const [settings, setSettings] = useState({})
  const [categories, setCategories] = useState([])
  const [siteReady, setSiteReady] = useState(false)
  const [cartCount, setCartCount] = useState(0)
  const [lang, setLangState] = useState(() => localStorage.getItem('dsk_lang') || '')

  const effectiveLang = lang || settings.default_language || 'en'

  // Load site settings + categories once; sync the cart badge.
  useEffect(() => {
    apiGet('/api/site')
      .then((d) => {
        setSettings(d.settings || {})
        setCategories(d.categories || [])
        document.title = (d.settings?.shop_name || 'Digital Seva Kendra')
      })
      .catch(() => {})
      .finally(() => setSiteReady(true))
    refreshCartCount()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Keep the Flask session language in sync (option values validate against it).
  useEffect(() => {
    apiPost(`/api/set-lang/${effectiveLang}`).catch(() => {})
  }, [effectiveLang])

  const setLang = useCallback((l) => {
    localStorage.setItem('dsk_lang', l)
    setLangState(l)
  }, [])

  const refreshCartCount = useCallback(() => {
    apiGet('/api/cart')
      .then((d) => setCartCount(d.cart_count || 0))
      .catch(() => setCartCount(0))
  }, [])

  const value = useMemo(() => {
    const t = (key, fallback = '') =>
      STRINGS[effectiveLang]?.[key] ?? STRINGS.en[key] ?? fallback
    const pick = (en, hi) => {
      const e = en || '', h = hi || ''
      return effectiveLang === 'hi' ? (h || e) : (e || h)
    }
    const errText = (code) => {
      if (!code) return t('err_generic')
      if (STRINGS[effectiveLang]?.[`err_${code}`]) return STRINGS[effectiveLang][`err_${code}`]
      if (STRINGS.en[`err_${code}`]) return STRINGS.en[`err_${code}`]
      return t('err_generic')
    }
    return {
      settings, categories, siteReady, lang: effectiveLang, setLang,
      pick, t, errText, cartCount, refreshCartCount,
    }
  }, [settings, categories, siteReady, effectiveLang, cartCount, setLang, refreshCartCount])

  return <AppCtx.Provider value={value}>{children}</AppCtx.Provider>
}

export function useApp() {
  return useContext(AppCtx)
}
