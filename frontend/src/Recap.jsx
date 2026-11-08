import { useEffect, useRef, useState } from 'react'
import { api } from './api.js'
import { mandaFile } from './caricamento.js'
import { translateMessage, translateLabel } from './i18n.js'

async function richiesta(path, method = 'GET', body) {
  const r = await fetch(`/api/recap${path}`, { method, headers: { 'Content-Type': 'application/json' },
    ...(body ? { body: JSON.stringify(body) } : {}) })
  const d = await r.json()
  if (!r.ok) throw new Error(d.detail || 'Recap request failed')
  return d
}

export default function Recap({ project, path, run, setError }) {
  const storageKey = `vedit-recap:${path || project.name}`
  const [saved] = useState(() => { try { return JSON.parse(sessionStorage.getItem(storageKey)) || {} } catch { return {} } })
  const [activities, setActivities] = useState(saved.activities || [])
  const [music, setMusic] = useState(saved.music || '')
  const [duration, setDuration] = useState(saved.duration || 30)
  const [format, setFormat] = useState(saved.format || '16:9')
  const [pace, setPace] = useState(saved.pace || 'balanced')
  const [consent, setConsent] = useState(false)
  const [job, setJob] = useState(saved.job || null)
  const [uploading, setUploading] = useState('')
  const drag = useRef(null)
  const abort = useRef(null)
  const busy = uploading || job?.state === 'running'
  const media = project?.media || []

  useEffect(() => {
    sessionStorage.setItem(storageKey, JSON.stringify({ activities, music, duration, format, pace, job }))
  }, [storageKey, activities, music, duration, format, pace, job])

  useEffect(() => {
    if (job?.state !== 'running') return
    let live = true
    const timer = setInterval(() => richiesta(`/${job.id}`).then((j) => {
      if (live) setJob(j)
    }).catch((e) => { if (live) setError(e.message) }), 1000)
    return () => { live = false; clearInterval(timer) }
  }, [job?.id, job?.state, setError])

  function dalBin() {
    const groups = new Map()
    for (const m of media.filter((m) => m.kind === 'video')) {
      const name = m.folder || 'Ungrouped'
      if (!groups.has(name)) groups.set(name, [])
      groups.get(name).push(m.id)
    }
    setActivities([...groups].map(([name, ids]) => ({ id: crypto.randomUUID(), name, media: ids, weight: 1, target: '' })))
  }

  async function importa(files, musica = false) {
    abort.current = new AbortController()
    setUploading('Uploading to the local editor…')
    try {
      if (musica) {
        const path = await mandaFile(api, files[0], { signal: abort.current.signal })
        const r = await run('import_media', { paths: [path] })
        setMusic(r[0].id)
      } else {
        const groups = new Map()
        for (const f of files) {
          if (!/\.(mp4|mov|mkv|avi|webm|m4v|mpg|mpeg|wmv|flv|ts)$/i.test(f.name)) continue
          const parts = (f.webkitRelativePath || f.name).split('/')
          // Una cartella radice contenente sottocartelle importa piu' eventi insieme.
          const name = parts.length > 2 ? parts.slice(0, -1).join('/') : parts[0]
          if (!groups.has(name)) groups.set(name, [])
          groups.get(name).push(f)
        }
        const added = []
        for (const [name, fs] of groups) {
          const ids = []
          // La cache degli upload usa nome/dimensione/mtime: due camere possono
          // avere file omonimi, quindi il nome locale include l'identita' del gruppo.
          const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(name))
          const prefix = [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, '0')).join('').slice(0, 16)
          for (const f of fs) {
            setUploading(`Importing ${name}: ${f.name}`)
            const path = await mandaFile(api, f, { signal: abort.current.signal, namespace: prefix })
            abort.current.signal.throwIfAborted()
            const r = await run('import_media', { paths: [path], folder: name })
            await run('set_media', { media_id: r[0].id, name: f.name })
            ids.push(...r.map((m) => m.id))
          }
          added.push({ id: crypto.randomUUID(), name, media: [...new Set(ids)], weight: 1, target: '' })
        }
        setActivities((a) => [...a, ...added])
        if (!added.length) throw new Error('No supported videos found in these folders')
      }
    } catch (e) { setError(e.message) } finally { setUploading('') }
  }

  function aggiorna(id, key, value) {
    setActivities((a) => a.map((e) => e.id === id ? { ...e, [key]: value } : e))
  }
  function sposta(from, to) {
    setActivities((a) => { const b = [...a]; const [e] = b.splice(from, 1); b.splice(to, 0, e); return b })
  }
  async function genera() {
    try {
      setJob(await richiesta('', 'POST', { activities: activities.map((e) => ({ ...e, weight: Number(e.weight),
        target: e.target === '' ? null : Number(e.target) })), music, duration: Number(duration), format, pace, consent }))
    } catch (e) { setError(e.message) }
  }

  return <div className="recap side">
    <h3>Activity recap</h3>
    <p>Start in an empty, saved project. Import activity folders separately, or choose a parent containing several activity folders.</p>
    <fieldset disabled={!!busy}>
      <label className="file-picker">Import activity folders<input type="file" webkitdirectory="" multiple onChange={(e) => { importa([...e.target.files]); e.target.value = '' }} /></label>
      <button onClick={dalBin}>Use folders from media bin</button>
      <ol>{activities.map((e, i) => <li key={e.id} draggable={!busy} onDragStart={(ev) => {
        drag.current = i; ev.dataTransfer.setData('text/vedit-activity', String(i))
      }} onDragEnd={() => { drag.current = null }}
        onDragOver={(ev) => { if (drag.current != null) { ev.preventDefault(); ev.stopPropagation() } }}
        onDrop={(ev) => { if (drag.current != null && !busy) { ev.preventDefault(); ev.stopPropagation(); sposta(drag.current, i) }; drag.current = null }}>
        <strong>{e.name}</strong> ({e.media.length} videos)
        <div><button disabled={i === 0} aria-label={`Move ${e.name} up`} onClick={() => sposta(i, i-1)}>↑</button>
          <button disabled={i === activities.length-1} aria-label={`Move ${e.name} down`} onClick={() => sposta(i, i+1)}>↓</button>
          <button onClick={() => setActivities((a) => a.filter((x) => x.id !== e.id))}>Remove</button></div>
        <label>Target seconds (optional)<input type="number" min="0.5" step="0.1" value={e.target} onChange={(ev) => aggiorna(e.id, 'target', ev.target.value)} /></label>
        <label>Weight<input type="number" min="0.1" step="0.1" value={e.weight} onChange={(ev) => aggiorna(e.id, 'weight', ev.target.value)} /></label>
      </li>)}</ol>
      <label className="file-picker">Upload your music<input type="file" accept="audio/*" onChange={(e) => { if (e.target.files.length) importa([...e.target.files], true); e.target.value = '' }} /></label>
      <label>Music<select value={music} onChange={(e) => setMusic(e.target.value)}><option value="">Choose music</option>
        {media.filter((m) => m.kind === 'audio').map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}</select></label>
      <label>Duration in seconds<input type="number" min="0.5" step="0.1" value={duration} onChange={(e) => setDuration(e.target.value)} /></label>
      <label>Aspect ratio<select value={format} onChange={(e) => setFormat(e.target.value)}>{['16:9', '9:16', '1:1', '4:5'].map((f) => <option key={f} value={f}>{f}</option>)}</select></label>
      <label>Pace<select value={pace} onChange={(e) => setPace(e.target.value)}>{['calm', 'balanced', 'fast'].map((p) => <option key={p} value={p}>{translateLabel(p)}</option>)}</select></label>
      <p>Configure a vision-capable model in Assistant settings first. Analysis sends contact sheets (three sampled frames per candidate, up to eight candidates per request) to that provider. No source audio or full video is sent. Provider fees may apply; the total depends on footage length and model pricing. Successful file analyses are cached locally.</p>
      <label><input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />Allow sampled-frame analysis with my configured model and any provider charges</label>
      <button className="primary" disabled={!consent || !music || !activities.length} onClick={genera}>Generate recap video</button>
    </fieldset>
    {uploading && <p role="status">{translateMessage(uploading)}</p>}
    {job && <div role="status"><progress max="100" value={job.percent} /><p>{translateMessage(job.message)}</p>
      {job.error && <p role="alert">{translateMessage(job.error)}</p>}
      {job.state === 'done' && <p>Ready on the timeline. Select any clip to trim, replace, animate, or add graphics. Save and export using the editor controls.</p>}
      {job.state === 'error' && <button onClick={genera}>Retry using cached analysis</button>}
    </div>}
    {!!busy && <button onClick={() => { if (uploading) abort.current?.abort(); else richiesta(`/${job.id}`, 'DELETE').then(setJob).catch((e) => setError(e.message)) }}>Cancel</button>}
    {job?.cancel && job.state === 'running' && <p>Cancellation requested; waiting for the current analysis step. The timeline will remain unchanged.</p>}
  </div>
}
