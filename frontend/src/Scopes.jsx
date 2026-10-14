import React, { useEffect, useState } from 'react'
import { api } from './api.js'

// review.SCOPI, con quello che serve sapere per leggerli
const VISTE = [
  ['waveform', 'waveform', 'Luminanza da sinistra a destra come nell\'immagine, in IRE: 0 nero, 100 bianco pieno. Sopra 100 e sotto 0 si perde dettaglio.'],
  ['parade', 'parade RGB', 'Rosso, verde e blu affiancati: su un grigio neutro le tre colonne stanno alla stessa altezza; quella piu\' alta e\' la dominante.'],
  ['vectorscope', 'vettorscopio', 'Tinta (angolo) e saturazione (distanza dal centro). La pelle cade sulla linea fra giallo e rosso; oltre i quadratini il colore e\' fuori gamma.'],
  ['histogram', 'istogramma', 'Quanti pixel per ogni livello, su scala logaritmica: ammassati ai bordi vuol dire nero chiuso o bianco bruciato.'],
]

/**
 * Scope del fotogramma sotto la testina. Si chiedono solo a riproduzione
 * ferma, e dopo una breve pausa: durante uno scrub ne partirebbe uno per
 * fotogramma, ognuno con un render dagli originali.
 */
export default function Scopes({ project, playhead, playing, revision }) {
  const [vista, setVistaState] = useState(() => {
    try { return localStorage.getItem('vedit.scope') || 'waveform' } catch { return 'waveform' }
  })
  const setVista = (v) => {
    setVistaState(v)
    try { localStorage.setItem('vedit.scope', v) } catch { /* resta per questa sessione */ }
  }
  const [src, setSrc] = useState(null)
  const [stato, setStato] = useState('')
  const vuoto = !project || !(project.duration > 0)

  useEffect(() => {
    if (vuoto || playing) return undefined
    const t = setTimeout(() => setSrc(api.scopeUrl(playhead, vista, revision)), 250)
    return () => clearTimeout(t)
  }, [vuoto, playing, playhead, vista, revision])

  const info = VISTE.find(([k]) => k === vista)
  return (
    <div className="scopes">
      <div className="scopes-scelta">
        {VISTE.map(([k, nome]) => (
          <button key={k} className={vista === k ? 'on' : ''} onClick={() => setVista(k)}>{nome}</button>
        ))}
      </div>
      {vuoto ? <div className="hint">Metti qualcosa in timeline: gli scope misurano il fotogramma sotto la testina.</div> : (
        <>
          <div className="scopes-img">
            {src && <img src={src} alt={info[1]} onLoad={() => setStato('')}
              style={vista === 'vectorscope' ? { maxWidth: 300 } : undefined}
              onError={() => setStato('scope non disponibile per questo fotogramma')} />}
            {playing && <div className="scopes-pausa">in pausa si aggiorna</div>}
          </div>
          {stato && <div className="hint errore">{stato}</div>}
          <div className="hint">{info[2]}</div>
          <div className="hint">Misurati sugli originali, non sui proxy.</div>
        </>
      )}
    </div>
  )
}
