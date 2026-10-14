import React, { useEffect, useRef, useState } from 'react'
import { api } from './api.js'
import { Modal } from './Dialogs.jsx'
import Icon from './Icons.jsx'

// particelle.KINDS, con il nome che si legge nel menu
export const PARTICELLE = [['snow', 'snow'], ['rain', 'rain'], ['sparks', 'sparks'],
  ['confetti', 'confetti'], ['dust', 'dust'], ['bokeh', 'bokeh'], ['stars', 'stars'],
  ['fireflies', 'fireflies']]

const DATI = /<script type="application\/json" id="vedit-particelle">([\s\S]*?)<\/script>/

/** I parametri con cui e' nata una clip di particelle (particelle.parametri), o null. */
export function parametriParticelle(html) {
  const m = DATI.exec(html || '')
  if (!m) return null
  try {
    const p = JSON.parse(m[1])
    return p && p.kind ? p : null
  } catch { return null }
}

/**
 * Menu "+ particelle": i tipi integrati, quelli salvati da chi monta e la voce
 * per farne di nuove. Le personali si rileggono a ogni apertura, cosi' quelle
 * create dall'agente (create_particles) compaiono senza ricaricare la pagina.
 */
export function MenuParticelle({ disabled, onAggiungi, onSuMisura }) {
  const [mie, setMie] = useState([])
  const ricarica = () => api.particelle().then((r) => setMie(r.personali || [])).catch(() => {})
  useEffect(() => { if (!disabled) ricarica() }, [disabled])
  return (
    <select className="ghost act" disabled={disabled} value=""
      title="Particles at the playhead: snow, sparks, confetti... or custom (transparent html clip)"
      onFocus={ricarica} onPointerDown={ricarica}
      onChange={(e) => {
        const v = e.target.value
        if (v === '__nuove') onSuMisura()
        else if (v) onAggiungi(v)
      }}>
      <option value="">+ particles</option>
      {PARTICELLE.map(([k, nome]) => <option key={k} value={k}>{nome}</option>)}
      {mie.length > 0 && (
        <optgroup label="mine">
          {mie.map((p) => <option key={p.id} value={p.id}>{p.nome}</option>)}
        </optgroup>
      )}
      <option value="__nuove">custom…</option>
    </select>
  )
}

const VUOTA = { forme: {}, moti: {}, predefinita: null, limiti: {}, personali: [] }

/**
 * Editor delle particelle su misura, con anteprima dal vivo: il documento
 * arriva da particelle.html, lo stesso che va in render, quindi quello che si
 * vede qui e' quello che esce.
 *
 * ``iniziale`` e' la ricetta da cui partire (quella della clip che si modifica);
 * ``onApplica(spec)`` la mette in timeline o sulla clip. Senza ``setError``
 * gli errori restano scritti dentro la finestra.
 */
export function EditorParticelle({ iniziale, titolo, applica, onApplica, onClose, setError }) {
  const [info, setInfo] = useState(VUOTA)
  const [spec, setSpec] = useState(iniziale || null)
  const [mia, setMia] = useState('')          // id delle personali da cui si e' partiti
  const [nome, setNome] = useState('')
  const [anteprima, setAnteprima] = useState(null)
  const [errore, setErrore] = useState(null)
  const avvisa = (msg) => (setError ? setError(msg) : setErrore(msg))

  useEffect(() => {
    api.particelle().then((r) => {
      setInfo(r)
      setSpec((s) => ({ ...r.predefinita, ...(s || {}) }))
    }).catch((e) => setErrore(e.message))
  }, [])

  // anteprima: si chiede al server dopo una breve pausa, e la richiesta
  // vecchia si abbandona se nel frattempo si e' mosso un altro cursore
  const ctrl = useRef(null)
  useEffect(() => {
    if (!spec) return undefined
    const t = setTimeout(() => {
      ctrl.current?.abort()
      ctrl.current = new AbortController()
      api.anteprimaParticelle(spec, ctrl.current.signal)
        .then((r) => { setAnteprima(r); setErrore(null) })
        .catch((e) => { if (e.name !== 'AbortError') setErrore(e.message) })
    }, 220)
    return () => clearTimeout(t)
  }, [spec])
  useEffect(() => () => ctrl.current?.abort(), [])

  const set = (k, v) => setSpec((s) => ({ ...s, [k]: v }))
  const setCoppia = (k, i, v) => setSpec((s) => {
    const c = [...s[k]]
    c[i] = v
    return { ...s, [k]: c }
  })
  const lim = (k) => info.limiti[k] || [0, 1]

  const parti = (id) => {
    setMia(id)
    const p = info.personali.find((x) => x.id === id)
    setSpec({ ...info.predefinita, ...(p?.spec || {}) })
    setNome(p?.nome || '')
  }
  const salva = () => api.salvaParticelle({ nome: nome.trim(), spec, id: mia || null })
    .then((r) => { setInfo(r); setMia(r.particelle) })
    .catch((e) => avvisa(e.message))
  const elimina = () => api.eliminaParticelle(mia)
    .then((r) => { setInfo(r); setMia(''); setNome('') })
    .catch((e) => avvisa(e.message))

  if (!spec || !info.predefinita) {
    return <Modal title={titolo} onClose={onClose} actions={<button onClick={onClose}>close</button>}>
      <div className="hint">{errore || <><Icon name="attesa" className="spin" /> loading…</>}</div>
    </Modal>
  }

  const moto = spec.motion
  const lineare = moto === 'fall' || moto === 'rise' || moto === 'drift'
  // larga quanto la finestra ma mai piu' alta di un terzo dello schermo: i comandi restano in vista
  const scala = anteprima
    ? Math.min(1, 560 / anteprima.width, Math.max(140, window.innerHeight * 0.3) / anteprima.height) : 1

  return (
    <Modal title={titolo} onClose={onClose}
      actions={<>
        {mia && <button onClick={elimina} title="Delete from my particles">
          <Icon name="cestino" />delete</button>}
        <input className="nomeparticelle" value={nome} placeholder="name to save them"
          onChange={(e) => setNome(e.target.value)} />
        <button disabled={!nome.trim()} onClick={salva}
          title="They stay on this computer and show up in the particles menu">
          {mia ? 'update mine' : 'save to mine'}</button>
        <span className="spacer" />
        <button onClick={onClose}>cancel</button>
        <button className="primary" disabled={!!errore}
          onClick={() => { onApplica(spec); onClose() }}>{applica}</button>
      </>}>
      <div className="particelle-anteprima"
        style={anteprima ? { width: anteprima.width * scala, height: anteprima.height * scala } : undefined}>
        {anteprima && (
          <iframe title="particles preview" sandbox="allow-scripts" srcDoc={anteprima.html}
            style={{ width: anteprima.width, height: anteprima.height, transform: `scale(${scala})` }} />
        )}
      </div>
      {errore && <div className="hint errore">{errore}</div>}

      {info.personali.length > 0 && (
        <div className="row"><label>start from</label>
          <select value={mia} onChange={(e) => parti(e.target.value)}>
            <option value="">new</option>
            {info.personali.map((p) => <option key={p.id} value={p.id}>{p.nome}</option>)}
          </select><span /></div>
      )}
      <div className="row"><label>shape</label>
        <select value={spec.shape} onChange={(e) => set('shape', e.target.value)}>
          {Object.entries(info.forme).map(([k, n]) => <option key={k} value={k}>{n}</option>)}
        </select><span /></div>
      {spec.shape === 'text' && (
        <div className="row"><label>symbols</label>
          <input value={spec.text} placeholder="❤ ✨ 🎉  (space separated)"
            onChange={(e) => set('text', e.target.value)} /><span /></div>
      )}
      <div className="row"><label>motion</label>
        <select value={moto} onChange={(e) => set('motion', e.target.value)}>
          {Object.entries(info.moti).map(([k, n]) => <option key={k} value={k}>{n}</option>)}
        </select><span /></div>
      <div className="row"><label>colours</label>
        <div className="particelle-colori">
          {spec.colors.map((c, i) => (
            <span key={i} className="particelle-colore">
              <input type="color" value={c.length === 4 ? `#${c[1]}${c[1]}${c[2]}${c[2]}${c[3]}${c[3]}` : c}
                onChange={(e) => set('colors', spec.colors.map((x, j) => (j === i ? e.target.value : x)))} />
              {spec.colors.length > 1 && (
                <button className="icon sm" title="Remove the colour"
                  onClick={() => set('colors', spec.colors.filter((_, j) => j !== i))}>×</button>
              )}
            </span>
          ))}
          {spec.colors.length < 12 && (
            <button className="icon sm" title="Add a colour"
              onClick={() => set('colors', [...spec.colors, spec.colors[spec.colors.length - 1]])}>
              <Icon name="piu" size={12} /></button>
          )}
        </div><span /></div>

      <Cursore label="count" value={spec.count} lim={[1, 1000]} step={1} onChange={(v) => set('count', v)} />
      <Coppia label="size" value={spec.size} lim={[0.5, 120]} step={0.5}
        onChange={(i, v) => setCoppia('size', i, v)} />
      <Coppia label="speed" value={spec.speed} lim={[0, moto === 'burst' ? 2000 : 800]} step={5}
        onChange={(i, v) => setCoppia('speed', i, v)} />
      {(lineare || moto === 'burst') && (
        <Cursore label={lineare && moto !== 'drift' ? 'tilt' : 'direction'} value={spec.direction}
          lim={lineare && moto !== 'drift' ? [-60, 60] : [-180, 180]} step={1}
          onChange={(v) => set('direction', v)} />
      )}
      {moto !== 'burst' && (
        <Cursore label="wobble" value={spec.wobble} lim={[0, 300]} step={1} onChange={(v) => set('wobble', v)} />
      )}
      <Cursore label="spin" value={spec.spin} lim={lim('spin')} step={0.05} onChange={(v) => set('spin', v)} />
      <Coppia label="opacity" value={spec.opacity} lim={[0, 1]} step={0.01}
        onChange={(i, v) => setCoppia('opacity', i, v)} />
      <Cursore label="glow" value={spec.glow} lim={[0, 80]} step={1} onChange={(v) => set('glow', v)} />
      <Cursore label="twinkle" value={spec.twinkle} lim={[0, 1]} step={0.01} onChange={(v) => set('twinkle', v)} />

      {moto === 'burst' && (<>
        <Coppia label="origin x/y" value={spec.origin} lim={[0, 1]} step={0.01}
          onChange={(i, v) => setCoppia('origin', i, v)} />
        <Cursore label="spread" value={spec.spread} lim={lim('spread')} step={1} onChange={(v) => set('spread', v)} />
        <Cursore label="gravity" value={spec.gravity} lim={[-1500, 1500]} step={10} onChange={(v) => set('gravity', v)} />
        <Cursore label="every (s)" value={spec.interval} lim={[0.2, 20]} step={0.1} onChange={(v) => set('interval', v)} />
      </>)}
      {(moto === 'burst' || moto === 'still') && (
        <Cursore label="life (s)" value={spec.life} lim={[0.1, 20]} step={0.1} onChange={(v) => set('life', v)} />
      )}
      {(moto === 'burst' || moto === 'still') && (
        <div className="row"><label>fade</label>
          <input type="checkbox" checked={spec.fade} onChange={(e) => set('fade', e.target.checked)} /><span /></div>
      )}
      <div className="hint" style={{ marginTop: 8 }}>
        The preview is the render itself, on a dark background. On footage try the
        <i> screen</i> blend for lights and sparks.
      </div>
    </Modal>
  )
}

/** Cursore con il numero accanto, per scriverlo preciso. */
function Cursore({ label, value, lim, step, onChange }) {
  const num = (v) => {
    const n = parseFloat(v)
    if (Number.isFinite(n)) onChange(n)
  }
  return (
    <div className="row"><label>{label}</label>
      <input type="range" min={lim[0]} max={lim[1]} step={step} value={value}
        onChange={(e) => num(e.target.value)} />
      <input className="particelle-num" type="number" step={step} value={value}
        onChange={(e) => num(e.target.value)} />
    </div>
  )
}

/** Due valori [da, a]: ogni particella ne prende uno a caso fra i due. */
function Coppia({ label, value, lim, step, onChange }) {
  const num = (i, v) => {
    const n = parseFloat(v)
    if (Number.isFinite(n)) onChange(i, n)
  }
  return (
    <div className="row"><label>{label}</label>
      <div className="particelle-coppia">
        {[0, 1].map((i) => (
          <input key={i} type="range" min={lim[0]} max={lim[1]} step={step} value={value[i]}
            title={i ? 'to' : 'from'} onChange={(e) => num(i, e.target.value)} />
        ))}
      </div>
      <span className="particelle-val">{value[0]}–{value[1]}</span>
    </div>
  )
}
