import React, { useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api.js'
import Icon from './Icons.jsx'
import { rispostaEq } from './util.js'

/**
 * Editor delle parti audio "da studio": il grafico dell'equalizzatore
 * parametrico e i parametri di un plugin VST.
 */

// etichette corte: il pannello e' stretto; il nome lungo sta nel suggerimento
const TIPI = [
  ['peak', 'campana', 'campana: alza o abbassa intorno a una frequenza'],
  ['lowshelf', 'bassi', 'scaffale basso: tutto sotto la frequenza'],
  ['highshelf', 'alti', 'scaffale alto: tutto sopra la frequenza'],
  ['highpass', 'HP', 'passa-alto: taglia sotto la frequenza'],
  ['lowpass', 'LP', 'passa-basso: taglia sopra la frequenza'],
  ['notch', 'notch', 'notch: toglie una frequenza sola (ronzii)'],
]
const COLORI = ['#ff8a5c', '#6fa8ff', '#5fd6b4', '#b792ff', '#ffc65c', '#ff6b7d',
  '#8fd3ff', '#c8e86b', '#f7a8e0', '#9aa6ff']
const W = 300
const H = 140
const DB = 18
const LOG_MIN = Math.log10(20)
const LOG_SPAN = 3   // 20 Hz .. 20 kHz
const conGuadagno = (t) => t === 'peak' || t === 'lowshelf' || t === 'highshelf'

const xDaFreq = (f) => ((Math.log10(f) - LOG_MIN) / LOG_SPAN) * W
const freqDaX = (x) => 10 ** (LOG_MIN + (Math.max(0, Math.min(W, x)) / W) * LOG_SPAN)
const yDaDb = (g) => H / 2 - (g / DB) * (H / 2 - 8)
const dbDaY = (y) => ((H / 2 - y) / (H / 2 - 8)) * DB
const arrotonda = (v, n = 1) => Math.round(v * 10 ** n) / 10 ** n
const etichettaHz = (f) => (f >= 1000 ? `${arrotonda(f / 1000, f >= 10000 ? 0 : 1)}k` : `${Math.round(f)}`)

/** Equalizzatore parametrico: curva, punti da trascinare, e le bande in elenco. */
export function EqGraph({ bands, onChange }) {
  const [bozza, setBozza] = useState(null)   // bande mentre si trascina
  const svgRef = useRef(null)
  const lista = bozza || bands || []

  const curva = useMemo(() => {
    const punti = []
    for (let i = 0; i <= 120; i++) {
      const f = 10 ** (LOG_MIN + (i / 120) * LOG_SPAN)
      punti.push([xDaFreq(f), yDaDb(Math.max(-DB - 6, Math.min(DB + 6, rispostaEq(lista, f))))])
    }
    return 'M' + punti.map(([x, y]) => `${x.toFixed(1)} ${y.toFixed(1)}`).join(' L')
  }, [lista])

  const cambia = (i, patch) => onChange(lista.map((b, j) => (j === i ? { ...b, ...patch } : b)))

  const trascina = (i, e) => {
    e.preventDefault()
    const svg = svgRef.current
    const r = svg.getBoundingClientRect()
    const scala = W / r.width
    let ultima = lista
    const move = (ev) => {
      const x = (ev.clientX - r.left) * scala
      const y = (ev.clientY - r.top) * (H / r.height)
      const freq = Math.round(Math.max(20, Math.min(20000, freqDaX(x))))
      const b = lista[i]
      const patch = { freq }
      if (conGuadagno(b.type)) patch.gain = arrotonda(Math.max(-24, Math.min(24, dbDaY(y))))
      ultima = lista.map((x2, j) => (j === i ? { ...x2, ...patch } : x2))
      setBozza(ultima)
    }
    const up = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      setBozza(null)
      onChange(ultima)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }

  // rotellina sul punto = larghezza della banda (Q)
  const rotella = (i, e) => {
    e.preventDefault()
    const b = lista[i]
    const q = Math.max(0.1, Math.min(18, arrotonda(b.q * (e.deltaY < 0 ? 1.15 : 1 / 1.15), 2)))
    cambia(i, { q })
  }

  return (
    <div className="eqpro">
      <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} className="eqgrafico">
        {[50, 100, 200, 500, 1000, 2000, 5000, 10000].map((f) => (
          <g key={f}>
            <line x1={xDaFreq(f)} x2={xDaFreq(f)} y1={0} y2={H} className="eqgriglia" />
            <text x={xDaFreq(f) + 2} y={H - 3} className="eqetichetta">{etichettaHz(f)}</text>
          </g>
        ))}
        {[-12, -6, 0, 6, 12].map((g) => (
          <line key={g} x1={0} x2={W} y1={yDaDb(g)} y2={yDaDb(g)}
            className={g === 0 ? 'eqzero' : 'eqgriglia'} />
        ))}
        <path d={curva} className="eqcurva" />
        {lista.map((b, i) => b.on !== false && (
          <circle key={i} cx={xDaFreq(b.freq)} cy={yDaDb(conGuadagno(b.type) ? b.gain || 0 : 0)}
            r={6} fill={COLORI[i % COLORI.length]} className="eqpunto"
            onPointerDown={(e) => trascina(i, e)} onWheel={(e) => rotella(i, e)}>
            <title>{`${TIPI.find((t) => t[0] === b.type)?.[2]} · ${etichettaHz(b.freq)} Hz`}</title>
          </circle>
        ))}
      </svg>
      <div className="hint">trascina i punti; la rotellina su un punto allarga o stringe la banda</div>
      <div className="eqbande">
        {lista.map((b, i) => (
          <div key={i} className="eqbanda">
            <span className="eqcolore" style={{ background: COLORI[i % COLORI.length] }} />
            <input type="checkbox" checked={b.on !== false} title="Accesa"
              onChange={(e) => cambia(i, { on: e.target.checked })} />
            <select value={b.type} title={TIPI.find((t) => t[0] === b.type)?.[2]}
              onChange={(e) => cambia(i, { type: e.target.value })}>
              {TIPI.map(([v, l, d]) => <option key={v} value={v} title={d}>{l}</option>)}
            </select>
            <input type="number" value={Math.round(b.freq)} min={20} max={20000} title="frequenza (Hz)"
              onChange={(e) => cambia(i, { freq: Math.max(20, Math.min(20000, +e.target.value || 20)) })} />
            <input type="number" value={b.gain ?? 0} step={0.5} min={-24} max={24} title="guadagno (dB)"
              disabled={!conGuadagno(b.type)}
              onChange={(e) => cambia(i, { gain: Math.max(-24, Math.min(24, +e.target.value || 0)) })} />
            <input type="number" value={b.q ?? 1} step={0.1} min={0.1} max={18} title="larghezza (Q)"
              onChange={(e) => cambia(i, { q: Math.max(0.1, Math.min(18, +e.target.value || 1)) })} />
            <button className="icon sm" title="Togli la banda"
              onClick={() => onChange(lista.filter((_, j) => j !== i))}><Icon name="chiudi" size={12} /></button>
          </div>
        ))}
        <div className="eqintesta"><span>tipo</span><span>Hz</span><span>dB</span><span>Q</span></div>
        <button className="chip" disabled={lista.length >= 10}
          onClick={() => onChange([...lista, { type: 'peak', freq: 1000, gain: 0, q: 1, on: true }])}>
          <Icon name="piu" size={12} />aggiungi banda</button>
      </div>
    </div>
  )
}

/** Scelta del plugin fra quelli installati, o un percorso scritto a mano. */
export function PluginFile({ value, onChange }) {
  const [installati, setInstallati] = useState(null)
  useEffect(() => { api.plugins().then((r) => setInstallati(r.plugin)).catch(() => setInstallati([])) }, [])
  const noto = installati?.some((p) => p.path === value)
  return (
    <div className="pluginfile">
      <select value={noto ? value : ''} onChange={(e) => e.target.value && onChange(e.target.value)}>
        <option value="">{installati == null ? 'cerco i plugin…' : installati.length
          ? 'scegli un plugin installato' : 'nessun plugin VST3 trovato'}</option>
        {(installati || []).map((p) => <option key={p.path} value={p.path}>{p.nome}</option>)}
      </select>
      <input value={value || ''} placeholder="oppure il percorso del file .vst3"
        onChange={(e) => onChange(e.target.value)} />
    </div>
  )
}

/** Parametri del plugin scelto: cursori, scelte e interruttori, con ricerca. */
export function PluginParams({ file, values, onChange }) {
  const [info, setInfo] = useState(null)
  const [errore, setErrore] = useState(null)
  const [cerca, setCerca] = useState('')
  const [tutti, setTutti] = useState(false)
  const [bozza, setBozza] = useState({})

  useEffect(() => {
    setInfo(null); setErrore(null)
    if (!file) return
    api.pluginParams(file).then(setInfo).catch((e) => setErrore(e.message))
  }, [file])

  if (!file) return <div className="hint">scegli un plugin per vederne i parametri</div>
  if (errore) return <div className="hint warn">{errore}</div>
  if (!info) return <div className="hint">leggo i parametri del plugin…</div>

  const vals = { ...(values || {}), ...bozza }
  const filtro = cerca.trim().toLowerCase()
  const lista = info.parametri.filter((p) => !filtro || p.etichetta.toLowerCase().includes(filtro))
  const visibili = tutti || filtro ? lista : lista.slice(0, 12)
  const conferma = (nome, v) => {
    setBozza((b) => { const c = { ...b }; delete c[nome]; return c })
    onChange({ ...(values || {}), [nome]: v })
  }

  return (
    <div className="pluginparams">
      <div className="pluginnome"><Icon name="audio" size={13} />{info.nome}
        <span className="hint">{info.parametri.length} parametri</span></div>
      <input className="cerca" placeholder="cerca un parametro" value={cerca}
        onChange={(e) => setCerca(e.target.value)} />
      {visibili.map((p) => {
        const v = vals[p.nome] ?? p.valore
        const cambiato = values && p.nome in values
        if (p.tipo === 'scelta') {
          return (
            <label key={p.nome} className={`pparam ${cambiato ? 'cambiato' : ''}`}>
              <span>{p.etichetta}</span>
              <select value={String(v)} onChange={(e) => conferma(p.nome, e.target.value)}>
                {p.scelte.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </label>
          )
        }
        if (p.tipo === 'bool') {
          return (
            <label key={p.nome} className={`pparam ${cambiato ? 'cambiato' : ''}`}>
              <span>{p.etichetta}</span>
              <input type="checkbox" checked={!!v} onChange={(e) => conferma(p.nome, e.target.checked)} />
            </label>
          )
        }
        const min = p.min ?? 0
        const max = p.max ?? 1
        const passo = (max - min) / 200 || 0.01
        return (
          <label key={p.nome} className={`pparam ${cambiato ? 'cambiato' : ''}`}>
            <span>{p.etichetta}</span>
            <input type="range" min={min} max={max} step={passo} value={Number(v) || 0}
              onChange={(e) => setBozza((b) => ({ ...b, [p.nome]: +e.target.value }))}
              onPointerUp={(e) => conferma(p.nome, +e.target.value)}
              onKeyUp={(e) => conferma(p.nome, +e.target.value)} />
            <span className="pvalore">{arrotonda(Number(v) || 0, 2)}{p.unita ? ` ${p.unita}` : ''}</span>
          </label>
        )
      })}
      {!tutti && !filtro && lista.length > 12 && (
        <button className="chip" onClick={() => setTutti(true)}>mostra tutti ({lista.length})</button>
      )}
    </div>
  )
}
