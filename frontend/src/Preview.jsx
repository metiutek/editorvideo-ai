import React, { useEffect, useRef, useState } from 'react'
import { api } from './api.js'
import Gizmo from './Gizmo.jsx'
import LivePlayer from './LivePlayer.jsx'
import useFrame from './useFrame.js'
import { fmt, mostraEsatto } from './util.js'

const SEGMENT = 12   // secondi renderizzati per volta durante la riproduzione
// Il primo pezzo si aspetta da fermi, con il dito ancora sul tasto play: va
// tenuto corto. Quelli dopo si preparano mentre il precedente e' in onda, e li'
// conviene il contrario — meno stacchi, meno occasioni di restare a secco.
const PRIMO = 4

/**
 * Anteprima fedele al render finale: da fermi si mostra il fotogramma
 * renderizzato da ffmpeg, in riproduzione si scarica un segmento in bozza.
 * Il segmento successivo viene preparato mentre il corrente e' in onda, cosi'
 * il passaggio non si sente.
 */
export default function Preview({
  project, revision, playhead, seek, playing, setPlaying, clip, run, setError, prova,
  diretta = true, pickArea = false, onArea, onCancelArea,
}) {
  const videoRef = useRef(null)
  const imgRef = useRef(null)
  const [segment, setSegment] = useState(null)   // {start, duration, url}
  const [loading, setLoading] = useState(false)
  const [failed, setFailed] = useState(null)
  const [approssimato, setApprossimato] = useState(false)
  const duration = project?.duration || 0

  // il progetto e' cambiato mentre si riproduce in modalita' fedele: ci si
  // ferma e si riparte a mano, perche' il segmento in onda e' stato
  // renderizzato dalla versione precedente. In diretta invece il browser
  // compone dal progetto corrente: la modifica si vede senza fermarsi.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { if (playing && !diretta) setPlaying(false) }, [revision])

  // avvio riproduzione: prepara il segmento a partire dalla testina
  useEffect(() => {
    if (diretta) { setSegment(null); return }
    if (!playing || duration <= 0) { setSegment(null); return }
    const start = playhead >= duration - 0.05 ? 0 : playhead
    const len = Math.min(PRIMO, duration - start)
    if (len <= 0.05) { setPlaying(false); return }
    setLoading(true)
    setFailed(null)
    setSegment({ start, duration: len, url: api.previewUrl(start, len, revision) })
    // dipende solo dall'avvio: durante la riproduzione i segmenti si concatenano da soli
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing])

  // cache predittiva: il pezzo dopo quello in onda
  useEffect(() => {
    if (diretta || !segment || loading) return
    const next = segment.start + segment.duration
    if (next < duration - 0.05) api.prefetch(next, Math.min(SEGMENT, duration - next))
  }, [segment?.start, loading, duration])

  // da fermi: prepara il segmento sotto la testina, cosi' play parte subito
  useEffect(() => {
    if (diretta || playing || duration <= 0) return
    const id = setTimeout(() => {
      // esattamente il pezzo che chiederebbe play: preparane uno da dodici
      // secondi voleva dire tre volte il lavoro, e comunque non quello giusto
      if (playhead < duration - 0.05) api.prefetch(playhead, Math.min(PRIMO, duration - playhead))
    }, 900)
    return () => clearTimeout(id)
    // diretta fra le dipendenze: passando di modo il lavoro gia' in coda va
    // annullato, altrimenti parte un render che nessuno guardera'
  }, [playhead, playing, revision, duration, diretta])

  const onEnded = () => {
    const next = segment.start + segment.duration
    if (next >= duration - 0.05) { setPlaying(false); seek(duration); return }
    const len = Math.min(SEGMENT, duration - next)
    setLoading(true)
    setSegment({ start: next, duration: len, url: api.previewUrl(next, len, revision) })
  }

  useEffect(() => {
    const v = videoRef.current
    if (v && segment && !loading) {
      // il browser puo' rifiutare l'avvio automatico: senza avviso sembra che il
      // pulsante play non faccia niente
      v.play().catch(() => { setFailed('il browser ha bloccato la riproduzione'); setPlaying(false) })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [segment, loading])

  /** Il player non dice perche' ha fallito: il motivo lo sa il server. */
  const onVideoError = () => {
    setPlaying(false)
    setFailed('anteprima non disponibile')
    if (!segment) return
    fetch(segment.url)
      .then((r) => (r.ok ? null : r.json().catch(() => null)))
      .then((body) => { if (body?.detail) setFailed(body.detail) })
      .catch(() => {})
  }

  const empty = !project || duration <= 0

  // In diretta il fotogramma da ffmpeg serve da fermi dove il browser non sa
  // rifare tutto (glitch, warp, LUT...): senza, non c'era modo di vedere un
  // effetto se non passando a "fedele". In modalita' fedele e per la prova di
  // un effetto serve sempre.
  const usaFrame = !empty && !playing && (!diretta || prova || approssimato)
  const frame = useFrame(
    usaFrame
      ? api.frameUrl(Math.min(playhead, Math.max(0, duration - 0.02)), revision, 960, prova)
      : null,
  )
  // il fotogramma esatto copre la diretta solo se e' quello della testina: uno
  // vecchio mentre si trascina mostrerebbe l'istante sbagliato
  const esatto = mostraEsatto({ diretta, prova, approssimato, playing, url: frame.url, pending: frame.pending })

  return (
    <div className="preview">
      {empty ? (
        <div className="empty">
          Timeline vuota.<br />Importa dei file e trascinali qui sotto.
        </div>
      ) : diretta && !prova ? (
        <>
          <LivePlayer project={project} playhead={playhead} seek={seek}
            playing={playing} setPlaying={setPlaying} onApprossimato={setApprossimato}
            esatto={esatto ? frame.url : null} />
          {approssimato && (
            esatto ? (
              <div className="badge sottile" title="Fotogramma calcolato da ffmpeg, uguale all'export.">
                fotogramma esatto
              </div>
            ) : (
              <div className="badge sottile" title={
                'In riproduzione la composizione la fa il browser: glitch, warp, LUT,'
                + ' chroma key, glow, curve, tendine e scorrimenti non si vedono.'
                + '\nFermati per il fotogramma esatto, o passa a "fedele" per riprodurlo esatto.'}>
                {playing ? 'approssimata: fermati per vedere gli effetti' : 'calcolo il fotogramma esatto…'}
              </div>
            )
          )}
        </>
      ) : playing && segment ? (
        <>
          {/* il fotogramma resta a video finche' il segmento non e' pronto:
              altrimenti premendo play lo schermo diventa nero e sembra rotto */}
          {loading && (
            <img src={api.frameUrl(Math.min(segment.start, Math.max(0, duration - 0.02)), revision)}
              alt="" />
          )}
          <video
            ref={videoRef}
            src={segment.url}
            onLoadedData={() => setLoading(false)}
            onTimeUpdate={(e) => seek(segment.start + e.target.currentTime, true)}
            onEnded={onEnded}
            onError={onVideoError}
            style={{ visibility: loading ? 'hidden' : 'visible' }}
          />
          {loading && <div className="badge">preparo l'anteprima…</div>}
        </>
      ) : (
        <>
          {frame.url && <img ref={imgRef} src={frame.url} alt="" />}
          <Gizmo project={project} clip={clip} imgRef={imgRef} playhead={playhead}
            run={run} setError={setError} />
          {prova
            ? <div className="badge prova">{prova.label} — anteprima, non applicato</div>
            : frame.pending && <div className="badge sottile">aggiorno…</div>}
        </>
      )}
      {pickArea && !empty && <AreaPicker onArea={onArea} onCancel={onCancelArea} />}
      {(failed || (frame.failed && !playing)) && (
        <div className="badge">{failed || 'fotogramma non disponibile'}</div>
      )}
      {!empty && (!playing || diretta) && (
        <div className="badge" style={{ left: 'auto', right: 12 }}>
          {fmt(playhead)} / {fmt(duration)}
        </div>
      )}
    </div>
  )
}

/**
 * Riquadro da disegnare sull'inquadratura, per indicare all'assistente un punto
 * preciso ("questo logo", "quella scritta"). Le misure tornano in frazioni del
 * fotogramma, quindi valgono a qualunque dimensione del monitor.
 */
function AreaPicker({ onArea, onCancel }) {
  const ref = useRef(null)
  const [box, setBox] = useState(null)

  useEffect(() => {
    const esc = (e) => { if (e.key === 'Escape') onCancel?.() }
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [onCancel])

  const fotogramma = () => {
    const host = ref.current?.parentElement
    return host?.querySelector('.livecanvas') || host?.querySelector('img')
  }

  const down = (e) => {
    const r = ref.current.getBoundingClientRect()
    const x0 = e.clientX - r.left
    const y0 = e.clientY - r.top
    ref.current.setPointerCapture(e.pointerId)
    let ultimo = { x: x0, y: y0, w: 0, h: 0 }
    const move = (ev) => {
      const x1 = ev.clientX - r.left
      const y1 = ev.clientY - r.top
      ultimo = { x: Math.min(x0, x1), y: Math.min(y0, y1), w: Math.abs(x1 - x0), h: Math.abs(y1 - y0) }
      setBox(ultimo)
    }
    const up = () => {
      ref.current?.removeEventListener('pointermove', move)
      setBox(null)
      const f = fotogramma()?.getBoundingClientRect()
      if (!f || ultimo.w < 6 || ultimo.h < 6) return
      const ax = (r.left + ultimo.x - f.left) / f.width
      const ay = (r.top + ultimo.y - f.top) / f.height
      const x = Math.max(0, Math.min(1, ax))
      const y = Math.max(0, Math.min(1, ay))
      const w = Math.max(0, Math.min(1, ax + ultimo.w / f.width) - x)
      const h = Math.max(0, Math.min(1, ay + ultimo.h / f.height) - y)
      if (w > 0.005 && h > 0.005) onArea?.({ x, y, w, h })
    }
    ref.current.addEventListener('pointermove', move)
    ref.current.addEventListener('pointerup', up, { once: true })
  }

  return (
    <div className="areapick" ref={ref} onPointerDown={down}>
      {box && <div className="areabox" style={{ left: box.x, top: box.y, width: box.w, height: box.h }} />}
      <div className="badge prova">disegna un riquadro su quello che vuoi indicare · Esc annulla</div>
    </div>
  )
}
