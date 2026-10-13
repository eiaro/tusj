// Tiny i18n: nested message objects per locale, {param} interpolation, {one, other} plurals.
// To add a language: create locales/<code>.js (copy en.js) and register it below.
import en from './locales/en.js'
import nb from './locales/nb.js'

export const LOCALES = { en, nb }
const FALLBACK = 'en'
const STORAGE_KEY = 'tusj.locale'

function detect() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored in LOCALES) return stored
  } catch {}
  for (const tag of navigator.languages ?? [navigator.language]) {
    let code = tag.toLowerCase().split('-')[0]
    if (code === 'no' || code === 'nn') code = 'nb'
    if (code in LOCALES) return code
  }
  return FALLBACK
}

// `version` bumps when plugin messages are registered, so translated text re-renders.
export const i18n = $state({ locale: detect(), version: 0 })
document.documentElement.lang = i18n.locale

export function setLocale(code) {
  i18n.locale = code
  document.documentElement.lang = code
  try {
    localStorage.setItem(STORAGE_KEY, code)
  } catch {}
}

function lookup(messages, key) {
  return key.split('.').reduce((node, part) => node?.[part], messages)
}

/** Merge a plugin's own strings ({en: {...}, nb: {...}}) under plugins.<id>. */
export function registerPluginMessages(pluginId, messages = {}) {
  for (const [code, msgs] of Object.entries(messages)) {
    if (!(code in LOCALES)) continue
    LOCALES[code].plugins ??= {}
    LOCALES[code].plugins[pluginId] = msgs
  }
  i18n.version++
}

export function t(key, params = {}) {
  void i18n.version
  let msg = lookup(LOCALES[i18n.locale], key) ?? lookup(LOCALES[FALLBACK], key) ?? key
  if (typeof msg === 'object') msg = params.n === 1 ? msg.one : msg.other
  return msg.replace(/\{(\w+)\}/g, (_, name) => params[name] ?? `{${name}}`)
}

export function has(key) {
  void i18n.version
  return lookup(LOCALES[i18n.locale], key) != null || lookup(LOCALES[FALLBACK], key) != null
}

/** Template/allergen text: a plain string or a {locale: text} map. */
export function pick(value) {
  if (value && typeof value === 'object') return value[i18n.locale] ?? value[FALLBACK] ?? Object.values(value)[0]
  return value ?? ''
}

/** Human-readable text for an error from api.js, translated when the backend sent a known code. */
export function errorText(err) {
  const code = err?.code
  if (code) {
    // Plugin errors are "<plugin id>.<code>" and live in the plugin's own messages.
    const dot = code.indexOf('.')
    const key = dot > 0 ? `plugins.${code.slice(0, dot)}.errors.${code.slice(dot + 1)}` : `errors.${code}`
    if (has(key)) return t(key, err.params)
  }
  return err?.message ?? String(err)
}

/** Label for a date preset such as "+3d" or "+1y". */
export function presetLabel(value) {
  const m = /^\+(\d+)([dwmy])$/.exec(value)
  return m ? t(`presets.${m[2]}`, { n: Number(m[1]) }) : value
}
