import React, { useEffect, useRef, useState } from 'react'
import { api } from './api.js'
import { Confirm, FileBrowser, Modal } from './Dialogs.jsx'
import Icon from './Icons.jsx'

/**
 * I file dei progetti (progetti.py): rinominare, duplicare, spostare in una
 * raccolta o in una cartella, eliminare nel cestino e ripristinare. Ogni
 * risposta del server porta recenti e raccolte aggiornati: ``onFatto`` li
 * passa a chi tiene gli elenchi.
 */

/** Il menu "..." di un progetto: nella schermata iniziale, in una raccolta, in testata. */
export function MenuProgetto({ path, name, raccolte, onApri, onChiudi, onFatto, setError, flash, titolo }) {
  const [aperto, setAperto] = useState(false)
  const [finestra, setFinestra] = useState(null)   // 'rinomina' | 'sposta' | 'elimina'
  const box = useRef(null)

  useEffect(() => {
    if (!aperto) return undefined
    const fuori = (e) => { if (!box.current?.contains(e.target)) setAperto(false) }
    const esc = (e) => { if (e.key === 'Escape') setAperto(false) }
    window.addEventListener('pointerdown', fuori)
    window.addEventListener('keydown', esc)
    return () => { window.removeEventListener('pointerdown', fuori); window.removeEventListener('keydown', esc) }
  }, [aperto])

  const fatto = (azione, msg) => (r) => { onFatto?.(r, azione); if (msg) flash?.(msg(r), 3500) }
  const errore = (e) => setError(e.message)
  const voce = (icona, testo, fn, cls = '') => (
    <button className={`ghost ${cls}`} onClick={() => { setAperto(false); fn() }}>
      <Icon name={icona} size={14} />{testo}</button>
  )

  return (
    <span className="menu-progetto" ref={box} onClick={(e) => e.stopPropagation()}>
      <button className="icon sm" title={titolo || 'Rename, duplicate, move, delete'}
        aria-haspopup="menu" aria-expanded={aperto} onClick={() => setAperto((a) => !a)}>
        <Icon name="altro" size={15} /></button>
      {aperto && (
        <div className="menu-voci" role="menu">
          {onApri && voce('apri', 'open', onApri)}
          {voce('testo', 'rename…', () => setFinestra('rinomina'))}
          {voce('copia', 'duplicate', () => api.duplicaProgetto(path)
            .then(fatto('duplica', (r) => `duplicated as «${r.name}»`)).catch(errore))}
          {voce('raccolta', 'move to…', () => setFinestra('sposta'))}
          {onChiudi && voce('chiudi', 'close project', onChiudi)}
          <span className="menu-sep" />
          {voce('cestino', 'delete', () => setFinestra('elimina'), 'danger')}
        </div>
      )}
      {finestra === 'rinomina' && (
        <RinominaProgetto nome={name} onClose={() => setFinestra(null)}
          onRinomina={(nome) => api.rinominaProgetto(path, nome)
            .then(fatto('rinomina', (r) => `renamed «${r.name}»`)).catch(errore)} />
      )}
      {finestra === 'sposta' && (
        <SpostaProgetto path={path} nome={name} raccolte={raccolte} onClose={() => setFinestra(null)}
          onSposta={(dove) => api.spostaProgetto(path, dove)
            .then(fatto('sposta', (r) => (r.raccolta ? `moved into ${r.raccolta.name}` : `moved to ${r.path}`)))
            .catch(errore)} />
      )}
      {finestra === 'elimina' && (
        <Confirm title="Delete the project" danger ok="move to trash" onClose={() => setFinestra(null)}
          message={<>Move «{name}» to the trash? The media files stay on disk. You can restore it
            from the trash for 30 days.</>}
          onOk={() => api.eliminaProgetto(path)
            .then(fatto('elimina', (r) => `«${r.name}» moved to the trash`)).catch(errore)} />
      )}
    </span>
  )
}

function RinominaProgetto({ nome, onClose, onRinomina }) {
  const [v, setV] = useState(nome || '')
  const ok = v.trim() && v.trim() !== nome
  const vai = () => { if (ok) { onRinomina(v.trim()); onClose() } }
  return (
    <Modal narrow title="Rename the project" onClose={onClose}
      actions={<>
        <button onClick={onClose}>cancel</button>
        <button className="primary" disabled={!ok} onClick={vai}>rename</button>
      </>}>
      <div className="row"><label>name</label>
        <input value={v} onChange={(e) => setV(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && vai()}
          onFocus={(e) => e.target.select()} /><span /></div>
      <div className="hint" style={{ marginTop: 8 }}>The file and its folder follow the name when they can.</div>
    </Modal>
  )
}

/** Dove portare il progetto: una raccolta (nella sua cartella per video) o una cartella. */
function SpostaProgetto({ path, nome, raccolte, onClose, onSposta }) {
  const [sfoglia, setSfoglia] = useState(false)
  const vai = (dove) => { onSposta(dove); onClose() }
  return (
    <Modal narrow title={`Move «${nome}»`} onClose={onClose}
      actions={<button onClick={onClose}>cancel</button>}>
      <div className="hint" style={{ marginBottom: 8 }}>into a collection: it gets its memory and references</div>
      <div className="sposta-elenco">
        {(raccolte || []).map((c) => {
          const dentro = path.startsWith(c.path + (c.path.includes('\\') ? '\\' : '/'))
          return (
            <button key={c.path} className="ghost recente" disabled={dentro} title={c.path}
              onClick={() => vai({ raccolta: c.path })}>
              <Icon name="raccolta" size={14} /><span className="nome">{c.name}</span>
              {dentro && <span className="hint">already here</span>}
            </button>
          )
        })}
        {!raccolte?.length && <div className="hint">No collections yet.</div>}
      </div>
      <button style={{ marginTop: 10 }} onClick={() => setSfoglia(true)}>
        <Icon name="cartella" size={14} />to a folder…</button>
      {sfoglia && (
        <FileBrowser title="Move to folder" cartella memoria="sposta" onClose={() => setSfoglia(false)}
          onPick={([p]) => vai({ cartella: p })} />
      )}
    </Modal>
  )
}

const quando = (t) => new Date(t * 1000).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })

/** I progetti eliminati: si ripristinano dov'erano, o si cancellano per sempre. */
export function Cestino({ onClose, onFatto, setError, flash }) {
  const [voci, setVoci] = useState(null)
  const [svuota, setSvuota] = useState(false)
  const ricarica = () => api.cestino().then(setVoci).catch((e) => setError(e.message))
  useEffect(() => { ricarica() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <Modal title="Trash" onClose={onClose}
      actions={<>
        <button className="ghost danger" disabled={!voci?.length} onClick={() => setSvuota(true)}>
          <Icon name="cestino" size={14} />empty the trash</button>
        <span className="spacer" />
        <button onClick={onClose}>close</button>
      </>}>
      <div className="hint" style={{ marginBottom: 8 }}>
        Deleted projects stay here for 30 days. Their media files were never touched.
      </div>
      <div className="cestino-elenco">
        {voci?.map((v) => (
          <div key={v.id} className="cestino-voce">
            <Icon name="video" size={14} />
            <span className="nome" title={v.path}>{v.name}</span>
            <span className="hint">{[v.raccolta, quando(v.quando)].filter(Boolean).join(' · ')}</span>
            <button className="ghost" title={`Back to ${v.path}`}
              onClick={() => api.ripristina(v.id).then((r) => {
                onFatto?.(r, 'ripristina'); flash?.(`«${r.name}» restored`); ricarica()
              }).catch((e) => setError(e.message))}>
              <Icon name="ripristina" size={14} />restore</button>
            <button className="icon sm danger" title="Delete forever"
              onClick={() => api.svuotaCestino(v.id).then(ricarica).catch((e) => setError(e.message))}>
              <Icon name="chiudi" size={13} /></button>
          </div>
        ))}
        {voci && !voci.length && <div className="hint">The trash is empty.</div>}
      </div>
      {svuota && (
        <Confirm title="Empty the trash" danger ok="delete forever" onClose={() => setSvuota(false)}
          message={`Delete ${voci.length} project${voci.length === 1 ? '' : 's'} forever? This cannot be undone.`}
          onOk={() => api.svuotaCestino().then(ricarica).catch((e) => setError(e.message))} />
      )}
    </Modal>
  )
}
