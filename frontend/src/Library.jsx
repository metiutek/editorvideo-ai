import React, { useMemo, useState } from 'react'
import Icon from './Icons.jsx'
import { translateLabel, translateMessage, useLanguage } from './i18n.js'

/**
 * Libreria di look, catene audio e transizioni gia' pronte.
 *
 * Il pannello proprieta' espone i mattoni con tutti i parametri; qui si sceglie
 * per nome. Clic = applica alla clip selezionata, trascina = applica alla clip
 * su cui lasci il mouse.
 */
export default function Library({ library, blocks, clip, onPreset, onTransition, onBlock, setError, onProva }) {
  const [language] = useLanguage()
  const [q, setQ] = useState('')
  const [tab, setTab] = useState('video')   // video | audio | transitions | graphics
  const [scelto, setScelto] = useState(null) // blocco aperto nel modulo
  const [vals, setVals] = useState({})

  const items = useMemo(() => {
    // i blocchi grafici hanno le stesse righe delle altre voci (id, nome, gruppo, descrizione)
    const list = tab === 'graphics'
      ? (blocks || []).map((b) => ({
        id: b.id, name: b.id.replace(/_/g, ' '), group: b.categoria, desc: b.descrizione,
      }))
      : (library?.[tab] || [])
    const needle = q.trim().toLowerCase()
    const hit = needle
      ? list.filter((p) => `${p.name} ${p.desc || ''} ${p.group} ${translateLabel(p.name)} ${translateLabel(p.desc)} ${translateLabel(p.group)}`.toLowerCase().includes(needle))
      : list
    const groups = new Map()
    for (const p of hit) {
      if (!groups.has(p.group)) groups.set(p.group, [])
      groups.get(p.group).push(p)
    }
    return [...groups.entries()]
  }, [library, blocks, tab, q, language])

  const isTransition = tab === 'transitions'
  const isGraphics = tab === 'graphics'
  const blocco = scelto ? (blocks || []).find((b) => b.id === scelto) : null

  const apriBlocco = (id) => {
    const b = (blocks || []).find((x) => x.id === id)
    if (!b) return
    setVals(Object.fromEntries(Object.entries(b.parametri).map(([k, p]) => [k, p.default])))
    setScelto(id)
  }
  const aggiungiBlocco = () => {
    if (!blocco) return
    // al server solo cio' che l'utente ha cambiato: il resto sono i default del blocco
    const cambiati = {}
    for (const [k, p] of Object.entries(blocco.parametri)) {
      const v = vals[k]
      if (v === p.default || v === '' || v === undefined) continue
      cambiati[k] = p.tipo === 'numero' ? Number(v) : v
    }
    onBlock?.(blocco.id, cambiati)
  }

  const apply = (item) => {
    if (isGraphics) { apriBlocco(item.id); return }
    if (isTransition) {
      if (!clip) { setError('select a clip first: the transition goes at its end'); return }
      onTransition(item.id, item.duration)
      return
    }
    // senza clip selezionata i look video vanno sul master, cioe' su tutto il video
    if (!clip && tab === 'audio') { setError('select the audio clip to apply it to'); return }
    onPreset(item.id, clip?.id ?? null)
  }

  const target = isTransition
    ? (clip ? `at the end of ${clip.name || clip.id}` : 'no clip selected')
    : (clip ? `on ${clip.name || clip.id}` : tab === 'audio' ? 'no clip selected' : 'on the whole video')

  return (
    <div className="side">
      <div className="tabs">
        <button className={tab === 'video' ? 'on' : ''} onClick={() => setTab('video')}>look</button>
        <button className={tab === 'audio' ? 'on' : ''} onClick={() => setTab('audio')}>audio</button>
        <button className={tab === 'transitions' ? 'on' : ''}
          onClick={() => setTab('transitions')}>transitions</button>
        <button className={tab === 'graphics' ? 'on' : ''}
          title="Ready-made motion graphics: titles, counters, charts, transitions"
          onClick={() => { setTab('graphics'); setScelto(null) }}>graphics</button>
      </div>

      {isGraphics && blocco ? (
        <div className="blockform">
          <button className="ghost" onClick={() => setScelto(null)}>‹ all graphics</button>
          <div className="pname">{translateLabel(blocco.id.replace(/_/g, ' '))}</div>
          <div className="pdesc">{translateLabel(blocco.descrizione)}</div>
          {Object.entries(blocco.parametri).map(([k, p]) => (
            <label key={k} className="campo" title={translateLabel(p.descrizione)}>
              <span>{translateLabel(k.replace(/_/g, ' '))}</span>
              {p.tipo === 'scelta' ? (
                <select value={vals[k] ?? p.default}
                  onChange={(e) => setVals((v) => ({ ...v, [k]: e.target.value }))}>
                  {p.scelte.map((c) => <option key={c} value={c}>{translateLabel(c)}</option>)}
                </select>
              ) : p.tipo === 'numero' ? (
                <input type="number" min={p.min} max={p.max} step="any" value={vals[k] ?? p.default}
                  onChange={(e) => setVals((v) => ({ ...v, [k]: e.target.value }))} />
              ) : p.tipo === 'colore' && /^#[0-9a-f]{6}$/i.test(String(vals[k] ?? p.default)) ? (
                <input type="color" value={vals[k] ?? p.default}
                  onChange={(e) => setVals((v) => ({ ...v, [k]: e.target.value }))} />
              ) : (
                <input type="text" value={vals[k] ?? p.default} placeholder={translateLabel(p.descrizione)}
                  onChange={(e) => setVals((v) => ({ ...v, [k]: e.target.value }))} />
              )}
            </label>
          ))}
          <button className="primary" onClick={aggiungiBlocco}>add at the playhead</button>
        </div>
      ) : null}

      {!(isGraphics && blocco) && <div className="libsearch">
        <Icon name="cerca" size={14} />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="search…"
          onKeyDown={(e) => e.key === 'Escape' && setQ('')} />
      </div>}

      {!(isGraphics && blocco) && <div className="medialist">
        {items.map(([group, list]) => (
          <div key={group}>
            <div className="libgroup">{translateLabel(group)}</div>
            {list.map((p) => (
              <div
                key={p.id}
                className="preset"
                draggable={!isGraphics}
                onDragStart={(e) => {
                  e.dataTransfer.setData(isTransition ? 'text/transition' : 'text/preset', p.id)
                  if (isTransition) e.dataTransfer.setData('text/duration', String(p.duration))
                  e.dataTransfer.effectAllowed = 'copy'
                }}
                onClick={() => { onProva?.(null); apply(p) }}
                // le transizioni non si provano in un fotogramma fermo: sono un
                // passaggio *fra* due clip, e un istante solo non direbbe nulla
                onMouseEnter={() => !isTransition && !isGraphics && clip && onProva?.({ preset: p.id, label: p.name })}
                onMouseLeave={() => onProva?.(null)}
                title={`${translateLabel(p.desc || '')}`
                  + (isTransition || !clip ? '' : '\nhover to preview it')
                  + '\nclick: apply · drag: drop on the clip'}
              >
                {/* l'icona sta sull'id: e' lo stesso nome che usa il backend,
                    quindi non serve una tabella di conversione qui */}
                <div className="picon">{isGraphics ? <Icon name="immagine" size={18} /> : <Icon name={p.id} size={18} />}</div>
                <div className="ptesto">
                  <div className="pname">{translateLabel(p.name)}</div>
                  {p.desc && <div className="pdesc">{translateLabel(p.desc)}</div>}
                </div>
              </div>
            ))}
          </div>
        ))}
        {!items.length && <div className="hint" style={{ padding: 12 }}>No results.</div>}
      </div>}

      <div className="libfoot hint">{isGraphics ? 'graphics go on a track above the footage' : translateMessage(target)}</div>
    </div>
  )
}
