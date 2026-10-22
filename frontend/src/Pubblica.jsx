import React, { useEffect, useRef, useState } from 'react'
import { api } from './api.js'
import { FileBrowser, Modal } from './Dialogs.jsx'
import Icon from './Icons.jsx'

const PIATTAFORME = [
  { id: 'youtube', nome: 'YouTube' },
  { id: 'tiktok', nome: 'TikTok' },
]

/**
 * Pubblica un video gia' esportato (social.py). Il clic su "publish" e' la
 * conferma: niente parte da solo. YouTube parte privato se non si sceglie
 * altro; TikTok riceve una bozza che si pubblica dall'app.
 */
export default function Pubblica({ file: fileIniziale, nome, setError, flash, onClose }) {
  const [stato, setStato] = useState(null)
  const [pid, setPid] = useState('youtube')
  const [file, setFile] = useState(fileIniziale || '')
  const [sfoglia, setSfoglia] = useState(false)
  const [titolo, setTitolo] = useState(nome || '')
  const [descrizione, setDescrizione] = useState('')
  const [tag, setTag] = useState('')
  const [privacy, setPrivacy] = useState('private')
  const [clientId, setClientId] = useState('')
  const [segreto, setSegreto] = useState('')
  const [token, setToken] = useState('')
  const [lavoro, setLavoro] = useState(null)   // {percent, state, url, error}
  const attesa = useRef(null)

  const aggiorna = () => api.social().then(setStato).catch((e) => setError(e.message))
  useEffect(() => { aggiorna(); return () => clearInterval(attesa.current) }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  const yt = stato?.youtube
  const tt = stato?.tiktok
  const collegato = pid === 'youtube' ? yt?.collegato : tt?.collegato

  /** Il login avviene nel browser: si guarda ogni 2 s se il token e' arrivato. */
  const accedi = async () => {
    try {
      if (clientId || segreto) {
        await api.setSocial({ piattaforma: 'youtube', client_id: clientId || null, client_secret: segreto || null })
        setClientId(''); setSegreto('')
      }
      const { url } = await api.loginYoutube()
      flash('sign in to Google in the browser tab that just opened')
      clearInterval(attesa.current)
      let giri = 0
      attesa.current = setInterval(async () => {
        const st = await api.social().catch(() => null)
        if (st) setStato(st)
        if (st?.youtube.collegato || ++giri > 150) clearInterval(attesa.current)
      }, 2000)
      return url
    } catch (e) { setError(e.message) }
  }

  const salvaToken = () => api.setSocial({ piattaforma: 'tiktok', token })
    .then((st) => { setStato(st); setToken('') }).catch((e) => setError(e.message))

  const pubblica = async () => {
    try {
      const j = await api.pubblica({
        piattaforma: pid, file, titolo, descrizione, privacy,
        tag: tag.split(',').map((t) => t.trim()).filter(Boolean),
      })
      setLavoro(j)
      clearInterval(attesa.current)
      attesa.current = setInterval(async () => {
        const ora = await api.statoPubblica(j.id).catch(() => null)
        if (!ora) return
        setLavoro(ora)
        if (ora.state !== 'running') {
          clearInterval(attesa.current)
          if (ora.state === 'error') setError(ora.error)
          else flash(ora.url ? `published: ${ora.url}` : ora.nota || 'sent', 8000)
        }
      }, 1000)
    } catch (e) { setError(e.message) }
  }

  const inCorso = lavoro?.state === 'running'

  return (
    <Modal title="Publish" onClose={onClose}
      actions={<>
        <button onClick={onClose}>{lavoro?.state === 'done' ? 'close' : 'cancel'}</button>
        <button className="primary" disabled={!stato || !collegato || !file.trim() || inCorso
          || lavoro?.state === 'done' || (pid === 'youtube' && !titolo.trim())} onClick={pubblica}>
          <Icon name="pubblica" />
          {inCorso ? `uploading ${Math.round(lavoro.percent || 0)}%`
            : pid === 'tiktok' ? 'send to TikTok' : `publish (${privacy})`}
        </button>
      </>}>
      {!stato ? <div className="hint">loading…</div> : (<>
        <div className="provgrid">
          {PIATTAFORME.map((x) => (
            <button key={x.id} className={`prov ${x.id === pid ? 'on' : ''}`} onClick={() => setPid(x.id)}>
              <span className={`dot ${stato[x.id].collegato ? 'ok' : ''}`} />
              <span className="pnome">{x.nome}</span>
            </button>
          ))}
        </div>

        <div className="provform" style={{ marginTop: 10 }}>
          {pid === 'youtube' && (yt.collegato ? (
            <div className="hint">Connected{yt.canale ? <> to <b>{yt.canale}</b></> : ''}.{' '}
              <button className="ghost" onClick={() => api.scollegaSocial('youtube').then(setStato)}>sign out</button>
            </div>
          ) : (<>
            <div className="hint">{yt.nota}</div>
            <label className="campo"><span>OAuth client id</span>
              <input value={clientId} placeholder={yt.client ? 'saved' : '…apps.googleusercontent.com'}
                onChange={(e) => setClientId(e.target.value)} /></label>
            <label className="campo"><span>client secret</span>
              <input type="password" autoComplete="off" value={segreto} placeholder={yt.client ? 'saved' : ''}
                onChange={(e) => setSegreto(e.target.value)} /></label>
            <div className="azioni">
              <button disabled={!yt.client && !(clientId && segreto)} onClick={accedi}>sign in with Google</button>
            </div>
          </>))}

          {pid === 'tiktok' && (<>
            <div className="hint">{tt.nota}</div>
            {tt.scaduto && <div className="hint warn">The saved token is older than 24 hours: it has probably expired.</div>}
            <label className="campo"><span>access token</span>
              <input type="password" autoComplete="off" value={token}
                placeholder={tt.collegato ? 'saved' : 'act.…'} onChange={(e) => setToken(e.target.value)} /></label>
            <div className="azioni">
              <button disabled={!token.trim()} onClick={salvaToken}>save token</button>
              {tt.collegato && <button className="ghost" onClick={() => api.scollegaSocial('tiktok').then(setStato)}>forget</button>}
            </div>
          </>)}

          <div className="row"><label>video</label>
            <input value={file} placeholder="export the video first" onChange={(e) => setFile(e.target.value)} />
            <button className="ghost" onClick={() => setSfoglia(true)}>…</button></div>

          {pid === 'youtube' && (<>
            <div className="row"><label>title</label>
              <input value={titolo} maxLength={100} onChange={(e) => setTitolo(e.target.value)} /><span /></div>
            <label className="campo"><span>description</span>
              <textarea rows={4} value={descrizione} maxLength={5000}
                onChange={(e) => setDescrizione(e.target.value)} /></label>
            <div className="row"><label>tags</label>
              <input value={tag} placeholder="travel, mountains, shorts" onChange={(e) => setTag(e.target.value)} /><span /></div>
            <div className="row"><label>visibility</label>
              <select value={privacy} onChange={(e) => setPrivacy(e.target.value)}>
                <option value="private">private — only you</option>
                <option value="unlisted">unlisted — anyone with the link</option>
                <option value="public">public</option>
              </select><span /></div>
          </>)}

          {lavoro?.state === 'done' && (
            <div className="hint">
              {lavoro.url ? <>Published: <a href={lavoro.url} target="_blank" rel="noreferrer">{lavoro.url}</a></> : lavoro.nota}
            </div>
          )}
        </div>
      </>)}
      {sfoglia && (
        <FileBrowser title="Video to publish" multiple={false} onClose={() => setSfoglia(false)}
          onPick={(paths) => { setFile(Array.isArray(paths) ? paths[0] : paths); setSfoglia(false) }} />
      )}
    </Modal>
  )
}
