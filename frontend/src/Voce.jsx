import React, { useEffect, useState } from 'react'
import { api } from './api.js'
import { Modal } from './Dialogs.jsx'
import Icon from './Icons.jsx'

/**
 * Voce fuori campo dal testo (tts.py). Ogni paragrafo e' una battuta: la
 * prima parte dalla testina, le altre in fila. Generare e' fuori dal progetto
 * (/api/tts/genera); metterle in timeline e' un'operazione sola
 * (add_voiceover), quindi un solo Ctrl+Z.
 */
export default function Voce({ playhead, run, setError, flash, onClose }) {
  const [stato, setStato] = useState(null)
  const [mid, setMid] = useState('')
  const [testo, setTesto] = useState('')
  const [voce, setVoce] = useState('')
  const [velocita, setVelocita] = useState(1)
  const [istruzioni, setIstruzioni] = useState('')
  const [chiave, setChiave] = useState('')
  const [indirizzo, setIndirizzo] = useState('')
  const [lavoro, setLavoro] = useState('')

  const applicaStato = (st) => {
    setStato(st)
    setMid((m) => m || st.motore)
  }
  useEffect(() => {
    api.tts().then(applicaStato).catch((e) => { setError(e.message); onClose() })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const m = stato?.motori.find((x) => x.id === mid)
  useEffect(() => {
    setVoce(m?.voce || '')
    setIndirizzo(m?.indirizzo || '')
    setChiave('')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mid, stato === null])

  const voci = m ? (m.id === 'system' ? stato.voci_sistema : m.voci) : []
  const battute = testo.split(/\n\s*\n/).map((t) => t.trim()).filter(Boolean)

  const salvaMotore = async () => {
    setLavoro('saving…')
    try {
      const st = await api.setTts({
        motore: mid, voce, chiave: chiave || null,
        indirizzo: m?.indirizzo_modificabile ? indirizzo : null,
      })
      applicaStato(st)
      setChiave('')
      const ora = st.motori.find((x) => x.id === mid)
      if (ora && !ora.pronto) setError(ora.motivo)
      return ora?.pronto
    } catch (e) { setError(e.message); return false } finally { setLavoro('') }
  }

  const genera = async () => {
    if (!battute.length) return
    // chiave o indirizzo appena scritti valgono da subito
    if ((chiave || (m?.indirizzo_modificabile && indirizzo !== m.indirizzo) || !m?.pronto)
        && !(await salvaMotore())) return
    setLavoro(`generating ${battute.length > 1 ? `${battute.length} lines` : 'the voice'}…`)
    try {
      const lines = battute.map((text, i) => (i === 0 ? { text, start: playhead } : { text }))
      const { voci: files } = await api.generaVoce({
        lines, motore: mid, voce, velocita, istruzioni,
      })
      await run('add_voiceover', { items: files })
      flash(`${files.length} voice ${files.length > 1 ? 'clips' : 'clip'} on the VO track`)
      onClose()
    } catch (e) { setError(e.message) } finally { setLavoro('') }
  }

  return (
    <Modal title="Voiceover from text" onClose={onClose}
      actions={<>
        <button onClick={onClose}>cancel</button>
        <button className="primary" disabled={!stato || !battute.length || !!lavoro} onClick={genera}>
          <Icon name="voce" />{lavoro || 'generate and add'}
        </button>
      </>}>
      {!stato ? <div className="hint">loading…</div> : (<>
        <div className="provgrid">
          {stato.motori.map((x) => (
            <button key={x.id} className={`prov ${x.id === mid ? 'on' : ''}`} onClick={() => setMid(x.id)}>
              <span className={`dot ${x.pronto ? 'ok' : ''}`} />
              <span className="pnome">{x.nome}</span>
            </button>
          ))}
        </div>
        {m && (
          <div className="provform" style={{ marginTop: 10 }}>
            <div className="hint">{m.nota}</div>
            {m.vuole_chiave && (
              <label className="campo"><span>API key</span>
                <input type="password" autoComplete="off" value={chiave}
                  placeholder={m.chiave ? `saved (${m.chiave})` : 'paste the key here'}
                  onChange={(e) => setChiave(e.target.value)} />
              </label>
            )}
            {m.indirizzo_modificabile && (
              <label className="campo"><span>address</span>
                <input value={indirizzo} placeholder="https://…/v1"
                  onChange={(e) => setIndirizzo(e.target.value)} />
              </label>
            )}
            <label className="campo"><span>voice</span>
              <input list="voci-tts" value={voce}
                placeholder={m.id === 'piper' ? 'C:\\voices\\it_IT-paola-medium.onnx' : 'default'}
                onChange={(e) => setVoce(e.target.value)} />
              <datalist id="voci-tts">{voci.map((v) => <option key={v} value={v} />)}</datalist>
            </label>
            {!m.pronto && m.motivo && <div className="hint warn">{m.motivo}</div>}
          </div>
        )}
        <label className="campo"><span>text — one paragraph per line, separated by an empty line</span>
          <textarea className="voce-testo" value={testo} onChange={(e) => setTesto(e.target.value)}
            placeholder="What the voice says. The first line starts at the playhead, the others follow." />
        </label>
        <div className="row"><label>speed</label>
          <input type="range" min={0.5} max={2} step={0.05} value={velocita}
            onChange={(e) => setVelocita(Number(e.target.value))} />
          <span className="hint">{velocita.toFixed(2)}x</span></div>
        {mid === 'openai' && (
          <label className="campo"><span>how to say it (tone, pace, emotion)</span>
            <input value={istruzioni} placeholder="calm and warm, like a documentary narrator"
              onChange={(e) => setIstruzioni(e.target.value)} />
          </label>
        )}
        <div className="hint">
          Keys stay on this computer (~/.vedit/tts.json). Audio files are saved next to the project.
        </div>
      </>)}
    </Modal>
  )
}
