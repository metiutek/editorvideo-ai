import React, { useEffect, useRef, useState } from 'react'
import { api, chat as sendChat } from './api.js'
import Icon from './Icons.jsx'
import { fmt } from './util.js'

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
  music_beats: 'ascolta il ritmo', Read: 'guarda un\'immagine', render_video: 'esporta',
}

/** Etichetta breve di un riferimento, per le pastiglie e per il messaggio. */
export function rifLabel(r, project) {
  if (r.kind === 'time') return fmt(r.t)
  if (r.kind === 'range') return `${fmt(Math.min(r.a, r.b))} → ${fmt(Math.max(r.a, r.b))}`
  if (r.kind === 'area') return `area a ${fmt(r.t)}`
  if (r.kind === 'clip') {
    const c = project?.tracks.flatMap((t) => t.clips).find((x) => x.id === r.id)
    return c ? `clip ${c.name || c.id}` : `clip ${r.id}`
  }
  return '?'
}

const RIF_ICON = { time: 'orologio', range: 'taglia', area: 'riquadro', clip: 'video' }

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
  refs, setRefs, pickArea, setPickArea,
}) {
  const [turns, setTurns] = useState([])   // {role, text, tools:[], refs}
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [settings, setSettings] = useState(false)
  const [tratto, setTratto] = useState(null)   // inizio di un tratto in costruzione
  const endRef = useRef(null)
  const abortRef = useRef(null)

  useEffect(() => { endRef.current?.scrollIntoView({ block: 'end' }) }, [turns, busy])

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
      await sendChat(q, sentRefs, (ev) => {
        if (ev.type === 'text') patch((m) => ({ ...m, thinking: false, text: m.text + ev.text }))
        else if (ev.type === 'thinking') patch((m) => ({ ...m, thinking: true }))
        else if (ev.type === 'note') patch((m) => ({ ...m, note: ev.message }))
        else if (ev.type === 'tool') {
          patch((m) => ({ ...m, thinking: false, tools: [...m.tools, { name: ev.name, state: 'run' }] }))
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
    <div className="chat">
      <div className="section-title">
        <button className="modelpill" title="Cambia modello" onClick={() => setSettings(true)}>
          <span className="dot" />
          {available.nome}{available.model ? ` · ${available.model}` : ''}
        </button>
        <span className="spacer" />
        <button className="icon sm" onClick={reset} title="Ricomincia la conversazione">
          <Icon name="cestino" size={14} />
        </button>
      </div>

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
              Vuoi indicare un punto preciso? Usa i pulsanti qui sotto: istante, tratto, clip
              oppure disegna un'area sull'inquadratura. Ogni modifica si annulla con Ctrl+Z.
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
                      <span key={j} className="rif"><b>{j + 1}</b>{rifLabel(r, project)}</span>
                    ))}
                  </div>
                )}
                {m.text}
              </>
            ) : (
              <>
                {m.tools?.map((t, j) => (
                  <div key={j} className={`toolrow ${t.state}`}>
                    <Icon size={13} className={t.state === 'run' ? 'spin' : ''}
                      name={t.state === 'run' ? 'attesa' : t.state === 'ok' ? 'spunta' : 'chiudi'} />
                    {TOOL_LABEL[t.name] || t.name.replace(/_/g, ' ')}
                    {t.message && <span className="hint"> — {t.message}</span>}
                  </div>
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
        <div ref={endRef} />
      </div>

      <div className="chatfoot">
        {refs.length > 0 && (
          <div className="rifs">
            {refs.map((r, j) => (
              <span key={j} className="rif" title="Vai a questo punto">
                <button className="rifgo" onClick={() => seek(r.kind === 'range' ? Math.min(r.a, r.b)
                  : r.kind === 'clip' ? (project?.tracks.flatMap((t) => t.clips)
                    .find((c) => c.id === r.id)?.start ?? 0) : r.t)}>
                  <b>{j + 1}</b>{rifLabel(r, project)}
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
        </div>
        <div className="chatbar">
          <textarea
            rows={2} value={input} disabled={busy}
            placeholder={busy ? 'sto lavorando…'
              : refs.length ? 'cosa vuoi cambiare? (puoi scrivere "in 1", "nel 2"…)' : 'chiedi una modifica…'}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() }
            }}
          />
          <button className="primary icon" disabled={busy || !input.trim()} onClick={send}
            title="Invia (Invio)"><Icon name="invia" /></button>
        </div>
      </div>
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
