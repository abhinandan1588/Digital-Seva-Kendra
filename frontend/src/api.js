// Small fetch wrapper for the Flask JSON API (see app/api/routes.py).
// Cookies are always sent: the cart, forms and checkout state live in the
// same Flask session used by the server-rendered flow.

async function handle(res) {
  let data = {}
  try { data = await res.json() } catch { /* non-JSON error page */ }
  if (!res.ok) {
    const err = new Error(data.error || `HTTP ${res.status}`)
    err.status = res.status
    err.code = data.error || 'unknown'
    err.data = data
    throw err
  }
  return data
}

export function apiGet(path) {
  return fetch(path, { credentials: 'same-origin', headers: { Accept: 'application/json' } })
    .then(handle)
}

export function apiPost(path, body = null) {
  const opts = { method: 'POST', credentials: 'same-origin' }
  if (body instanceof FormData) {
    opts.body = body
  } else {
    opts.headers = { 'Content-Type': 'application/json', Accept: 'application/json' }
    opts.body = JSON.stringify(body ?? {})
  }
  return fetch(path, opts).then(handle)
}

// --- rupee formatting (amounts arrive as fixed-point strings) ---------------
export function inr(value) {
  const n = parseFloat(value)
  if (Number.isNaN(n)) return '₹0'
  return '₹' + n.toLocaleString('en-IN', { minimumFractionDigits: 0, maximumFractionDigits: 2 })
}

export function fmtDateTime(iso, lang) {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleString(lang === 'hi' ? 'hi-IN' : 'en-IN', {
    day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

// --- remembered orders (tracking credentials shown once; keep locally) -----
const ORDERS_KEY = 'dsk_orders'

export function rememberOrder(entry) {
  const list = savedOrders().filter((o) => o.order_number !== entry.order_number)
  list.unshift(entry)
  localStorage.setItem(ORDERS_KEY, JSON.stringify(list.slice(0, 20)))
}

export function savedOrders() {
  try { return JSON.parse(localStorage.getItem(ORDERS_KEY) || '[]') } catch { return [] }
}

export function findSavedOrder(orderNumber) {
  return savedOrders().find((o) => o.order_number === orderNumber) || null
}
