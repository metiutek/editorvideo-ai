import React, { useMemo, useState } from 'react'
import Icon from './Icons.jsx'

/**
 * Libreria di look, catene audio e transizioni gia' pronte.
 *
 * Il pannello proprieta' espone i mattoni con tutti i parametri; qui si sceglie
 * per nome. Clic = applica alla clip selezionata, trascina = applica alla clip
 * su cui lasci il mouse.
 */
export default function Library({ library, clip, onPreset, onTransition, setError, onProva }) {
  const [q, setQ] = useState('')
  const [tab, setTab] = useState('video')   // video | audio | transitions

  const items = useMemo(() => {
    const list = library?.[tab] || []
    const needle = q.trim().toLowerCase()
    const hit = needle
      ? list.filter((p) => `${p.name} ${p.desc || ''} ${p.group}`.toLowerCase().includes(needle))
      : list
    const groups = new Map()
    for (const p of hit) {
      if (!groups.has(p.group)) groups.set(p.group, [])
      groups.get(p.group).push(p)
    }
    return [...groups.entries()]
  }, [library, tab, q])

  const isTransition = tab === 'transitions'

  const apply = (item) => {
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
      </div>

      <div className="libsearch">
        <Icon name="cerca" size={14} />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="search…"
          onKeyDown={(e) => e.key === 'Escape' && setQ('')} />
      </div>

      <div className="medialist">
        {items.map(([group, list]) => (
          <div key={group}>
            <div className="libgroup">{group}</div>
            {list.map((p) => (
              <div
                key={p.id}
                className="preset"
                draggable
                onDragStart={(e) => {
                  e.dataTransfer.setData(isTransition ? 'text/transition' : 'text/preset', p.id)
                  if (isTransition) e.dataTransfer.setData('text/duration', String(p.duration))
                  e.dataTransfer.effectAllowed = 'copy'
                }}
                onClick={() => { onProva?.(null); apply(p) }}
                // le transizioni non si provano in un fotogramma fermo: sono un
                // passaggio *fra* due clip, e un istante solo non direbbe nulla
                onMouseEnter={() => !isTransition && clip && onProva?.({ preset: p.id, label: p.name })}
                onMouseLeave={() => onProva?.(null)}
                title={`${p.desc || ''}`
                  + (isTransition || !clip ? '' : '\nhover to preview it')
                  + '\nclick: apply · drag: drop on the clip'}
              >
                {/* l'icona sta sull'id: e' lo stesso nome che usa il backend,
                    quindi non serve una tabella di conversione qui */}
                <div className="picon"><Icon name={p.id} size={18} /></div>
                <div className="ptesto">
                  <div className="pname">{p.name}</div>
                  {p.desc && <div className="pdesc">{p.desc}</div>}
                </div>
              </div>
            ))}
          </div>
        ))}
        {!items.length && <div className="hint" style={{ padding: 12 }}>No results.</div>}
      </div>

      <div className="libfoot hint">{target}</div>
    </div>
  )
}
