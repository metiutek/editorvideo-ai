import React, { useEffect, useRef, useState } from 'react'
import { api } from './api.js'
import Icon from './Icons.jsx'
import { FORMATI_VIDEO, dimensioni, formatoDi } from './util.js'

/**
 * Finestra modale.
 *
 * Il fuoco entra nella finestra all'apertura e non ne esce con Tab: senza,
 * si tabula dentro l'editor sotto senza vederlo, e Esc non chiude niente.
 */
export function Modal({ title, children, onClose, actions, narrow }) {
  const box = useRef(null)

  useEffect(() => {
    const prev = document.activeElement
    const focusables = () => box.current?.querySelectorAll(
      'button:not(:disabled), input:not(:disabled), select, textarea, [tabindex]:not([tabindex="-1"])'
    ) || []
    // primo campo di testo se c'e', altrimenti il primo comando
    const first = box.current?.querySelector('input:not([type=checkbox]), textarea')
      || focusables()[0]
    first?.focus()

    const onKey = (e) => {
      if (e.key === 'Escape') { e.preventDefault(); onClose(); return }
      if (e.key !== 'Tab') return
      const f = [...focusables()]
      if (!f.length) return
      const i = f.indexOf(document.activeElement)
      if (e.shiftKey && (i <= 0)) { e.preventDefault(); f[f.length - 1].focus() }
      else if (!e.shiftKey && i === f.length - 1) { e.preventDefault(); f[0].focus() }
    }
    window.addEventListener('keydown', onKey, true)
    // Il fuoco torna dove stava, ma *dopo* che il tasto che ha chiuso la
    // finestra ha finito il suo giro: con Invio in un campo la finestra si
    // chiude a keydown, il fuoco tornava sul pulsante "nuovo" e il keypress
    // dello stesso Invio lo premeva, riaprendo la finestra appena chiusa.
    return () => {
      window.removeEventListener('keydown', onKey, true)
      setTimeout(() => prev?.focus?.(), 0)
    }
  }, [onClose])

  return (
    <div className="overlay" onPointerDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`dialog ${narrow ? 'narrow' : ''}`} ref={box}
        role="dialog" aria-modal="true" aria-label={title}>
        <h3>{title}</h3>
        <div className="body">{children}</div>
        <div className="foot">{actions}</div>
      </div>
    </div>
  )
}

/** Conferma per le azioni che distruggono lavoro. */
export function Confirm({ title, message, ok = 'confirm', danger, onOk, onClose }) {
  return (
    <Modal narrow title={title} onClose={onClose}
      actions={<>
        <button onClick={onClose}>cancel</button>
        <button className="primary" onClick={() => { onOk(); onClose() }}>
          {danger && <Icon name="cestino" />}{ok}
        </button>
      </>}>
      <div style={{ lineHeight: 1.6 }}>{message}</div>
    </Modal>
  )
}

/** Ultima cartella visitata per ogni uso (import, apri): si riparte da li'. */
const ricordaCartella = (chiave, path) => {
  try { if (chiave && path) localStorage.setItem(`vedit.cartella.${chiave}`, path) } catch { /* niente */ }
}
const cartellaRicordata = (chiave) => {
  try { return chiave ? localStorage.getItem(`vedit.cartella.${chiave}`) : null } catch { return null }
}

/**
 * Sfoglia il disco: usato sia per importare media sia per aprire progetti.
 *
 * Il percorso in cima si puo' scrivere (Invio per andarci), e la cartella da
 * cui si parte e' l'ultima usata per quello scopo: arrivare ai propri file a
 * colpi di clic dalla cartella utente era la cosa piu' lenta dell'editor.
 * ``recenti`` mette in cima un elenco di scorciatoie (i progetti aperti di
 * recente): un clic e si apre.
 */
export function FileBrowser({
  title, filter, multiple = true, onPick, onClose, startPath, memoria, recenti, cartella = false,
  onPickFolder,
}) {
  const [cwd, setCwd] = useState(null)
  const [picked, setPicked] = useState([])
  const [err, setErr] = useState(null)
  const [scritto, setScritto] = useState(null)   // percorso in scrittura, null = non attivo

  const load = (path) => api.browse(path).then((d) => {
    setCwd(d); setErr(null); setScritto(null); ricordaCartella(memoria, d.path)
  }).catch((e) => setErr(e.message))
  useEffect(() => { load(startPath || cartellaRicordata(memoria) || undefined) }, [])

  const files = (cwd?.files || []).filter((f) => (filter ? filter(f.name) : true))
  const toggle = (path) => setPicked((p) =>
    p.includes(path) ? p.filter((x) => x !== path) : (multiple ? [...p, path] : [path]))
  const scegli = (paths) => { onPick(paths); onClose() }

  return (
    <Modal
      title={title} onClose={onClose}
      actions={<>
        <span className="hint">{picked.length ? `${picked.length} selected` : ''}</span>
        <span className="spacer" />
        <button onClick={onClose}>cancel</button>
        {!cartella && multiple && files.length > 1 && (
          <button title="Select every file in this folder"
            onClick={() => setPicked(files.map((f) => f.path))}>all ({files.length})</button>
        )}
        {onPickFolder && (
          // la scheda di una camera, la cartella di un girato: tutto, sottocartelle
          // comprese, usato dove sta e senza copiarlo
          <button disabled={!cwd || cwd.path === '::dischi'}
            title="Import every media file in this folder and its subfolders, without copying them"
            onClick={() => { onPickFolder(cwd.path); onClose() }}>import folder</button>
        )}
        {cartella ? (
          <button className="primary" disabled={!cwd || cwd.path === '::dischi'} onClick={() => scegli([cwd.path])}>
            use this folder</button>
        ) : (
          <button className="primary" disabled={!picked.length}
            onClick={() => scegli(picked)}>confirm</button>
        )}
      </>}
    >
      {err && <div className="hint" style={{ color: 'var(--danger)', marginBottom: 8 }}>{err}</div>}
      <input
        className="crumb percorso" value={scritto ?? (cwd?.path === '::dischi' ? 'drives' : cwd?.path) ?? ''} placeholder="folder path"
        title="Type a path and press Enter to go there"
        onChange={(e) => setScritto(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && scritto?.trim()) { e.preventDefault(); load(scritto.trim()) }
          if (e.key === 'Escape' && scritto !== null) { e.stopPropagation(); setScritto(null) }
        }}
        onBlur={() => setScritto(null)}
      />
      <div className="browser">
        {recenti?.length > 0 && !picked.length && (
          <>
            <div className="item hint" style={{ cursor: 'default' }}>recent projects</div>
            {recenti.map((r) => (
              <div className="item recente" key={r.path} title={r.path}
                onClick={() => scegli([r.path])}>
                <Icon name="apri" /> {r.name}
                <span className="spacer" style={{ flex: 1 }} />
                <span className="hint">{r.path}</span>
              </div>
            ))}
            <div className="item hint" style={{ cursor: 'default' }}>browse</div>
          </>
        )}
        {cwd?.parent && (
          <div className="item" onClick={() => { setPicked([]); load(cwd.parent) }}>
            <Icon name="cartella" /> ..
          </div>
        )}
        {(cwd?.dirs || []).map((d) => (
          <div className="item" key={d.path} onClick={() => { setPicked([]); load(d.path) }}>
            <Icon name="cartella" /> {d.name}
          </div>
        ))}
        {files.map((f) => (
          <div className={`item ${picked.includes(f.path) ? 'picked' : ''}`} key={f.path}
            // scegliendo una cartella i file si vedono ma non si selezionano
            style={cartella ? { opacity: .6, cursor: 'default' } : undefined}
            onClick={() => !cartella && toggle(f.path)}
            onDoubleClick={() => !cartella && scegli([f.path])}>
            <Icon name="video" /> {f.name}
            <span className="spacer" style={{ flex: 1 }} />
            <span className="hint">{(f.size / 1e6).toFixed(1)} MB</span>
          </div>
        ))}
        {!cwd && <div className="item hint">loading…</div>}
        {cwd && !files.length && !cwd.dirs?.length && (
          <div className="item hint">empty folder</div>
        )}
      </div>
    </Modal>
  )
}

/** Separatore di cartelle di chi sta usando l'editor: Windows o il resto. */
const sep = (dir) => (dir && dir.includes('\\') ? '\\' : '/')

/** Nome di file sicuro: niente caratteri che il filesystem rifiuta. */
const nomeFile = (name) => (name || 'project').trim().replace(/[<>:"/\\|?*]+/g, '-')

const QUALITA = [{ lato: 720, nome: '720p' }, { lato: 1080, nome: '1080p' },
  { lato: 1440, nome: '1440p' }, { lato: 2160, nome: '4K' }]

/** Riquadri cliccabili, ognuno disegnato nella sua proporzione. */
function SceltaFormato({ formato, lato, onFormato, onLato }) {
  return (
    <>
      <div className="formati" role="radiogroup" aria-label="aspect ratio">
        {FORMATI_VIDEO.map((f) => {
          const k = 26 / Math.max(f.a, f.b)
          return (
            <button key={f.id} type="button" role="radio" aria-checked={formato === f.id}
              className={`formato${formato === f.id ? ' on' : ''}`} title={f.uso}
              onClick={() => onFormato(f.id)}>
              <span className="sagoma"><i style={{ width: f.a * k, height: f.b * k }} /></span>
              <b>{f.id}</b><small>{f.uso}</small>
            </button>
          )
        })}
      </div>
      <div className="row"><label>quality</label>
        <select value={lato} onChange={(e) => onLato(Number(e.target.value))}>
          {QUALITA.map((q) => <option key={q.lato} value={q.lato}>{q.nome}</option>)}
        </select>
        <span className="hint">{(dimensioni(formato, lato) || []).join(' x ')}</span></div>
    </>
  )
}

/**
 * Nuovo progetto. Il percorso viene proposto dalla cartella Video dell'utente
 * e segue il nome finche' non lo si tocca a mano: prima bisognava inventarsi
 * un percorso completo e scriverlo per esteso, per un'azione che si fa per
 * prima appena si apre l'editor.
 */
export function NewProject({ home, onCreate, onClose }) {
  const [name, setName] = useState('new project')
  const [formato, setFormato] = useState('16:9')
  const [lato, setLato] = useState(1080)
  const [fps, setFps] = useState(30)
  const proposto = (n) => (home ? `${home}${sep(home)}${nomeFile(n)}.json` : '')
  const [path, setPath] = useState(() => proposto('new project'))
  const [pathManuale, setPathManuale] = useState(false)

  const rinomina = (n) => {
    setName(n)
    if (!pathManuale) setPath(proposto(n))
  }

  const create = () => {
    let p = path.trim()
    if (!p) return
    if (!p.toLowerCase().endsWith('.json')) p += '.json'
    onCreate(p, name, formato, { size: lato, fps })
    onClose()
  }

  return (
    <Modal title="New project" narrow onClose={onClose}
      actions={<>
        <button onClick={onClose}>cancel</button>
        <button className="primary" disabled={!path.trim()} onClick={create}>create</button>
      </>}>
      <div className="row"><label>name</label>
        <input value={name} onChange={(e) => rinomina(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && create()} /><span /></div>
      <div className="row"><label>file</label>
        <input value={path} placeholder="C:\video\project.json"
          onKeyDown={(e) => e.key === 'Enter' && create()}
          onChange={(e) => { setPathManuale(true); setPath(e.target.value) }} /><span /></div>
      <SceltaFormato formato={formato} lato={lato} onFormato={setFormato} onLato={setLato} />
      <div className="row"><label>fps</label>
        <select value={fps} onChange={(e) => setFps(Number(e.target.value))}>
          {[24, 25, 30, 50, 60].map((f) => <option key={f} value={f}>{f}</option>)}
        </select><span /></div>
      <div className="hint" style={{ marginTop: 10 }}>
        The format can be changed later from the top bar.<br />
        The .json file is the project: your videos stay where they are.
      </div>
    </Modal>
  )
}

/**
 * Formato del progetto aperto. Cambia il fotogramma, non la timeline: le clip
 * ci si adattano col proprio "inquadra", oppure lo riempiono tagliando i
 * bordi se si spunta "fill".
 */
export function ProjectFormat({ resolution, onApply, onClose }) {
  const [w, h] = (resolution || '1920x1080').split('x').map(Number)
  const [formato, setFormato] = useState(formatoDi(w, h) || '16:9')
  const [lato, setLato] = useState(() => {
    const corto = Math.min(w, h)
    return QUALITA.some((q) => q.lato === corto) ? corto : 1080
  })
  const [fill, setFill] = useState(true)
  const applica = () => { onApply({ format: formato, size: lato, fill }); onClose() }

  return (
    <Modal title="Video format" narrow onClose={onClose}
      actions={<>
        <button onClick={onClose}>cancel</button>
        <button className="primary" onClick={applica}>apply</button>
      </>}>
      <div className="hint" style={{ marginBottom: 8 }}>now {w} x {h}</div>
      <SceltaFormato formato={formato} lato={lato} onFormato={setFormato} onLato={setLato} />
      <label className="spunta-riga">
        <input type="checkbox" checked={fill} onChange={(e) => setFill(e.target.checked)} />
        fill the frame: crop the clips instead of leaving black bars
      </label>
      <div className="hint" style={{ marginTop: 10 }}>
        The timeline stays the same. To keep a moving subject in the crop,
        ask the assistant for an auto reframe after the change. Undo brings it back.
      </div>
    </Modal>
  )
}

/**
 * Formati di uscita. La timeline resta quella: cambia il fotogramma in cui
 * viene composta, e le clip ci si adattano secondo il proprio "inquadra"
 * (cover riempie tagliando ai lati, contain lascia le bande).
 */
const FORMATI = [
  { id: 'progetto', nome: 'same as the project', w: null, h: null },
  { id: '16:9 1080p', nome: '16:9 · 1920x1080', w: 1920, h: 1080 },
  { id: '16:9 720p', nome: '16:9 · 1280x720', w: 1280, h: 720 },
  { id: '16:9 4k', nome: '16:9 · 3840x2160', w: 3840, h: 2160 },
  { id: '1:1', nome: 'square · 1080x1080', w: 1080, h: 1080 },
  { id: '9:16', nome: 'vertical · 1080x1920', w: 1080, h: 1920 },
  { id: '9:16 720', nome: 'vertical · 720x1280', w: 720, h: 1280 },
]

/** Estensione adatta al codec: .webm per VP9, .mov per i mezzanine, .mp4 per il resto. */
const estensione = (codec) => (
  codec === 'vp9' ? '.webm' : codec === 'prores' || codec === 'dnxhr' ? '.mov' : '.mp4')

// profili dei codec da montaggio per livello di qualita' (hw.PRORES_PROFILI, DNXHR_PROFILI)
const PROFILI = {
  prores: { draft: 'Proxy', medium: '422', high: '422 HQ', max: '4444' },
  dnxhr: { draft: 'LB', medium: 'SQ', high: 'HQ', max: 'HQX 10 bit' },
}

/**
 * Esporta. Il file di uscita viene proposto accanto al progetto, con il suo
 * nome: si preme "esporta" e basta, il percorso si cambia solo se si vuole.
 */
export function RenderDialog({ project, path, job, onStart, onClose, onTimeline, onSottotitoli }) {
  const proposto = (codec) => {
    if (!path) return ''
    const base = path.replace(/\.json$/i, '')
    return `${base}${estensione(codec)}`
  }
  const [output, setOutput] = useState(() => proposto('h264'))
  const [outputManuale, setOutputManuale] = useState(false)
  const [quality, setQuality] = useState('high')
  const [codec, setCodec] = useState('h264')
  const [formato, setFormato] = useState('progetto')
  const [range, setRange] = useState(false)
  const [start, setStart] = useState(0)
  const [end, setEnd] = useState(project?.duration || 0)
  // tracce fatte di testi: possono uscire come sottotitoli del file (render.SOTTOTITOLI_CODEC)
  const testi = (project?.tracks || []).filter(
    (t) => t.kind === 'video' && t.clips.length && t.clips.every((c) => c.type === 'text'))
  const [subTrack, setSubTrack] = useState(() => testi.find((t) => /sottotit|subtit/i.test(t.name))?.id || '')
  const [subLang, setSubLang] = useState('eng')
  const [subBurn, setSubBurn] = useState(false)
  const subOk = /\.(mp4|mov|m4v|mkv|webm)$/i.test(output.trim())

  const running = job && job.state === 'running'

  return (
    <Modal title="Export" onClose={onClose}
      actions={<>
        <button onClick={onClose}>close</button>
        <button className="primary" disabled={!output.trim() || running}
          onClick={() => {
            const f = FORMATI.find((x) => x.id === formato) || FORMATI[0]
            onStart({
              output: output.trim(), quality, codec,
              width: f.w, height: f.h,
              start: range ? start : null, end: range ? end : null,
              ...(subTrack && (subOk || subBurn)
                ? (subBurn ? {} : { subtitle_track: subTrack, subtitle_lang: subLang })
                : {}),
            })
          }}>
          {running ? <><Icon name="attesa" className="spin" />running…</> : <><Icon name="esporta" />export</>}
        </button>
      </>}>
      <div className="row"><label>file</label>
        <input value={output} placeholder="C:\video\final.mp4"
          onChange={(e) => { setOutputManuale(true); setOutput(e.target.value) }} /><span /></div>
      <div className="row"><label>quality</label>
        <select value={quality} onChange={(e) => setQuality(e.target.value)}>
          <option value="draft">draft (very fast)</option>
          <option value="medium">medium</option>
          <option value="high">high</option>
          <option value="max">maximum</option>
        </select><span /></div>
      <div className="row"><label>codec</label>
        <select value={codec} onChange={(e) => {
          setCodec(e.target.value)
          // il contenitore segue il codec finche' il percorso e' quello proposto
          if (!outputManuale) setOutput(proposto(e.target.value))
        }}>
          <option value="h264">H.264 (plays everywhere)</option>
          <option value="hevc">HEVC / H.265</option>
          <option value="av1">AV1</option>
          <option value="vp9">VP9 (webm)</option>
          <option value="prores">ProRes (mov, for finishing elsewhere)</option>
          <option value="dnxhr">DNxHR (mov or mxf, for Avid and broadcast)</option>
        </select><span /></div>
      {PROFILI[codec] && (
        <div className="hint" style={{ margin: '-2px 0 8px' }}>
          {codec === 'prores' ? 'ProRes' : 'DNxHR'} {PROFILI[codec][quality]} profile · 24-bit PCM audio ·
          large files, made to hand the work over to Premiere, Resolve, Avid or Final Cut.
          {codec === 'dnxhr' && ' For an .mxf, change the file extension.'}
        </div>
      )}
      <div className="row"><label>format</label>
        <select value={formato} onChange={(e) => setFormato(e.target.value)}>
          {FORMATI.map((f) => <option key={f.id} value={f.id}>{f.nome}</option>)}
        </select><span /></div>
      {testi.length > 0 && (<>
        <div className="row"><label>subtitles</label>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
            <select value={subTrack} onChange={(e) => setSubTrack(e.target.value)}>
              <option value="">no track</option>
              {testi.map((t) => <option key={t.id} value={t.id}>{t.name || t.id} ({t.clips.length})</option>)}
            </select>
            {subTrack && <>
              <input style={{ width: 56 }} value={subLang} title="language, ISO code (eng, ita, fra...)"
                onChange={(e) => setSubLang(e.target.value.trim().toLowerCase().slice(0, 3))} />
              <label style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                <input type="checkbox" checked={subBurn} onChange={(e) => setSubBurn(e.target.checked)} />
                burn in</label>
              {onSottotitoli && (
                <button title="Save the track as an .srt file next to the output"
                  onClick={() => onSottotitoli(subTrack, (output.trim() || path).replace(/\.[^./\\]+$/, '') + '.srt')}>
                  save .srt</button>
              )}
            </>}
          </div><span /></div>
        {subTrack && (
          <div className="hint" style={{ margin: '-2px 0 8px' }}>
            {subBurn
              ? 'Burnt into the picture, as in the timeline: always visible, they cannot be turned off.'
              : subOk
                ? 'A subtitle stream inside the file: the player turns it on and off, YouTube reads it. Not burnt into the picture.'
                : 'This format cannot carry a subtitle stream: they are burnt in. For a stream use .mp4, .mov, .mkv or .webm.'}
          </div>
        )}
      </>)}
      <div className="row"><label>range only</label>
        <input type="checkbox" checked={range} onChange={(e) => setRange(e.target.checked)} /><span /></div>
      {range && (
        <div className="row"><label>from / to</label>
          <div style={{ display: 'flex', gap: 6 }}>
            <input type="number" step="0.1" value={start} onChange={(e) => setStart(+e.target.value)} />
            <input type="number" step="0.1" value={end} onChange={(e) => setEnd(+e.target.value)} />
          </div><span /></div>
      )}
      <div className="hint" style={{ marginTop: 10 }}>
        The extension picks the container: .mp4 .mov .mkv .mxf .webm .gif .mp3 .wav<br />
        Exporting to a different format than the project ({project?.settings?.resolution}),
        clips set to <b>fit: cover</b> fill the frame cropping the sides; with <b>contain</b> they keep the bars.
      </div>

      {onTimeline && (
        <div className="timeline-scambio">
          <div className="row"><label>timeline</label>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {[['.fcpxml', 'FCPXML', 'Final Cut and DaVinci Resolve, every track'],
                ['.otio', 'OTIO', 'OpenTimelineIO: Resolve, Premiere, Avid, every track'],
                ['.edl', 'EDL', 'CMX3600: any editor reads it, one track']].map(([ext, nome, t]) => (
                <button key={ext} title={t} disabled={!output.trim() && !path}
                  onClick={() => onTimeline((output.trim() || path).replace(/\.[^./\\]+$/, '') + ext)}>
                  {nome}</button>
              ))}
            </div><span /></div>
          <div className="hint">
            No re-encoding: the edit (cuts, positions, dissolves) to open in another program
            with the original files, written next to the file above. Effects, colour and text
            stay in vedit; to take them along, export to ProRes or DNxHR first.
          </div>
        </div>
      )}

      {job && (
        <div style={{ marginTop: 16 }}>
          <div className="progress"><div style={{ width: `${job.percent || 0}%` }} /></div>
          <div className="hint" style={{ marginTop: 7 }}>
            {job.state === 'done' && (
              <span style={{ color: 'var(--ok)' }}>
                done: {job.output} ({job.mb} MB, {job.encoder}, {job.seconds_total}s)
              </span>
            )}
            {job.state === 'error' && <span style={{ color: 'var(--danger)' }}>error: {job.error}</span>}
            {job.state === 'running' && (job.phase === 'html'
              ? `${(job.percent || 0).toFixed(1)}% · HTML graphics: frame ${job.frames}/${job.total_frames}`
              : `${(job.percent || 0).toFixed(1)}% · ${(job.seconds || 0).toFixed(1)}/${(job.duration || 0).toFixed(1)}s`)}
          </div>
        </div>
      )}
    </Modal>
  )
}
