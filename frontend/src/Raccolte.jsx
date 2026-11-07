import React, { useEffect, useRef, useState } from 'react'
import { api } from './api.js'
import { FileBrowser, Modal, SceltaFormato } from './Dialogs.jsx'
import Icon from './Icons.jsx'
import { fmt } from './util.js'

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

/**
 * La raccolta: dettagli, video, memoria e riferimenti. Note e immagini si
 * salvano subito; nome, descrizione e memoria col pulsante "save".
 */
export function Raccolta({ path, onClose, onApriVideo, onCreaVideo, onCambiata, setError, flash }) {
  const [info, setInfo] = useState(null)
  const [nome, setNome] = useState('')
  const [desc, setDesc] = useState('')
  const [mem, setMem] = useState('')
  const [video, setVideo] = useState('')
  const [formato, setFormato] = useState('16:9')
  const [lato, setLato] = useState(1080)
  const [sfoglia, setSfoglia] = useState(false)
  const [sopra, setSopra] = useState(false)
  const [versione, setVersione] = useState(0)
  const file = useRef(null)

  const applica = (c) => {
    setInfo(c); setNome(c.name); setDesc(c.description); setMem(c.memoria)
    setVersione((v) => v + 1)
    onCambiata?.(c)
  }
  useEffect(() => {
    api.raccolta(path).then(applica).catch((e) => { setError(e.message); onClose() })
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
    api.caricaRiferimenti(path, imm).then(applica).catch((e) => setError(e.message))
  }
  const nuovoVideo = () => {
    const n = video.trim()
    if (!n) return
    onCreaVideo({ path, nome: n, preset: formato, size: lato })
    onClose()
  }

  if (!info) return null
  return (
    <Modal title={`Collection · ${info.name}`} wide onClose={onClose}
      actions={<>
        <span className="hint" title={info.path}>{info.path}</span>
        <span className="spacer" />
        <button onClick={onClose}>close</button>
        <button className="primary" disabled={!cambiata} onClick={salva}>save</button>
      </>}>
      <div className="ch-vista">
        <section>
          <div className="row"><label>name</label>
            <input value={nome} onChange={(e) => setNome(e.target.value)} /><span /></div>
          <div className="row" style={{ alignItems: 'start' }}><label>about</label>
            <textarea rows={3} value={desc} onChange={(e) => setDesc(e.target.value)}
              placeholder="What these videos are, who they are for, their tone: the assistant reads it in every video" />
            <span /></div>
        </section>

        <section>
          <h4>videos <span className="hint">{info.video.length}</span></h4>
          <div className="ch-video">
            {info.video.map((v) => (
              <button key={v.path} className="ghost recente" title={v.path}
                onClick={() => { onApriVideo(v.path); onClose() }}>
                <Icon name="video" size={14} />
                <span className="nome">{v.name}</span>
                <span className="hint">{[v.resolution, v.duration ? fmt(v.duration) : 'empty'].filter(Boolean).join(' · ')}</span>
              </button>
            ))}
            {!info.video.length && <div className="hint">No videos yet.</div>}
          </div>
          <div className="ch-nuovo">
            <input value={video} placeholder="title of the new video" onChange={(e) => setVideo(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && nuovoVideo()} />
            <button className="primary" disabled={!video.trim()} onClick={nuovoVideo}>
              <Icon name="nuovo" size={14} />new video</button>
          </div>
          {video.trim() && <SceltaFormato formato={formato} lato={lato} onFormato={setFormato} onLato={setLato} />}
        </section>

        <section>
          <h4>references <span className="hint">logo, thumbnails, palette, people, graphics</span></h4>
          <div className={`ch-rif ${sopra ? 'sopra' : ''}`}
            onDragOver={(e) => { if (e.dataTransfer.types.includes('Files')) { e.preventDefault(); e.stopPropagation(); setSopra(true) } }}
            onDragLeave={() => setSopra(false)}
            onDrop={(e) => {
              e.preventDefault(); e.stopPropagation(); setSopra(false)
              if (e.dataTransfer.files?.length) carica(e.dataTransfer.files)
            }}>
            {info.riferimenti.map((r) => (
              <Riferimento key={r.file} rif={r} src={api.immagineRaccolta(path, r.file, versione)}
                onNota={(nota) => api.notaRiferimento(path, r.file, nota).then(applica).catch((e) => setError(e.message))}
                onTogli={() => api.togliRiferimento(path, r.file).then(applica).catch((e) => setError(e.message))} />
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
          <h4>memory <span className="hint">audience, tone, format, recurring people and names, mistakes to avoid</span></h4>
          <textarea className="memoria-testo" style={{ minHeight: 150 }} value={mem} spellCheck={false}
            onChange={(e) => setMem(e.target.value)}
            placeholder={'## people\n- Anna and Luca, the kids\n\n## graphics\n- yellow subtitles, logo top right'} />
          <div className="hint">The assistant adds lines here when you tell it something that holds for these videos.</div>
        </section>
      </div>
      {sfoglia && (
        <FileBrowser title="Reference images" memoria="raccolta-rif" onClose={() => setSfoglia(false)}
          filter={(n) => IMMAGINE.test(n)}
          onPick={(paths) => api.aggiungiRiferimenti(path, paths).then(applica).catch((e) => setError(e.message))} />
      )}
    </Modal>
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
