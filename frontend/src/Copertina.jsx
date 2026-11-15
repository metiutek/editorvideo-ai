import React, { useCallback, useEffect, useRef, useState } from 'react'
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

/**
 * Richiesta libera per l'assistente: un prompt e le immagini che servono
 * (la propria faccia, il prodotto, una miniatura da imitare). Le immagini si
 * caricano dal computer, si trascinano o si incollano; restano accanto al
 * progetto (``/api/chat/allega``), quindi possono anche diventare subito
 * opzioni di copertina senza passare dall'assistente.
 */
function Chiedi({ cover, run, setError, onChiedi }) {
  const [testo, setTesto] = useState('')
  const [immagini, setImmagini] = useState([])   // allegati: {name, path, size, tipo}
  const [caricando, setCaricando] = useState(0)
  const [sopra, setSopra] = useState(false)
  const fileRef = useRef(null)

  const carica = async (lista) => {
    const files = [...(lista || [])].filter((f) => IMMAGINE.test(f.name) || f.type?.startsWith('image/'))
    if (!files.length) return
    setCaricando((n) => n + files.length)
    try {
      const r = await api.allega(files)
      setImmagini((xs) => [...xs, ...r.allegati])
    } catch (e) { setError(e.message) } finally { setCaricando((n) => Math.max(0, n - files.length)) }
  }

  const invia = () => {
    const q = testo.trim()
    if (!q) return
    const nota = immagini.length
      ? `

The attached ${immagini.length === 1 ? 'image is' : 'images are'} for the cover: material to use or a reference to follow, as the request says.`
      : ''
    onChiedi?.(`Cover (thumbnail) for this video, not part of the edit. Make the options and add them with add_covers${cover ? '' : ', choosing the best one'}.

${q}${nota}`,
      immagini.map((a) => ({ kind: 'file', ...a })))
    setTesto('')
    setImmagini([])
  }

  const comeOpzioni = () => {
    if (!immagini.length) return
    run('add_covers', { paths: immagini.map((a) => a.path), choose: !cover })
      .then(() => setImmagini([])).catch((e) => setError(e.message))
  }

  return (
    <div className={`copertina-chiedi ${sopra ? 'sopra' : ''}`}
      onDragOver={(e) => { if (e.dataTransfer?.types?.includes('Files')) { e.preventDefault(); e.stopPropagation(); setSopra(true) } }}
      onDragLeave={() => setSopra(false)}
      onDrop={(e) => {
        if (!e.dataTransfer?.files?.length) return
        // il file e' per la copertina: App lo vede e non lo importa nel progetto
        e.preventDefault(); setSopra(false)
        carica(e.dataTransfer.files)
      }}>
      <textarea rows={3} value={testo}
        placeholder="Describe the cover: e.g. close-up of my face on the right, big yellow title “30 DAYS”, dark background like the image I attached"
        onChange={(e) => setTesto(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); invia() } }}
        onPaste={(e) => {
          const files = [...(e.clipboardData?.files || [])]
          if (files.length) { e.preventDefault(); carica(files) }
        }} />
      {(immagini.length > 0 || caricando > 0) && (
        <div className="copertina-allegati">
          {immagini.map((a) => (
            <div key={a.path} className="copertina-allegato" title={a.path}>
              <img src={url(a.path)} alt={a.name} />
              <button className="icon sm" title="Remove" aria-label={`Remove ${a.name}`}
                onClick={() => setImmagini((xs) => xs.filter((x) => x.path !== a.path))}>
                <Icon name="chiudi" size={12} /></button>
            </div>
          ))}
          {caricando > 0 && <div className="copertina-allegato attesa"><Icon name="attesa" className="spin" size={16} /></div>}
        </div>
      )}
      <div className="copertina-crea-riga">
        <button className="ghost" disabled={caricando > 0} onClick={() => fileRef.current?.click()}
          title="Images from your computer: you can also drop or paste them here">
          <Icon name="graffetta" size={14} />images</button>
        {immagini.length > 0 && (
          <button className="ghost" onClick={comeOpzioni} title="Use the images as they are, as cover options">
            <Icon name="piu" size={14} />as options</button>
        )}
        <button className="primary" disabled={!testo.trim() || caricando > 0} onClick={invia}
          title="The assistant makes the covers (Ctrl+Enter)">
          <Icon name="invia" size={14} />ask the assistant</button>
      </div>
      <input ref={fileRef} type="file" accept="image/*" multiple hidden
        onChange={(e) => { carica(e.target.files); e.target.value = '' }} />
    </div>
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
export default function Copertina({ project, revision, run, applyState, setError, onChiedi }) {
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

      <div className="section-title">ask for a cover</div>
      <Chiedi cover={cover} run={run} setError={setError} onChiedi={onChiedi} />

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
