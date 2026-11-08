import { useEffect, useSyncExternalStore } from 'react'
import zh from './locales/zh-CN.json' with { type: 'json' }

const STORAGE_KEY = 'vedit.language'
const lingue = new Set(['en', 'zh-CN'])
let lingua = 'en'
try {
  const salvata = globalThis.localStorage?.getItem(STORAGE_KEY)
  if (lingue.has(salvata)) lingua = salvata
} catch { /* lo storage puo' essere disabilitato */ }
const osservatori = new Set()
const snapshot = () => lingua
const subscribe = (fn) => { osservatori.add(fn); return () => osservatori.delete(fn) }

export function setLanguage(value) {
  if (!lingue.has(value)) return
  lingua = value
  try { globalThis.localStorage?.setItem(STORAGE_KEY, value) } catch { /* vale comunque nella scheda */ }
  for (const fn of osservatori) fn()
}

export function useLanguage() {
  const value = useSyncExternalStore(subscribe, snapshot, () => 'en')
  useEffect(() => {
    document.documentElement.lang = value
    const aggiorna = (e) => { if (e.key === STORAGE_KEY && lingue.has(e.newValue)) setLanguage(e.newValue) }
    window.addEventListener('storage', aggiorna)
    return () => window.removeEventListener('storage', aggiorna)
  }, [value])
  return [value, setLanguage]
}

// Le chiavi inglesi restano la lingua sorgente. I valori interpolati non si
// traducono: nomi, percorsi e testo scritto dall'utente restano intatti.
export function translate(text, values = []) {
  if (typeof text !== 'string') return text
  const key = text.trim()
  if (!key) return text
  const modello = lingua === 'zh-CN' && Object.hasOwn(zh, key) ? zh[key] : key
  const tradotto = modello.replace(/\{(\d+)\}/g, (match, i) => i in values ? String(values[i] ?? '') : match)
  return text.slice(0, text.length-text.trimStart().length) + tradotto + text.slice(text.trimEnd().length)
}

// Solo messaggi noti dell'applicazione, mai la risposta libera del modello.
const messaggi = [
  [/^Analyzing (.*): (.*)$/, 'Analyzing {0}: {1}'],
  [/^Importing (.*): (.*)$/, 'Importing {0}: {1}'],
  [/^export failed: ([\s\S]*)$/, 'export failed: {0}'],
  [/^Activity (.*?), (.*?): ([\s\S]*)$/, 'Activity {0}, {1}: {2}'],
  [/^Activity (.*?): no usable distinct footage; add videos or remove this activity$/, 'Activity {0}: no usable distinct footage; add videos or remove this activity'],
  [/^Activity (.*?): select valid videos$/, 'Activity {0}: select valid videos'],
  [/^at the end of (.*)$/, 'at the end of {0}'],
  [/^on (.*)$/, 'on {0}'],
  [/^paste the (.*) API key$/, 'paste the {0} API key'],
]
export function translateMessage(text) {
  if (typeof text !== 'string' || lingua === 'en') return text
  if (Object.hasOwn(zh, text.trim())) return translate(text)
  for (const [regex, key] of messaggi) {
    const match = text.match(regex)
    if (match) {
      const values = match.slice(1)
      if (key === 'Activity {0}, {1}: {2}') values[2] = translateMessage(values[2])
      return translate(key, values)
    }
  }
  return text
}

// Per etichette del registro effetti/parametri e opzioni enum, non per i nomi
// dei media, dei progetti o per il contenuto dell'assistente.
export const translateLabel = (text) => translate(text)
