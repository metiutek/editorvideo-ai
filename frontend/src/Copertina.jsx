import React, { useEffect, useState } from 'react'
import { api } from './api.js'
import { FileBrowser } from './Dialogs.jsx'
import Icon from './Icons.jsx'
import { fmt } from './util.js'

const IMMAGINE = /\.(png|jpe?g|webp|gif|bmp)$/i

/**
 * La copertina fatta a parte (Store.set_cover), guardata accanto al video:
 * intera nel formato del progetto e piccola come la vede chi scorre, con
 * titolo e durata. Il render non la usa.
 */
export default function Copertina({ project, revision, run, setError }) {
  const [info, setInfo] = useState(null)
  const [sfoglia, setSfoglia] = useState(false)
  const [giro, setGiro] = useState(0)   // "reload": l'immagine rifatta fuori dall'editor
  const cover = project?.cover || ''

  useEffect(() => {
    if (!cover) { setInfo(null); return undefined }
    let vivo = true
    api.copertina().then((r) => { if (vivo) setInfo(r) }).catch(() => {})
    return () => { vivo = false }
  }, [cover, revision, giro])

  if (!project) return <div className="copertina"><div className="hint">Open a project first.</div></div>

  const [w, h] = (project.settings.resolution || '1920x1080').split('x').map(Number)
  const verticale = h > w
  const src = cover && info?.cover === cover && !info.missing
    ? `/api/file?path=${encodeURIComponent(cover)}&v=${info.mtime || 0}` : null
  const scegli = (paths) => {
    setSfoglia(false)
    const p = Array.isArray(paths) ? paths[0] : paths
    if (p) run('set_cover', { path: p }).catch((e) => setError(e.message))
  }

  return (
    <div className="copertina">
      <div className="section-title">
        cover
        <span className="spacer" />
        {cover && (<>
          <button className="icon sm" title="Reload: the image was changed outside the editor"
            onClick={() => setGiro((g) => g + 1)}><Icon name="ripeti" size={14} /></button>
          <button className="icon sm" title="Remove the cover"
            onClick={() => run('set_cover', { path: '' }).catch((e) => setError(e.message))}>
            <Icon name="cestino" size={14} /></button>
        </>)}
      </div>

      {!cover ? (
        <div className="copertina-vuota">
          <Icon name="immagine" size={28} />
          <div className="hint">
            The thumbnail you made elsewhere (an editor, an image generator, the assistant):
            see it next to the video, full size and as it looks in a feed.
          </div>
          <button className="primary" onClick={() => setSfoglia(true)}>
            <Icon name="immagine" size={14} />choose an image</button>
        </div>
      ) : (<>
        <div className="copertina-grande" style={{ aspectRatio: `${w} / ${h}` }}>
          {src ? <img src={src} alt="cover" />
            : <div className="hint">{info?.missing ? 'the file is gone: choose it again' : 'loading…'}</div>}
        </div>

        <div className="hint copertina-dove">{verticale ? 'in a feed of shorts' : 'in a feed of videos'}</div>
        <div className={`copertina-feed ${verticale ? 'verticale' : ''}`}>
          <div className="copertina-mini" style={{ aspectRatio: verticale ? '9 / 16' : '16 / 9' }}>
            {src && <img src={src} alt="" />}
            {!verticale && project.duration > 0 && <span className="durata">{fmt(project.duration)}</span>}
          </div>
          <div className="copertina-titolo">
            <b>{project.name}</b>
            <span className="hint">your channel</span>
          </div>
        </div>

        {info?.width && (
          <div className="hint">
            {info.width}×{info.height} · {info.format} · {Math.round(info.bytes / 1024)} KB
          </div>
        )}
        {info?.warnings?.map((a) => <div key={a} className="copertina-avviso">{a}</div>)}
        <div className="copertina-percorso" title={cover}>{cover}</div>
        <button className="ghost" onClick={() => setSfoglia(true)}>
          <Icon name="immagine" size={14} />replace</button>
      </>)}

      {sfoglia && (
        <FileBrowser title="Cover image" multiple={false} memoria="copertina"
          filter={(n) => IMMAGINE.test(n)} onClose={() => setSfoglia(false)} onPick={scegli} />
      )}
    </div>
  )
}
