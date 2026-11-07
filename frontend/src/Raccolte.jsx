import React, { useEffect, useRef, useState } from 'react'
import { api } from './api.js'
import { FileBrowser, Modal, SceltaFormato } from './Dialogs.jsx'
import Icon from './Icons.jsx'
import { FORMATI_VIDEO, fmt } from './util.js'
import { MenuProgetto } from './Progetti.jsx'

/**
 * Raccolte (raccolte.py): una cartella per qualunque gruppo di video con
 * qualcosa in comune (un canale YouTube o TikTok, i video di famiglia, un
 * cliente, una serie), con una memoria e delle immagini di riferimento che
 * valgono per tutti. L'assistente e l'agente MCP li ricevono a ogni video
 * della raccolta: logo, palette, persone, tono non si ripetono ogni volta.
 */

const IMMAGINE = /\.(png|jpe?g|webp|gif|bmp)$/i
const sep = (dir) => (dir && dir.includes('\\') ? '\\' : '/')
const nomeCartella = (n) => (n || 'collection').trim().replace(/[<>:"/\\|?*]+/g, '-')

// idee per il nome: dicono a colpo d'occhio che non serve solo per i canali
const ESEMPI = ['My YouTube channel', 'TikTok', 'Family videos', 'Travels', 'Client: Acme']

/** Le raccolte nella schermata iniziale: un clic apre la raccolta. */
export function RaccolteHome({ raccolte, onApri, onNuova }) {
  return (
    <div className="benvenuto-raccolte">
      <div className="ch-testa">
        <span className="hint">collections</span>
        <button className="ghost" onClick={onNuova}
          title="A folder for any group of videos: a channel, family videos, a client, a series. They share one memory and reference images">
          <Icon name="piu" size={14} />new collection</button>
      </div>
      {raccolte?.length > 0 ? (
        <div className="ch-griglia">
          {raccolte.map((c) => (
            <button key={c.path} className="ch-scheda" title={c.path} onClick={() => onApri(c.path)}>
              <Icon name="raccolta" size={18} />
              <span className="nome">{c.name}</span>
              <span className="hint">{c.description || c.path}</span>
            </button>
          ))}
        </div>
      ) : (
        <div className="hint">
          Group videos that belong together (a YouTube or TikTok channel, family videos, a client,
          a series): the assistant remembers their style, logo and people in every one.
        </div>
      )}
    </div>
  )
}

/** Raccolta nuova: nome, cartella proposta dalla cartella Video, descrizione. */
export function NuovaRaccolta({ home, onClose, onCreata, setError }) {
  const [nome, setNome] = useState('')
  const proposta = (n) => (home ? `${home}${sep(home)}${nomeCartella(n || 'collection')}` : '')
  const [cartella, setCartella] = useState(() => proposta(''))
  const [manuale, setManuale] = useState(false)
  const [desc, setDesc] = useState('')
  const [sfoglia, setSfoglia] = useState(false)

  const rinomina = (n) => { setNome(n); if (!manuale) setCartella(proposta(n)) }
  const crea = () => {
    if (!nome.trim()) return
    api.creaRaccolta(nome.trim(), cartella.trim() || null, desc)
      .then((c) => { onCreata(c); onClose() }).catch((e) => setError(e.message))
  }

  return (
    <Modal title="New collection" narrow onClose={onClose}
      actions={<>
        <button onClick={onClose}>cancel</button>
        <button className="primary" disabled={!nome.trim()} onClick={crea}>create</button>
      </>}>
      <div className="row"><label>name</label>
        <input value={nome} placeholder="e.g. Family videos" onKeyDown={(e) => e.key === 'Enter' && crea()}
          onChange={(e) => rinomina(e.target.value)} />
        <span /></div>
      <div className="ch-esempi">
        {ESEMPI.map((e) => (
          <button key={e} className="ghost" onClick={() => rinomina(e)}>{e}</button>
        ))}
      </div>
      <div className="row"><label>folder</label>
        <input value={cartella} onChange={(e) => { setManuale(true); setCartella(e.target.value) }} />
        <button className="icon sm" title="Choose a folder" onClick={() => setSfoglia(true)}>
          <Icon name="cartella" size={14} /></button></div>
      <div className="row" style={{ alignItems: 'start' }}><label>about</label>
        <textarea rows={3} value={desc} placeholder="What these videos are, who they are for, their tone"
          onChange={(e) => setDesc(e.target.value)} /><span /></div>
      <div className="hint" style={{ marginTop: 10 }}>
        Each video gets its own folder inside this one. An existing folder with projects becomes a
        collection with all of them.
      </div>
      {sfoglia && (
        <FileBrowser title="Collection folder" cartella memoria="raccolte" onClose={() => setSfoglia(false)}
          onPick={([p]) => { setManuale(true); setCartella(p) }} />
      )}
    </Modal>
  )
}

/** Il disegno del formato: un rettangolo nella proporzione del video. */
function Sagoma({ resolution }) {
  const [w, h] = (resolution || '16x9').split('x').map(Number)
  const k = 34 / Math.max(w || 16, h || 9)
  return <span className="sp-sagoma"><i style={{ width: (w || 16) * k, height: (h || 9) * k }} /></span>
}

const quando = (t) => {
  const d = new Date(t * 1000)
  return d.toDateString() === new Date().toDateString()
    ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : d.toLocaleDateString([], { day: 'numeric', month: 'short', year: 'numeric' })
}

/**
 * La raccolta come posto di lavoro, come un progetto di Claude: a sinistra i
 * suoi video (nuovo video con un clic, senza chiedere il titolo: si rinomina
 * dopo), a destra il contesto che vale per tutti — descrizione, memoria,
 * immagini di riferimento. Aprire un video porta all'editor; il nome della
 * raccolta in testata riporta qui.
 */
export function SpazioRaccolta({ path, raccolte, progettoAperto, onClose, onApriVideo, onCreaVideo,
  onCambiata, onProgetti, setError, flash }) {
  const [info, setInfo] = useState(null)
  const [nome, setNome] = useState('')
  const [desc, setDesc] = useState('')
  const [mem, setMem] = useState('')
  const [formato, setFormato] = useState('16:9')
  const [lato, setLato] = useState(1080)
  const [altriFormati, setAltriFormati] = useState(false)
  const [sfoglia, setSfoglia] = useState(false)
  const [sopra, setSopra] = useState(false)
  const [versione, setVersione] = useState(0)
  const [cerca, setCerca] = useState('')
  const file = useRef(null)

  const applica = (c, tutto = true) => {
    setInfo(c)
    if (tutto) { setNome(c.name); setDesc(c.description); setMem(c.memoria) }
    setVersione((v) => v + 1)
    onCambiata?.(c)
  }
  const ricarica = () => api.raccolta(path).then((c) => applica(c, false)).catch((e) => setError(e.message))
  useEffect(() => {
    api.raccolta(path).then((c) => {
      applica(c)
      if (c.formato?.preset) { setFormato(c.formato.preset); if (c.formato.size) setLato(c.formato.size) }
    }).catch((e) => { setError(e.message); onClose() })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path])

  const cambiata = info && (nome !== info.name || desc !== info.description || mem !== info.memoria)
  const salva = async () => {
    try {
      let c = info
      if (nome !== info.name || desc !== info.description) c = await api.modificaRaccolta(path, nome, desc)
      if (mem !== info.memoria) c = await api.memoriaRaccolta(path, mem)
      applica(c)
      flash?.('collection saved')
    } catch (e) { setError(e.message) }
  }
  const carica = (files) => {
    const imm = [...files].filter((f) => IMMAGINE.test(f.name))
    if (!imm.length) { setError('references are images: png, jpg, webp, gif'); return }
    api.caricaRiferimenti(path, imm).then((c) => applica(c, false)).catch((e) => setError(e.message))
  }
  const nuovoVideo = () => onCreaVideo({ path, preset: formato, size: lato })

  if (!info) {
    return <div className="spazio"><div className="empty"><Icon name="attesa" className="spin" /> opening…</div></div>
  }
  const video = info.video.filter((v) => !cerca || v.name.toLowerCase().includes(cerca.toLowerCase()))
  return (
    <div className="spazio"
      onDragOver={(e) => { if (e.dataTransfer.types.includes('Files')) { e.preventDefault(); e.stopPropagation() } }}
      onDrop={(e) => { e.preventDefault(); e.stopPropagation() }}>
      <div className="sp-testa">
        <button className="ghost" onClick={onClose}
          title={progettoAperto ? 'Back to the open video' : 'Back to the start screen'}>
          <Icon name="sinistra" size={14} />{progettoAperto ? 'back to the editor' : 'home'}</button>
        <span className="sp-icona"><Icon name="raccolta" size={20} /></span>
        <input className="sp-nome" value={nome} onChange={(e) => setNome(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && cambiata && salva()} aria-label="collection name" />
        <span className="spacer" />
        <span className="hint sp-percorso" title={info.path}>{info.path}</span>
        <button className="primary" disabled={!cambiata} onClick={salva}><Icon name="salva" size={14} />save</button>
      </div>

      <div className="sp-corpo">
        <section className="sp-video">
          <div className="sp-nuovo">
            <button className="primary sp-crea" onClick={nuovoVideo}>
              <Icon name="nuovo" />new video</button>
            <div className="sp-formati" role="radiogroup" aria-label="format of the new video">
              {FORMATI_VIDEO.slice(0, 4).map((f) => (
                <button key={f.id} type="button" role="radio" aria-checked={formato === f.id}
                  className={`ghost ${formato === f.id ? 'on' : ''}`} title={f.uso}
                  onClick={() => setFormato(f.id)}>{f.id}</button>
              ))}
              <button type="button" className={`ghost ${altriFormati ? 'on' : ''}`} title="Other formats and quality"
                onClick={() => setAltriFormati((v) => !v)}><Icon name="altro" size={14} /></button>
            </div>
            <span className="spacer" />
            {info.video.length > 6 && (
              <input className="sp-cerca" value={cerca} placeholder="search" onChange={(e) => setCerca(e.target.value)} />
            )}
          </div>
          {altriFormati && (
            <div className="sp-altri"><SceltaFormato formato={formato} lato={lato} onFormato={setFormato} onLato={setLato} /></div>
          )}

          <div className="sp-griglia">
            {video.map((v) => (
              <div key={v.path} className={`sp-scheda ${progettoAperto === v.path ? 'aperto' : ''}`}
                role="button" tabIndex={0} title={v.path}
                onClick={() => onApriVideo(v.path)}
                onKeyDown={(e) => e.key === 'Enter' && e.target === e.currentTarget && onApriVideo(v.path)}>
                <Sagoma resolution={v.resolution} />
                <span className="nome">{v.name}</span>
                <span className="hint">
                  {[v.duration ? fmt(v.duration) : 'empty', v.resolution, quando(v.modified)].filter(Boolean).join(' · ')}
                </span>
                <MenuProgetto path={v.path} name={v.name} raccolte={raccolte} setError={setError} flash={flash}
                  onApri={() => onApriVideo(v.path)}
                  onFatto={(r, azione) => { onProgetti?.(r, azione); ricarica() }} />
              </div>
            ))}
            {!info.video.length && (
              <div className="sp-vuoto">
                <Icon name="video" size={22} />
                <div>No videos yet. <b>new video</b> opens the editor right away: every video here
                  knows this collection's memory and references.</div>
              </div>
            )}
          </div>
        </section>

        <aside className="sp-contesto">
          <div className="hint sp-spiega">
            What you put here reaches the assistant in every video of the collection.
          </div>
          <section>
            <h4>about</h4>
            <textarea rows={4} value={desc} onChange={(e) => setDesc(e.target.value)}
              placeholder="What these videos are, who they are for, their tone" />
          </section>

          <section>
            <h4>references <span className="hint">logo, thumbnails, palette, people</span></h4>
            <div className={`ch-rif ${sopra ? 'sopra' : ''}`}
              onDragOver={(e) => { if (e.dataTransfer.types.includes('Files')) { e.preventDefault(); e.stopPropagation(); setSopra(true) } }}
              onDragLeave={() => setSopra(false)}
              onDrop={(e) => {
                e.preventDefault(); e.stopPropagation(); setSopra(false)
                if (e.dataTransfer.files?.length) carica(e.dataTransfer.files)
              }}>
              {info.riferimenti.map((r) => (
                <Riferimento key={r.file} rif={r} src={api.immagineRaccolta(path, r.file, versione)}
                  onNota={(nota) => api.notaRiferimento(path, r.file, nota).then((c) => applica(c, false)).catch((e) => setError(e.message))}
                  onTogli={() => api.togliRiferimento(path, r.file).then((c) => applica(c, false)).catch((e) => setError(e.message))} />
              ))}
              <div className="ch-aggiungi">
                <span className="hint">drop images here</span>
                <button onClick={() => file.current?.click()}><Icon name="piu" size={14} />upload</button>
                <button className="ghost" onClick={() => setSfoglia(true)}><Icon name="cartella" size={14} />from disk…</button>
              </div>
            </div>
            <input ref={file} type="file" accept="image/*" multiple hidden
              onChange={(e) => { if (e.target.files?.length) carica(e.target.files); e.target.value = '' }} />
          </section>

          <section>
            <h4>memory <span className="hint">audience, tone, format, people, mistakes to avoid</span></h4>
            <textarea className="memoria-testo" style={{ minHeight: 170 }} value={mem} spellCheck={false}
              onChange={(e) => setMem(e.target.value)}
              placeholder={'## people\n- Anna and Luca, the kids\n\n## graphics\n- yellow subtitles, logo top right'} />
            <div className="hint">The assistant adds lines here when you tell it something that holds for these videos.</div>
          </section>
        </aside>
      </div>
      {sfoglia && (
        <FileBrowser title="Reference images" memoria="raccolta-rif" onClose={() => setSfoglia(false)}
          filter={(n) => IMMAGINE.test(n)}
          onPick={(paths) => api.aggiungiRiferimenti(path, paths).then((c) => applica(c, false)).catch((e) => setError(e.message))} />
      )}
    </div>
  )
}

/** Un'immagine di riferimento con la sua nota: si salva uscendo dal campo. */
function Riferimento({ rif, src, onNota, onTogli }) {
  const [nota, setNota] = useState(rif.nota)
  useEffect(() => setNota(rif.nota), [rif.nota])
  return (
    <div className="ch-img">
      <img src={src} alt={rif.file} title={rif.file} loading="lazy" />
      <div className="ch-riga">
        <span className="hint" title={rif.file}>{rif.file}</span>
        <button className="icon sm danger" title="Remove the reference" onClick={onTogli}>
          <Icon name="cestino" size={13} /></button>
      </div>
      <input value={nota} placeholder="what it is, how to use it"
        onChange={(e) => setNota(e.target.value)}
        onBlur={() => nota !== rif.nota && onNota(nota)}
        onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()} />
    </div>
  )
}
