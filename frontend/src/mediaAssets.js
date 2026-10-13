import { useEffect, useMemo, useState } from 'react'
import { api } from './api.js'

// Stessa altezza per tutti quelli che la usano: la striscia la genera ffmpeg e
// chiederne due misure diverse significa fargliela rigenerare da capo.
export const STRIP_H = 44

/**
 * Strisce di fotogrammi e forme d'onda, chieste una volta sola per file.
 *
 * Timeline e pannello media mostrano gli stessi media: senza una cache comune
 * ogni pannello rifarebbe le stesse richieste, e dietro la forma d'onda c'e' la
 * decodifica dell'audio del file. La chiave e' il percorso, non l'id: gli id
 * sono validi dentro un progetto, il percorso identifica il file.
 */
const valori = new Map()    // chiave -> valore, null se non disponibile
const inCorso = new Set()   // chiavi in lavorazione
const inCoda = new Map()    // chiave -> {carica, prio, n}
const ascolto = new Set()   // componenti da ridisegnare quando arriva qualcosa

// Dietro ogni richiesta c'e' ffmpeg che decodifica un file intero. Importati
// trecento file partivano trecento richieste insieme: il browser ne tiene sei
// per server, e fotogrammi e modifiche restavano in fila dietro di loro. Ne
// girano poche alla volta, prima quelle della timeline (priorita' 0) e poi
// quelle del pannello media (1), che chiede solo cio' che si vede.
export const IN_PARALLELO = 3
let attive = 0
let ordine = 0

function avanti() {
  while (attive < IN_PARALLELO && inCoda.size) {
    let scelta = null
    for (const [k, v] of inCoda) {
      if (!scelta || v.prio < scelta[1].prio || (v.prio === scelta[1].prio && v.n < scelta[1].n)) {
        scelta = [k, v]
      }
    }
    const [chiave, { carica }] = scelta
    inCoda.delete(chiave)
    inCorso.add(chiave)
    attive += 1
    carica()
      .then((r) => valori.set(chiave, r ?? null))
      .catch(() => valori.set(chiave, null))
      .finally(() => {
        inCorso.delete(chiave)
        attive -= 1
        for (const sveglia of ascolto) sveglia()
        avanti()
      })
  }
}

export function chiedi(chiave, carica, prio = 1) {
  if (valori.has(chiave) || inCorso.has(chiave)) return
  const gia = inCoda.get(chiave)
  if (gia) { gia.prio = Math.min(gia.prio, prio); return }
  inCoda.set(chiave, { carica, prio, n: ordine++ })
  avanti()
}

/** Solo per i test: riparte da cache e coda vuote. */
export function _azzera() {
  valori.clear(); inCorso.clear(); inCoda.clear(); attive = 0
}

export default function useMediaAssets(media, prio = 1) {
  const [arrivi, ridisegna] = useState(0)

  useEffect(() => {
    const sveglia = () => ridisegna((n) => n + 1)
    ascolto.add(sveglia)
    for (const m of media || []) {
      if (!m.path) continue
      if (m.kind !== 'audio') chiedi(`s:${m.path}`, () => api.strip(m.id, STRIP_H), prio)
      if (m.audio) chiedi(`w:${m.path}`, () => api.waveform(m.id), prio)
    }
    return () => ascolto.delete(sveglia)
  }, [media, prio])

  // L'oggetto cambia identita' solo quando arriva qualcosa di nuovo: la
  // timeline lo tiene fra le dipendenze del memo che disegna le clip, e uno
  // nuovo a ogni render lo invaliderebbe sempre.
  return useMemo(() => ({
    strip: (m) => (m?.path ? valori.get(`s:${m.path}`) : null) || null,
    peaks: (m) => (m?.path ? valori.get(`w:${m.path}`)?.peaks : null) || null,
  }), [arrivi])
}
