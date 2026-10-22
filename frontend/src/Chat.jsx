import React, { useCallback, useEffect, useRef, useState } from 'react'
import { api, chat as sendChat } from './api.js'
import { FileBrowser, Modal } from './Dialogs.jsx'
import { useFineTrascinamento } from './trascina.js'
import Icon from './Icons.jsx'
import { dettaglioStrumento, fmt } from './util.js'

const TOOL_LABEL = {
  project_info: 'looks at the timeline', import_media: 'imports files', add_clip: 'adds a clip',
  add_clips: 'lays down the cuts', apply_style: 'applies the style', review_edit: 'reviews the edit',
  create_style: 'creates a style', add_text: 'adds a title', add_html: 'creates a graphic',
  set_html: 'touches up the graphic', split_clip: 'splits', split: 'splits', remove_clip: 'deletes a clip',
  move_clip: 'moves a clip', move: 'moves a clip', trim_clip: 'trims', trim: 'trims',
  set_speed: 'changes speed', set_fades: 'fades', crossfade: 'transition',
  set_transition: 'transition', apply_preset: 'applies a preset', add_effect: 'applies an effect',
  set_transform: 'position and scale', set_audio: 'clip audio', set_text: 'edits the text',
  add_track: 'adds a track', close_gaps: 'closes the gaps', undo: 'undo',
  preview_frame: 'looks at a frame', preview_grid: 'looks at the edit',
  ask_user: 'asks you a question', add_color: 'adds a solid colour', music_beats: 'listens to the beat', Read: 'looks at an image', render_video: 'exports',
  marker: 'adds a marker', remove_marker: 'removes a marker', markers: 'reads the markers',
  set_clip: 'edits the clip', set_track: 'edits the track', move_track: 'moves the track',
  remove_track: 'deletes a track', delete: 'deletes', redo: 'redo', move_effect: 'reorders the effects',
  update_effect: 'adjusts an effect', remove_effect: 'removes an effect', list_effects: 'looks at the effects',
  inspect_footage: 'looks at the footage', plan_edit: 'plans the edit', analyze_media: 'analyses a file',
  transcribe: 'transcribes the speech', make_captions: 'creates the subtitles', duck_music: 'ducks the music under the voice',
  normalize_audio: 'normalises the audio', audio_levels: 'measures the levels', check_cuts: 'checks the cuts',
  verify_edit: 'checks the edit', remember: 'remembers it for every project',
  forget: 'forgets a preference', memory: 'reads the memory',
  web_search: 'searches the web', web_read: 'reads a page', web_download: 'downloads from the web',
  WebSearch: 'searches the web', generate_voice: 'generates the voice', snapshot: 'saves a version', match_color: 'matches the colours',
  Glob: 'searches files', WebFetch: 'reads a web page',
}

/** Etichetta breve di un riferimento, per le pastiglie e per il messaggio. */
export function rifLabel(r, project) {
  if (r.kind === 'time') return fmt(r.t)
  if (r.kind === 'range') return `${fmt(Math.min(r.a, r.b))} → ${fmt(Math.max(r.a, r.b))}`
  if (r.kind === 'area') return `area at ${fmt(r.t)}`
  if (r.kind === 'file') return r.name
  if (r.kind === 'link') return r.name || r.url
  if (r.kind === 'folder') return r.name || r.path
  if (r.kind === 'clip') {
    const c = project?.tracks.flatMap((t) => t.clips).find((x) => x.id === r.id)
    return c ? `clip ${c.name || c.id}` : `clip ${r.id}`
  }
  return '?'
}

const RIF_ICON = { time: 'orologio', range: 'taglia', area: 'riquadro', clip: 'video', file: 'graffetta', link: 'link', folder: 'cartella' }

const URL_SOLO = /^https?:\/\/\S+$/i

/**
 * Chat con l'assistente. Gli strumenti che usa sono le stesse operazioni dei
 * pulsanti: quello che fa compare in timeline e si annulla con Ctrl+Z.
 *
 * I riferimenti dicono *dove*: un istante, un tratto, una clip, un'area
 * disegnata sull'inquadratura. Il modello li riceve numerati, con il
 * fotogramma davanti, cosi' "rendi piu' grande il titolo in 2" e' una frase
 * che basta.
 */
export default function Chat({
  available, onAvailable, onProject, setError, project, playhead, seek, selected,
  refs, setRefs, pickArea, setPickArea, stili = [], onStili, domanda, onRisposta, nuovoProgetto = 0,
}) {
  const [turns, setTurns] = useState([])   // {role, text, tools:[], refs}
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [settings, setSettings] = useState(false)
  const [memoriaAperta, setMemoriaAperta] = useState(false)
  // stile di montaggio: resta scelto fra una sessione e l'altra, ma un
  // progetto nuovo riparte da "nessuno"
  const [stile, setStileState] = useState(() => {
    try { return localStorage.getItem('vedit.stile') || '' } catch { return '' }
  })
  const setStile = (v) => {
    setStileState(v)
    try { localStorage.setItem('vedit.stile', v) } catch { /* senza storage resta per questa sessione */ }
  }
  useEffect(() => { if (nuovoProgetto) setStileState('') }, [nuovoProgetto])
  const [menuStili, setMenuStili] = useState(false)
  const [editStile, setEditStile] = useState(null)   // stile personale in scrittura
  const [tratto, setTratto] = useState(null)   // inizio di un tratto in costruzione
  const [caricando, setCaricando] = useState(0)  // allegati in arrivo
  const [sopra, setSopra] = useState(false)      // file trascinati sopra la chat
  const fileRef = useRef(null)
  useFineTrascinamento(useCallback(() => setSopra(false), []))
  const [linkAperto, setLinkAperto] = useState(false)
  const [linkTesto, setLinkTesto] = useState('')
  const [sceltaCartella, setSceltaCartella] = useState(false)
  const endRef = useRef(null)
  const abortRef = useRef(null)

  useEffect(() => { endRef.current?.scrollIntoView({ block: 'end' }) }, [turns, busy, domanda])

  if (settings || !available?.ok) {
    return (
      <div className="chat">
        <div className="section-title">
          choose the model
          <span className="spacer" />
          {available?.ok && (
            <button className="icon sm" title="Back to the chat" onClick={() => setSettings(false)}>
              <Icon name="chiudi" size={14} />
            </button>
          )}
        </div>
        <ModelSettings available={available} setError={setError}
          onSaved={(st) => { onAvailable(st); if (st.ok) setSettings(false) }} />
      </div>
    )
  }

  const addRef = (r) => setRefs((xs) => [...xs, r])

  /** Il server legge la pagina o scarica il file: qui arriva il riferimento pronto. */
  const aggiungiLink = async (url) => {
    const u = url.trim()
    if (!u) return
    setCaricando((n) => n + 1)
    try {
      addRef(await api.chatLink(u))
      setLinkTesto('')
      setLinkAperto(false)
    } catch (e) { setError(e.message) } finally { setCaricando((n) => Math.max(0, n - 1)) }
  }

  /** Carica i file e li aggiunge come riferimenti numerati, come gli altri. */
  const allega = async (lista) => {
    const files = [...(lista || [])]
    if (!files.length) return
    setCaricando((n) => n + files.length)
    try {
      const r = await api.allega(files)
      setRefs((xs) => [...xs, ...r.allegati.map((a) => ({ kind: 'file', ...a }))])
    } catch (e) { setError(e.message) } finally { setCaricando((n) => Math.max(0, n - files.length)) }
  }

  const send = async () => {
    const q = input.trim()
    if (!q || busy) return
    const sentRefs = refs
    setInput('')
    setRefs([])
    setTratto(null)
    setPickArea(false)
    setBusy(true)
    setTurns((t) => [...t, { role: 'user', text: q, refs: sentRefs },
      { role: 'assistant', text: '', tools: [] }])

    const patch = (fn) => setTurns((t) => {
      const out = [...t]
      out[out.length - 1] = fn(out[out.length - 1])
      return out
    })

    const ctrl = new AbortController()
    abortRef.current = ctrl
    try {
      await sendChat(q, sentRefs, stile || null, (ev) => {
        if (ev.type === 'text') patch((m) => ({ ...m, thinking: false, text: m.text + ev.text }))
        else if (ev.type === 'thinking') patch((m) => ({ ...m, thinking: true }))
        else if (ev.type === 'note') patch((m) => ({ ...m, note: ev.message }))
        else if (ev.type === 'tool') {
          patch((m) => ({
            ...m, thinking: false,
            tools: [...m.tools, { name: ev.name, state: 'run', input: ev.input }],
          }))
        } else if (ev.type === 'tool_done' || ev.type === 'tool_error') {
          patch((m) => {
            const tools = [...m.tools]
            for (let i = tools.length - 1; i >= 0; i--) {
              if (tools[i].name === ev.name && tools[i].state === 'run') {
                tools[i] = { ...tools[i], state: ev.type === 'tool_done' ? 'ok' : 'err', message: ev.message }
                break
              }
            }
            return { ...m, tools }
          })
        } else if (ev.type === 'stopped') {
          patch((m) => ({
            ...m, thinking: false,
            tools: m.tools.map((t) => (t.state === 'run' ? { ...t, state: 'err', message: 'fermato' } : t)),
            note: 'Stopped. The changes already made stay: Ctrl+Z to undo them.',
          }))
        } else if (ev.type === 'error') {
          patch((m) => ({ ...m, error: ev.message }))
        } else if (ev.type === 'end') {
          onProject(ev)
        }
      }, ctrl.signal)
    } catch (e) {
      if (e.name !== 'AbortError') setError(e.message)
    } finally {
      setBusy(false)
      abortRef.current = null
    }
  }

  const reset = () => {
    abortRef.current?.abort()
    api.chatReset().catch(() => {})
    setTurns([])
  }

  return (
    <div className={`chat ${sopra ? 'sopra' : ''}`}
      // i file lasciati qui sono allegati per l'assistente, non media del
      // progetto: il trascinamento non deve arrivare all'import della finestra
      onDragOver={(e) => {
        if (!e.dataTransfer.types.includes('Files')) return
        // niente stopPropagation: la finestra deve sapere che il file e' sulla
        // chat, per spegnere l'invito a importarlo nel progetto
        e.preventDefault(); setSopra(true)
      }}
      onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget)) setSopra(false) }}
      onDrop={(e) => {
        if (!e.dataTransfer.files?.length) return
        e.preventDefault(); e.stopPropagation(); setSopra(false)
        allega(e.dataTransfer.files)
      }}>
      {sopra && <div className="chatdrop">drop to attach to the message</div>}
      <div className="section-title">
        <button className="modelpill" title="Change model" onClick={() => setSettings(true)}>
          <span className="dot" />
          {available.nome}{available.model ? ` · ${available.model}` : ''}
        </button>
        <span className="spacer" />
        <button className={`stilepill ${stile ? 'on' : ''}`} title="Editing style"
          onClick={() => {
            // l'agente puo' aver creato uno stile nel frattempo (create_style)
            if (!menuStili) api.stili().then((r) => onStili?.(r.stili)).catch(() => {})
            setMenuStili((v) => !v)
          }}>
          <Icon name="libreria" size={13} />
          {stili.find((s) => s.id === stile)?.nome || 'style'}
        </button>
        <button className="icon sm" onClick={() => setMemoriaAperta(true)}
          title="Memory: what the assistant remembers across all your projects">
          <Icon name="memoria" size={14} />
        </button>
        <button className="icon sm" onClick={reset} title="Start the conversation over">
          <Icon name="cestino" size={14} />
        </button>
      </div>

      {memoriaAperta && <EditorMemoria setError={setError} onClose={() => setMemoriaAperta(false)} />}

      {menuStili && (
        <div className="stilimenu">
          {editStile ? (
            <EditorStile stile={editStile} setError={setError}
              onClose={() => setEditStile(null)}
              onSalvato={(r) => { onStili?.(r.stili); if (r.stile) setStile(r.stile); setEditStile(null) }}
              onEliminato={(r, id) => {
                onStili?.(r.stili)
                if (stile === id) setStile('')
                setEditStile(null)
              }} />
          ) : (<>
            <div className="hint">The style guides the assistant in every choice: pace, transitions, colour, text.</div>
            <button className={`stilevoce ${!stile ? 'on' : ''}`}
              onClick={() => { setStile(''); setMenuStili(false) }}>
              <b>None</b><span>the assistant decides case by case</span>
            </button>
            {stili.filter((s) => !s.personale).map((s) => (
              <button key={s.id} className={`stilevoce ${stile === s.id ? 'on' : ''}`}
                onClick={() => { setStile(s.id); setMenuStili(false) }}>
                <b>{s.nome}</b><span>{s.breve}</span>
              </button>
            ))}
            <div className="libgroup stiligruppo">your styles</div>
            {stili.filter((s) => s.personale).map((s) => (
              <div key={s.id} className="stilemio">
                <button className={`stilevoce ${stile === s.id ? 'on' : ''}`}
                  onClick={() => { setStile(s.id); setMenuStili(false) }}>
                  <b>{s.nome}</b><span>{s.breve}</span>
                </button>
                <button className="icon sm" title="Edit the style" onClick={() => setEditStile(s)}>
                  <Icon name="ingranaggio" size={14} />
                </button>
              </div>
            ))}
            <button className="ghost stilenuovo"
              onClick={() => setEditStile({ nome: '', breve: '', guida: '', piano: 'vlog' })}>
              <Icon name="piu" size={14} />create your own style
            </button>
          </>)}
        </div>
      )}

      <div className="chatlog">
        {!turns.length && (
          <div className="chatempty">
            <b>Just ask, the assistant edits for you.</b>
            <div className="esempi">
              {['cut the first 2 seconds of the first clip',
                'put a dissolve between the two shots',
                'make an animated lower third with my name',
                'make the video more cinematic'].map((e) => (
                <button key={e} className="esempio" onClick={() => setInput(e)}>{e}</button>
              ))}
            </div>
            <div className="hint">
              Want to point at something precise? Use the buttons below: a moment, a range,
              a clip, an area drawn on the frame, a file (also by dropping it here or pasting
              a screenshot), a link or a folder. A link pasted on its own becomes a reference by
              itself. Every change can be undone with Ctrl+Z.
            </div>
          </div>
        )}
        {turns.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            {m.role === 'user' ? (
              <>
                {m.refs?.length > 0 && (
                  <div className="rifs inmsg">
                    {m.refs.map((r, j) => (
                      <span key={j} className="rif" title={[r.url, r.path].filter(Boolean).join('\n')}>
                        <b>{j + 1}</b><span className="riftesto">{rifLabel(r, project)}</span>
                      </span>
                    ))}
                  </div>
                )}
                {m.text}
              </>
            ) : (
              <>
                {m.tools?.map((t, j) => (
                  <Passo key={j} passo={t} project={project} />
                ))}
                {m.thinking && !m.text && (
                  <div className="toolrow"><Icon size={13} name="attesa" className="spin" />thinking…</div>
                )}
                {m.note && <div className="hint">{m.note}</div>}
                {m.text}
                {m.error && <div className="chaterr">{m.error}</div>}
              </>
            )}
          </div>
        ))}
        {domanda && <DomandaCard key={domanda.id} domanda={domanda} onRisposta={onRisposta} />}
        <div ref={endRef} />
      </div>

      <div className="chatfoot">
        {refs.length > 0 && (
          <div className="rifs">
            {refs.map((r, j) => (
              <span key={j} className="rif">
                <button className="rifgo"
                  // il nome intero (titolo, indirizzo, percorso) sta nel suggerimento:
                  // nell'etichetta si accorcia, se no spinge la x fuori dal pannello
                  title={[rifLabel(r, project), r.url, r.path].filter(Boolean).join('\n')}
                  onClick={() => {
                    // link, file e cartelle non sono punti della timeline
                    if (['link', 'file', 'folder'].includes(r.kind)) return
                    seek(r.kind === 'range' ? Math.min(r.a, r.b)
                      : r.kind === 'clip' ? (project?.tracks.flatMap((t) => t.clips)
                        .find((c) => c.id === r.id)?.start ?? 0) : r.t)
                  }}>
                  <b>{j + 1}</b><span className="riftesto">{rifLabel(r, project)}</span>
                </button>
                <button className="rifx" title="Remove"
                  onClick={() => setRefs((xs) => xs.filter((_, k) => k !== j))}>
                  <Icon name="chiudi" size={11} />
                </button>
              </span>
            ))}
          </div>
        )}
        <div className="rifbar">
          <span className="hint">point at:</span>
          <button className="chip" disabled={!project} title="The moment under the playhead"
            onClick={() => addRef({ kind: 'time', t: playhead })}>
            <Icon name={RIF_ICON.time} size={13} />moment</button>
          <button className={`chip ${tratto != null ? 'on' : ''}`} disabled={!project}
            title={tratto == null ? 'Mark the start, move the playhead, then mark the end'
              : 'Move the playhead to the end of the range and press again'}
            onClick={() => {
              if (tratto == null) { setTratto(playhead); return }
              addRef({ kind: 'range', a: tratto, b: playhead })
              setTratto(null)
            }}>
            <Icon name={RIF_ICON.range} size={13} />
            {tratto == null ? 'range' : `end (from ${fmt(tratto)})`}</button>
          <button className="chip" disabled={!selected} title="The clip selected in the timeline"
            onClick={() => addRef({ kind: 'clip', id: selected })}>
            <Icon name={RIF_ICON.clip} size={13} />clip</button>
          <button className={`chip ${pickArea ? 'on' : ''}`} disabled={!project}
            title="Draw a box on the frame"
            onClick={() => setPickArea((v) => !v)}>
            <Icon name={RIF_ICON.area} size={13} />{pickArea ? 'draw…' : 'area'}</button>
          <button className="chip" disabled={caricando > 0}
            title="Attach images, PDFs, text, video or audio (also by dropping them here or with Ctrl+V)"
            onClick={() => fileRef.current?.click()}>
            <Icon name={RIF_ICON.file} size={13} />{caricando ? 'uploading…' : 'file'}</button>
          <input ref={fileRef} type="file" multiple hidden
            onChange={(e) => { allega(e.target.files); e.target.value = '' }} />
          <button className={`chip ${linkAperto ? 'on' : ''}`} disabled={caricando > 0}
            title="A web page, an image, a video or an audio file from the internet"
            onClick={() => setLinkAperto((v) => !v)}>
            <Icon name={RIF_ICON.link} size={13} />link</button>
          <button className="chip" title="A folder on this computer: the assistant sees its files"
            onClick={() => setSceltaCartella(true)}>
            <Icon name={RIF_ICON.folder} size={13} />folder</button>
        </div>
        {linkAperto && (
          <div className="linkbar">
            <input autoFocus value={linkTesto} placeholder="paste a link and press Enter"
              onChange={(e) => setLinkTesto(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') { e.preventDefault(); aggiungiLink(linkTesto) }
                if (e.key === 'Escape') setLinkAperto(false)
              }} />
            <button className="chip" disabled={!linkTesto.trim() || caricando > 0}
              onClick={() => aggiungiLink(linkTesto)}>{caricando ? 'reading…' : 'add'}</button>
          </div>
        )}
        {sceltaCartella && (
          <FileBrowser title="Choose a folder to show the assistant" cartella
            memoria="chat-cartelle" onClose={() => setSceltaCartella(false)}
            onPick={([p]) => addRef({ kind: 'folder', path: p, name: p.split(/[\\/]/).filter(Boolean).pop() })} />
        )}
        <div className="chatbar">
          <textarea
            rows={2} value={input} disabled={busy}
            placeholder={busy ? 'working…'
              : refs.length ? 'what should change? (you can write "in 1", "at 2"…)' : 'ask for a change…'}
            onChange={(e) => setInput(e.target.value)}
            onPaste={(e) => {
              // un'immagine copiata (uno screenshot) si incolla come allegato
              const files = [...(e.clipboardData?.files || [])]
              if (files.length) { e.preventDefault(); allega(files); return }
              // un link incollato da solo diventa un riferimento, letto dal server
              const testo = e.clipboardData?.getData('text')?.trim() || ''
              if (URL_SOLO.test(testo)) { e.preventDefault(); aggiungiLink(testo) }
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() }
            }}
          />
          {busy ? (
            <button className="primary icon ferma" title="Stop the assistant"
              onClick={() => api.chatStop().catch(() => {})}><Icon name="ferma" /></button>
          ) : (
            <button className="primary icon" disabled={caricando > 0 || !input.trim()} onClick={send}
              title="Send (Enter)"><Icon name="invia" /></button>
          )}
        </div>
      </div>
    </div>
  )
}

/**
 * Le domande dell'assistente, come in Claude Code: opzioni da cliccare, una
 * casella per scrivere altro, e "non rispondere" per chiuderle. Finche' non si
 * risponde l'assistente aspetta: niente export o scelte prese al posto tuo.
 */
function DomandaCard({ domanda, onRisposta }) {
  const [scelte, setScelte] = useState({})   // indice -> etichette scelte
  const [altro, setAltro] = useState({})     // indice -> testo libero
  const lista = domanda.domande || []
  const pronta = lista.every((_, i) => (scelte[i]?.length > 0) || (altro[i] || '').trim())

  const tocca = (i, etichetta, multipla) => setScelte((s) => {
    const ora = s[i] || []
    if (!multipla) return { ...s, [i]: ora[0] === etichetta ? [] : [etichetta] }
    return { ...s, [i]: ora.includes(etichetta) ? ora.filter((x) => x !== etichetta) : [...ora, etichetta] }
  })

  const invia = () => {
    const risposte = {}
    lista.forEach((d, i) => {
      const scritto = (altro[i] || '').trim()
      const sc = scelte[i] || []
      risposte[d.domanda] = d.multipla ? [...sc, ...(scritto ? [scritto] : [])] : (scritto || sc[0])
    })
    onRisposta(risposte)
  }

  return (
    <div className="domande">
      <div className="domtesta"><Icon name="assistente" size={14} />The assistant asks you</div>
      {lista.map((d, i) => (
        <div key={i} className="domanda">
          {d.titolo && <span className="domtitolo">{d.titolo}</span>}
          <div className="domtesto">{d.domanda}</div>
          <div className="opzioni">
            {d.opzioni.map((o) => {
              const on = (scelte[i] || []).includes(o.etichetta)
              return (
                <button key={o.etichetta} className={`opzione ${on ? 'on' : ''}`}
                  onClick={() => tocca(i, o.etichetta, d.multipla)}>
                  <span className={`spunta ${d.multipla ? 'quadra' : ''}`}>{on && <Icon name="spunta" size={11} />}</span>
                  <span className="otesto"><b>{o.etichetta}</b>{o.descrizione && <small>{o.descrizione}</small>}</span>
                </button>
              )
            })}
          </div>
          <input className="altro" placeholder="other: write your answer" value={altro[i] || ''}
            onChange={(e) => setAltro((a) => ({ ...a, [i]: e.target.value }))}
            onKeyDown={(e) => { if (e.key === 'Enter' && pronta) invia() }} />
          {d.multipla && <div className="hint">you can pick more than one</div>}
        </div>
      ))}
      <div className="domazioni">
        <button className="primary" disabled={!pronta} onClick={invia}>
          <Icon name="invia" />answer</button>
        <button className="ghost" onClick={() => onRisposta({ __annulla__: true })}>don't answer</button>
      </div>
    </div>
  )
}

/**
 * Un passo dell'assistente: cosa fa, su cosa, e con un clic i parametri esatti.
 */
function Passo({ passo, project }) {
  const [aperto, setAperto] = useState(false)
  const det = dettaglioStrumento(passo.name, passo.input, project)
  const haInput = passo.input && Object.keys(passo.input).length > 0
  return (
    <div className={`toolrow ${passo.state} ${aperto ? 'aperto' : ''}`}>
      <button className="toolhead" disabled={!haInput} title={haInput ? 'Show the parameters' : ''}
        onClick={() => setAperto((v) => !v)}>
        <Icon size={13} className={passo.state === 'run' ? 'spin' : ''}
          name={passo.state === 'run' ? 'attesa' : passo.state === 'ok' ? 'spunta' : 'chiudi'} />
        <span className="toolname">{TOOL_LABEL[passo.name] || passo.name.replace(/_/g, ' ')}</span>
        {det && <span className="tooldet">{det}</span>}
      </button>
      {passo.message && <div className="toolmsg">{passo.message}</div>}
      {aperto && (
        <pre className="toolargs">{JSON.stringify(passo.input, null, 2)}</pre>
      )}
    </div>
  )
}

/**
 * Scelta del modello: Claude Code sul computer, Claude con chiave, o qualunque
 * servizio compatibile OpenAI. La chiave resta su questo computer.
 */
function ModelSettings({ available, setError, onSaved }) {
  const list = available?.providers || []
  const [pid, setPid] = useState(available?.provider || list[0]?.id || '')
  const p = list.find((x) => x.id === pid)
  const [chiave, setChiave] = useState('')
  const [modello, setModello] = useState(p?.modello || '')
  const [indirizzo, setIndirizzo] = useState(p?.indirizzo || '')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    setChiave('')
    setModello(p?.modello || '')
    setIndirizzo(p?.indirizzo || '')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pid])

  const save = async () => {
    setSaving(true)
    try {
      const st = await api.setLlm({
        provider: pid, modello,
        chiave: chiave || null,
        indirizzo: p?.indirizzo_modificabile ? indirizzo : null,
      })
      onSaved(st)
      const ora = st.providers?.find((x) => x.id === pid)
      if (ora && !ora.pronto) setError(ora.motivo)
    } catch (e) { setError(e.message) } finally { setSaving(false) }
  }

  return (
    <div className="modelset">
      {available?.motivo && !available?.ok && (
        <div className="avviso">{available.motivo}</div>
      )}
      <div className="provgrid">
        {list.map((x) => (
          <button key={x.id} className={`prov ${x.id === pid ? 'on' : ''}`} onClick={() => setPid(x.id)}>
            <span className={`dot ${x.pronto ? 'ok' : ''}`} />
            <span className="pnome">{x.nome}</span>
          </button>
        ))}
      </div>
      {p && (
        <div className="provform">
          {p.nota && <div className="hint">{p.nota}</div>}
          {p.vuole_chiave && (
            <label className="campo">
              <span>API key</span>
              <input type="password" autoComplete="off" value={chiave}
                placeholder={p.chiave ? `saved (${p.chiave})${p.chiave_da_ambiente ? ' from the environment' : ''}` : 'paste the key here'}
                onChange={(e) => setChiave(e.target.value)} />
            </label>
          )}
          <label className="campo">
            <span>model</span>
            <input list={`modelli-${p.id}`} value={modello}
              placeholder={p.tipo === 'claude_code' ? 'the Claude Code default' : 'model name'}
              onChange={(e) => setModello(e.target.value)} />
            <datalist id={`modelli-${p.id}`}>
              {p.modelli.filter(Boolean).map((m) => <option key={m} value={m} />)}
            </datalist>
          </label>
          {p.indirizzo_modificabile && (
            <label className="campo">
              <span>address</span>
              <input value={indirizzo} placeholder="https://…/v1"
                onChange={(e) => setIndirizzo(e.target.value)} />
            </label>
          )}
          {p.tipo === 'claude_code' && (
            <div className="hint">
              Claude Code works on this project through the editor's MCP server
              {available?.mcp ? <> (<code>{available.mcp}</code>)</> : ''}: you see every change
              appear in the timeline as it makes it.
            </div>
          )}
          {!p.pronto && p.motivo && <div className="hint warn">{p.motivo}</div>}
          <div className="azioni">
            <button className="primary" disabled={saving} onClick={save}>
              <Icon name="spunta" />{saving ? 'saving…' : 'use this'}
            </button>
            {p.chiave && !p.chiave_da_ambiente && (
              <button className="ghost" onClick={() => { setChiave(''); api.setLlm({ provider: pid, chiave: '', attiva: false }).then(onSaved) }}>
                forget the key
              </button>
            )}
          </div>
          <div className="hint">Keys stay on this computer (~/.vedit/llm.json), never in the project.</div>
        </div>
      )}
    </div>
  )
}

/**
 * Memoria comune a tutti i progetti (memoria.py): la scrivono l'assistente e
 * l'agente MCP, qui si legge e si corregge a mano. E' un file Markdown.
 */
function EditorMemoria({ setError, onClose }) {
  const [testo, setTesto] = useState(null)
  const [file, setFile] = useState('')
  const [saving, setSaving] = useState(false)
  useEffect(() => {
    api.memoria().then((r) => { setTesto(r.testo); setFile(r.file) })
      .catch((e) => { setError(e.message); onClose() })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  const salva = async () => {
    setSaving(true)
    try { await api.salvaMemoria(testo); onClose() }
    catch (e) { setError(e.message) } finally { setSaving(false) }
  }
  return (
    <Modal title="Memory across projects" onClose={onClose}
      actions={<>
        <button onClick={onClose}>cancel</button>
        <button className="primary" disabled={testo === null || saving} onClick={salva}>
          {saving ? 'saving…' : 'save'}</button>
      </>}>
      <div className="hint" style={{ marginBottom: 8 }}>
        Preferences and choices the assistant keeps for every project: usual format, style,
        voice, channel, things to avoid. It adds them when you state one; edit or delete
        lines freely. Stays on this computer{file ? <> (<code>{file}</code>)</> : ''}.
      </div>
      <textarea className="memoria-testo" value={testo ?? 'loading…'} disabled={testo === null}
        spellCheck={false} onChange={(e) => setTesto(e.target.value)}
        placeholder={'## preferences\n- my videos are 9:16 for Reels'} />
    </Modal>
  )
}

// stili.MAX_GUIDA: quanto puo' essere lunga la guida di uno stile
const MAX_GUIDA = 20000

const PIANI = [
  ['vlog', 'medium — vlog, personal story'],
  ['shortform', 'fast — social, short cuts'],
  ['documentary', 'calm — driven by speech'],
  ['cinematic', 'slow — held shots'],
]

/**
 * Uno stile scritto dall'utente: e' un'istruzione all'assistente, con parole
 * sue, che arriva al modello a ogni messaggio come gli stili gia' pronti.
 * Resta su questo computer (~/.vedit/stili.json), non nel progetto.
 */
function EditorStile({ stile, setError, onClose, onSalvato, onEliminato }) {
  const [f, setF] = useState(stile)
  const [salvo, setSalvo] = useState(false)
  const set = (k) => (e) => setF((x) => ({ ...x, [k]: e.target.value }))
  const salva = async () => {
    setSalvo(true)
    try {
      onSalvato(await api.salvaStile({ id: f.id || null, nome: f.nome, breve: f.breve, guida: f.guida, piano: f.piano }))
    } catch (e) { setError(e.message) } finally { setSalvo(false) }
  }
  return (
    <div className="editorstile">
      <b>{f.id ? 'Edit style' : 'New style'}</b>
      <label>name<input value={f.nome} onChange={set('nome')} placeholder="e.g. My channel" autoFocus /></label>
      <label>in short<input value={f.breve} onChange={set('breve')} placeholder="one line describing it (optional)" /></label>
      <label>how the assistant should edit
        <textarea rows={14} value={f.guida} onChange={set('guida')} maxLength={MAX_GUIDA}
          placeholder={'Write it as you would tell an editor. E.g.:\n'
            + 'Always open with the strongest line. Cuts of 1-2 s, never dissolves. '
            + 'Big yellow subtitles at the bottom. Warm, saturated colour. '
            + 'Music rising at the end, close on the logo.'} />
        <span className={`hint ${f.guida.length > MAX_GUIDA * 0.9 ? 'warn' : ''}`}>
          {f.guida.length.toLocaleString()} / {MAX_GUIDA.toLocaleString()} characters</span>
      </label>
      <label>base pace
        <select value={f.piano} onChange={set('piano')}>
          {PIANI.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
      </label>
      <div className="hint">The instructions reach the assistant with every message, like a system prompt. The base pace sets how long the cuts are when it plans an edit from the footage.</div>
      <div className="editorstile-azioni">
        {f.id && (
          <button className="ghost danger" onClick={() => api.eliminaStile(f.id)
            .then((r) => onEliminato(r, f.id)).catch((e) => setError(e.message))}>
            <Icon name="cestino" size={13} />delete</button>
        )}
        <span className="spacer" />
        <button className="ghost" onClick={onClose}>cancel</button>
        <button className="primary" disabled={salvo || !f.nome.trim() || !f.guida.trim()} onClick={salva}>
          save and use</button>
      </div>
    </div>
  )
}
