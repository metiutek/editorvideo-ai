import React, { useEffect, useState } from 'react'
import { api } from './api.js'
import { Modal } from './Dialogs.jsx'
import Icon from './Icons.jsx'

/**
 * Immagini e video da un prompt (generativo.py): il servizio e le chiavi, e una
 * generazione a mano. Le chiavi restano su questo computer (~/.vedit/gen.json).
 * Generare costa crediti di chi ha la chiave: qui lo decide chi preme il
 * bottone; quando lo chiede l'assistente, l'editor domanda prima.
 */
export default function Generazione({ run, setError, flash, onClose }) {
  const [stato, setStato] = useState(null)
  const [sid, setSid] = useState('')
  const [tipo, setTipo] = useState('image')
  const [prompt, setPrompt] = useState('')
  const [formato, setFormato] = useState('16:9')
  const [durata, setDurata] = useState(5)
  const [chiave, setChiave] = useState('')
  const [indirizzo, setIndirizzo] = useState('')
  const [modello, setModello] = useState('')
  const [lavoro, setLavoro] = useState('')

  const applicaStato = (st) => {
    setStato(st)
    setSid((s) => s || st.motore || st.motori[0]?.id || '')
  }
  useEffect(() => {
    api.gen().then(applicaStato).catch((e) => { setError(e.message); onClose() })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const m = stato?.motori.find((x) => x.id === sid)
  // un servizio che non sa fare il tipo scelto: si passa a quello che sa
  useEffect(() => {
    if (m && !m.tipi.includes(tipo)) setTipo(m.tipi[0])
  }, [m, tipo])
  useEffect(() => {
    setChiave('')
    setIndirizzo(m?.indirizzo || '')
    setModello(m?.modelli?.[tipo] || '')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sid, tipo, stato === null])

  const salva = async () => {
    setLavoro('saving…')
    try {
      const st = await api.setGen({
        servizio: sid, chiave: chiave || null,
        indirizzo: m?.id === 'openai' ? indirizzo : null,
        ...(tipo === 'image' ? { modello_immagini: modello } : { modello_video: modello }),
      })
      applicaStato(st)
      setChiave('')
      const ora = st.motori.find((x) => x.id === sid)
      if (ora && !ora.pronto[tipo]) setError(ora.motivo?.[tipo] || 'the service is not ready')
      return !!ora?.pronto[tipo]
    } catch (e) { setError(e.message); return false } finally { setLavoro('') }
  }

  const genera = async () => {
    if (!prompt.trim()) return
    // chiave, indirizzo o modello appena scritti valgono da subito
    if (!(await salva())) return
    setLavoro(tipo === 'video' ? 'generating the video — it can take minutes…' : 'generating…')
    try {
      const r = await api.generaMedia({
        kind: tipo, prompt, aspect: formato, servizio: sid,
        modello: modello || null, duration: tipo === 'video' ? durata : null,
      })
      await run('import_media', { paths: [r.path], folder: 'generated' })
      flash(r.cache ? 'already generated: imported again, nothing spent' : `${tipo} generated and imported`)
      onClose()
    } catch (e) { setError(e.message) } finally { setLavoro('') }
  }

  return (
    <Modal title="Generate an image or a video" onClose={onClose}
      actions={<>
        <button onClick={onClose}>cancel</button>
        <button disabled={!stato || !!lavoro} onClick={salva} title="Keep the key and model without generating">
          save settings
        </button>
        <button className="primary" disabled={!stato || !prompt.trim() || !!lavoro} onClick={genera}>
          <Icon name="immagine" />{lavoro || 'generate and import'}
        </button>
      </>}>
      {!stato ? <div className="hint">loading…</div> : (<>
        <div className="provgrid">
          {stato.motori.map((x) => (
            <button key={x.id} className={`prov ${x.id === sid ? 'on' : ''}`} onClick={() => setSid(x.id)}>
              <span className={`dot ${Object.values(x.pronto).some(Boolean) ? 'ok' : ''}`} />
              <span className="pnome">{x.nome}</span>
            </button>
          ))}
        </div>
        {m && (
          <div className="provform" style={{ marginTop: 10 }}>
            <div className="hint">{m.nota}</div>
            {m.chiave && (
              <label className="campo"><span>API key</span>
                <input type="password" autoComplete="off" value={chiave}
                  placeholder={m.ha_chiave ? 'saved' : 'paste the key here'}
                  onChange={(e) => setChiave(e.target.value)} />
              </label>
            )}
            {m.id === 'openai' && (
              <label className="campo"><span>address</span>
                <input value={indirizzo} placeholder="https://…/v1"
                  onChange={(e) => setIndirizzo(e.target.value)} />
              </label>
            )}
            <label className="campo"><span>{tipo} model</span>
              <input value={modello} placeholder="default"
                onChange={(e) => setModello(e.target.value)} />
            </label>
            {m.motivo?.[tipo] && <div className="hint warn">{m.motivo[tipo]}</div>}
          </div>
        )}
        <div className="row">
          {['image', 'video'].map((t) => (
            <button key={t} className={`ghost ${t === tipo ? 'on' : ''}`}
              disabled={!m?.tipi.includes(t)} onClick={() => setTipo(t)}>{t}</button>
          ))}
          <select value={formato} onChange={(e) => setFormato(e.target.value)}>
            {['16:9', '9:16', '1:1'].map((f) => <option key={f} value={f}>{f}</option>)}
          </select>
          {tipo === 'video' && (
            <select value={durata} onChange={(e) => setDurata(Number(e.target.value))}>
              {[5, 10].map((d) => <option key={d} value={d}>{d} s</option>)}
            </select>
          )}
        </div>
        <label className="campo"><span>what to generate</span>
          <textarea className="voce-testo" value={prompt} onChange={(e) => setPrompt(e.target.value)}
            placeholder="A lighthouse at dusk, waves breaking, warm light from the window…" />
        </label>
        <div className="hint">
          It uses credits on your account at the service. Keys stay on this computer
          (~/.vedit/gen.json); the file is saved next to the project and the same request is never
          paid twice.
        </div>
      </>)}
    </Modal>
  )
}
