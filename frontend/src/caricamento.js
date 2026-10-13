/**
 * Import di tanti file, trascinati o scelti dal disco.
 *
 * Trascinati: il browser non dice dove sta un file, quindi va copiato accanto
 * al progetto. Ogni file viaggia a pezzi su richieste sue (``/api/upload/pezzo``):
 * il progresso e' vero, una richiesta caduta si rimanda da sola, e un file gia'
 * arrivato — o arrivato a meta' in un tentativo precedente — riparte da dove era.
 *
 * Dal disco: niente copia, si importano i percorsi. In tutti e due i casi
 * l'import vero va a blocchi: il bin si riempie mentre si lavora, e un file
 * rovinato viene scartato senza buttare via gli altri.
 */

export const PEZZO = 32 << 20          // 32 MB: progresso fluido, poche richieste
const IN_PARALLELO = 3                 // file copiati insieme: il disco e' uno
export const BLOCCO = 50               // percorsi per richiesta di import
const OGNI_MS = 1500                   // un file finito aspetta al massimo tanto

const attendi = (ms, signal) => new Promise((ok, ko) => {
  const t = setTimeout(ok, ms)
  signal?.addEventListener('abort', () => { clearTimeout(t); ko(signal.reason) }, { once: true })
})

/**
 * Accoda i percorsi arrivati e li importa a blocchi, una richiesta alla volta.
 * ``importa(paths, cartella)`` torna ``{scartati}``.
 */
function importatore(importa, avanzamento, fermo = () => false) {
  let attesa = []
  let ultimo = 0
  let coda = Promise.resolve()
  const svuota = () => {
    const lotto = attesa
    attesa = []
    ultimo = Date.now()
    const gruppi = new Map()
    for (const { path, cartella } of lotto) {
      if (!gruppi.has(cartella)) gruppi.set(cartella, [])
      gruppi.get(cartella).push(path)
    }
    coda = coda.then(async () => {
      for (const [cartella, paths] of gruppi) {
        for (let i = 0; i < paths.length && !fermo(); i += BLOCCO) {
          const parte = paths.slice(i, i + BLOCCO)
          try {
            const r = await importa(parte, cartella)
            avanzamento.importati(parte.length - (r?.scartati?.length || 0), r?.scartati || [])
          } catch (e) {
            avanzamento.importati(0, parte.map((path) => ({ path, errore: e.message })))
          }
        }
      }
    })
  }
  return {
    aggiungi(path, cartella) {
      attesa.push({ path, cartella })
      if (attesa.length >= BLOCCO || Date.now() - ultimo > OGNI_MS) svuota()
    },
    fine() { if (attesa.length) svuota(); return coda },
  }
}

/** Stato dell'avanzamento, passato a ``onProgress`` a ogni cambiamento. */
function contatore(fase, file, byte, onProgress) {
  const s = { fase, file, byte, fatti: 0, inviati: 0, importati: 0, scartati: [], inizio: Date.now() }
  const avvisa = () => onProgress?.({ ...s, scartati: [...s.scartati] })
  avvisa()
  return {
    stato: s,
    inviati(n) { s.inviati += n; avvisa() },
    fatto() { s.fatti += 1; avvisa() },
    importati(n, scartati) { s.importati += n; s.scartati.push(...scartati); avvisa() },
  }
}

/** Manda un file a pezzi, riprendendo da quello che il server ha gia'. Torna il percorso. */
export async function mandaFile(api, file, { signal, onByte } = {}) {
  const q = { nome: file.name, size: file.size, mtime: Math.floor(file.lastModified || 0) }
  let st = await api.uploadStato(q)
  let off = st.ricevuti
  onByte?.(off)
  let errori = 0
  while (!st.completo) {
    signal?.throwIfAborted()
    const fine = Math.min(off + PEZZO, file.size)
    try {
      st = await api.uploadPezzo(q, off, file.slice(off, fine), signal)
      errori = 0
    } catch (e) {
      if (signal?.aborted) throw e
      // 400/404/413...: il server ha detto di no, riprovare non cambia niente
      if (e.status && e.status !== 409 && e.status < 500) throw e
      if (++errori > 4) throw e
      await attendi(500 * 2 ** (errori - 1), signal)
      st = await api.uploadStato(q)      // da dove ripartire lo sa il server
    }
    onByte?.(st.ricevuti - off)
    off = st.ricevuti
  }
  return st.path
}

/**
 * File trascinati: ``voci`` = [{file, cartella}] con la cartella del bin gia'
 * completa. Copia, importa a blocchi, torna lo stato finale.
 */
export async function caricaTrascinati(api, voci, { onProgress, signal } = {}) {
  const totale = voci.reduce((s, v) => s + v.file.size, 0)
  const conta = contatore('copio', voci.length, totale, onProgress)
  const imp = importatore((paths, cartella) => api.importa(paths, cartella), conta)
  let prossimo = 0
  const lavoratore = async () => {
    while (prossimo < voci.length && !signal?.aborted) {
      const { file, cartella } = voci[prossimo++]
      try {
        const path = await mandaFile(api, file, { signal, onByte: (n) => conta.inviati(n) })
        imp.aggiungi(path, cartella)
      } catch (e) {
        if (signal?.aborted) break
        conta.importati(0, [{ path: file.name, errore: e.message }])
      }
      conta.fatto()
    }
  }
  await Promise.all(Array.from({ length: Math.min(IN_PARALLELO, voci.length) }, lavoratore))
  // interrotto o no, quello che e' arrivato intero entra nel progetto
  await imp.fine()
  return { ...conta.stato, interrotto: !!signal?.aborted }
}

/** Percorsi sul disco (o sui dischi esterni): ``voci`` = [{path, cartella, size?}]. */
export async function importaPercorsi(api, voci, { onProgress, signal } = {}) {
  const totale = voci.reduce((s, v) => s + (v.size || 0), 0)
  const conta = contatore('importo', voci.length, totale, onProgress)
  const imp = importatore(async (paths, cartella) => {
    const r = await api.importa(paths, cartella)
    for (let i = 0; i < paths.length; i += 1) conta.fatto()
    return r
  }, conta, () => !!signal?.aborted)
  for (const v of voci) {
    if (signal?.aborted) break
    imp.aggiungi(v.path, v.cartella || '')
  }
  await imp.fine()
  return { ...conta.stato, interrotto: !!signal?.aborted }
}
