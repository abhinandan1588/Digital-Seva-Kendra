import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { apiGet, apiPost } from '../api.js'
import { useApp } from '../context.jsx'
import { FIELD_ERRORS } from '../i18n.js'
import { Loading, ErrorAlert, OkAlert, StickyActionBar, useOffscreen } from '../components/Bits.jsx'

const FILE_TYPES = ['file', 'file_multi', 'image']
const TEXT_TYPES = { text: 'text', number: 'number', email: 'email', mobile: 'tel', date: 'date' }

/** Fields asking for the applicant's own name/mobile/email/address are
 *  answered once by the common details. Match by admin field_key AND by
 *  label ("Applicant Name", "Mobile number", "Candidate Name"…) — never by
 *  relation/business names. */
const NOT_PERSONAL_RE = /(father|mother|spouse|husband|wife|guardian|nominee|business|shop|company|firm|organisation|organization|institute|institution|school|college|authority|department)/i
const COMMON_FIELD_KEYS = {
  name: ['full_name', 'name', 'applicant_name', 'candidate_name', 'customer_name', 'your_name'],
  mobile: ['mobile', 'phone', 'mobile_number', 'phone_number', 'contact_number'],
  email: ['email', 'email_id', 'e_mail'],
  address: ['address', 'full_address'],
}
const COMMON_FIELD_PATTERNS = [
  ['name', /^(applicant|candidate|customer|full|your|owner)?\s?s? ?name$/],
  ['mobile', /^(mobile|phone|contact)( ?(number|no?\.?))?$/],
  ['email', /^(e ?mail|email)( ?(id|address))?$/],
  ['address', /^(full )?address$/],
]
const COVERED_FIELD_TYPES = ['text', 'number', 'email', 'mobile', 'textarea']

function normLabel(s) {
  return String(s || '').toLowerCase().replace(/[^a-z0-9\u0900-\u097f]+/g, ' ').trim()
}

/** Which common detail ('name'|'mobile'|'email'|'address') this field asks
 *  for, or null when it is service-specific. */
function profileKindFor(f) {
  if (!COVERED_FIELD_TYPES.includes(f.field_type)) return null
  const key = String(f.field_key || '').toLowerCase().trim()
  const label = normLabel(f.label_en).split(/ +/).filter((w) => w !== 's').join(' ')
  for (const [kind, re] of COMMON_FIELD_PATTERNS) {
    if (!COMMON_FIELD_KEYS[kind].includes(key) && !(label && re.test(label))) continue
    if (NOT_PERSONAL_RE.test(key) || NOT_PERSONAL_RE.test(f.label_en || '')) return null
    return kind
  }
  return null
}

/** Identity used to deduplicate the same question across services: same
 *  type + same label (choice fields must also offer the same options). */
function fieldGroupKey(f) {
  const base = `${f.field_type}|${normLabel(f.label_en)}`
  if (['select', 'radio', 'checkbox'].includes(f.field_type)) {
    return `${base}|${JSON.stringify(f.options || [])}`
  }
  return base
}

function docGroupKey(r) {
  return normLabel(r.label_en)
}

/** The set of details needed by the whole list: one group per unique
 *  question. A group stores every service entry that asks it, so one
 *  answer can be submitted to each service on save. */
function mergeFieldGroups(items) {
  const groups = []
  const byKey = new Map()
  for (const item of items || []) {
    for (const f of item.form_fields) {
      const gk = fieldGroupKey(f)
      let g = byKey.get(gk)
      if (!g) {
        g = {
          key: `fg${groups.length}`,
          field_type: f.field_type,
          label_en: f.label_en, label_hi: f.label_hi,
          help_text_en: f.help_text_en, help_text_hi: f.help_text_hi,
          placeholder: f.placeholder,
          options: f.options || [],
          allowed_extensions: [...(f.allowed_extensions || [])],
          max_file_mb: f.max_file_mb,
          is_required: false,
          entries: [],
          prefills: [],
          prefill_wallet_ids: [],
        }
        byKey.set(gk, g)
        groups.push(g)
      }
      g.entries.push({ itemKey: item.key, field: f })
      g.is_required = g.is_required || !!f.is_required
      if (f.prefill != null && f.prefill !== '') g.prefills.push(f.prefill)
      if (f.prefill_wallet_id) g.prefill_wallet_ids.push(f.prefill_wallet_id)
      for (const e of (f.allowed_extensions || [])) {
        if (!g.allowed_extensions.includes(e)) g.allowed_extensions.push(e)
      }
      if (f.max_file_mb) g.max_file_mb = Math.min(g.max_file_mb ?? f.max_file_mb, f.max_file_mb)
    }
  }
  // a group is auto-answered from the common details only when every
  // service entry maps it to the same profile field
  for (const g of groups) {
    const kinds = [...new Set(g.entries.map((en) => profileKindFor(en.field)))]
    g.profile_kind = kinds.length === 1 && kinds[0] ? kinds[0] : null
  }
  return groups
}

/** The set of documents needed by the whole list: one group per unique
 *  requirement label. The strictest rules win (required, min size). */
function mergeDocGroups(items) {
  const groups = []
  const byKey = new Map()
  for (const item of items || []) {
    for (const r of item.document_requirements) {
      const gk = docGroupKey(r)
      let g = byKey.get(gk)
      if (!g) {
        g = {
          key: `dg${groups.length}`,
          label_en: r.label_en, label_hi: r.label_hi,
          description_en: r.description_en, description_hi: r.description_hi,
          allowed_extensions: [...(r.allowed_extensions || [])],
          allow_multiple: false,
          max_file_mb: r.max_file_mb,
          is_required: false,
          entries: [],
          prefill_wallet_ids: [],
        }
        byKey.set(gk, g)
        groups.push(g)
      }
      g.entries.push({ itemKey: item.key, req: r })
      g.is_required = g.is_required || !!r.is_required
      g.allow_multiple = g.allow_multiple || !!r.allow_multiple
      if (r.prefill_wallet_id) g.prefill_wallet_ids.push(r.prefill_wallet_id)
      for (const e of (r.allowed_extensions || [])) {
        if (!g.allowed_extensions.includes(e)) g.allowed_extensions.push(e)
      }
      if (r.max_file_mb) g.max_file_mb = Math.min(g.max_file_mb ?? r.max_file_mb, r.max_file_mb)
    }
  }
  return groups
}

function fileAccept(extensions) {
  return (extensions || []).map((e) => `.${String(e).toLowerCase().replace('.', '')}`).join(',')
}

function errText(code, lang, t) {
  const table = FIELD_ERRORS[lang] || FIELD_ERRORS.en
  return table[code] || FIELD_ERRORS.en[code] || t('err_generic')
}

function extOf(entry) {
  return String(entry.ext || (entry.original_name || '').split('.').pop() || '').toLowerCase()
}

/** Local suggestion: compatible wallet entry, filename-token match first.
 *  Mirrors the server-side suggest_wallet_entry ranking. `matched` tells the
 *  caller whether the label actually matched the filename — optional rows
 *  should only be auto-covered on a real match. */
function suggestEntry(entries, label, allowed, isImage) {
  let compat = entries.filter((e) => (allowed || []).map((a) => a.toLowerCase()).includes(extOf(e)))
  if (isImage) compat = compat.filter((e) => ['jpg', 'jpeg', 'png', 'webp'].includes(extOf(e)))
  if (!compat.length) return null
  const tokens = (label || '').toLowerCase().split(/[^a-z0-9\u0900-\u097f]+/).filter((x) => x.length >= 3)
  for (const entry of compat) {
    const etoks = (entry.original_name || '').toLowerCase().split(/[^a-z0-9\u0900-\u097f]+/).filter((x) => x.length >= 3)
    const overlap = etoks.some((b) => tokens.some((a) => a === b ||
      (Math.min(a.length, b.length) >= 4 && (a.startsWith(b) || b.startsWith(a)))))
    if (overlap) return { entry, matched: true }
  }
  return { entry: compat[0], matched: false }
}

/** Unified application form: ONE merged form for every service in the list.
 *  The complete set of required details and documents is deduplicated
 *  across services — each question/document is asked once and submitted to
 *  every service that needs it. Server-side validation unchanged (same
 *  per-item endpoints, wallet:<id> references). */
export default function ApplyAll() {
  const { t, pick, lang } = useApp()
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [loadError, setLoadError] = useState('')
  const [profile, setProfile] = useState({ name: '', mobile: '', email: '', address: '' })
  const [answers, setAnswers] = useState({})        // group key -> string | array
  const [wallet, setWallet] = useState([])           // saved documents
  const [newWalletFiles, setNewWalletFiles] = useState([]) // picked, saved on "Save all"
  const [reqMode, setReqMode] = useState({})         // doc group key -> 'wallet'|'file'
  const [reqWallet, setReqWallet] = useState({})     // doc group key -> wallet id
  const [fieldMode, setFieldMode] = useState({})     // file group key -> 'wallet'|'file'
  const [fieldWallet, setFieldWallet] = useState({}) // file group key -> wallet id
  const [fileInputs, setFileInputs] = useState({})   // group key -> File|File[]
  const [expandedRows, setExpandedRows] = useState({}) // doc rows the user opened
  const [errors, setErrors] = useState({})
  const [topError, setTopError] = useState('')
  const [notice, setNotice] = useState('')
  const [saving, setSaving] = useState(false)
  const saveBtnRef = useRef(null)
  // the in-flow save button sits at the page bottom; the fixed bar takes
  // over whenever it is scrolled out of view
  const saveOffscreen = useOffscreen(saveBtnRef, data)

  const fieldGroups = useMemo(() => mergeFieldGroups(data?.items), [data])
  const docGroups = useMemo(() => mergeDocGroups(data?.items), [data])

  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        const overview = await apiGet('/api/apply/overview')
        if (!alive) return
        setData(overview)
        setWallet(overview.common.wallet || [])
        setProfile({ name: '', mobile: '', email: '', address: '', ...(overview.common.profile || {}) })
        const saved = overview.common.wallet || []
        const prefills = {}
        const fm = {}; const fw = {}; const rm = {}; const rw = {}
        // best wallet doc for a group: server prefill, else local match —
        // required groups accept the best compatible file, optional groups
        // only a real filename match (server prefills pass the same gate)
        const pickWallet = (prefillIds, label, allowed, isRequired, isImage) => {
          const s = suggestEntry(saved, label, allowed, isImage)
          if (!s || (!s.matched && !isRequired)) return null
          return prefillIds.length ? prefillIds[0] : s.entry.id
        }
        for (const g of mergeFieldGroups(overview.items)) {
          if (FILE_TYPES.includes(g.field_type)) {
            const sug = pickWallet(g.prefill_wallet_ids, g.label_en, g.allowed_extensions,
                                   g.is_required, g.field_type === 'image')
            if (sug) { fm[g.key] = 'wallet'; fw[g.key] = sug } else fm[g.key] = 'file'
          } else if (g.prefills.length) {
            prefills[g.key] = g.prefills[0]
          }
        }
        for (const g of mergeDocGroups(overview.items)) {
          const sug = pickWallet(g.prefill_wallet_ids, g.label_en, g.allowed_extensions,
                                 g.is_required, false)
          if (sug) { rm[g.key] = 'wallet'; rw[g.key] = sug } else rm[g.key] = 'file'
        }
        setAnswers(prefills)
        setReqMode(rm); setReqWallet(rw); setFieldMode(fm); setFieldWallet(fw)
      } catch (e) {
        if (alive) setLoadError(e.code || 'err_generic')
      }
    })()
    return () => { alive = false }
  }, [])

  if (loadError) {
    return (
      <section className="container py-5">
        <ErrorAlert>{t('err_' + loadError) || t('err_generic')}</ErrorAlert>
        <Link to="/cart" className="btn btn-outline-secondary">{t('cart_title')}</Link>
      </section>
    )
  }
  if (!data) return <Loading />

  const items = data.items || []
  const setAnswer = (key, value) => setAnswers((s) => ({ ...s, [key]: value }))
  // files picked in the common section but not saved yet — they cover doc
  // rows visually and are assigned for real right after the "Save all" upload
  const pendingEntries = newWalletFiles.map((f, i) => ({
    id: `pending:${i}`, original_name: f.name,
    ext: f.name.split('.').pop(), size_bytes: f.size,
  }))
  const profileValue = (kind) => (profile[kind] || '').trim()

  // which merged questions are shown: everything not answered by the common
  // details. name/mobile are always collected there; email/address only
  // stay hidden while they are optional or already provided
  const visibleFieldGroups = fieldGroups.filter((g) => {
    if (!g.profile_kind) return true
    if (g.profile_kind === 'name' || g.profile_kind === 'mobile') return false
    if (profileValue(g.profile_kind)) return false
    return g.is_required
  })

  // answer submitted for a merged question: the common detail when the
  // group asks for it, otherwise what the user typed here
  const valueForGroup = (g) => {
    if (g.profile_kind) {
      const v = profileValue(g.profile_kind)
      if (v) return v
    }
    return answers[g.key] ?? ''
  }

  // entry (service field / requirement) -> group, for save + error mapping
  const fieldGroupObj = {}
  for (const g of fieldGroups) for (const en of g.entries) fieldGroupObj[`${en.itemKey}:${en.field.field_key}`] = g
  const docGroupObj = {}
  for (const g of docGroups) for (const en of g.entries) docGroupObj[`${en.itemKey}:${en.req.id}`] = g

  const compatible = (allowed, isImage) => wallet.filter((entry) => {
    let list = (allowed || []).map((e) => e.toLowerCase())
    if (isImage) list = list.filter((e) => ['jpg', 'jpeg', 'png', 'webp'].includes(e))
    return list.includes(extOf(entry))
  })

  const removeWalletEntry = async (id) => {
    const res = await apiPost('/api/wallet/remove', { id }).catch(() => null)
    if (res) {
      setWallet(res.wallet || [])
      setNotice(t('wallet_removed'))
    }
  }

  const walletName = (id) => wallet.find((e) => String(e.id) === String(id))?.original_name
    || pendingEntries.find((e) => String(e.id) === String(id))?.original_name

  /** Which common/wallet document covers a group, if any. Optional groups
   *  are only covered on a real filename match; required groups accept the
   *  best compatible document. */
  const coverFor = (modeMap, walletMap, key, label, allowed, isImage, isRequired) => {
    if ((modeMap[key] || 'file') === 'wallet') {
      const name = walletName(walletMap[key])
      if (name) return { name, pending: String(walletMap[key]).startsWith('pending:') }
      return null
    }
    const s = suggestEntry([...wallet, ...pendingEntries], label, allowed, isImage)
    if (!s || (!s.matched && !isRequired)) return null
    return { name: s.entry.original_name, pending: String(s.entry.id).startsWith('pending:') }
  }

  const expandRow = (key) => setExpandedRows((s) => ({ ...s, [key]: true }))
  const collapseRow = (key) => setExpandedRows((s) => {
    const next = { ...s }; delete next[key]; return next
  })

  const save = async () => {
    setSaving(true); setErrors({}); setTopError(''); setNotice('')
    try {
      // Remember what the UI suggested for each untouched group, so the file
      // shown pre-save is exactly the one assigned after upload.
      const entriesNow = [...wallet, ...pendingEntries]
      const preSuggest = {}
      const recordPre = (modeMap, g, isImage) => {
        if ((modeMap[g.key] || 'file') !== 'file') return
        if (fileInputs[g.key]?.length) return
        const s = suggestEntry(entriesNow, g.label_en, g.allowed_extensions, isImage)
        if (s && (s.matched || g.is_required)) preSuggest[g.key] = s.entry
      }
      for (const g of docGroups) recordPre(reqMode, g, false)
      for (const g of fieldGroups) {
        if (FILE_TYPES.includes(g.field_type)) recordPre(fieldMode, g, g.field_type === 'image')
      }

      // 1) common details + new wallet files (one call). Text answers are
      //    also remembered under the services' own field keys.
      const commonFd = new FormData()
      commonFd.append('name', profile.name || '')
      commonFd.append('mobile', profile.mobile || '')
      commonFd.append('email', profile.email || '')
      commonFd.append('address', profile.address || '')
      for (const g of fieldGroups) {
        if (FILE_TYPES.includes(g.field_type) || g.field_type === 'checkbox') continue
        const v = valueForGroup(g)
        if (v === null || v === undefined || v === '') continue
        const fk = g.entries[0].field.field_key
        commonFd.append(`answer_${fk}`, v)
      }
      for (const f of newWalletFiles) commonFd.append('wallet_files', f)
      const common = await apiPost('/api/apply/common', commonFd)
      if (common.errors) {
        const mapped = {}
        for (const [field, code] of Object.entries(common.errors)) mapped[`profile:${field}`] = code
        setErrors(mapped); setSaving(false)
        window.scrollTo({ top: 0, behavior: 'smooth' })
        return
      }
      setWallet(common.wallet || [])
      setNewWalletFiles([])

      // Just-saved wallet documents fill any group the user has not
      // explicitly handled — common docs stay one-time work. The file the
      // UI showed pre-save wins over a fresh guess.
      const w = common.wallet || []
      const nextReqMode = { ...reqMode }
      const nextReqWallet = { ...reqWallet }
      const nextFieldMode = { ...fieldMode }
      const nextFieldWallet = { ...fieldWallet }
      const assignGroup = (modeMap, walletMap, g, isImage) => {
        if ((modeMap[g.key] || 'file') !== 'file') return
        if (fileInputs[g.key]?.length) return
        const pre = preSuggest[g.key]
        let sug = pre ? w.find((e) => e.original_name === pre.original_name)?.id : null
        if (!sug) {
          const s = suggestEntry(w, g.label_en, g.allowed_extensions, isImage)
          if (s && (s.matched || g.is_required)) sug = s.entry.id
        }
        if (sug) { modeMap[g.key] = 'wallet'; walletMap[g.key] = sug }
      }
      for (const g of docGroups) assignGroup(nextReqMode, nextReqWallet, g, false)
      for (const g of fieldGroups) {
        if (FILE_TYPES.includes(g.field_type)) assignGroup(nextFieldMode, nextFieldWallet, g, g.field_type === 'image')
      }
      setReqMode(nextReqMode); setReqWallet(nextReqWallet)
      setFieldMode(nextFieldMode); setFieldWallet(nextFieldWallet)

      // per-service forms: the same merged answer/document goes to every
      // service that asks for it (server validates each application)
      const itemErrors = {}
      const mapItemError = (itemKey, k, v) => {
        const colon = k.indexOf(':')
        const kind = colon > -1 ? k.slice(0, colon) : ''
        const rest = colon > -1 ? k.slice(colon + 1) : k
        const gk = kind === 'field' ? fieldGroupObj[`${itemKey}:${rest}`]?.key
          : kind === 'req' ? docGroupObj[`${itemKey}:${rest}`]?.key : null
        itemErrors[gk || `_top:${itemKey}`] = v
      }
      for (const item of items) {
        const fd = new FormData()
        for (const f of item.form_fields) {
          const g = fieldGroupObj[`${item.key}:${f.field_key}`]
          if (!g) continue
          if (FILE_TYPES.includes(g.field_type)) {
            const mode = nextFieldMode[g.key] || 'file'
            if (mode === 'wallet') {
              const wid = nextFieldWallet[g.key]
              if (wid) fd.append(f.field_key, `wallet:${wid}`)
            } else {
              for (const x of (fileInputs[g.key] || [])) {
                fd.append(`file_${f.field_key}`, x)
              }
            }
          } else if (g.field_type === 'checkbox') {
            for (const v of (answers[g.key] || [])) fd.append(f.field_key, v)
          } else {
            fd.append(f.field_key, valueForGroup(g) ?? '')
          }
        }
        for (const r of item.document_requirements) {
          const g = docGroupObj[`${item.key}:${r.id}`]
          if (!g) continue
          const mode = nextReqMode[g.key] || 'file'
          if (mode === 'wallet') {
            const wid = nextReqWallet[g.key]
            if (wid) fd.append(`req_${r.id}`, `wallet:${wid}`)
          } else {
            for (const x of (fileInputs[g.key] || [])) {
              fd.append(`req_${r.id}`, x)
            }
          }
        }
        try {
          await apiPost(`/api/cart/${item.key}/form`, fd)
        } catch (e) {
          if (e.status === 422 && e.data?.errors) {
            for (const [k, v] of Object.entries(e.data.errors)) mapItemError(item.key, k, v)
          } else {
            itemErrors[`_top:${item.key}`] = e.code || 'err_generic'
          }
        }
      }
      if (Object.keys(itemErrors).length) {
        setErrors(itemErrors)
        setSaving(false)
        window.scrollTo({ top: 0, behavior: 'smooth' })
        return
      }
      navigate('/cart')
    } catch (e) {
      setTopError(e.code || 'err_generic')
      setSaving(false)
      window.scrollTo({ top: 0, behavior: 'smooth' })
    }
  }

  // ---- building blocks -----------------------------------------------------

  const profileField = (name, labelKey, attrs = {}) => (
    <div className="mb-3" key={name}>
      <label className="form-label fw-semibold" htmlFor={`cm-${name}`}>
        {t(labelKey)}
        {attrs.required && <span className="text-danger"> *</span>}
      </label>
      {name === 'address' ? (
        <textarea className="form-control" id={`cm-${name}`} rows={2}
                  value={profile[name]} onChange={(e) => setProfile((s) => ({ ...s, [name]: e.target.value }))} />
      ) : (
        <input className="form-control" id={`cm-${name}`} type={attrs.type || 'text'}
               inputMode={attrs.inputMode} value={profile[name]}
               onChange={(e) => setProfile((s) => ({ ...s, [name]: e.target.value }))} />
      )}
      {errors[`profile:${name}`] && (
        <div className="small text-danger mt-1">
          <i className="bi bi-exclamation-circle me-1"></i>
          {t('err_' + errors[`profile:${name}`]) || t('err_generic')}
        </div>
      )}
    </div>
  )

  const sharedNote = (g) => g.entries.length > 1 && (
    <div className="form-text mb-2">
      <i className="bi bi-collection me-1" aria-hidden="true"></i>
      {t('shared_note').replace('{n}', g.entries.length)}
    </div>
  )

  const fieldControl = (g) => {
    const err = errors[g.key]
    const errNode = err && (
      <div className="small text-danger mt-1">
        <i className="bi bi-exclamation-circle me-1"></i>{errText(err, lang, t)}
      </div>
    )
    const label = pick(g.label_en, g.label_hi)
    const help = pick(g.help_text_en, g.help_text_hi)

    if (FILE_TYPES.includes(g.field_type)) {
      const mode = fieldMode[g.key] || 'file'
      const options = compatible(g.allowed_extensions, g.field_type === 'image')
      const cover = coverFor(fieldMode, fieldWallet, g.key, g.label_en,
                             g.allowed_extensions, g.field_type === 'image', g.is_required)
      const expanded = !!expandedRows[g.key]
      const picker = (
        <>
          {options.length > 0 && (
            <div className="form-check">
              <input className="form-check-input" type="radio" id={`fm-${g.key}-w`}
                     checked={mode === 'wallet'} onChange={() => setFieldMode((s) => ({ ...s, [g.key]: 'wallet' }))} />
              <label className="form-check-label" htmlFor={`fm-${g.key}-w`}>
                {t('use_wallet')}
              </label>
              {mode === 'wallet' && (
                <select className="form-select form-select-sm mt-1"
                        value={fieldWallet[g.key] || ''}
                        onChange={(e) => setFieldWallet((s) => ({ ...s, [g.key]: e.target.value }))}>
                  <option value="" disabled>—</option>
                  {options.map((entry) => (
                    <option key={entry.id} value={entry.id}>{entry.original_name}</option>
                  ))}
                </select>
              )}
            </div>
          )}
          <div className="form-check">
            <input className="form-check-input" type="radio" id={`fm-${g.key}-f`}
                   checked={mode === 'file'} onChange={() => setFieldMode((s) => ({ ...s, [g.key]: 'file' }))} />
            <label className="form-check-label" htmlFor={`fm-${g.key}-f`}>{t('upload_new')}</label>
          </div>
          {mode === 'file' && (
            <input type="file" className="form-control form-control-sm mt-1"
                   accept={fileAccept(g.allowed_extensions)}
                   multiple={g.field_type === 'file_multi'}
                   onChange={(e) => setFileInputs((s) => ({ ...s, [g.key]: [...(e.target.files || [])] }))} />
          )}
          <div className="form-text">
            {t('ext_hint')}: {g.allowed_extensions?.join(', ') || 'pdf, jpg, png'} · {t('max_size')}: {g.max_file_mb} MB
          </div>
          {cover && expanded && (
            <button type="button" className="btn btn-sm btn-link p-0"
                    onClick={() => collapseRow(g.key)}>{t('hide_options')}</button>
          )}
          {errNode}
          {help && <div className="form-text">{help}</div>}
        </>
      )
      return (
        <div className="mb-3 p-3 border rounded bg-white" key={g.key}>
          <div className="fw-semibold mb-2">
            <i className="bi bi-paperclip me-1" aria-hidden="true"></i>{label}
            {g.is_required && <span className="text-danger"> *</span>}
          </div>
          {sharedNote(g)}
          {cover && !expanded ? (
            <>
              <div className="covered-row">
                <i className="bi bi-check-circle-fill text-success" aria-hidden="true"></i>
                <span className="flex-grow-1">
                  {t('covered_doc')}: <strong>{cover.name}</strong>
                  {cover.pending && <span className="text-muted"> · {t('pending_note')}</span>}
                </span>
                <button type="button" className="btn btn-sm btn-link p-0"
                        onClick={() => expandRow(g.key)}>{t('change_doc')}</button>
              </div>
              {errNode}
            </>
          ) : picker}
        </div>
      )
    }

    const value = answers[g.key] ?? ''
    if (g.field_type === 'textarea') {
      return (
        <div className="mb-3" key={g.key}>
          <label className="form-label fw-semibold">{label}{g.is_required && <span className="text-danger"> *</span>}</label>
          {sharedNote(g)}
          <textarea className="form-control" rows={3} value={value}
                    onChange={(e) => setAnswer(g.key, e.target.value)} />
          {help && <div className="form-text">{help}</div>}
          {errNode}
        </div>
      )
    }
    if (g.field_type === 'select') {
      return (
        <div className="mb-3" key={g.key}>
          <label className="form-label fw-semibold">{label}{g.is_required && <span className="text-danger"> *</span>}</label>
          {sharedNote(g)}
          <select className="form-select" value={value}
                  onChange={(e) => setAnswer(g.key, e.target.value)}>
            <option value="">—</option>
            {(g.options || []).map((opt, i) => {
              const v = typeof opt === 'string' ? opt : pick(opt.en || '', opt.hi || '')
              return <option key={i} value={v}>{v}</option>
            })}
          </select>
          {help && <div className="form-text">{help}</div>}
          {errNode}
        </div>
      )
    }
    if (g.field_type === 'radio') {
      return (
        <div className="mb-3" key={g.key}>
          <div className="fw-semibold">{label}{g.is_required && <span className="text-danger"> *</span>}</div>
          {sharedNote(g)}
          {(g.options || []).map((opt, i) => {
            const v = typeof opt === 'string' ? opt : pick(opt.en || '', opt.hi || '')
            return (
              <div className="form-check" key={i}>
                <input className="form-check-input" type="radio" id={`fld-${g.key}-${i}`}
                       checked={value === v} onChange={() => setAnswer(g.key, v)} />
                <label className="form-check-label" htmlFor={`fld-${g.key}-${i}`}>{v}</label>
              </div>
            )
          })}
          {errNode}
        </div>
      )
    }
    if (g.field_type === 'checkbox') {
      const selected = Array.isArray(value) ? value : []
      return (
        <div className="mb-3" key={g.key}>
          <div className="fw-semibold">{label}{g.is_required && <span className="text-danger"> *</span>}</div>
          {sharedNote(g)}
          {(g.options || []).map((opt, i) => {
            const v = typeof opt === 'string' ? opt : pick(opt.en || '', opt.hi || '')
            return (
              <div className="form-check" key={i}>
                <input className="form-check-input" type="checkbox" id={`fld-${g.key}-${i}`}
                       checked={selected.includes(v)}
                       onChange={(e) => setAnswer(g.key, e.target.checked
                         ? [...selected, v] : selected.filter((x) => x !== v))} />
                <label className="form-check-label" htmlFor={`fld-${g.key}-${i}`}>{v}</label>
              </div>
            )
          })}
          {errNode}
        </div>
      )
    }
    return (
      <div className="mb-3" key={g.key}>
        <label className="form-label fw-semibold">{label}{g.is_required && <span className="text-danger"> *</span>}</label>
        {sharedNote(g)}
        <input className="form-control" type={TEXT_TYPES[g.field_type] || 'text'}
               placeholder={g.placeholder || undefined} value={value}
               onChange={(e) => setAnswer(g.key, e.target.value)} />
        {help && <div className="form-text">{help}</div>}
        {errNode}
      </div>
    )
  }

  const requirementBlock = (g) => {
    const mode = reqMode[g.key] || 'file'
    const options = compatible(g.allowed_extensions, false)
    const err = errors[g.key]
    const errNode = err && (
      <div className="small text-danger mt-1">
        <i className="bi bi-exclamation-circle me-1"></i>{errText(err, lang, t)}
      </div>
    )
    const cover = coverFor(reqMode, reqWallet, g.key, g.label_en,
                           g.allowed_extensions, false, g.is_required)
    const expanded = !!expandedRows[g.key]
    const picker = (
      <>
        {options.length > 0 && (
          <div className="form-check">
            <input className="form-check-input" type="radio" id={`rm-${g.key}-w`}
                   checked={mode === 'wallet'} onChange={() => setReqMode((s) => ({ ...s, [g.key]: 'wallet' }))} />
            <label className="form-check-label" htmlFor={`rm-${g.key}-w`}>
              {t('use_wallet')} <span className="badge bg-success-subtle text-success-emphasis">{t('from_wallet')}</span>
            </label>
            {mode === 'wallet' && (
              <select className="form-select form-select-sm mt-1"
                      value={reqWallet[g.key] || ''}
                      onChange={(e) => setReqWallet((s) => ({ ...s, [g.key]: e.target.value }))}>
                <option value="" disabled>—</option>
                {options.map((entry) => (
                  <option key={entry.id} value={entry.id}>{entry.original_name}</option>
                ))}
              </select>
            )}
          </div>
        )}
        <div className="form-check">
          <input className="form-check-input" type="radio" id={`rm-${g.key}-f`}
                 checked={mode === 'file'} onChange={() => setReqMode((s) => ({ ...s, [g.key]: 'file' }))} />
          <label className="form-check-label" htmlFor={`rm-${g.key}-f`}>{t('upload_new')}</label>
        </div>
        {mode === 'file' && (
          <input type="file" className="form-control form-control-sm mt-1"
                 accept={fileAccept(g.allowed_extensions)} multiple={g.allow_multiple || false}
                 onChange={(e) => setFileInputs((s) => ({ ...s, [g.key]: [...(e.target.files || [])] }))} />
        )}
        <div className="form-text">
          {t('ext_hint')}: {g.allowed_extensions?.join(', ')} · {t('max_size')}: {g.max_file_mb} MB
          {g.allow_multiple ? ` · ${t('each')}` : ''}
        </div>
        {cover && expanded && (
          <button type="button" className="btn btn-sm btn-link p-0"
                  onClick={() => collapseRow(g.key)}>{t('hide_options')}</button>
        )}
        {errNode}
      </>
    )
    return (
      <div className="mb-3 p-3 border rounded bg-white" key={g.key}>
        <div className="fw-semibold mb-1">
          <i className="bi bi-paperclip me-1" aria-hidden="true"></i>
          {pick(g.label_en, g.label_hi)}{g.is_required && <span className="text-danger"> *</span>}
          <span className={`badge ms-2 ${g.is_required ? 'bg-danger-subtle text-danger-emphasis' : 'bg-secondary-subtle text-secondary-emphasis'}`}>
            {g.is_required ? t('required') : t('optional')}
          </span>
        </div>
        {pick(g.description_en, g.description_hi) && (
          <div className="form-text mb-2">{pick(g.description_en, g.description_hi)}</div>
        )}
        {sharedNote(g)}
        {cover && !expanded ? (
          <>
            <div className="covered-row">
              <i className="bi bi-check-circle-fill text-success" aria-hidden="true"></i>
              <span className="flex-grow-1">
                {t('covered_doc')}: <strong>{cover.name}</strong>
                {cover.pending && <span className="text-muted"> · {t('pending_note')}</span>}
              </span>
              <button type="button" className="btn btn-sm btn-link p-0"
                      onClick={() => expandRow(g.key)}>{t('change_doc')}</button>
            </div>
            {errNode}
          </>
        ) : picker}
      </div>
    )
  }

  // ---- page ----------------------------------------------------------------

  return (
    <section className="container py-5">
      <div className="row justify-content-center">
        <div className="col-lg-9">
          <div className="mb-3 small">
            <Link to="/cart" className="text-decoration-none"><i className="bi bi-arrow-left me-1"></i>{t('cart_title')}</Link>
          </div>
          <h1 className="h3 fw-bold">{t('apply_for')}</h1>
          <p className="text-muted">{t('unified_note')}</p>

          <OkAlert>{notice || ''}</OkAlert>
          <ErrorAlert>{topError ? (t('err_' + topError) || t('err_generic')) : ''}</ErrorAlert>

          {/* 1) common details — filled once for every application */}
          <div className="card mb-4" id="common-card">
            <div className="card-body">
              <h5 className="fw-bold mb-1">{t('common_once')}</h5>
              <div className="form-text mb-3">{t('common_once_hint')}</div>
              <div className="row">
                <div className="col-md-6">{profileField('name', 'full_name', { required: true })}</div>
                <div className="col-md-6">{profileField('mobile', 'mobile', { required: true, type: 'tel', inputMode: 'numeric' })}</div>
                <div className="col-md-6">{profileField('email', 'email')}</div>
                <div className="col-md-6">{profileField('address', 'address')}</div>
              </div>
            </div>
          </div>

          {/* 2) document wallet — uploaded once, reused everywhere */}
          <div className="card mb-4">
            <div className="card-body">
              <h5 className="fw-bold mb-1">{t('wallet_once')}</h5>
              <div className="form-text mb-3">{t('wallet_hint')}</div>
              <input type="file" className="form-control" multiple accept={fileAccept(['pdf', 'jpg', 'jpeg', 'png', 'webp'])}
                     onChange={(e) => setNewWalletFiles([...(e.target.files || [])])} />
              {newWalletFiles.length > 0 && (
                <ul className="small mt-2 mb-0 ps-3">
                  {newWalletFiles.map((f, i) => <li key={i}>{f.name}</li>)}
                </ul>
              )}
              <div className="fw-semibold small mt-3 mb-1">{t('wallet_saved')}</div>
              {wallet.length === 0 && <div className="text-muted small">{t('wallet_empty')}</div>}
              <ul className="list-group list-group-flush">
                {wallet.map((entry) => (
                  <li className="list-group-item d-flex justify-content-between align-items-center px-0 bg-transparent" key={entry.id}>
                    <span className="small">
                      <i className="bi bi-file-earmark-check text-success me-1"></i>
                      {entry.original_name}
                      <span className="text-muted ms-2">{Math.max(1, Math.round(entry.size_bytes / 1024))} KB</span>
                    </span>
                    <button type="button" className="btn btn-sm btn-link text-danger p-0"
                            onClick={() => removeWalletEntry(entry.id)}>
                      <i className="bi bi-trash me-1"></i>{t('remove')}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          </div>

          {/* 3) required details — the deduplicated set of questions across
                 every service in the list */}
          <div className="card mb-4">
            <div className="card-body">
              <h5 className="fw-bold mb-1">{t('required_details')}</h5>
              <div className="form-text mb-3">{t('required_details_hint')}</div>
              {visibleFieldGroups.length === 0 ? (
                <div className="covered-row">
                  <i className="bi bi-check-circle-fill text-success" aria-hidden="true"></i>
                  <span>{t('details_all_common')}</span>
                </div>
              ) : visibleFieldGroups.map((g) => fieldControl(g))}
            </div>
          </div>

          {/* 4) required documents — the deduplicated set of uploads */}
          <div className="card mb-4">
            <div className="card-body">
              <h5 className="fw-bold mb-1">{t('required_docs')}</h5>
              <div className="form-text mb-3">{t('required_docs_hint')}</div>
              {docGroups.length === 0 ? (
                <div className="covered-row">
                  <i className="bi bi-check-circle-fill text-success" aria-hidden="true"></i>
                  <span>{t('docs_none')}</span>
                </div>
              ) : docGroups.map((g) => requirementBlock(g))}
            </div>
          </div>

          <button ref={saveBtnRef} className="btn btn-primary btn-lg w-100" onClick={save} disabled={saving}>
            {saving
              ? <><span className="spinner-border spinner-border-sm me-2"></span>{t('saving_all')}</>
              : <><i className="bi bi-save me-1"></i>{t('save_all')}</>}
          </button>
        </div>
      </div>

      {/* long forms: keep "Save all" reachable at all times */}
      <StickyActionBar show={saveOffscreen}>
        <button className="btn btn-primary btn-lg w-100" onClick={save} disabled={saving}>
          {saving
            ? <><span className="spinner-border spinner-border-sm me-2"></span>{t('saving_all')}</>
            : <><i className="bi bi-save me-1"></i>{t('save_all')}</>}
        </button>
      </StickyActionBar>
    </section>
  )
}
