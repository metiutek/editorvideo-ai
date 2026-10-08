export const fmt = (s) => {
  if (!isFinite(s)) return '0:00.0'
  const neg = s < 0
  s = Math.abs(s)
  const m = Math.floor(s / 60)
  const sec = s - m * 60
  return `${neg ? '-' : ''}${m}:${sec.toFixed(1).padStart(4, '0')}`
}

export const isKf = (v) => !!(v && typeof v === 'object' && Array.isArray(v.kf))

// Valore del parametro al tempo t (stessa interpolazione del backend, per la UI).
export function sampleKf(value, t) {
  if (!isKf(value)) return Number(value) || 0
  const keys = [...value.kf].sort((a, b) => a.t - b.t)
  if (t <= keys[0].t) return keys[0].v
  if (t >= keys[keys.length - 1].t) return keys[keys.length - 1].v
  for (let i = 0; i < keys.length - 1; i++) {
    const a = keys[i], b = keys[i + 1]
    if (t >= a.t && t <= b.t) {
      const span = b.t - a.t
      const p = span <= 0 ? 0 : (t - a.t) / span
      return a.v + (b.v - a.v) * ease(a.ease || 'linear', p)
    }
  }
  return keys[keys.length - 1].v
}

function ease(name, p) {
  switch (name) {
    case 'hold': return 0
    case 'ease_in': return p * p
    case 'ease_out': return 1 - (1 - p) ** 2
    case 'ease_in_out': return p * p * (3 - 2 * p)
    case 'ease_in_cubic': return p ** 3
    case 'ease_out_cubic': return 1 - (1 - p) ** 3
    case 'ease_in_out_cubic': return p < 0.5 ? 4 * p ** 3 : 1 - 4 * (1 - p) ** 3
    default: return p
  }
}

export const EASINGS = ['linear', 'hold', 'ease_in', 'ease_out', 'ease_in_out',
  'ease_in_cubic', 'ease_out_cubic', 'ease_in_out_cubic']

/**
 * Impronta breve di un testo (FNV-1a). Serve all'anteprima delle clip html:
 * entra nell'indirizzo dell'iframe, che cosi' si ricarica solo quando il
 * documento cambia davvero e non a ogni aggiornamento del progetto.
 */
export function impronta(testo) {
  let h = 0x811c9dc5
  const s = String(testo ?? '')
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 0x01000193) >>> 0
  }
  return h.toString(36)
}

const base = (p) => String(p).split(/[\\/]/).filter(Boolean).pop() || String(p)
const corto = (s, n = 32) => (s.length > n ? `${s.slice(0, n - 1)}…` : s)

/**
 * Su cosa lavora un passo dell'assistente, in poche parole: "clip intro ·
 * 0:23.5" invece del solo "posizione e scala". Legge gli argomenti dello
 * strumento cosi' come arrivano (UI, API o MCP: i nomi cambiano un po').
 */
export function dettaglioStrumento(nome, input, project) {
  const a = input && typeof input === 'object' ? input : {}
  const clips = project ? project.tracks.flatMap((t) => t.clips) : []
  const media = project?.media || []
  const parti = []
  const nomeClip = (id) => {
    const c = clips.find((x) => x.id === id)
    return `clip ${c ? (c.name || c.id) : id}`
  }
  for (const k of ['clip_id', 'clip', 'clip_a']) {
    if (typeof a[k] === 'string') { parti.push(nomeClip(a[k])); break }
  }
  if (typeof a.clip_b === 'string') parti.push(`→ ${nomeClip(a.clip_b)}`)
  for (const k of ['media_id', 'media']) {
    if (typeof a[k] === 'string') {
      const m = media.find((x) => x.id === a[k])
      parti.push(m ? m.name : a[k]); break
    }
  }
  if (typeof a.track_id === 'string' || typeof a.track === 'string') parti.push(`traccia ${a.track_id || a.track}`)
  const percorsi = a.paths || a.files || (typeof a.path === 'string' ? [a.path] : null)
    || (typeof a.file_path === 'string' ? [a.file_path] : null)
  if (Array.isArray(percorsi) && percorsi.length) parti.push(corto(percorsi.map(base).join(', ')))
  if (Array.isArray(a.clips)) parti.push(`${a.clips.length} tagli`)
  const t = [a.at, a.t, a.time, a.quando].find((v) => typeof v === 'number')
  if (t != null) parti.push(fmt(t))
  if (typeof a.start === 'number' && typeof a.duration === 'number') {
    parti.push(`${fmt(a.start)} → ${fmt(a.start + a.duration)}`)
  } else if (typeof a.start === 'number') parti.push(`da ${fmt(a.start)}`)
  else if (typeof a.duration === 'number') parti.push(`${a.duration}s`)
  if (typeof a.effect === 'string') parti.push(a.effect)
  if (typeof a.preset_id === 'string') parti.push(a.preset_id)
  if (typeof a.type === 'string' && /transition|crossfade/.test(nome)) parti.push(a.type)
  if (typeof a.speed === 'number') parti.push(`${a.speed}x`)
  if (typeof a.text === 'string') parti.push(`«${corto(a.text, 28)}»`)
  if (typeof a.note === 'string') parti.push(`«${corto(a.note, 28)}»`)
  if (typeof a.html === 'string') parti.push(`${a.html.length} caratteri`)
  if (typeof a.kind === 'string') parti.push(a.kind)
  if (typeof a.color === 'string' && nome === 'add_color') parti.push(a.color)
  const tr = ['x', 'y', 'scale', 'rotation', 'opacity'].filter((k) => a[k] != null)
  if (tr.length) parti.push(tr.join(', '))
  if (typeof a.url === 'string') { try { parti.push(new URL(a.url).host) } catch { parti.push(corto(a.url)) } }
  if (typeof a.pattern === 'string') parti.push(corto(a.pattern))
  if (typeof a.output === 'string') parti.push(base(a.output))
  return parti.join(' · ')
}

export const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v))

/**
 * Geometria del riquadro di trasformazione: dai valori del progetto (pixel del
 * canvas, origine al centro) ai pixel dell'immagine mostrata a schermo.
 *
 * E' una funzione pura per poterla verificare senza browser: e' il punto in cui
 * un errore di conversione sposterebbe il riquadro rispetto all'immagine.
 */
export function transformBox({ box, canvas, native, x = 0, y = 0, scale = 1 }) {
  const k = box.w / canvas.width          // pixel a schermo per pixel di progetto
  const w = native.width * scale * k
  const h = native.height * scale * k
  const cx = box.left + box.w / 2 + x * k
  const cy = box.top + box.h / 2 + y * k
  return { k, left: cx - w / 2, top: cy - h / 2, width: w, height: h }
}

export const allClips = (project) =>
  project ? project.tracks.flatMap((t) => t.clips.map((c) => ({ ...c, trackId: t.id, kind: t.kind }))) : []

export const findClip = (project, id) => allClips(project).find((c) => c.id === id)
