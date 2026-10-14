import React, { useEffect, useState } from 'react'
import { api } from './api.js'

// model.SURROUND, con il nome che si legge
const INSTRADA = [['front', 'front'], ['center', 'centre'], ['surround', 'rear'],
  ['all', 'all'], ['lfe', 'LFE']]
const DB_MIN = -60
const DB_MAX = 6
const SCALA = [6, 0, -6, -12, -24, -36, -48, -60]

/** Volume lineare (1 = invariato) e decibel: il fader ragiona in dB, il progetto in lineare. */
const aDb = (v) => (v <= 0 ? DB_MIN : Math.max(DB_MIN, Math.min(DB_MAX, 20 * Math.log10(v))))
const daDb = (db) => (db <= DB_MIN + 0.01 ? 0 : 10 ** (db / 20))
const altezza = (db) => Math.max(0, Math.min(1, (db - DB_MIN) / (DB_MAX - DB_MIN)))
const testoDb = (db) => (db <= -89 ? '-∞' : `${db > 0 ? '+' : ''}${db.toFixed(1)}`)

/**
 * Mixer: un canale per traccia che suona e il master.
 *
 * I misuratori leggono l'inviluppo calcolato dal server (review.livelli): ogni
 * traccia renderizzata da sola con effetti e fader, il master col mix vero.
 * Sono i livelli che usciranno nel file, non una stima del browser, e si
 * vedono anche a riproduzione ferma, sotto la testina.
 */
export default function Mixer({ project, playhead, revision, run, setError }) {
  const [livelli, setLivelli] = useState(null)
  const [misuro, setMisuro] = useState(false)
  const vuoto = !project || !(project.duration > 0)

  useEffect(() => {
    if (vuoto) { setLivelli(null); return undefined }
    let vivo = true
    const t = setTimeout(() => {
      setMisuro(true)
      api.mixerLevels(revision)
        .then((d) => { if (vivo) setLivelli(d) })
        .catch((e) => { if (vivo) setError(e.message) })
        .finally(() => { if (vivo) setMisuro(false) })
    }, 500)
    return () => { vivo = false; clearTimeout(t) }
  }, [vuoto, revision, setError])

  if (vuoto) return <div className="mixer"><div className="hint">The timeline is empty: nothing to mix.</div></div>

  const surround = project.settings?.audio_layout === '5.1'
  const i = livelli ? Math.floor(playhead / livelli.passo) : 0
  const tracce = project.tracks.filter((t) => livelli?.tracce?.[t.id] || t.kind === 'audio')
  const call = (op, args) => run(op, args).catch((e) => setError(e.message))

  return (
    <div className="mixer">
      <div className="mixer-testa">
        <select value={surround ? '5.1' : 'stereo'} title="Channels of the mix and of the exported file"
          onChange={(e) => call('set_settings', { audio_layout: e.target.value })}>
          <option value="stereo">stereo</option>
          <option value="5.1">5.1 surround</option>
        </select>
        {misuro && <span className="hint">measuring…</span>}
      </div>
      <div className="mixer-canali">
        {tracce.map((t) => (
          <Canale key={t.id} nome={t.name || t.id} env={livelli?.tracce?.[t.id]} i={i}
            volume={t.volume} muto={t.muted} solo={t.solo}
            onVolume={(v) => call('set_track', { track_id: t.id, volume: v })}
            onMuto={() => call('set_track', { track_id: t.id, muted: !t.muted })}
            onSolo={() => call('set_track', { track_id: t.id, solo: !t.solo })}
            instrada={surround ? t.surround || 'front' : null}
            onInstrada={(v) => call('set_track', { track_id: t.id, surround: v })} />
        ))}
        <Canale nome="master" master env={livelli?.master} i={i}
          volume={project.master?.volume ?? 1}
          onVolume={(v) => call('set_master_volume', { volume: v })} />
      </div>
      <div className="hint">
        Peak (line) and RMS (bar) under the playhead, as they will come out in the file: each track
        with its effects and fader, the master with the real mix. Double-click a fader: 0 dB.
        {surround && ' In 5.1 each track goes where its routing says: dialogue in the centre, music in front.'}
      </div>
    </div>
  )
}

function Canale({ nome, env, i, volume, muto, solo, onVolume, onMuto, onSolo, instrada, onInstrada, master }) {
  const animato = typeof volume === 'object' && volume !== null
  const db = animato ? 0 : aDb(Number(volume))
  const [bozza, setBozza] = useState(null)
  const rms = env?.rms?.[i] ?? -90
  const picco = env?.picco?.[i] ?? -90
  // tenuta del picco: il massimo dell'ultimo secondo e mezzo
  const tenuta = env?.picco ? Math.max(-90, ...env.picco.slice(Math.max(0, i - 30), i + 1)) : -90
  const mostrato = bozza ?? db
  return (
    <div className={`canale ${master ? 'master' : ''} ${muto ? 'muto' : ''}`}>
      <div className="canale-nome" title={nome}>{nome}</div>
      <div className="canale-corpo">
        <div className="misuratore" title={`peak ${testoDb(picco)} dB · RMS ${testoDb(rms)} dB`}>
          <div className="misuratore-rms" style={{ height: `${altezza(rms) * 100}%` }} />
          <div className="misuratore-picco" style={{ bottom: `${altezza(picco) * 100}%` }} />
          <div className={`misuratore-tenuta ${tenuta > -0.5 ? 'rosso' : ''}`}
            style={{ bottom: `${altezza(tenuta) * 100}%` }} />
          {SCALA.map((s) => <div key={s} className="tacca" style={{ bottom: `${altezza(s) * 100}%` }} />)}
        </div>
        <input type="range" className="fader" min={DB_MIN} max={DB_MAX} step={0.5}
          value={mostrato} disabled={animato || (!env && !master)}
          title={animato ? 'keyframed volume: change it from the track properties' : `${testoDb(mostrato)} dB`}
          onChange={(e) => setBozza(+e.target.value)}
          onPointerUp={() => { if (bozza != null) { onVolume(+daDb(bozza).toFixed(4)); setBozza(null) } }}
          onKeyUp={() => { if (bozza != null) { onVolume(+daDb(bozza).toFixed(4)); setBozza(null) } }}
          onDoubleClick={() => { setBozza(null); onVolume(1) }} />
      </div>
      <div className="canale-db">{animato ? 'kf' : testoDb(mostrato)}</div>
      <div className="canale-max" title="highest peak of the track">{env ? testoDb(env.max_db) : '—'}</div>
      {!master && (
        <div className="canale-tasti">
          <button className={muto ? 'on' : ''} title="mute" onClick={onMuto}>M</button>
          <button className={solo ? 'on' : ''} title="solo" onClick={onSolo}>S</button>
        </div>
      )}
      {instrada && (
        <select className="canale-instrada" value={instrada} onChange={(e) => onInstrada(e.target.value)}
          title="Where this track goes in 5.1">
          {INSTRADA.map(([k, n]) => <option key={k} value={k}>{n}</option>)}
        </select>
      )}
    </div>
  )
}
