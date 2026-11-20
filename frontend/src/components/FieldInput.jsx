import { FIELD_ERRORS } from '../i18n.js'
import { useApp } from '../context.jsx'

const TEXT_TYPES = {
  text: 'text', number: 'number', email: 'email', mobile: 'tel', date: 'date',
}

function fileAccept(extensions) {
  return (extensions || []).map((e) => `.${String(e).toLowerCase().replace('.', '')}`).join(',')
}

function FIELD_ERROR_TEXT(code, lang, t) {
  const table = FIELD_ERRORS[lang] || FIELD_ERRORS.en
  return table[code] || FIELD_ERRORS.en[code] || t('err_generic')
}

/** One dynamic form field (mirrors the Jinja macro in fill_form.html).
 *  Text values POST under the field's key; files under file_<field_key>. */
export function FieldInput({ field, errorKey }) {
  const { pick, t, lang } = useApp()
  const label = pick(field.label_en, field.label_hi)
  const help = pick(field.help_text_en, field.help_text_hi)
  const errCode = errorKey || ''
  const errText = errCode ? FIELD_ERROR_TEXT(errCode, lang, t) : ''
  const common = { name: field.field_key, id: `f-${field.field_key}` }
  const isFile = ['file', 'file_multi', 'image'].includes(field.field_type)
  const inputAttrs = {
    required: field.is_required || false,
    placeholder: field.placeholder || undefined,
    minLength: field.min_length || undefined,
    maxLength: field.max_length || undefined,
    min: field.min_value ?? undefined,
    max: field.max_value ?? undefined,
  }

  let control
  if (field.field_type === 'textarea') {
    control = <textarea className="form-control" rows={3} {...common} {...inputAttrs} />
  } else if (field.field_type === 'select') {
    control = (
      <select className="form-select" {...common} required={field.is_required || false}>
        <option value="">—</option>
        {(field.options || []).map((opt, i) => {
          const value = typeof opt === 'string' ? opt : pick(opt.en || '', opt.hi || '')
          const label2 = typeof opt === 'string' ? opt : pick(opt.en || '', opt.hi || '')
          return <option key={i} value={value}>{label2}</option>
        })}
      </select>
    )
  } else if (field.field_type === 'radio') {
    control = (
      <div>
        {(field.options || []).map((opt, i) => {
          const value = typeof opt === 'string' ? opt : pick(opt.en || '', opt.hi || '')
          return (
            <div className="form-check" key={i}>
              <input className="form-check-input" type="radio" name={field.field_key}
                     id={`f-${field.field_key}-${i}`} value={value}
                     required={field.is_required || false} />
              <label className="form-check-label" htmlFor={`f-${field.field_key}-${i}`}>{value}</label>
            </div>
          )
        })}
      </div>
    )
  } else if (field.field_type === 'checkbox') {
    control = (
      <div>
        {(field.options || []).map((opt, i) => {
          const value = typeof opt === 'string' ? opt : pick(opt.en || '', opt.hi || '')
          return (
            <div className="form-check" key={i}>
              <input className="form-check-input" type="checkbox" name={field.field_key}
                     id={`f-${field.field_key}-${i}`} value={value} />
              <label className="form-check-label" htmlFor={`f-${field.field_key}-${i}`}>{value}</label>
            </div>
          )
        })}
      </div>
    )
  } else if (isFile) {
    let allowed = (field.allowed_extensions || ['pdf', 'jpg', 'jpeg', 'png']).map((e) => e.toLowerCase())
    if (field.field_type === 'image') {
      allowed = allowed.filter((e) => ['jpg', 'jpeg', 'png', 'webp'].includes(e))
    }
    control = (
      <input type="file" className="form-control" name={`file_${field.field_key}`}
             id={`f-${field.field_key}`} accept={fileAccept(allowed)}
             multiple={field.field_type === 'file_multi'} required={field.is_required || false} />
    )
  } else {
    control = <input className="form-control" type={TEXT_TYPES[field.field_type] || 'text'}
                     {...common} {...inputAttrs} />
  }

  return (
    <div className={`mb-3 ${errText ? 'has-error' : ''}`}>
      <label className="form-label fw-semibold" htmlFor={isFile ? `f-${field.field_key}` : common.id}>
        {label}{field.is_required && <span className="text-danger"> *</span>}
      </label>
      {control}
      {isFile && (
        <div className="form-text">
          {t('ext_hint')}: {field.allowed_extensions?.join(', ') || 'pdf, jpg, png'} · {t('max_size')}: {field.max_file_mb} MB
        </div>
      )}
      {!isFile && help && <div className="form-text">{help}</div>}
      {isFile && help && <div className="form-text">{help}</div>}
      {errText && <div className="small text-danger mt-1"><i className="bi bi-exclamation-circle me-1"></i>{errText}</div>}
    </div>
  )
}

/** One document requirement row. Files POST under req_<requirement_id>. */
export function RequirementInput({ req, errorKey }) {
  const { pick, t, lang } = useApp()
  const label = pick(req.label_en, req.label_hi)
  const desc = pick(req.description_en, req.description_hi)
  const errCode = errorKey || ''
  const errText = errCode ? FIELD_ERROR_TEXT(errCode, lang, t) : ''
  const inputId = `req-${req.id}`

  return (
    <div className="mb-3 p-3 border rounded bg-white">
      <label className="form-label fw-semibold mb-1" htmlFor={inputId}>
        <i className="bi bi-paperclip me-1" aria-hidden="true"></i>
        {label}{req.is_required && <span className="text-danger"> *</span>}
        <span className={`badge ms-2 ${req.is_required ? 'bg-danger-subtle text-danger-emphasis' : 'bg-secondary-subtle text-secondary-emphasis'}`}>
          {req.is_required ? t('required') : t('optional')}
        </span>
      </label>
      {desc && <div className="form-text mb-2">{desc}</div>}
      <input type="file" className="form-control" id={inputId} name={`req_${req.id}`}
             accept={fileAccept(req.allowed_extensions)}
             multiple={req.allow_multiple || false}
             required={req.is_required || false} />
      <div className="form-text">
        {t('ext_hint')}: {req.allowed_extensions?.join(', ')} · {t('max_size')}: {req.max_file_mb} MB
        {req.allow_multiple ? ` · ${t('each')}` : ''}
      </div>
      {errText && <div className="small text-danger mt-1"><i className="bi bi-exclamation-circle me-1"></i>{errText}</div>}
    </div>
  )
}
