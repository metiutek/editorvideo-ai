import React, { useCallback, useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { api } from './api.js'
import { FileBrowser } from './Dialogs.jsx'
import Icon from './Icons.jsx'
import { fmt } from './util.js'

const IMMAGINE = /\.(png|jpe?g|webp|gif|bmp)$/i

const url = (path, v = 0) => `/api/file?path=${encodeURIComponent(path)}&v=${v}`
const nome = (path) => path.split(/[\\/]/).pop()

/** Scarica il file com'e' (Content-Disposition dal server, download= per il nome). */
function Scarica({ path, label }) {
  return (
    <a className="icon sm copertina-scarica" href={`${url(path)}&download=true`} download={nome(path)}
      title={`Download ${nome(path)}`} aria-label={`Download ${nome(path)}`}>
      <Icon name="scarica" size={14} />{label}
    </a>
  )
}

/** Una copertina a schermo intero; frecce per le altre opzioni, Esc per uscire. */
function SchermoIntero({ opzioni, indice, scelta, onIndice, onScegli, onClose }) {
  const path = opzioni[indice]
  const vai = useCallback((d) => onIndice((indice + d + opzioni.length) % opzioni.length),
    [indice, opzioni.length, onIndice])

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') { e.preventDefault(); onClose() }
      else if (e.key === 'ArrowRight') vai(1)
      else if (e.key === 'ArrowLeft') vai(-1)
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [vai, onClose])

  return createPortal(
    <div className="copertina-intera" role="dialog" aria-label="Cover, full screen" onClick={onClose}>
      <img src={url(path)} alt={nome(path)} onClick={(e) => e.stopPropagation()} />
      <div className="copertina-intera-barra" onClick={(e) => e.stopPropagation()}>
        {opzioni.length > 1 && (
          <button className="icon" title="Previous (←)" onClick={() => vai(-1)}>
            <Icon name="sinistra" size={16} /></button>
        )}
        <span>{opzioni.length > 1 ? `${indice + 1} / ${opzioni.length} · ` : ''}{nome(path)}</span>
        {opzioni.length > 1 && (
          <button className="icon" title="Next (→)" onClick={() => vai(1)}>
            <Icon name="destra" size={16} /></button>
        )}
        {path === scelta
          ? <span className="copertina-scelta-tag"><Icon name="spunta" size={14} />chosen</span>
          : <button className="primary" onClick={() => onScegli(path)}>
            <Icon name="spunta" size={14} />use this one</button>}
        <Scarica path={path} label="download" />
        <button className="icon" title="Close (Esc)" onClick={onClose}><Icon name="chiudi" size={16} /></button>
      </div>
    </div>,
    document.body,
  )
}

/**
 * La copertina fatta a parte (Store.set_cover), guardata accanto al video:
 * intera nel formato del progetto e piccola come la vede chi scorre, con
 * titolo e durata. Le opzioni (Store.add_covers, make_covers) stanno sotto:
 * si guardano a schermo intero, si sceglie, si scarica. Il render non la usa.
 */
export default function Copertina({ project, revision, run, applyState, setError }) {
  const [info, setInfo] = useState(null)
  const [sfoglia, setSfoglia] = useState(false)
  const [giro, setGiro] = useState(0)   // "reload": l'immagine rifatta fuori dall'editor
  const [intera, setIntera] = useState(null)   // indice dell'opzione a schermo intero
  const [quante, setQuante] = useState(6)
  const [titolo, setTitolo] = useState('')
  const [lavoro, setLavoro] = useState(false)
  const cover = project?.cover || ''
  const opzioni = project?.covers?.length ? project.covers : (cover ? [cover] : [])

  useEffect(() => {
    if (!cover) { setInfo(null); return undefined }
    let vivo = true
    api.copertina().then((r) => { if (vivo) setInfo(r) }).catch(() => {})
    return () => { vivo = false }
  }, [cover, revision, giro])

  useEffect(() => {
    if (intera !== null && intera >= opzioni.length) setIntera(opzioni.length ? 0 : null)
  }, [intera, opzioni.length])

  if (!project) return <div className="copertina"><div className="hint">Open a project first.</div></div>

  const [w, h] = (project.settings.resolution || '1920x1080').split('x').map(Number)
  const verticale = h > w
  const src = cover && info?.cover === cover && !info.missing ? url(cover, info.mtime || 0) : null
  const fallito = (e) => setError(e.message)
  const scegli = (p) => run('set_cover', { path: p }).catch(fallito)
  const aggiungi = (paths) => {
    setSfoglia(false)
    const lista = (Array.isArray(paths) ? paths : [paths]).filter(Boolean)
    if (lista.length) run('add_covers', { paths: lista, choose: !cover }).catch(fallito)
  }
  const crea = () => {
    setLavoro(true)
    api.faiCopertine({ count: quante, title: titolo, choose: !cover })
      .then(applyState).catch(fallito).finally(() => setLavoro(false))
  }
  const vuota = !project.duration

  return (
    <div className="copertina">
      <div className="section-title">
        cover
        <span className="spacer" />
        {cover && (<>
          <button className="icon sm" title="Full screen" onClick={() => setIntera(Math.max(0, opzioni.indexOf(cover)))}>
            <Icon name="espandi" size={14} /></button>
          <Scarica path={cover} />
          <button className="icon sm" title="Reload: the image was changed outside the editor"
            onClick={() => setGiro((g) => g + 1)}><Icon name="ripeti" size={14} /></button>
        </>)}
      </div>

      {!cover ? (
        <div className="copertina-vuota">
          <Icon name="immagine" size={28} />
          <div className="hint">
            {opzioni.length
              ? 'Pick one of the options below: click it to see it full screen.'
              : 'Make cover options from the best frames of your edit, or add a thumbnail you made elsewhere. You see them next to the video, full size and as they look in a feed.'}
          </div>
        </div>
      ) : (<>
        <button className="copertina-grande" style={{ aspectRatio: `${w} / ${h}` }}
          title="Full screen" onClick={() => setIntera(Math.max(0, opzioni.indexOf(cover)))}>
          {src ? <img src={src} alt="cover" />
            : <span className="hint">{info?.missing ? 'the file is gone: choose it again' : 'loading…'}</span>}
        </button>

        <div className="hint copertina-dove">{verticale ? 'in a feed of shorts' : 'in a feed of videos'}</div>
        <div className={`copertina-feed ${verticale ? 'verticale' : ''}`}>
          <div className="copertina-mini" style={{ aspectRatio: verticale ? '9 / 16' : '16 / 9' }}>
            {src && <img src={src} alt="" />}
            {!verticale && project.duration > 0 && <span className="durata">{fmt(project.duration)}</span>}
          </div>
          <div className="copertina-titolo">
            <b>{project.name}</b>
            <span className="hint">your channel</span>
          </div>
        </div>

        {info?.width && (
          <div className="hint">
            {info.width}×{info.height} · {info.format} · {Math.round(info.bytes / 1024)} KB
          </div>
        )}
        {info?.warnings?.map((a) => <div key={a} className="copertina-avviso">{a}</div>)}
        <div className="copertina-percorso" title={cover}>{cover}</div>
      </>)}

      {opzioni.length > 0 && (<>
        <div className="section-title">options <span className="hint">{opzioni.length}</span></div>
        <div className={`copertina-opzioni ${verticale ? 'verticale' : ''}`}>
          {opzioni.map((p, i) => (
            <div key={p} className={`copertina-opzione ${p === cover ? 'on' : ''}`}>
              <button className="copertina-opzione-img" style={{ aspectRatio: `${w} / ${h}` }}
                title={`${nome(p)}: full screen`} onClick={() => setIntera(i)}>
                <img src={url(p, revision)} alt={nome(p)} loading="lazy" />
                {p === cover && <span className="copertina-spunta"><Icon name="spunta" size={12} /></span>}
              </button>
              <div className="copertina-opzione-barra">
                {p === cover
                  ? <span className="hint">chosen</span>
                  : <button className="ghost" onClick={() => scegli(p)}>use</button>}
                <span className="spacer" />
                <Scarica path={p} />
                <button className="icon sm" title="Remove from the options (the file stays)"
                  onClick={() => run('remove_cover', { path: p }).catch(fallito)}>
                  <Icon name="cestino" size={14} /></button>
              </div>
            </div>
          ))}
        </div>
      </>)}

      <div className="section-title">make options</div>
      <div className="copertina-crea">
        <label className="hint" htmlFor="copertina-titolo">title on the cover (optional)</label>
        <input id="copertina-titolo" value={titolo} placeholder="e.g. I tried it for 30 days"
          onChange={(e) => setTitolo(e.target.value)} />
        <div className="copertina-crea-riga">
          <label className="hint" htmlFor="copertina-quante">how many</label>
          <input id="copertina-quante" type="number" min={1} max={12} value={quante}
            onChange={(e) => setQuante(Math.max(1, Math.min(12, Number(e.target.value) || 1)))} />
          <button className="primary" disabled={lavoro || vuota} onClick={crea}
            title={vuota ? 'The timeline is empty' : 'The sharpest, most colorful frame of each part of the edit'}>
            <Icon name={lavoro ? 'attesa' : 'immagine'} size={14} />
            {lavoro ? 'making…' : `make ${quante} from the video`}</button>
        </div>
        <button className="ghost" onClick={() => setSfoglia(true)}>
          <Icon name="piu" size={14} />add images made elsewhere</button>
        <div className="hint">You can also ask the assistant: "make 6 covers with the title …".</div>
      </div>

      {intera !== null && opzioni[intera] && (
        <SchermoIntero opzioni={opzioni} indice={intera} scelta={cover}
          onIndice={setIntera} onScegli={scegli} onClose={() => setIntera(null)} />
      )}

      {sfoglia && (
        <FileBrowser title="Cover images" multiple memoria="copertina"
          filter={(n) => IMMAGINE.test(n)} onClose={() => setSfoglia(false)} onPick={aggiungi} />
      )}
    </div>
  )
}
