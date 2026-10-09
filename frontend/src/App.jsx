import React, { useCallback, useEffect, useRef, useState } from 'react'
import { api, connectEvents } from './api.js'
import Chat from './Chat.jsx'
import { Confirm, FileBrowser, NewProject, RenderDialog } from './Dialogs.jsx'
import Icon from './Icons.jsx'
import Inspector from './Inspector.jsx'
import Library from './Library.jsx'
import MediaBin from './MediaBin.jsx'
import Preview from './Preview.jsx'
import SourceMonitor from './SourceMonitor.jsx'
import Timeline from './Timeline.jsx'
import { useFineTrascinamento } from './trascina.js'
import { clamp, findClip, fmt } from './util.js'

const MEDIA_EXT = /\.(mp4|mov|mkv|avi|webm|m4v|mpe?g|wmv|flv|ts|mp3|wav|aac|m4a|flac|ogg|opus|png|jpe?g|webp|bmp|tiff?)$/i

// Le misure dei pannelli restano tra una sessione e l'altra. Vengono rilette
// entro i limiti di adesso: una misura salvata da una versione precedente puo'
// essere fuori scala e mandare i comandi fuori dalla loro riga.
// particelle.KINDS, con il nome che si legge nel menu
const PARTICELLE = [['snow', 'neve'], ['rain', 'pioggia'], ['sparks', 'scintille'],
  ['confetti', 'coriandoli'], ['dust', 'pulviscolo'], ['bokeh', 'bokeh'], ['stars', 'stelle'],
  ['fireflies', 'lucciole']]
const LIMITS = { bin: [170, 520], inspector: [240, 600], timeline: [120, 1400], trackH: [44, 140] }

const loadSizes = () => {
  let saved = {}
  try { saved = JSON.parse(localStorage.getItem('vedit.layout')) || {} } catch { saved = {} }
  for (const [k, [lo, hi]] of Object.entries(LIMITS)) {
    if (typeof saved[k] === 'number') saved[k] = Math.max(lo, Math.min(hi, saved[k]))
    else delete saved[k]
  }
  return saved
}

export default function App() {
  const [sys, setSys] = useState(null)
  const [project, setProject] = useState(null)
  const [path, setPath] = useState(null)
  const [revision, setRevision] = useState('0')
  const [selected, setSelected] = useState(null)
  // effetto sotto il mouse nel catalogo: il monitor lo mostra applicato senza
  // che il progetto cambi, cosi' si sceglie guardando invece di provare e annullare
  const [provaFx, setProvaFx] = useState(null)
  // diretta: compone il browser, si parte subito ma alcuni effetti non si
  // vedono. fedele: lo renderizza ffmpeg, esatto ma si aspetta.
  const [diretta, setDiretta] = useState(
    () => localStorage.getItem('vedit.diretta') !== 'no')
  const [playhead, setPlayhead] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [pxPerSec, setPxPerSec] = useState(70)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(null)
  const [dialog, setDialog] = useState(null)     // 'new' | 'open' | 'import' | 'render'
  const [job, setJob] = useState(null)
  const [source, setSource] = useState(null)     // media aperto nel monitor
  const [tab, setTab] = useState('program')      // program | source
  const [leftTab, setLeftTab] = useState('media')      // media | libreria
  // L'assistente e' il cuore dell'app: e' la scheda aperta di default. Se
  // l'utente preferisce le proprieta' la scelta resta fra una sessione e l'altra.
  const [rightTab, setRightTabState] = useState(() => {
    try { return localStorage.getItem('vedit.destra') === 'props' ? 'props' : 'chat' } catch { return 'chat' }
  })
  const setRightTab = useCallback((t) => {
    setRightTabState(t)
    try { localStorage.setItem('vedit.destra', t) } catch { /* resta per questa sessione */ }
  }, [])
  const [uploading, setUploading] = useState(null)
  const [dropping, setDropping] = useState(false)
  useFineTrascinamento(useCallback(() => setDropping(false), []))
  const [confirm, setConfirm] = useState(null)   // {title, message, ok, danger, onOk}
  // riferimenti per l'assistente: punti del video di cui si sta parlando
  const [refs, setRefs] = useState([])
  const [pickArea, setPickArea] = useState(false)
  const [llmSt, setLlmSt] = useState(null)
  // domanda dell'assistente in attesa di risposta: arriva dal server e si
  // risponde nella chat, chiunque l'abbia fatta (chat, Claude Code, un agente MCP)
  const [domanda, setDomanda] = useState(null)
  const [sizes, setSizes] = useState(() => ({
    bin: 250, inspector: 320, timeline: 300, trackH: 72, ...loadSizes(),
  }))
  const playheadRef = useRef(0)
  // numero dell'ultima modifica applicata: una risposta arrivata in ritardo
  // (piu' vecchia di quello che si vede gia') non deve riportare indietro la timeline
  const seqRef = useRef(0)

  useEffect(() => {
    localStorage.setItem('vedit.layout', JSON.stringify(sizes))
  }, [sizes])

  /**
   * Applica uno stato del progetto arrivato dal server: risposta a un'operazione,
   * evento del websocket, fine di un turno con l'assistente. E' l'unico punto
   * in cui progetto, percorso e revisione cambiano, cosi' non possono andare
   * fuori passo tra loro.
   */
  const applyState = useCallback((r) => {
    if (!r) return
    if (typeof r.seq === 'number') {
      if (r.seq < seqRef.current) return
      seqRef.current = r.seq
    }
    setProject(r.project)
    if ('path' in r) setPath(r.path)
    if (r.revision) setRevision(r.revision)
  }, [])

  // ---- stato iniziale ed eventi dal server --------------------------------
  useEffect(() => {
    api.state().then((s) => { setSys(s); applyState(s) }).catch((e) => setError(e.message))
    api.llm().then(setLlmSt).catch(() => {})
    api.domanda().then((r) => { if (r.domanda) { setDomanda(r.domanda); setRightTab('chat') } })
      .catch(() => {})

    // Il progetto cambia anche senza un clic qui dentro: l'assistente, un
    // agente via MCP (open_ui), un'altra finestra. Il server avvisa e la UI
    // ricarica lo stato: senza questo la timeline restava ferma a guardare.
    let ricarica = null
    const aggiorna = () => {
      if (ricarica) return
      ricarica = api.project().then((r) => { ricarica = null; applyState(r) })
        .catch(() => { ricarica = null })
    }
    return connectEvents((ev) => {
      if (ev.type === 'render') setJob(ev.job)
      if (ev.type === 'domande') { setDomanda({ id: ev.id, domande: ev.domande }); setRightTab('chat') }
      if (ev.type === 'domande_chiuse') setDomanda((d) => (d && d.id === ev.id ? null : d))
      if (ev.type === 'proxies') {
        // anche in caso di errore: altrimenti l'avviso "genero i proxy" resta li' per sempre
        setBusy(null)
        if (ev.state === 'error') setError(`proxy non riusciti: ${ev.error}`)
        else aggiorna()   // i media adesso hanno il proxy: le anteprime lo usano
      }
      // l'evento porta solo il numero: se e' piu' nuovo di quello che si vede,
      // si chiede lo stato. Le proprie operazioni arrivano gia' con la risposta.
      if ((ev.type === 'project' || ev.type === 'hello') && ev.seq > seqRef.current) aggiorna()
    })
  }, [applyState])

  useEffect(() => {
    if (!error) return
    const t = setTimeout(() => setError(null), 6000)
    return () => clearTimeout(t)
  }, [error])

  // Conferma per le azioni che distruggono lavoro. Sostituisce confirm() del
  // browser: quello blocca tutta la pagina, non si puo' vestire e su Windows
  // compare come una finestra di sistema in mezzo a un editor scuro.
  const ask = useCallback((opts) => setConfirm(opts), [])

  // avviso che sparisce da solo (le operazioni lunghe usano setBusy direttamente)
  const flash = useCallback((msg, ms = 2500) => {
    setBusy(msg)
    setTimeout(() => setBusy((b) => (b === msg ? null : b)), ms)
  }, [])

  // ---- operazioni ----------------------------------------------------------
  const run = useCallback(async (op, args) => {
    const res = await api.op(op, args)
    applyState(res)
    return res.result
  }, [applyState])

  const seek = useCallback((t, fromPlayer = false) => {
    const dur = project?.duration || 0
    const v = clamp(t, 0, Math.max(0, dur))
    playheadRef.current = v
    setPlayhead(v)
    if (!fromPlayer && playing) setPlaying(false)
  }, [project?.duration, playing])

  const selectedClip = project && selected ? findClip(project, selected) : null

  // ---- libreria -------------------------------------------------------------
  const applyPreset = useCallback((presetId, clipId) =>
    api.applyPreset(presetId, clipId).then(applyState).catch((e) => setError(e.message)),
  [applyState])

  /**
   * Una transizione ha bisogno di sovrapposizione: se la clip dopo e' attaccata
   * la si accosta (crossfade), altrimenti si scopre lo sfondo (set_transition).
   */
  const applyTransition = useCallback((type, duration, clipId) => {
    const id = clipId ?? selected
    if (!project || !id) { setError('seleziona prima una clip'); return }
    const clip = findClip(project, id)
    if (!clip) return
    const track = project.tracks.find((t) => t.clips.some((c) => c.id === id))
    const next = track?.clips
      .filter((c) => c.start >= clip.end - 1e-6 && c.id !== id)
      .sort((a, b) => a.start - b.start)[0]
    const dur = Math.min(duration, clip.duration)
    if (next && Math.abs(next.start - clip.end) < 1e-3) {
      run('crossfade', { clip_a: id, clip_b: next.id, duration: dur, type })
        .catch((e) => setError(e.message))
    } else {
      run('set_transition', { clip_id: id, type, duration: dur }).catch((e) => setError(e.message))
    }
  }, [project, selected, run])

  // ---- import ---------------------------------------------------------------
  const importPaths = (paths) =>
    run('import_media', { paths }).catch((e) => setError(e.message))

  const importFiles = async (fileList, folder = '') => {
    if (!fileList) { setDialog('import'); return }
    const files = [...fileList].filter((f) => MEDIA_EXT.test(f.name))
    if (!files.length) { setError('nessun file multimediale riconosciuto'); return }
    if (!project) {
      // trascinare dei file e' il primo gesto naturale: senza progetto se ne
      // crea uno nella cartella proposta, col nome del primo file
      if (!sys?.home) { setError('crea prima un progetto'); return }
      const sep = sys.home.includes('\\') ? '\\' : '/'
      const nome = files[0].name.replace(/\.[^.]+$/, '') || 'progetto'
      try {
        progettoAperto(await api.createProject(`${sys.home}${sep}${nome}.json`, nome, '1080p'))
      } catch (e) { setError(e.message); return }
    }
    const mb = files.reduce((s, f) => s + f.size, 0) / 1e6
    setUploading(`${files.length} file, ${mb.toFixed(0)} MB`)
    try {
      applyState(await api.upload(files, folder))
    } catch (e) { setError(e.message) } finally { setUploading(null) }
  }

  // ---- scorciatoie da tastiera --------------------------------------------
  useEffect(() => {
    const onKey = (e) => {
      const tag = e.target.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
      const step = 1 / (project?.settings?.fps || 30)
      const act = {
        ' ': () => setPlaying((p) => !p),
        ArrowLeft: () => seek(playheadRef.current - (e.shiftKey ? 1 : step)),
        ArrowRight: () => seek(playheadRef.current + (e.shiftKey ? 1 : step)),
        Home: () => seek(0),
        End: () => seek(project?.duration || 0),
        s: () => selected && run('split_clip', { clip_id: selected, at: playheadRef.current })
          .catch((err) => setError(err.message)),
        Delete: () => selected && run('remove_clip', { clip_id: selected, ripple: e.shiftKey })
          .then(() => setSelected(null)).catch((err) => setError(err.message)),
        '+': () => setPxPerSec((p) => clamp(p * 1.25, 8, 600)),
        '-': () => setPxPerSec((p) => clamp(p / 1.25, 8, 600)),
      }
      if (e.ctrlKey && e.key.toLowerCase() === 'z') {
        e.preventDefault(); run('undo').catch((err) => setError(err.message)); return
      }
      if (e.ctrlKey && e.key.toLowerCase() === 'y') {
        e.preventDefault(); run('redo').catch((err) => setError(err.message)); return
      }
      if (e.ctrlKey && e.key.toLowerCase() === 's') {
        e.preventDefault()
        if (project) run('save', {}).then(() => flash('progetto salvato')).catch((err) => setError(err.message))
        return
      }
      const fn = act[e.key]
      if (fn) { e.preventDefault(); fn() }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [project, selected, run, seek, flash])

  const startRender = (body) =>
    api.render(body).then(setJob).catch((e) => setError(e.message))

  // L'export dura minuti e nel frattempo si chiude la finestra e si continua
  // a lavorare: quando finisce lo si deve sapere anche senza riaprirla.
  const jobVisto = useRef(null)
  useEffect(() => {
    if (!job || job.state === 'running' || jobVisto.current === job.id) return
    jobVisto.current = job.id
    if (dialog === 'render') return
    if (job.state === 'done') flash(`esportato: ${job.output}`, 6000)
    else if (job.state === 'error') setError(`export fallito: ${job.error}`)
  }, [job, dialog, flash])

  /** Progetto appena creato o aperto: stato nuovo, testina e selezione a zero. */
  const progettoAperto = useCallback((r) => {
    applyState(r)
    setSelected(null)
    setPlayhead(0)
    playheadRef.current = 0
    setSource(null)
    setTab('program')
    if (r.recenti) setSys((s) => (s ? { ...s, recenti: r.recenti } : s))
  }, [applyState])

  /** Aggiunge un riferimento e porta l'assistente in primo piano. */
  const aggiungiRif = useCallback((r) => {
    setRefs((xs) => [...xs, r])
    setRightTab('chat')
  }, [])

  const openProject = useCallback((p) =>
    api.openProject(p).then(progettoAperto).catch((e) => setError(e.message)), [progettoAperto])

  return (
    <div
      className={`app ${dropping ? 'dropping' : ''}`}
      onDragOver={(e) => {
        if (!e.dataTransfer.types.includes('Files')) return
        // sopra la chat il file diventa un allegato: l'invito a importarlo
        // nel progetto direbbe il contrario di quello che succede
        if (e.target.closest?.('.chat')) { setDropping(false); return }
        e.preventDefault(); setDropping(true)
      }}
      onDragLeave={(e) => {
        // relatedTarget nullo = il puntatore ha lasciato la finestra: senza questo
        // controllo il riquadro blu resta acceso quando il trascinamento finisce fuori
        if (!e.relatedTarget || (e.clientX === 0 && e.clientY === 0)) setDropping(false)
      }}
      onDragEnd={() => setDropping(false)}
      onDrop={(e) => {
        if (!e.dataTransfer.files?.length) return
        e.preventDefault()
        setDropping(false)
        importFiles(e.dataTransfer.files)
      }}
    >
      <div className="topbar">
        <span className="name"><img src="/logo.svg" alt="" className="marchio" />vedit</span>
        <button className="ghost" onClick={() => setDialog('new')}>
          <Icon name="nuovo" />nuovo</button>
        <button className="ghost" onClick={() => setDialog('open')}>
          <Icon name="apri" />apri</button>
        <button className="ghost" disabled={!project} onClick={() => run('save', {})
          .then(() => flash('progetto salvato')).catch((e) => setError(e.message))}>
          <Icon name="salva" />salva</button>

        <span className="sep" />
        <button className="icon" disabled={!project} title="Annulla (Ctrl+Z)"
          onClick={() => run('undo').catch((e) => setError(e.message))}><Icon name="annulla" /></button>
        <button className="icon" disabled={!project} title="Ripeti (Ctrl+Y)"
          onClick={() => run('redo').catch((e) => setError(e.message))}><Icon name="ripeti" /></button>

        <span className="sep" />
        <button className="ghost act sky" disabled={!project} title="Nuova traccia video"
          onClick={() => run('add_track', { kind: 'video' }).catch((e) => setError(e.message))}>
          <Icon name="video" />traccia video</button>
        <button className="ghost act mint" disabled={!project} title="Nuova traccia audio"
          onClick={() => run('add_track', { kind: 'audio' }).catch((e) => setError(e.message))}>
          <Icon name="audio" />traccia audio</button>
        <button className="ghost act grape" disabled={!project} title="Titolo alla testina"
          onClick={() => run('add_text', { text: 'Testo', start: playhead, duration: 3 })
            .then((c) => setSelected(c.id)).catch((e) => setError(e.message))}>
          <Icon name="testo" />titolo</button>
        <button className="ghost act sun" disabled={!project}
          title="Grafica animata in HTML/CSS/JS alla testina: si vede animata qui, dal vivo"
          onClick={() => run('add_html', { start: playhead, duration: 4 })
            .then((c) => setSelected(c.id)).catch((e) => setError(e.message))}>
          <Icon name="codice" />grafica html</button>
        <select className="ghost act" disabled={!project} value=""
          title="Particelle alla testina: neve, scintille, coriandoli... (clip html trasparente)"
          onChange={(e) => {
            const kind = e.target.value
            if (!kind) return
            run('add_particles', { kind, start: playhead, duration: 5 })
              .then((c) => setSelected(c.id)).catch((err) => setError(err.message))
          }}>
          <option value="">✦ particelle</option>
          {PARTICELLE.map(([k, nome]) => <option key={k} value={k}>{nome}</option>)}
        </select>

        <span className="spacer" />
        <span className="path" title={path || ''}>{path || 'nessun progetto'}</span>
        <button className="ghost" disabled={!project}
          title="Genera copie a bassa risoluzione: anteprime molto piu' rapide"
          onClick={() => { setBusy('genero i proxy…'); api.buildProxies() }}>
          <Icon name="proxy" />proxy</button>
        <button className="primary" disabled={!project || !project.duration}
          onClick={() => setDialog('render')}><Icon name="esporta" />esporta</button>
      </div>

      <div className="middle">
        <div style={{ width: sizes.bin, flex: 'none', display: 'flex', minWidth: 0 }}>
          <div className="panel">
            <div className="tabs">
              <button className={leftTab === 'media' ? 'on' : ''}
                onClick={() => setLeftTab('media')}><Icon name="video" />media</button>
              <button className={leftTab === 'libreria' ? 'on' : ''}
                onClick={() => setLeftTab('libreria')}><Icon name="libreria" />libreria</button>
            </div>
            {leftTab === 'media' ? (
              <MediaBin project={project} run={run} setError={setError} uploading={uploading}
                onImport={importFiles} ask={ask}
                onOpenSource={(m) => { setSource(m); setTab('source') }} />
            ) : (
              <Library library={sys?.library} clip={selectedClip} setError={setError}
                onProva={setProvaFx}
                onPreset={applyPreset}
                onTransition={(type, dur) => applyTransition(type, dur)} />
            )}
          </div>
        </div>
        <Divider onDrag={(dx) => setSizes((s) => ({ ...s, bin: clamp(s.bin + dx, 170, 520) }))} />

        <div className="center">
          <div className="tabs">
            <button className={tab === 'program' ? 'on' : ''} onClick={() => setTab('program')}>
              programma
            </button>
            <button className={tab === 'source' ? 'on' : ''} disabled={!source}
              onClick={() => setTab('source')}>
              sorgente{source ? `: ${source.name}` : ''}
            </button>
            <span className="spacer" />
          </div>

          {!sys ? (
            <div className="preview"><div className="empty">
              <Icon name="attesa" className="spin" /> collegamento al server…
            </div></div>
          ) : !project ? (
            <Benvenuto recenti={sys.recenti} onNew={() => setDialog('new')}
              onOpen={() => setDialog('open')} onRecent={openProject} />
          ) : tab === 'source' && source ? (
            <SourceMonitor media={source} tracks={project?.tracks || []} run={run}
              setError={setError} playhead={playhead}
              onClose={() => { setSource(null); setTab('program') }} />
          ) : (
            <Preview project={project} revision={revision} playhead={playhead} seek={seek}
              playing={playing} setPlaying={setPlaying} clip={selectedClip}
              run={run} setError={setError}
              pickArea={pickArea}
              onArea={(a) => { aggiungiRif({ kind: 'area', t: playheadRef.current, ...a }); setPickArea(false) }}
              onCancelArea={() => setPickArea(false)}
              prova={provaFx ? { ...provaFx, clip: selected } : null}
              diretta={diretta} />
          )}

          <div className="transport">
            <button className="icon" title="Torna all'inizio (Home)"
              onClick={() => seek(0)} disabled={!project}><Icon name="inizio" /></button>
            <button className="icon" title={playing ? 'Pausa (spazio)' : 'Riproduci (spazio)'}
              onClick={() => setPlaying((p) => !p)} disabled={!project?.duration}>
              <Icon name={playing ? 'pausa' : 'play'} size={17} />
            </button>
            <span className="time">
              <b>{fmt(playhead)}</b> / {fmt(project?.duration || 0)}
            </span>

            <button
              className={`modo ${diretta ? 'on' : ''}`}
              title={diretta
                ? 'Diretta: compone il browser, nessuna attesa. Alcuni effetti non si vedono.'
                : 'Fedele: lo renderizza ffmpeg, identico al file finale, ma va preparato.'}
              onClick={() => setDiretta((d) => {
                localStorage.setItem('vedit.diretta', d ? 'no' : 'si')
                return !d
              })}>
              {diretta ? 'diretta' : 'fedele'}
            </button>

            <span className="sep" />
            <button className="icon" disabled={!selectedClip} title="Taglia alla testina (S)"
              onClick={() => run('split_clip', { clip_id: selected, at: playhead })
                .catch((e) => setError(e.message))}><Icon name="taglia" /></button>
            <button className="icon danger" disabled={!selectedClip} title="Elimina la clip (Canc)"
              onClick={() => run('remove_clip', { clip_id: selected })
                .then(() => setSelected(null)).catch((e) => setError(e.message))}>
              <Icon name="cestino" /></button>

            <span className="spacer" />
            <span className="ctl">
              <span>zoom</span>
              <input type="range" min="8" max="400" value={pxPerSec} style={{ width: 120 }}
                title="Scala dei tempi in timeline"
                onChange={(e) => setPxPerSec(+e.target.value)} />
            </span>
            <span className="ctl">
              <span>tracce</span>
              {/* il minimo e' l'altezza sotto la quale i comandi della testata
                  non ci starebbero piu': due righe da 18px, spazi e margini */}
              <input type="range" min="44" max="140" step="2" value={sizes.trackH}
                style={{ width: 84 }} title="Altezza delle tracce: abbassala per vederne di piu'"
                onChange={(e) => setSizes((s) => ({ ...s, trackH: +e.target.value }))} />
            </span>
          </div>

          <Divider horizontal
            onDrag={(dy) => setSizes((s) => ({ ...s, timeline: clamp(s.timeline - dy, 120, 1400) }))} />
          <div style={{ height: sizes.timeline, flex: 'none', display: 'flex', minHeight: 0 }}>
            <Timeline project={project} playhead={playhead} seek={seek} pxPerSec={pxPerSec}
              selected={selected} setSelected={setSelected} run={run} setError={setError}
              onPreset={applyPreset} onTransition={applyTransition} trackH={sizes.trackH}
              ask={ask} />
          </div>
        </div>

        <Divider onDrag={(dx) => setSizes((s) => ({ ...s, inspector: clamp(s.inspector - dx, 240, 600) }))} />
        <div style={{ width: sizes.inspector, flex: 'none', display: 'flex', minWidth: 0 }}>
          <div className="panel">
            <div className="tabs">
              <button className={rightTab === 'chat' ? 'on' : ''}
                onClick={() => setRightTab('chat')}><Icon name="assistente" />assistente</button>
              <button className={rightTab === 'props' ? 'on' : ''}
                onClick={() => setRightTab('props')}><Icon name="proprieta" />proprieta'</button>
            </div>
            {rightTab === 'props' ? (
              <Inspector project={project} effects={sys?.effects || []}
                transitions={sys?.transitions || []} clip={selectedClip}
                playhead={playhead} run={run} setError={setError} setBusy={setBusy}
                onProva={setProvaFx}
                onRif={(id) => aggiungiRif({ kind: 'clip', id })} />
            ) : (
              <Chat available={llmSt || sys?.chat} onAvailable={setLlmSt} setError={setError}
                onProject={applyState} project={project} playhead={playhead} seek={seek}
                selected={selected} refs={refs} setRefs={setRefs}
                stili={sys?.stili || []} domanda={domanda}
                onStili={(l) => setSys((x) => (x ? { ...x, stili: l } : x))}
                onRisposta={(risposte) => {
                  const d = domanda
                  setDomanda(null)
                  if (d) api.rispondi(d.id, risposte).catch((e) => setError(e.message))
                }}
                pickArea={pickArea}
                setPickArea={(v) => {
                  const next = typeof v === 'function' ? v(pickArea) : v
                  setPickArea(next)
                  if (next) { setTab('program'); setPlaying(false) }
                }} />
            )}
          </div>
        </div>
      </div>

      {dialog === 'new' && (
        <NewProject presets={sys?.presets || ['1080p']} home={sys?.home}
          onClose={() => setDialog(null)}
          onCreate={(p, name, preset) => api.createProject(p, name, preset)
            .then(progettoAperto).catch((e) => setError(e.message))} />
      )}
      {dialog === 'open' && (
        <FileBrowser title="Apri progetto" multiple={false} onClose={() => setDialog(null)}
          memoria="progetti" recenti={sys?.recenti}
          filter={(n) => n.toLowerCase().endsWith('.json')}
          onPick={([p]) => openProject(p)} />
      )}
      {dialog === 'import' && (
        <FileBrowser title="Importa file" onClose={() => setDialog(null)} memoria="media"
          filter={(n) => MEDIA_EXT.test(n)} onPick={importPaths} />
      )}
      {dialog === 'render' && (
        <RenderDialog project={project} path={path} job={job} onStart={startRender}
          onClose={() => setDialog(null)} />
      )}

      {confirm && (
        <Confirm {...confirm} onClose={() => setConfirm(null)} />
      )}

      {dropping && <div className="dropzone">rilascia qui i file da importare</div>}
      {busy && (
        <div className="toast ok"><Icon name="attesa" className="spin" />{busy}</div>
      )}
      {error && (
        <div className="toast">
          <span>{error}</span>
          <button className="icon sm" title="Chiudi" onClick={() => setError(null)}>
            <Icon name="chiudi" size={13} />
          </button>
        </div>
      )}
    </div>
  )
}

/**
 * Prima schermata: senza progetto l'editor era un monitor nero con i comandi
 * spenti e nessuna indicazione su da dove partire. Qui ci sono le due cose che
 * si possono fare, e i progetti aperti di recente a un clic.
 */
function Benvenuto({ recenti, onNew, onOpen, onRecent }) {
  return (
    <div className="preview benvenuto">
      <div className="benvenuto-box">
        <img src="/logo.svg" alt="vedit" className="benvenuto-logo" />
        <div className="benvenuto-titolo">Ciao! Facciamo un video.</div>
        <div className="passi">
          <div className="passo"><b>1</b><span>Crea un progetto</span><small>o riaprine uno</small></div>
          <div className="passo"><b>2</b><span>Trascina i tuoi file</span><small>video, foto, musica</small></div>
          <div className="passo"><b>3</b><span>Monta e esporta</span><small>da solo o con l'assistente</small></div>
        </div>
        <div className="benvenuto-azioni">
          <button className="primary" onClick={onNew}><Icon name="nuovo" />nuovo progetto</button>
          <button onClick={onOpen}><Icon name="apri" />apri…</button>
        </div>
        {recenti?.length > 0 && (
          <div className="benvenuto-recenti">
            <div className="hint">recenti</div>
            {recenti.slice(0, 6).map((r) => (
              <button key={r.path} className="ghost recente" title={r.path}
                onClick={() => onRecent(r.path)}>
                <Icon name="apri" size={14} />
                <span className="nome">{r.name}</span>
                <span className="hint">{r.path}</span>
              </button>
            ))}
          </div>
        )}
        <div className="hint">Puoi anche trascinare qui dei file: il progetto si crea da solo.</div>
      </div>
    </div>
  )
}

/** Divisore trascinabile tra due pannelli. */
function Divider({ onDrag, horizontal }) {
  const down = (e) => {
    e.preventDefault()
    let last = horizontal ? e.clientY : e.clientX
    const move = (ev) => {
      const now = horizontal ? ev.clientY : ev.clientX
      onDrag(now - last)
      last = now
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', () => window.removeEventListener('pointermove', move), { once: true })
  }
  return <div className={`divider ${horizontal ? 'h' : 'v'}`} onPointerDown={down} />
}
