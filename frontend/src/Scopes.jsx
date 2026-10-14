import React, { useEffect, useState } from 'react'
import { api } from './api.js'

// review.SCOPI, con quello che serve sapere per leggerli
const VISTE = [
  ['waveform', 'waveform', 'Luminance from left to right as in the picture, in IRE: 0 black, 100 full white. Above 100 and below 0 detail is lost.'],
  ['parade', 'RGB parade', 'Red, green and blue side by side: on a neutral grey the three columns sit at the same height; the tallest one is the cast.'],
  ['vectorscope', 'vectorscope', 'Hue (angle) and saturation (distance from the centre). Skin falls on the line between yellow and red; past the small boxes the colour is out of gamut.'],
  ['histogram', 'histogram', 'How many pixels per level, on a log scale: piled at the edges means crushed blacks or clipped whites.'],
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
      {vuoto ? <div className="hint">Put something in the timeline: the scopes measure the frame under the playhead.</div> : (
        <>
          <div className="scopes-img">
            {src && <img src={src} alt={info[1]} onLoad={() => setStato('')}
              style={vista === 'vectorscope' ? { maxWidth: 300 } : undefined}
              onError={() => setStato('scope not available for this frame')} />}
            {playing && <div className="scopes-pausa">updates when paused</div>}
          </div>
          {stato && <div className="hint errore">{stato}</div>}
          <div className="hint">{info[2]}</div>
          <div className="hint">Measured on the originals, not the proxies.</div>
        </>
      )}
    </div>
  )
}
