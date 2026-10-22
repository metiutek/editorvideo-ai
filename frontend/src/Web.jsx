import React, { useEffect, useRef, useState } from 'react'
import { api } from './api.js'
import Icon from './Icons.jsx'

const TIPI = [
  { id: 'images', nome: 'images' },
  { id: 'videos', nome: 'videos' },
  { id: 'web', nome: 'pages' },
  { id: 'news', nome: 'news' },
]

/**
 * Cercare sul web e portare in progetto (web.py). Nessun sito fisso: il motore
 * cerca dappertutto. Un'immagine o un video si scarica accanto al progetto
 * (cartella "web", con la fonte in FONTI.md) e si importa nel bin: da li' va
 * in timeline come ogni altro media.
 */
export default function Web({ run, setError, flash }) {
  const [query, setQuery] = useState('')
  const [tipo, setTipo] = useState('images')
  const [risultati, setRisultati] = useState(null)
  const [cercando, setCercando] = useState(false)
  const [presi, setPresi] = useState({})        // url -> 'loading' | 'done'
  const [impostazioni, setImpostazioni] = useState(false)
  const [stato, setStato] = useState(null)
  const ferma = useRef(null)

  useEffect(() => { api.web().then(setStato).catch(() => {}) }, [])

  const cerca = async (t = tipo) => {
    if (!query.trim()) return
    ferma.current?.abort()
    ferma.current = new AbortController()
    setCercando(true)
    try {
      const r = await api.cercaWeb(query, t, ferma.current.signal)
      setRisultati(r)
    } catch (e) { if (e.name !== 'AbortError') setError(e.message) } finally { setCercando(false) }
  }

  const prendi = async (r) => {
    const url = r.media || r.url
    setPresi((p) => ({ ...p, [url]: 'loading' }))
    try {
      const { files, errori } = await api.scaricaWeb([url])
      await run('import_media', { paths: files, folder: 'web' })
      setPresi((p) => ({ ...p, [url]: 'done' }))
      flash(errori?.length ? errori[0].errore : 'added to the media bin, folder "web"')
    } catch (e) {
      setPresi((p) => { const n = { ...p }; delete n[url]; return n })
      setError(e.message)
    }
  }

  if (impostazioni) {
    return <MotoreWeb stato={stato} setError={setError}
      onSalvato={(st) => { setStato(st); setImpostazioni(false) }} onClose={() => setImpostazioni(false)} />
  }

  const voci = risultati?.risultati || []
  const scaricabile = (r) => risultati?.tipo === 'images' || risultati?.tipo === 'videos' || r.media

  return (
    <div className="webpanel">
      <div className="webcerca">
        <input value={query} placeholder="search the web…" onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && cerca()} />
        <button className="icon sm" title="Search" disabled={!query.trim() || cercando} onClick={() => cerca()}>
          <Icon name="cerca" size={14} />
        </button>
        <button className="icon sm" title="Search engine" onClick={() => setImpostazioni(true)}>
          <Icon name="ingranaggio" size={14} />
        </button>
      </div>
      <div className="webtipi">
        {TIPI.map((t) => (
          <button key={t.id} className={tipo === t.id ? 'on' : ''}
            onClick={() => { setTipo(t.id); if (query.trim()) cerca(t.id) }}>{t.nome}</button>
        ))}
      </div>
      {cercando && <div className="hint">searching…</div>}
      {!cercando && risultati && !voci.length && <div className="hint">no results</div>}
      {!risultati && !cercando && (
        <div className="hint">
          Find photos, videos and facts anywhere on the web. Downloaded files go next to the
          project with their source in FONTI.md: check the license before using them.
          {stato && !stato.yt_dlp && <> Install yt-dlp to download from video pages (YouTube, Vimeo…).</>}
        </div>
      )}
      <div className={risultati?.tipo === 'images' || risultati?.tipo === 'videos' ? 'webgriglia' : 'weblista'}>
        {voci.map((r, i) => {
          const url = r.media || r.url
          const st = presi[url]
          return (
            <div key={i} className="webvoce" title={r.title}>
              {r.thumb && <img src={r.thumb} alt="" loading="lazy" referrerPolicy="no-referrer" />}
              <div className="webtesto">
                <a href={r.url} target="_blank" rel="noreferrer">{r.title || r.url}</a>
                {r.snippet && <small>{r.snippet}</small>}
                {(r.source || r.duration || r.size) && (
                  <small className="dim">{[r.source, r.duration, r.size].filter(Boolean).join(' · ')}</small>
                )}
              </div>
              {scaricabile(r) && (
                <button className="ghost sm" disabled={!!st} onClick={() => prendi(r)}
                  title="Download and add to the media bin">
                  <Icon name={st === 'done' ? 'spunta' : 'piu'} size={13} />
                  {st === 'loading' ? '…' : st === 'done' ? '' : 'add'}
                </button>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function MotoreWeb({ stato, setError, onSalvato, onClose }) {
  const [mid, setMid] = useState(stato?.motore || 'duckduckgo')
  const [chiave, setChiave] = useState('')
  const m = stato?.motori.find((x) => x.id === mid)
  const [indirizzo, setIndirizzo] = useState(m?.indirizzo || '')
  const salva = () => api.setWeb({ motore: mid, chiave: chiave || null, indirizzo: m?.vuole_indirizzo ? indirizzo : null })
    .then(onSalvato).catch((e) => setError(e.message))
  return (
    <div className="webpanel provform">
      <div className="section-title">search engine<span className="spacer" />
        <button className="icon sm" onClick={onClose}><Icon name="chiudi" size={14} /></button></div>
      <div className="provgrid">
        {(stato?.motori || []).map((x) => (
          <button key={x.id} className={`prov ${x.id === mid ? 'on' : ''}`} onClick={() => setMid(x.id)}>
            <span className={`dot ${x.pronto ? 'ok' : ''}`} /><span className="pnome">{x.nome}</span>
          </button>
        ))}
      </div>
      {m && <div className="hint">{m.nota}</div>}
      {m?.vuole_chiave && (
        <label className="campo"><span>API key</span>
          <input type="password" autoComplete="off" value={chiave}
            placeholder={m.chiave ? 'saved' : 'paste the key here'} onChange={(e) => setChiave(e.target.value)} /></label>
      )}
      {m?.vuole_indirizzo && (
        <label className="campo"><span>address</span>
          <input value={indirizzo} placeholder="https://searx.example.org" onChange={(e) => setIndirizzo(e.target.value)} /></label>
      )}
      <div className="azioni"><button className="primary" onClick={salva}><Icon name="spunta" />use this</button></div>
      <div className="hint">Keys stay on this computer (~/.vedit/web.json).</div>
    </div>
  )
}
