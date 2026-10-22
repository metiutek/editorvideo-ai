// Unico punto di contatto con il backend.

/**
 * Altezza dei segmenti di anteprima riprodotti dal player.
 *
 * Deve stare sotto la soglia in cui il render va piu' lento della
 * riproduzione, altrimenti il pezzo successivo non e' pronto in tempo e il
 * filmato si ferma a ogni giunzione. Su un progetto pesante 540p rendeva a
 * 0,6x il tempo reale e si impuntava; 432p sta sopra il tempo reale. Il
 * fotogramma fermo resta a piena qualita' — questo vale solo per la
 * riproduzione. Prefetch e richiesta devono usare lo stesso valore, altrimenti
 * la chiave di cache cambia e il lavoro preparato si butta via.
 */
const PREVIEW_H = 432

async function req(url, options) {
  const res = await fetch(url, options)
  if (!res.ok) {
    let detail = res.statusText
    try {
      detail = (await res.json()).detail || detail
    } catch { /* risposta non JSON */ }
    const err = new Error(detail)
    err.status = res.status    // chi riprova distingue un rifiuto da un guasto
    throw err
  }
  return res.status === 204 ? null : res.json()
}

export const api = {
  state: () => req('/api/state'),
  // solo progetto, percorso e revisione: si chiede a ogni evento "project"
  project: () => req('/api/project'),
  recenti: () => req('/api/recenti'),

  // preset: un nome ('1080p') o un formato ('9:16'); extra: { size, fps }
  createProject: (path, name, preset, extra = {}) =>
    req('/api/project/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path, name, preset, ...extra }),
    }),

  openProject: (path) =>
    req('/api/project/open', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    }),

  // Ogni modifica passa di qui: stesso metodo che usa l'agente via MCP.
  op: (name, args = {}) =>
    req(`/api/op/${name}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(args),
    }),

  browse: (path) => req(`/api/browse${path ? `?path=${encodeURIComponent(path)}` : ''}`),
  waveform: (id) => req(`/api/media/${id}/waveform`),
  strip: (id, height = 44) => req(`/api/media/${id}/strip?height=${height}`),
  // quando il proxy e' pronto l'indirizzo cambia: il <video> lo ricarica invece
  // di restare sul file originale che non sapeva decodificare
  streamUrl: (id, media) => `/api/media/${id}/stream${media?.proxy ? '?p=1' : ''}`,
  // documento di una clip html con l'orologio virtuale: v cambia col contenuto
  htmlUrl: (id, v) => `/api/html/${id}?v=${v}`,

  // un link letto (pagina) o scaricato (immagine, video, audio) come riferimento
  chatLink: (url) =>
    req('/api/chat/link', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    }),

  // plugin audio VST installati e i parametri di uno
  plugins: () => req('/api/plugins'),
  pluginParams: (file) => req(`/api/plugin/parametri?file=${encodeURIComponent(file)}`),

  // file allegati a un messaggio per l'assistente (immagini, PDF, testi, media)
  allega: (files) => {
    const form = new FormData()
    for (const f of files) form.append('files', f)
    return req('/api/chat/allega', { method: 'POST', body: form })
  },

  // import per riferimento, a blocchi: i file illeggibili tornano in ``scartati``
  importa: (paths, folder = '') =>
    req('/api/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ paths, folder }),
    }),
  // tutti i file multimediali di una cartella, sottocartelle comprese
  scan: (path) => req(`/api/scan?path=${encodeURIComponent(path)}`),

  // upload a pezzi dei file trascinati (caricamento.js)
  uploadSpazio: () => req('/api/upload/spazio'),
  uploadStato: (q) => req(`/api/upload/stato?${new URLSearchParams(q)}`),
  uploadPezzo: (q, offset, blob, signal) =>
    req(`/api/upload/pezzo?${new URLSearchParams({ ...q, offset })}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/octet-stream' },
      body: blob,
      signal,
    }),

  prefetch: (start, duration, height = PREVIEW_H) =>
    req(`/api/preview/prefetch?start=${start.toFixed(3)}&duration=${duration.toFixed(3)}&height=${height}`,
      { method: 'POST' }).catch(() => null),

  // prova = {effect, clip}: il fotogramma esce come se quell'effetto fosse
  // applicato, ma il progetto non viene toccato
  // inviluppo dei livelli di tracce e master per i misuratori (review.livelli)
  mixerLevels: (revision) => req(`/api/mixer/levels?r=${revision}`),
  // scope grafico del fotogramma (review.SCOPI): la revisione invalida la cache
  scopeUrl: (t, view, revision) =>
    `/api/scope?t=${t.toFixed(3)}&view=${encodeURIComponent(view)}&r=${revision}`,
  frameUrl: (t, revision, width = 960, prova = null) =>
    `/api/frame?t=${t.toFixed(3)}&width=${width}&r=${revision}`
    + (prova?.effect ? `&effect=${encodeURIComponent(prova.effect)}` : '')
    + (prova?.preset ? `&preset=${encodeURIComponent(prova.preset)}` : '')
    + ((prova?.effect || prova?.preset) && prova.clip ? `&clip=${prova.clip}` : ''),
  previewUrl: (start, duration, revision, height = PREVIEW_H) =>
    `/api/preview?start=${start.toFixed(3)}&duration=${duration.toFixed(3)}&height=${height}&r=${revision}`,

  render: (body) =>
    req('/api/render', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  renderStatus: (id) => req(`/api/render/${id}`),
  buildProxies: () => req('/api/proxies?height=540', { method: 'POST' }),
  loudness: () => req('/api/loudness', { method: 'POST' }),

  // un preset = piu' effetti, applicati in un colpo solo (una sola voce di undo)
  applyPreset: (preset_id, clip_id = null) =>
    req('/api/preset/apply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ preset_id, clip_id }),
    }),

  chatReset: () => req('/api/chat/reset', { method: 'POST' }),
  // ferma il turno in corso: le modifiche gia' fatte restano e si annullano con Ctrl+Z
  chatStop: () => req('/api/chat/stop', { method: 'POST' }),
  // domande dell'assistente in attesa di risposta (ask_user, conferma export)
  domanda: () => req('/api/domanda'),
  rispondi: (qid, risposte) =>
    req(`/api/domanda/${qid}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ risposte }),
    }),

  // stili di montaggio scritti dall'utente (restano su questo computer)
  stili: () => req('/api/stili'),
  salvaStile: (body) =>
    req('/api/stili', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  eliminaStile: (id) => req(`/api/stili/${encodeURIComponent(id)}`, { method: 'DELETE' }),

  // una traccia di testi come .srt o .vtt
  esportaSottotitoli: (track, path) =>
    req('/api/subtitles/export', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ track, path }),
    }),

  // timeline per e da altri montaggi (interscambio.py): .edl .fcpxml .otio
  esportaTimeline: (path, track = null) =>
    req('/api/timeline/export', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path, track }),
    }),
  importaTimeline: (path, testo = null) =>
    req('/api/timeline/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path, testo }),
    }),

  // particelle su misura: cosa si puo' scegliere, anteprima, quelle salvate
  particelle: () => req('/api/particelle'),
  anteprimaParticelle: (spec, signal) =>
    req('/api/particelle/anteprima', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ spec }),
      signal,
    }),
  salvaParticelle: (body) =>
    req('/api/particelle', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  eliminaParticelle: (id) => req(`/api/particelle/${encodeURIComponent(id)}`, { method: 'DELETE' }),

  // modello dell'assistente: quale usare e con che chiave (resta su questo computer)
  // voce generata dal testo (tts.py)
  tts: () => req('/api/tts'),
  setTts: (body) =>
    req('/api/tts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  generaVoce: (body) =>
    req('/api/tts/genera', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  // skill e server MCP dell'utente per l'assistente (estensioni.py)
  estensioni: () => req('/api/estensioni'),
  setEstensioni: (body) => req('/api/estensioni', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  collegaEstensioni: () => req('/api/estensioni/collega', { method: 'POST' }),
  // web: cercare, scaricare (web.py)
  web: () => req('/api/web'),
  setWeb: (body) => req('/api/web', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  cercaWeb: (query, tipo, signal) =>
    req('/api/web/cerca', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ query, tipo }), signal }),
  scaricaWeb: (urls) => req('/api/web/scarica', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ urls }) }),
  // pubblicare sui social (social.py)
  social: () => req('/api/social'),
  setSocial: (body) => req('/api/social', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  loginYoutube: () => req('/api/social/login/youtube', { method: 'POST' }),
  scollegaSocial: (p) => req(`/api/social/scollega/${p}`, { method: 'POST' }),
  pubblica: (body) => req('/api/social/pubblica', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  statoPubblica: (id) => req(`/api/social/pubblica/${id}`),
  // memoria comune a tutti i progetti (~/.vedit/MEMORIA.md)
  memoria: () => req('/api/memoria'),
  salvaMemoria: (testo) =>
    req('/api/memoria', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ testo }),
    }),
  llm: () => req('/api/llm'),
  setLlm: (body) =>
    req('/api/llm', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
}

/**
 * Un turno con l'assistente. Gli eventi arrivano mentre il modello lavora
 * (testo, strumenti in esecuzione), quindi si legge il flusso invece di
 * aspettare la risposta completa.
 */
export async function chat(message, refs, stile, onEvent, signal) {
  const res = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, refs, stile }),
    signal,
  })
  if (!res.ok) {
    let detail = res.statusText
    try { detail = (await res.json()).detail || detail } catch { /* non JSON */ }
    throw new Error(detail)
  }
  const reader = res.body.getReader()
  const dec = new TextDecoder()
  let buf = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += dec.decode(value, { stream: true })
    // SSE: un evento per blocco separato da riga vuota
    let i
    while ((i = buf.indexOf('\n\n')) !== -1) {
      const line = buf.slice(0, i).trim()
      buf = buf.slice(i + 2)
      if (line.startsWith('data:')) {
        try { onEvent(JSON.parse(line.slice(5))) } catch { /* blocco parziale */ }
      }
    }
  }
}

export function connectEvents(onEvent) {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  let sock
  let closed = false
  const open = () => {
    sock = new WebSocket(`${proto}://${location.host}/ws`)
    sock.onmessage = (e) => onEvent(JSON.parse(e.data))
    sock.onclose = () => { if (!closed) setTimeout(open, 1500) }
  }
  open()
  return () => { closed = true; sock && sock.close() }
}
