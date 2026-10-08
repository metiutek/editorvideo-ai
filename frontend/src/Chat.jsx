import React, { useEffect, useRef, useState } from 'react'
import { api, chat as sendChat } from './api.js'
import { FileBrowser } from './Dialogs.jsx'
import Icon from './Icons.jsx'
import { dettaglioStrumento, fmt } from './util.js'

const TOOL_LABEL = {
  project_info: 'guarda la timeline', import_media: 'importa file', add_clip: 'aggiunge una clip',
  add_clips: 'monta i tagli', add_text: 'aggiunge un titolo', add_html: 'crea una grafica',
  set_html: 'ritocca la grafica', split_clip: 'taglia', split: 'taglia', remove_clip: 'elimina una clip',
  move_clip: 'sposta una clip', move: 'sposta una clip', trim_clip: 'ritaglia', trim: 'ritaglia',
  set_speed: 'cambia velocita\'', set_fades: 'dissolvenze', crossfade: 'transizione',
  set_transition: 'transizione', apply_preset: 'applica un preset', add_effect: 'applica un effetto',
  set_transform: 'posizione e scala', set_audio: 'audio della clip', set_text: 'modifica il testo',
  add_track: 'aggiunge una traccia', close_gaps: 'chiude i buchi', undo: 'annulla',
  preview_frame: 'guarda un fotogramma', preview_grid: 'guarda il montaggio',
  ask_user: 'ti fa una domanda', add_color: 'aggiunge un colore pieno', music_beats: 'ascolta il ritmo', Read: 'guarda un\'immagine', render_video: 'esporta',
  marker: 'aggiunge un marker', remove_marker: 'toglie un marker', markers: 'legge i marker',
  set_clip: 'modifica la clip', set_track: 'modifica la traccia', move_track: 'sposta la traccia',
  remove_track: 'elimina una traccia', delete: 'elimina', redo: 'ripete', move_effect: 'riordina gli effetti',
  update_effect: 'regola un effetto', remove_effect: 'toglie un effetto', list_effects: 'guarda gli effetti',
  inspect_footage: 'guarda il girato', plan_edit: 'pianifica il montaggio', analyze_media: 'analizza un file',
  transcribe: 'trascrive il parlato', make_captions: 'crea i sottotitoli', duck_music: 'abbassa la musica sotto la voce',
  normalize_audio: 'normalizza l\'audio', audio_levels: 'misura i livelli', check_cuts: 'controlla i tagli',
  verify_edit: 'controlla il montaggio', snapshot: 'salva una versione', match_color: 'uguaglia i colori',
  Glob: 'cerca file', WebFetch: 'legge una pagina web',
}

/** Etichetta breve di un riferimento, per le pastiglie e per il messaggio. */
export function rifLabel(r, project) {
  if (r.kind === 'time') return fmt(r.t)
  if (r.kind === 'range') return `${fmt(Math.min(r.a, r.b))} → ${fmt(Math.max(r.a, r.b))}`
  if (r.kind === 'area') return `area a ${fmt(r.t)}`
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
  refs, setRefs, pickArea, setPickArea, stili = [], domanda, onRisposta,
}) {
  const [turns, setTurns] = useState([])   // {role, text, tools:[], refs}
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [settings, setSettings] = useState(false)
  // stile di montaggio: resta scelto fra una sessione e l'altra
  const [stile, setStileState] = useState(() => {
    try { return localStorage.getItem('vedit.stile') || '' } catch { return '' }
  })
  const setStile = (v) => {
    setStileState(v)
    try { localStorage.setItem('vedit.stile', v) } catch { /* senza storage resta per questa sessione */ }
  }
  const [menuStili, setMenuStili] = useState(false)
  const [tratto, setTratto] = useState(null)   // inizio di un tratto in costruzione
  const [caricando, setCaricando] = useState(0)  // allegati in arrivo
  const [sopra, setSopra] = useState(false)      // file trascinati sopra la chat
  const fileRef = useRef(null)
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
          scegli il modello
          <span className="spacer" />
          {available?.ok && (
            <button className="icon sm" title="Torna alla chat" onClick={() => setSettings(false)}>
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
            note: 'Fermato. Le modifiche gia\' fatte restano: Ctrl+Z per annullarle.',
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
        e.preventDefault(); e.stopPropagation(); setSopra(true)
      }}
      onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget)) setSopra(false) }}
      onDrop={(e) => {
        if (!e.dataTransfer.files?.length) return
        e.preventDefault(); e.stopPropagation(); setSopra(false)
        allega(e.dataTransfer.files)
      }}>
      {sopra && <div className="chatdrop">rilascia per allegare al messaggio</div>}
      <div className="section-title">
        <button className="modelpill" title="Cambia modello" onClick={() => setSettings(true)}>
          <span className="dot" />
          {available.nome}{available.model ? ` · ${available.model}` : ''}
        </button>
        <span className="spacer" />
        <button className={`stilepill ${stile ? 'on' : ''}`} title="Stile di montaggio"
          onClick={() => setMenuStili((v) => !v)}>
          <Icon name="libreria" size={13} />
          {stili.find((s) => s.id === stile)?.nome || 'stile'}
        </button>
        <button className="icon sm" onClick={reset} title="Ricomincia la conversazione">
          <Icon name="cestino" size={14} />
        </button>
      </div>

      {menuStili && (
        <div className="stilimenu">
          <div className="hint">Lo stile guida l'assistente in ogni scelta: ritmo, transizioni, colore, testi.</div>
          <button className={`stilevoce ${!stile ? 'on' : ''}`}
            onClick={() => { setStile(''); setMenuStili(false) }}>
            <b>Nessuno</b><span>decide l'assistente caso per caso</span>
          </button>
          {stili.map((s) => (
            <button key={s.id} className={`stilevoce ${stile === s.id ? 'on' : ''}`}
              onClick={() => { setStile(s.id); setMenuStili(false) }}>
              <b>{s.nome}</b><span>{s.breve}</span>
            </button>
          ))}
        </div>
      )}

      <div className="chatlog">
        {!turns.length && (
          <div className="chatempty">
            <b>Chiedi in italiano, l'assistente monta per te.</b>
            <div className="esempi">
              {['togli i primi 2 secondi della prima clip',
                'metti una dissolvenza tra le due riprese',
                'crea un sottopancia animato con il mio nome',
                'rendi il video piu\' cinematografico'].map((e) => (
                <button key={e} className="esempio" onClick={() => setInput(e)}>{e}</button>
              ))}
            </div>
            <div className="hint">
              Vuoi indicare un punto preciso? Usa i pulsanti qui sotto: istante, tratto, clip,
              un'area disegnata sull'inquadratura, un file (anche trascinandolo qui o
              incollando uno screenshot), un link o una cartella. Un link incollato da solo
              diventa un riferimento da se'. Ogni modifica si annulla con Ctrl+Z.
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
                  <div className="toolrow"><Icon size={13} name="attesa" className="spin" />sto pensando…</div>
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
                <button className="rifx" title="Togli"
                  onClick={() => setRefs((xs) => xs.filter((_, k) => k !== j))}>
                  <Icon name="chiudi" size={11} />
                </button>
              </span>
            ))}
          </div>
        )}
        <div className="rifbar">
          <span className="hint">indica:</span>
          <button className="chip" disabled={!project} title="L'istante sotto la testina"
            onClick={() => addRef({ kind: 'time', t: playhead })}>
            <Icon name={RIF_ICON.time} size={13} />istante</button>
          <button className={`chip ${tratto != null ? 'on' : ''}`} disabled={!project}
            title={tratto == null ? 'Segna l\'inizio, sposta la testina, poi segna la fine'
              : 'Sposta la testina alla fine del tratto e premi di nuovo'}
            onClick={() => {
              if (tratto == null) { setTratto(playhead); return }
              addRef({ kind: 'range', a: tratto, b: playhead })
              setTratto(null)
            }}>
            <Icon name={RIF_ICON.range} size={13} />
            {tratto == null ? 'tratto' : `fine (da ${fmt(tratto)})`}</button>
          <button className="chip" disabled={!selected} title="La clip selezionata in timeline"
            onClick={() => addRef({ kind: 'clip', id: selected })}>
            <Icon name={RIF_ICON.clip} size={13} />clip</button>
          <button className={`chip ${pickArea ? 'on' : ''}`} disabled={!project}
            title="Disegna un riquadro sull'inquadratura"
            onClick={() => setPickArea((v) => !v)}>
            <Icon name={RIF_ICON.area} size={13} />{pickArea ? 'disegna…' : 'area'}</button>
          <button className="chip" disabled={caricando > 0}
            title="Allega immagini, PDF, testi, video o audio (anche trascinandoli qui o con Ctrl+V)"
            onClick={() => fileRef.current?.click()}>
            <Icon name={RIF_ICON.file} size={13} />{caricando ? 'carico…' : 'file'}</button>
          <input ref={fileRef} type="file" multiple hidden
            onChange={(e) => { allega(e.target.files); e.target.value = '' }} />
          <button className={`chip ${linkAperto ? 'on' : ''}`} disabled={caricando > 0}
            title="Una pagina web, un'immagine, un video o un audio da internet"
            onClick={() => setLinkAperto((v) => !v)}>
            <Icon name={RIF_ICON.link} size={13} />link</button>
          <button className="chip" title="Una cartella del computer: l'assistente ne vede i file"
            onClick={() => setSceltaCartella(true)}>
            <Icon name={RIF_ICON.folder} size={13} />cartella</button>
        </div>
        {linkAperto && (
          <div className="linkbar">
            <input autoFocus value={linkTesto} placeholder="incolla un link e premi Invio"
              onChange={(e) => setLinkTesto(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') { e.preventDefault(); aggiungiLink(linkTesto) }
                if (e.key === 'Escape') setLinkAperto(false)
              }} />
            <button className="chip" disabled={!linkTesto.trim() || caricando > 0}
              onClick={() => aggiungiLink(linkTesto)}>{caricando ? 'leggo…' : 'aggiungi'}</button>
          </div>
        )}
        {sceltaCartella && (
          <FileBrowser title="Scegli una cartella da indicare all'assistente" cartella
            memoria="chat-cartelle" onClose={() => setSceltaCartella(false)}
            onPick={([p]) => addRef({ kind: 'folder', path: p, name: p.split(/[\\/]/).filter(Boolean).pop() })} />
        )}
        <div className="chatbar">
          <textarea
            rows={2} value={input} disabled={busy}
            placeholder={busy ? 'sto lavorando…'
              : refs.length ? 'cosa vuoi cambiare? (puoi scrivere "in 1", "nel 2"…)' : 'chiedi una modifica…'}
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
            <button className="primary icon ferma" title="Ferma l'assistente"
              onClick={() => api.chatStop().catch(() => {})}><Icon name="ferma" /></button>
          ) : (
            <button className="primary icon" disabled={caricando > 0 || !input.trim()} onClick={send}
              title="Invia (Invio)"><Icon name="invia" /></button>
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
      <div className="domtesta"><Icon name="assistente" size={14} />L'assistente ti chiede</div>
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
          <input className="altro" placeholder="altro: scrivi la tua risposta" value={altro[i] || ''}
            onChange={(e) => setAltro((a) => ({ ...a, [i]: e.target.value }))}
            onKeyDown={(e) => { if (e.key === 'Enter' && pronta) invia() }} />
          {d.multipla && <div className="hint">puoi sceglierne piu' d'una</div>}
        </div>
      ))}
      <div className="domazioni">
        <button className="primary" disabled={!pronta} onClick={invia}>
          <Icon name="invia" />rispondi</button>
        <button className="ghost" onClick={() => onRisposta({ __annulla__: true })}>non rispondere</button>
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
      <button className="toolhead" disabled={!haInput} title={haInput ? 'Mostra i parametri' : ''}
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
              <span>chiave API</span>
              <input type="password" autoComplete="off" value={chiave}
                placeholder={p.chiave ? `salvata (${p.chiave})${p.chiave_da_ambiente ? ' dall\'ambiente' : ''}` : 'incolla qui la chiave'}
                onChange={(e) => setChiave(e.target.value)} />
            </label>
          )}
          <label className="campo">
            <span>modello</span>
            <input list={`modelli-${p.id}`} value={modello}
              placeholder={p.tipo === 'claude_code' ? 'quello predefinito di Claude Code' : 'nome del modello'}
              onChange={(e) => setModello(e.target.value)} />
            <datalist id={`modelli-${p.id}`}>
              {p.modelli.filter(Boolean).map((m) => <option key={m} value={m} />)}
            </datalist>
          </label>
          {p.indirizzo_modificabile && (
            <label className="campo">
              <span>indirizzo</span>
              <input value={indirizzo} placeholder="https://…/v1"
                onChange={(e) => setIndirizzo(e.target.value)} />
            </label>
          )}
          {p.tipo === 'claude_code' && (
            <div className="hint">
              Claude Code lavora su questo progetto attraverso il server MCP dell'editor
              {available?.mcp ? <> (<code>{available.mcp}</code>)</> : ''}: ogni modifica
              la vedi comparire in timeline mentre la fa.
            </div>
          )}
          {!p.pronto && p.motivo && <div className="hint warn">{p.motivo}</div>}
          <div className="azioni">
            <button className="primary" disabled={saving} onClick={save}>
              <Icon name="spunta" />{saving ? 'salvo…' : 'usa questo'}
            </button>
            {p.chiave && !p.chiave_da_ambiente && (
              <button className="ghost" onClick={() => { setChiave(''); api.setLlm({ provider: pid, chiave: '', attiva: false }).then(onSaved) }}>
                dimentica la chiave
              </button>
            )}
          </div>
          <div className="hint">Le chiavi restano su questo computer (~/.vedit/llm.json), mai nel progetto.</div>
        </div>
      )}
    </div>
  )
}
