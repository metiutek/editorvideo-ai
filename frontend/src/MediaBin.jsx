import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Icon from './Icons.jsx'
import useMediaAssets from './mediaAssets.js'
import { leggiTrascinati, useFineTrascinamento } from './trascina.js'
import { fmt } from './util.js'

const ICON = { audio: 'audio', image: 'immagine', video: 'video' }

// Misure del riquadro di anteprima, in pixel. Servono qui e non solo nel CSS
// perche' la striscia di fotogrammi si posiziona calcolando quale riquadro
// mostrare, e il conto vuole numeri.
const TH_W = 52
const TH_H = 30

/**
 * Un fotogramma preso dal mezzo del filmato.
 *
 * La striscia e' un'unica immagine con un fotogramma per secondo: se ne mostra
 * uno spostando lo sfondo, senza chiedere niente in piu' al server. Si prende
 * quello centrale perche' i primi secondi sono spesso neri o una sigla.
 */
function Miniatura({ strip }) {
  const w = Math.max(2, Math.round(TH_H * (strip.tile_width / strip.tile_height)))
  const scelto = Math.floor(strip.tiles / 2)
  return (
    <div className="thumb" style={{
      backgroundImage: `url(${strip.url})`,
      backgroundSize: `${strip.tiles * w}px ${TH_H}px`,
      backgroundPosition: `${-scelto * w + (TH_W - w) / 2}px center`,
    }} />
  )
}

/** Forma d'onda in miniatura: dice a colpo d'occhio dove c'e' segnale. */
function Onda({ peaks }) {
  const punti = 26
  const passo = Math.max(1, Math.floor(peaks.length / punti))
  const barre = []
  for (let i = 0; i < peaks.length && barre.length < punti; i += passo) {
    barre.push(Math.max(...peaks.slice(i, i + passo)))
  }
  return (
    <div className="thumb onda">
      {barre.map((v, i) => (
        // eslint-disable-next-line react/no-array-index-key
        <i key={i} style={{ height: `${Math.max(8, v * 100)}%` }} />
      ))}
    </div>
  )
}

/**
 * Elenco dei media organizzato in cartelle.
 * Le cartelle non esistono su disco: sono un'etichetta sul media, quindi
 * spostare un file nel bin non tocca nulla sul filesystem.
 */
/**
 * Quali media del pannello sono a schermo (con un margine).
 *
 * Le miniature si chiedono solo per quelli: con mille file importati il
 * pannello ne mostra una ventina, e generare le altre novecento strisce prima
 * di quelle visibili e' lavoro che nessuno guarda. Senza IntersectionObserver
 * (jsdom, browser vecchi) ``visibili`` e' null e si chiede tutto, come prima.
 */
function useVisibili() {
  const [visibili, setVisibili] = useState(() =>
    (typeof IntersectionObserver === 'undefined' ? null : new Set()))
  const lista = useRef(null)
  const osservatore = useRef(null)
  const inAttesa = useRef(new Set())

  const listaRef = useCallback((el) => {
    lista.current = el
    osservatore.current?.disconnect()
    osservatore.current = null
    if (!el || typeof IntersectionObserver === 'undefined') return
    osservatore.current = new IntersectionObserver((voci) => {
      setVisibili((prima) => {
        const dopo = new Set(prima)
        for (const v of voci) {
          const id = v.target.dataset.media
          if (v.isIntersecting) dopo.add(id); else dopo.delete(id)
        }
        return dopo
      })
    }, { root: el, rootMargin: '400px 0px' })
    for (const voce of inAttesa.current) osservatore.current.observe(voce)
  }, [])

  const osserva = useCallback((el) => {
    if (!el) return
    inAttesa.current.add(el)
    osservatore.current?.observe(el)
  }, [])

  // le voci smontate escono dall'elenco, altrimenti l'insieme cresce per sempre
  useEffect(() => () => osservatore.current?.disconnect(), [])
  useEffect(() => {
    for (const el of inAttesa.current) {
      if (!el.isConnected) { inAttesa.current.delete(el); osservatore.current?.unobserve(el) }
    }
  })
  return { visibili, osserva, listaRef }
}

const GB = 1e9
const misura = (b) => (b >= GB ? `${(b / GB).toFixed(1)} GB` : `${Math.round(b / 1e6)} MB`)

/** Copia o import in corso: quanti file, quanti byte, a che velocita', e come fermarlo. */
function Avanzamento({ stato, onAnnulla }) {
  const copia = stato.fase === 'copio'
  const sec = Math.max(0.5, (Date.now() - stato.inizio) / 1000)
  const quota = copia && stato.byte
    ? stato.inviati / stato.byte
    : stato.fatti / Math.max(1, stato.file)
  return (
    <div className="avanzamento">
      <div className="riga">
        <Icon name="attesa" className="spin" />
        <span>
          {copia ? 'copio' : 'importo'} {stato.fatti}/{stato.file} file
          {copia && stato.byte > 0 && <> · {misura(stato.inviati)} di {misura(stato.byte)}
            {' '}· {misura(stato.inviati / sec)}/s</>}
        </span>
        <span className="spacer" />
        {onAnnulla && <button className="sm" onClick={onAnnulla}>ferma</button>}
      </div>
      <div className="barra"><i style={{ width: `${Math.min(100, quota * 100).toFixed(1)}%` }} /></div>
      {stato.scartati.length > 0 && (
        <div className="hint">{stato.scartati.length} file non letti</div>
      )}
      {copia && stato.byte > 2 * GB && (
        <div className="hint">
          I file trascinati vengono copiati accanto al progetto. Per usarli dove sono,
          senza copia: <b>+</b> → «importa cartella».
        </div>
      )}
    </div>
  )
}

export default function MediaBin({
  project, run, setError, onOpenSource, onImport, uploading, onAnnulla, ask,
}) {
  const [open, setOpen] = useState({})
  const [dragOver, setDragOver] = useState(null)
  // il tratteggio di lista e cartelle si spegne comunque finisca il trascinamento
  useFineTrascinamento(useCallback(() => setDragOver(null), []))
  const [newFolder, setNewFolder] = useState(null)   // nome in scrittura, null = nessuno
  const media = project?.media || []
  const { visibili, osserva, listaRef } = useVisibili()
  const daMostrare = useMemo(
    () => (visibili ? media.filter((m) => visibili.has(m.id)) : media), [media, visibili])
  const assets = useMediaAssets(daMostrare, 1)

  const tree = useMemo(() => {
    const folders = new Map()
    const root = []
    for (const m of media) {
      const key = (m.folder || '').trim()
      if (!key) { root.push(m); continue }
      if (!folders.has(key)) folders.set(key, [])
      folders.get(key).push(m)
    }
    return { root, folders: [...folders.entries()].sort((a, b) => a[0].localeCompare(b[0])) }
  }, [media])

  const move = (mediaId, folder) =>
    run('set_media', { media_id: mediaId, folder }).catch((e) => setError(e.message))

  const dropTarget = (folder) => ({
    onDragOver: (e) => { e.preventDefault(); setDragOver(folder) },
    onDragLeave: () => setDragOver((f) => (f === folder ? null : f)),
    onDrop: (e) => {
      e.preventDefault()
      e.stopPropagation()
      setDragOver(null)
      const id = e.dataTransfer.getData('text/media')
      if (id) { move(id, folder); return }
      if (e.dataTransfer.files?.length) onImport(leggiTrascinati(e.dataTransfer), folder)
    },
  })

  const removeMedia = (m) => run('remove_media', { media_id: m.id }).catch((err) => {
    if (!err.message.includes('force')) { setError(err.message); return }
    ask({
      title: 'Il media è in uso',
      message: `${err.message}\n\nEliminando ${m.name} spariranno anche quelle clip dalla timeline.`,
      ok: 'elimina comunque', danger: true,
      onOk: () => run('remove_media', { media_id: m.id, force: true })
        .catch((e2) => setError(e2.message)),
    })
  })

  // Un clic apre il monitor sorgente, due accodano in timeline. Il browser
  // manda anche il clic singolo prima del doppio: senza questa attesa il doppio
  // clic accodava la clip *e* portava sul monitor sorgente, e chi voleva solo
  // mettere il file in timeline si ritrovava in un'altra scheda.
  const clicSingolo = useRef(null)
  const apri = (m) => {
    clearTimeout(clicSingolo.current)
    clicSingolo.current = setTimeout(() => onOpenSource(m), 220)
  }
  const accoda = (m) => {
    clearTimeout(clicSingolo.current)
    run('add_clip', { media_id: m.id }).catch((e) => setError(e.message))
  }

  // una funzione e non un componente: definito qui dentro, React lo vedrebbe
  // nuovo a ogni render e rimonterebbe ogni voce (e l'osservatore con lei)
  const voce = (m) => {
    const strip = assets.strip(m)
    const peaks = m.kind === 'audio' ? assets.peaks(m) : null
    return (
    <div
      key={m.id} className="media" draggable data-media={m.id} ref={osserva}
      onDragStart={(e) => {
        clearTimeout(clicSingolo.current)
        e.dataTransfer.setData('text/media', m.id)
        e.dataTransfer.effectAllowed = 'copyMove'
      }}
      onClick={() => apri(m)}
      onDoubleClick={() => accoda(m)}
      title="clic: apri nel monitor · doppio clic: accoda in timeline · trascina: timeline o cartella"
    >
      {/* finche' l'anteprima non e' arrivata resta l'icona: il riquadro ha
          comunque la sua misura, cosi' l'elenco non sobbalza quando arriva */}
      {strip?.url ? <Miniatura strip={strip} />
        : peaks?.length ? <Onda peaks={peaks} />
          : <div className="thumb vuoto"><Icon name={ICON[m.kind] || 'video'} /></div>}
      <div className="meta">
        <div className="mname">{m.name}</div>
        <div className="msub">
          {m.duration ? `${fmt(m.duration)} ` : ''}{m.resolution || ''}{m.audio ? ' · audio' : ''}
        </div>
      </div>
      <button className="icon sm danger" title="Togli dal progetto"
        onClick={(e) => { e.stopPropagation(); removeMedia(m) }}>
        <Icon name="chiudi" size={13} />
      </button>
    </div>
    )
  }

  return (
    <div className="side">
      <div className="section-title">
        media
        <span className="spacer" />
        <button className="icon sm" disabled={!project} title="Nuova cartella"
          onClick={() => setNewFolder('')}><Icon name="cartellaPiu" size={14} /></button>
        <button className="icon sm" disabled={!project} title="Importa file dal disco"
          onClick={() => onImport(null)}><Icon name="piu" size={14} /></button>
      </div>

      <div className={`medialist ${dragOver === '' ? 'droptarget' : ''}`} ref={listaRef}
        {...dropTarget('')}>
        {newFolder !== null && (
          <div className="folder">
            <Icon name="cartella" />
            <input autoFocus value={newFolder} placeholder="nome della cartella"
              style={{ height: 20 }}
              onChange={(e) => setNewFolder(e.target.value)}
              onBlur={() => setNewFolder(null)}
              onKeyDown={(e) => {
                if (e.key === 'Escape') setNewFolder(null)
                if (e.key === 'Enter' && newFolder.trim()) {
                  setOpen((o) => ({ ...o, [newFolder.trim()]: true }))
                  setNewFolder(null)
                }
              }} />
          </div>
        )}

        {tree.folders.map(([name, items]) => (
          <div key={name}>
            <div className={`folder ${dragOver === name ? 'droptarget' : ''}`}
              {...dropTarget(name)}
              onClick={() => setOpen((o) => ({ ...o, [name]: !o[name] }))}>
              <Icon name={open[name] === false ? 'giu' : 'su'} size={13} />
              <Icon name="cartella" />
              <span>{name}</span>
              <span className="spacer" />
              <span className="hint">{items.length}</span>
            </div>
            {open[name] !== false && items.map(voce)}
          </div>
        ))}

        {Object.keys(open).filter((f) => !tree.folders.some(([n]) => n === f)).map((f) => (
          <div key={f} className={`folder vuota ${dragOver === f ? 'droptarget' : ''}`} {...dropTarget(f)}>
            <Icon name="cartella" /><span>{f}</span>
            <span className="spacer" /><span className="hint">trascina qui</span>
          </div>
        ))}

        {tree.root.map(voce)}

        {project && !media.length && (
          <div className="hint" style={{ padding: 16, textAlign: 'center' }}>
            Nessun file.<br />Usa <b>+</b> oppure trascina qui i video dal desktop.
          </div>
        )}
        {!project && (
          <div className="hint" style={{ padding: 16, textAlign: 'center' }}>
            Nessun progetto aperto.
          </div>
        )}
        {uploading && <Avanzamento stato={uploading} onAnnulla={onAnnulla} />}
      </div>
    </div>
  )
}
