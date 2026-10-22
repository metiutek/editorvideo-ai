import React, { useEffect, useRef, useState } from 'react'
import Icon from './Icons.jsx'
import { Anim, Check, EffectParams, Num, Row, Select, Text } from './Params.jsx'
import { EditorParticelle, PARTICELLE, parametriParticelle } from './Particelle.jsx'
import { FORMATI_VIDEO, formatoDi, natura } from './util.js'

// come la clip si fonde con le tracce sotto (model.BLEND_MODES)
const BLEND = ['normal', 'screen', 'add', 'multiply', 'overlay', 'softlight', 'hardlight',
  'darken', 'lighten', 'difference', 'exclusion', 'dodge', 'burn']

/** Pannello proprieta': clip selezionata, oppure progetto e master. */
export default function Inspector({
  project, effects, transitions, clip, playhead, run, setError, setBusy, onProva, onRif,
}) {
  const call = (op, args) => run(op, args).catch((e) => setError(e.message))
  return (
    <div className="inspector">
      {clip
        ? <ClipPanel clip={clip} effects={effects} transitions={transitions}
            project={project} playhead={playhead} call={call} onProva={onProva} onRif={onRif} />
        : <ProjectPanel project={project} effects={effects} call={call} setBusy={setBusy}
            setError={setError} onProva={onProva} />}
    </div>
  )
}

function ClipPanel({ clip, effects, transitions, project, playhead, call, onProva, onRif }) {
  const clipTime = Math.max(0, playhead - clip.start)
  const set = (patch) => call('set_clip', { clip_id: clip.id, ...patch })
  const tr = clip.transform || {}
  const au = clip.audio || {}
  // si mostra solo quello che la clip produce davvero nel render
  const ha = natura(clip, project)

  return (
    <>
      <div className="section-title">
        {clip.name || clip.type}
        <span className="hint">{clip.type}</span>
        <span className="spacer" />
        {onRif && (
          <button className="chip" title="Add this clip as a reference in the chat"
            onClick={() => onRif(clip.id)}>
            <Icon name="assistente" size={13} />ask
          </button>
        )}
      </div>

      <div className="group">
        <h4>clip</h4>
        <Row label="name"><Text value={clip.name} onChange={(v) => set({ name: v })} /></Row>
        <Row label="start"><Num value={clip.start} step={0.05}
          onChange={(v) => call('move_clip', { clip_id: clip.id, start: v })} /></Row>
        <Row label="duration"><Num value={clip.duration} step={0.05} min={0.05}
          onChange={(v) => set({ duration: v })} /></Row>
        {clip.type === 'media' && (
          <Row label="in point"><Num value={clip.in ?? 0} step={0.05} min={0}
            onChange={(v) => set({ in_: v })} /></Row>
        )}
        <Row label="enabled"><Check value={clip.enabled !== false} onChange={(v) => set({ enabled: v })} /></Row>
        {clip.type === 'media' && ha.video && (
          <Row label="fit"><Select value={clip.fit || 'contain'} onChange={(v) => set({ fit: v })}
            options={['contain', 'cover', 'stretch', 'none']} /></Row>
        )}
        {(ha.video || clip.type !== 'media') && (
          <Row label="blend"><Select value={clip.blend || 'normal'} onChange={(v) => set({ blend: v })}
            options={BLEND} /></Row>
        )}
        {clip.type === 'color' && (
          <Row label="colour"><Text value={clip.color} onChange={(v) => set({ color: v })} /></Row>
        )}
        {clip.type === 'media' && ha.video && (
          <div className="hint">
            contain: all visible · cover: fills by cropping · none: original size
          </div>
        )}
      </div>

      {clip.type === 'media' && (
        <div className="group">
          <h4>speed</h4>
          <Row label="factor">
            <Num value={clip.speed ?? 1} min={0.01} max={100} step={0.05}
              onChange={(v) => call('set_speed', { clip_id: clip.id, speed: v })} />
          </Row>
          <Row label="reverse">
            <Check value={!!clip.reverse}
              onChange={(v) => call('set_reverse', { clip_id: clip.id, reverse: v })} />
          </Row>
          <div className="hint">2 = double speed, 0.5 = slow motion</div>
        </div>
      )}

      {ha.video && (<>
      <div className="group">
        <h4>fades</h4>
        <Row label="in"><Num value={clip.fade_in || 0} min={0} step={0.05}
          onChange={(v) => call('set_fades', { clip_id: clip.id, fade_in: v })} /></Row>
        <Row label="out"><Num value={clip.fade_out || 0} min={0} step={0.05}
          onChange={(v) => call('set_fades', { clip_id: clip.id, fade_out: v })} /></Row>
      </div>

      <Livello clip={clip} project={project} call={call} />

      <TransitionPanel clip={clip} transitions={transitions} project={project} call={call} />

      <div className="group">
        <h4>
          position and scale
          <button className="icon sm azzera" title="Reset every value"
            onClick={() => call('set_transform',
              { clip_id: clip.id, x: 0, y: 0, scale: 1, rotation: 0, opacity: 1 })}>
            <Icon name="annulla" size={12} />
          </button>
        </h4>
        {['x', 'y', 'scale', 'rotation', 'opacity'].map((k) => (
          <Anim key={k} label={k} value={tr[k] ?? (k === 'scale' || k === 'opacity' ? 1 : 0)}
            clipTime={clipTime} animatable def={k === 'scale' || k === 'opacity' ? 1 : 0}
            min={k === 'opacity' ? 0 : undefined} max={k === 'opacity' ? 1 : undefined}
            step={k === 'x' || k === 'y' || k === 'rotation' ? 1 : 0.05}
            onChange={(v) => call('set_transform', { clip_id: clip.id, [k]: v })} />
        ))}
        <div className="hint">x/y in pixels from the centre, negative y goes up</div>
      </div>
      </>)}

      {clip.type === 'text' && <TextPanel clip={clip} call={call} />}
      {clip.type === 'html' && parametriParticelle(clip.html) && <ParticellePanel clip={clip} call={call} />}
      {clip.type === 'html' && <HtmlPanel clip={clip} call={call} />}

      {clip.link && (
      <div className="group">
        <h4>linked</h4>
        <div className="hint">video and audio of the same shot: they move, split and get
          deleted together. Unlink them to move the audio on its own (J/L cut).</div>
        <button className="btn" onClick={() => call('unlink_clip', { clip_id: clip.id })}>unlink audio and video</button>
      </div>
      )}

      {ha.audio && (
      <div className="group">
        <h4>
          audio
          <button className="icon sm azzera" title="Reset every value"
            onClick={() => call('set_audio',
              { clip_id: clip.id, gain_db: 0, mute: false, pan: 0, fade_in: 0, fade_out: 0 })}>
            <Icon name="annulla" size={12} />
          </button>
        </h4>
        <Anim label="volume dB" value={au.gain_db ?? 0} clipTime={clipTime} animatable
          def={0} min={-60} max={24} step={0.5}
          onChange={(v) => call('set_audio', { clip_id: clip.id, gain_db: v })} />
        <Row label="mute"><Check value={!!au.mute}
          onChange={(v) => call('set_audio', { clip_id: clip.id, mute: v })} /></Row>
        <Row label="pan"><Num value={au.pan ?? 0} min={-1} max={1} step={0.1}
          onChange={(v) => call('set_audio', { clip_id: clip.id, pan: v })} /></Row>
        <Row label="fade in"><Num value={au.fade_in ?? 0} min={0} step={0.05}
          onChange={(v) => call('set_audio', { clip_id: clip.id, fade_in: v })} /></Row>
        <Row label="fade out"><Num value={au.fade_out ?? 0} min={0} step={0.05}
          onChange={(v) => call('set_audio', { clip_id: clip.id, fade_out: v })} /></Row>
      </div>
      )}

      <Effects target={clip.id} list={clip.effects || []} effects={effects}
        clipTime={clipTime} call={call} onProva={onProva} ha={ha} />
    </>
  )
}

/**
 * Davanti o dietro: su quale traccia sta la clip e chi la copre.
 *
 * L'ordine di sovrapposizione e' quello delle tracce video (la piu' in alto in
 * timeline copre le altre), ma dalla clip non si capiva: si aggiungeva un
 * titolo, finiva sotto una ripresa e semplicemente non si vedeva. Qui lo si
 * dice in chiaro e lo si cambia con un clic.
 */
function Livello({ clip, project, call }) {
  const video = (project?.tracks || []).filter((t) => t.kind === 'video')
  const i = video.findIndex((t) => t.clips.some((c) => c.id === clip.id))
  if (i < 0) return null
  const fine = clip.start + clip.duration
  // chi sta sopra nello stesso tratto di tempo: e' quello che la puo' coprire
  const sopra = video.slice(i + 1).filter((t) => !t.hidden).flatMap((t) => t.clips
    // un testo non riempie l'inquadratura: non e' lui che la nasconde
    .filter((c) => c.enabled !== false && c.type !== 'text'
      && c.start < fine - 1e-3 && c.start + c.duration > clip.start + 1e-3)
    .map((c) => `${c.name || c.type} (${t.name || t.id})`))
  const muovi = (direction) => call('move_layer', { clip_id: clip.id, direction })
  const dove = video.length === 1 ? 'only video track'
    : i === video.length - 1 ? 'in front of everything' : i === 0 ? 'at the back, behind everything' : `layer ${i + 1} of ${video.length}`
  return (
    <div className="group">
      <h4>front / back</h4>
      <div className="livello">
        <div className="pila" title="The video tracks: the top one is in front">
          {video.map((t, k) => <i key={t.id} className={k === i ? 'qui' : ''} />)}
        </div>
        <div className="dove">
          <b>{video[i].name || video[i].id}</b> · {dove}
          {sopra.length > 0 && (
            <div className="hint coperta">
              above, at the same time: {sopra.slice(0, 3).join(', ')}{sopra.length > 3 ? '…' : ''}
              {' '}— if they fill the frame this clip is not visible
            </div>
          )}
        </div>
      </div>
      <div className="livello-azioni">
        <button onClick={() => muovi('up')} title="Move the clip to the track above (creates one if needed)">
          <Icon name="su" size={13} />bring forward</button>
        <button disabled={i === 0} onClick={() => muovi('down')} title="Move the clip to the track below">
          <Icon name="giu" size={13} />send backward</button>
      </div>
      {sopra.length > 0 && (
        <button className="ghost" onClick={() => muovi('top')}>bring to front</button>
      )}
    </div>
  )
}

const TR_NAMES = {
  dissolve: 'dissolve', iris: 'iris (circle)',
  wipe_right: 'wipe right', wipe_left: 'wipe left',
  wipe_down: 'wipe down', wipe_up: 'wipe up',
  slide_left: 'slide left', slide_right: 'slide right',
  slide_up: 'slide up', slide_down: 'slide down',
}

function TransitionPanel({ clip, transitions, project, call }) {
  const tr = clip.transition_out || {}
  const active = clip.transition?.type || (clip.fade_out > 0 ? 'dissolve' : '')
  const dur = clip.transition?.duration || clip.fade_out || 1.0

  // clip successiva sulla stessa traccia: serve per accostarla e sovrapporla
  const track = project?.tracks.find((t) => t.clips.some((c) => c.id === clip.id))
  const next = track?.clips
    .filter((c) => c.start >= clip.end - 1e-6 && c.id !== clip.id)
    .sort((a, b) => a.start - b.start)[0]

  const apply = (type, duration) => {
    if (next && Math.abs(next.start - clip.end) < 1e-3) {
      // clip attaccate: la transizione ha bisogno di sovrapposizione, le accosta
      call('crossfade', { clip_a: clip.id, clip_b: next.id, duration, type })
    } else {
      call('set_transition', { clip_id: clip.id, type, duration })
    }
  }

  return (
    <div className="group">
      <h4>out transition</h4>
      <Row label="type">
        <select value={active} onChange={(e) => {
          if (!e.target.value) { call('set_transition', { clip_id: clip.id, duration: 0 }); return }
          apply(e.target.value, dur)
        }}>
          <option value="">none</option>
          {(transitions || []).map((t) => (
            <option key={t} value={t}>{TR_NAMES[t] || t}</option>
          ))}
        </select>
      </Row>
      {active && (
        <Row label="duration"><Num value={dur} min={0.05} max={clip.duration} step={0.1}
          onChange={(v) => apply(active, v)} /></Row>
      )}
      <div className="hint">
        {next && Math.abs(next.start - clip.end) < 1e-3
          ? 'the next clip is moved up and overlapped by the chosen duration'
          : next
            ? 'there is a gap before the next clip: the transition reveals the background. Butt them together to cross them.'
            : 'no clip after: the transition will reveal the background'}
      </div>
    </div>
  )
}

function TextPanel({ clip, call }) {
  const t = clip.text || {}
  const set = (patch) => call('set_text', { clip_id: clip.id, ...patch })
  return (
    <div className="group">
      <h4>text</h4>
      <div className="row wide">
        <textarea rows={3} value={t.text || ''} onChange={(e) => set({ text: e.target.value })} />
      </div>
      <Row label="size"><Num value={t.font_size ?? 64} min={8} max={400} step={2}
        onChange={(v) => set({ font_size: Math.round(v) })} /></Row>
      <Row label="colour"><Text value={t.color} onChange={(v) => set({ color: v })} /></Row>
      <Row label="align"><Select value={t.align || 'center'} onChange={(v) => set({ align: v })}
        options={['left', 'center', 'right']} /></Row>
      <Row label="box"><Check value={!!t.box} onChange={(v) => set({ box: v })} /></Row>
      {t.box && (
        <>
          <Row label="box col."><Text value={t.box_color} onChange={(v) => set({ box_color: v })} /></Row>
          <Row label="opacity"><Num value={t.box_opacity ?? 0.5} min={0} max={1} step={0.05}
            onChange={(v) => set({ box_opacity: v })} /></Row>
        </>
      )}
      <Row label="border"><Num value={t.border_width ?? 0} min={0} max={20} step={1}
        onChange={(v) => set({ border_width: Math.round(v) })} /></Row>
      <Row label="font"><Text value={t.font_file} placeholder=".ttf path (optional)"
        onChange={(v) => set({ font_file: v })} /></Row>
    </div>
  )
}

/**
 * Editor del documento di una clip html.
 *
 * Si scrive e l'anteprima dal vivo si aggiorna da sola: la modifica parte
 * quando si smette di scrivere per un attimo (un passo di undo per pausa, non
 * uno per tasto), oppure subito con Ctrl+Invio. Se il documento cambia da
 * fuori — l'agente via MCP — e qui non c'e' niente in sospeso, si prende
 * quello nuovo.
 */
/**
 * Clip nata da add_particles: i parametri stanno nel suo html, e si cambiano
 * con set_particles senza ricrearla (posizione, fusione ed effetti restano).
 */
function ParticellePanel({ clip, call }) {
  const par = parametriParticelle(clip.html)
  const [editor, setEditor] = useState(false)
  const imposta = (args) => call('set_particles', { clip_id: clip.id, ...args })
  const su = par.kind === 'custom'
  return (
    <div className="group">
      <h4>particles</h4>
      <Row label="type">
        <select value={par.kind} onChange={(e) => {
          if (e.target.value === 'custom') setEditor(true)
          else imposta({ kind: e.target.value })
        }}>
          {PARTICELLE.map(([k, nome]) => <option key={k} value={k}>{nome}</option>)}
          <option value="custom">custom</option>
        </select>
      </Row>
      {['density', 'speed', 'size'].map((k) => (
        <Row key={k} label={{ density: 'density', speed: 'speed', size: 'size' }[k]}>
          <Num value={par[k] ?? 1} min={0.05} max={20} step={0.05} onChange={(v) => imposta({ [k]: v })} />
        </Row>
      ))}
      <Row label="seed"><Num value={par.seed ?? 1} min={0} step={1}
        onChange={(v) => imposta({ seed: Math.round(v) })} /></Row>
      <button className="ghost" onClick={() => setEditor(true)}>
        <Icon name="fx" size={13} />{su ? 'edit shape and motion' : 'customise'}</button>
      {editor && (
        <EditorParticelle titolo="Edit particles" applica="apply to the clip"
          iniziale={su ? par.custom : null}
          onClose={() => setEditor(false)}
          onApplica={(custom) => imposta({ kind: 'custom', custom })} />
      )}
    </div>
  )
}

function HtmlPanel({ clip, call }) {
  const [bozza, setBozza] = useState(clip.html || '')
  const sporca = useRef(false)
  const timer = useRef(null)

  useEffect(() => {
    if (!sporca.current) setBozza(clip.html || '')
  }, [clip.id, clip.html])
  useEffect(() => () => clearTimeout(timer.current), [clip.id])

  const applica = (testo) => {
    clearTimeout(timer.current)
    if (!sporca.current) return
    sporca.current = false
    if (testo !== clip.html && testo.trim()) call('set_html', { clip_id: clip.id, html: testo })
  }
  const scrivi = (testo) => {
    setBozza(testo)
    sporca.current = true
    clearTimeout(timer.current)
    timer.current = setTimeout(() => applica(testo), 700)
  }

  return (
    <div className="group">
      <h4>html</h4>
      <div className="row wide">
        <textarea className="codice" rows={16} spellCheck={false} value={bozza}
          onChange={(e) => scrivi(e.target.value)}
          onBlur={() => applica(bozza)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); applica(bozza) }
            // il tab scrive un rientro invece di saltare al campo dopo
            if (e.key === 'Tab' && !e.shiftKey) {
              e.preventDefault()
              const el = e.target
              const a = el.selectionStart
              const nuovo = bozza.slice(0, a) + '  ' + bozza.slice(el.selectionEnd)
              scrivi(nuovo)
              requestAnimationFrame(() => { el.selectionStart = el.selectionEnd = a + 2 })
            }
          }} />
      </div>
      <Row label="folder"><Text value={clip.html_base || ''}
        placeholder="for relative images and fonts (optional)"
        onChange={(v) => call('set_html', { clip_id: clip.id, base: v })} /></Row>
      <div className="hint">
        A page as big as the project, transparent background. CSS animations, GSAP,
        requestAnimationFrame and setTimeout follow the playhead; for full control
        define <code>window.veditRender = t =&gt; …</code>. Ctrl+Enter applies at once.
      </div>
    </div>
  )
}

/**
 * Il catalogo: un riquadro per effetto, con l'icona.
 *
 * Sta fuori da ``Effects`` di proposito. Dichiarato dentro, era un componente
 * nuovo a ogni render: React smontava e rimontava tutti i pulsanti, e bastava
 * il passaggio del mouse (che accende l'anteprima e quindi ridisegna) perche'
 * il pulsante premuto non fosse piu' quello rilasciato. Il clic non arrivava
 * mai e l'effetto non si applicava.
 *
 * Col mouse sopra, il monitor mostra come verrebbe senza applicarlo — il
 * fotogramma lo rende il server su una copia del progetto, quindi non c'e'
 * niente da annullare se poi non lo si vuole. Gli effetti audio non cambiano
 * un fotogramma fermo: per quelli non si prova niente.
 */
function Catalogo({ kind, effects, onProva, onAdd }) {
  const prova = (e) => kind === 'video' && onProva?.(e ? { effect: e.name, label: e.label } : null)
  return (
    <div className="fxgrid">
      {effects.filter((e) => e.kind === kind).map((e) => (
        <button
          key={e.name} className="fxcard"
          title={`${e.label}${e.desc ? ` — ${e.desc}` : ''}`
            + (kind === 'video' ? '\nHover to preview it, click to apply it.' : '\nClick to apply it.')}
          onMouseEnter={() => prova(e)}
          onMouseLeave={() => prova(null)}
          onFocus={() => prova(e)}
          onBlur={() => prova(null)}
          onClick={() => { prova(null); onAdd(e) }}
        >
          <Icon name={e.name} fallback={kind === 'audio' ? 'audio' : 'fx'} size={20} />
          <span>{e.label}</span>
        </button>
      ))}
    </div>
  )
}

function Effects({ target, list, effects, clipTime, call, onProva, ha = { video: true, audio: true } }) {
  const byName = Object.fromEntries(effects.map((e) => [e.name, e]))
  const args = (extra) => (target ? { clip_id: target, ...extra } : { clip_id: null, ...extra })
  // l'effetto appena aggiunto: si porta in vista e si evidenzia, altrimenti
  // compare piu' in alto, fuori schermo, e sembra che il clic non abbia fatto niente
  const [nuovo, setNuovo] = useState(null)
  const refs = useRef(new Map())
  useEffect(() => {
    if (nuovo == null) return
    refs.current.get(nuovo)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
    const t = setTimeout(() => setNuovo(null), 1600)
    return () => clearTimeout(t)
  }, [nuovo, list.length])
  const aggiungi = (e) => {
    const indice = list.length
    call('add_effect', args({ effect: e.name })).then((r) => { if (r !== undefined) setNuovo(indice) })
  }

  return (
    <div className="group">
      <h4>effects {list.length > 0 && <span className="hint">· {list.length} applied, in chain order</span>}</h4>
      {!list.length && <div className="hint">No effects. Pick one below: it will show up here with its parameters.</div>}
      {list.map((e) => {
        const spec = byName[e.type]
        if (!spec) return null
        return (
          <div className={`effect ${nuovo === e.i ? 'appena' : ''}`} key={e.i}
            ref={(el) => { if (el) refs.current.set(e.i, el); else refs.current.delete(e.i) }}>
            <header>
              <Check value={e.enabled !== false} title="Turn the effect on or off"
                onChange={(v) => call('update_effect', args({ index: e.i, enabled: v }))} />
              <b>{spec.label}</b>
              <span className="spacer" />
              {/* l'ordine della catena cambia il risultato: denoise prima di
                  sharpen pulisce e poi incide, al contrario incide il rumore */}
              <button className="icon sm" title="Move earlier in the chain"
                disabled={e.i === 0}
                onClick={() => call('move_effect', args({ index: e.i, to: e.i - 1 }))}>
                <Icon name="su" size={13} />
              </button>
              <button className="icon sm" title="Move later in the chain"
                disabled={e.i === list.length - 1}
                onClick={() => call('move_effect', args({ index: e.i, to: e.i + 1 }))}>
                <Icon name="giu" size={13} />
              </button>
              <button className="icon sm danger" title="Remove the effect"
                onClick={() => call('remove_effect', args({ index: e.i }))}>
                <Icon name="chiudi" size={13} />
              </button>
            </header>
            <EffectParams spec={spec} params={e.params} clipTime={clipTime}
              onChange={(patch) => call('update_effect', args({ index: e.i, params: patch }))} />
            {spec.desc && <div className="hint">{spec.desc}</div>}
            {!ha[spec.kind] && (
              <div className="hint">this clip has no {spec.kind === 'audio' ? 'sound' : 'picture'}: the effect changes nothing</div>
            )}
          </div>
        )
      })}
      <h4 className="fxtitolo">add effect</h4>
      {/* solo gli effetti che la clip puo' usare: un colore su una clip audio
          non cambierebbe niente, un compressore su un testo nemmeno */}
      {ha.video && (<>
        <div className="hint fxnota">picture — hover to preview, click to apply</div>
        <Catalogo kind="video" effects={effects} onProva={onProva} onAdd={aggiungi} />
      </>)}
      {ha.audio && (<>
        <div className="hint fxnota">sound — click to apply, you hear it on playback</div>
        <Catalogo kind="audio" effects={effects} onProva={onProva} onAdd={aggiungi} />
      </>)}
    </div>
  )
}

function ProjectPanel({ project, effects, call, setBusy, setError, onProva }) {
  const s = project?.settings
  const ln = project?.master?.loudnorm || {}
  const [lufs, setLufs] = useState(ln.target_lufs ?? -14)
  if (!project) return <div className="group hint">No project open.</div>

  const measure = async () => {
    setBusy('measuring the mix loudness…')
    try {
      const res = await fetch('/api/loudness', { method: 'POST' }).then((r) => r.json())
      await call('set_loudnorm', { enabled: true, target_lufs: lufs, measured: res.measured })
    } catch (e) { setError(e.message) } finally { setBusy(null) }
  }

  return (
    <>
      <div className="section-title">project</div>
      <div className="group">
        <h4>{project.name}</h4>
        <Row label="format"><select value={formatoDi(...s.resolution.split('x').map(Number)) || ''}
          onChange={(e) => call('set_format', { format: e.target.value })}>
          {!formatoDi(...s.resolution.split('x').map(Number)) && <option value="">custom</option>}
          {FORMATI_VIDEO.map((f) => <option key={f.id} value={f.id}>{f.id} · {f.uso}</option>)}
        </select></Row>
        <Row label="resolution"><Text value={s.resolution} onChange={(v) => {
          const [w, h] = v.split('x').map((n) => parseInt(n, 10))
          if (w > 0 && h > 0) call('set_settings', { width: w, height: h })
        }} /></Row>
        <Row label="fps"><Num value={s.fps} min={1} max={240} step={1}
          onChange={(v) => call('set_settings', { fps: v })} /></Row>
        <Row label="background"><Text value={s.background} onChange={(v) => call('set_settings', { background: v })} /></Row>
        <div className="hint">timeline duration: {project.duration.toFixed(2)}s</div>
      </div>

      <div className="group">
        <h4>overall loudness</h4>
        <Row label="normalise"><Check value={!!ln.enabled}
          onChange={(v) => call('set_loudnorm', { enabled: v, target_lufs: lufs })} /></Row>
        <Row label="target LUFS"><Num value={lufs} min={-40} max={0} step={0.5} onChange={setLufs} /></Row>
        <button onClick={measure}>measure the mix and apply</button>
        <div className="hint">
          -14 YouTube/Spotify · -16 podcast · -23 TV. {ln.measured ? 'Measured.' : 'Not measured: dynamic normalisation.'}
        </div>
      </div>

      <Sidechain project={project} call={call} />

      <Effects target={null} list={project.master.effects.map((e, i) => ({ ...e, i }))}
        effects={effects} clipTime={0} call={call} onProva={onProva} />
    </>
  )
}

/**
 * Sidechain: una traccia (la musica) si abbassa da sola quando ne suona
 * un'altra (la voce). E' un compressore vero, quindi segue anche le modifiche
 * fatte dopo, a differenza dei keyframe di "musica sotto la voce".
 */
function Sidechain({ project, call }) {
  const tracce = project.tracks
  const attivi = tracce.filter((t) => t.sidechain?.source)
  const [bersaglio, setBersaglio] = useState('')
  const [sorgente, setSorgente] = useState('')
  const [quanto, setQuanto] = useState(-30)
  const nome = (id) => tracce.find((t) => t.id === id)?.name || id
  return (
    <div className="group">
      <h4>duck a track when another one plays</h4>
      {attivi.map((t) => (
        <div key={t.id} className="row scattivo">
          <span><b>{nome(t.id)}</b> ducks when <b>{nome(t.sidechain.source)}</b> plays
            <span className="hint"> · threshold {t.sidechain.threshold} dB</span></span>
          <button className="ghost" onClick={() => call('set_sidechain', { track_id: t.id, source: null })}>
            turn off</button>
        </div>
      ))}
      <Row label="duck">
        <select value={bersaglio} onChange={(e) => setBersaglio(e.target.value)}>
          <option value="">choose the track (e.g. music)</option>
          {tracce.map((t) => <option key={t.id} value={t.id}>{t.name || t.id}</option>)}
        </select>
      </Row>
      <Row label="when plays">
        <select value={sorgente} onChange={(e) => setSorgente(e.target.value)}>
          <option value="">choose the track (e.g. voice)</option>
          {tracce.filter((t) => t.id !== bersaglio).map((t) =>
            <option key={t.id} value={t.id}>{t.name || t.id}</option>)}
        </select>
      </Row>
      <Row label="sensitivity"><Num value={quanto} min={-60} max={0} step={1} onChange={setQuanto} /></Row>
      <button disabled={!bersaglio || !sorgente}
        onClick={() => call('set_sidechain', { track_id: bersaglio, source: sorgente, threshold: quanto })}>
        turn on</button>
      <div className="hint">threshold in dB: the lower it is, the sooner it kicks in. You can also ask the assistant.</div>
    </div>
  )
}
