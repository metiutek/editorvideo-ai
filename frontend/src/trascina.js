import { useEffect } from 'react'

/**
 * Chiama ``spegni`` quando un trascinamento finisce, dovunque finisca.
 *
 * Ogni zona che si accende sotto un file trascinato si spegneva solo se il
 * file veniva lasciato *su di lei*: lasciandolo altrove (la chat, che lo
 * trattiene per allegarlo) il tratteggio restava acceso. Il rilascio si
 * ascolta sulla finestra in fase di cattura, cosi' arriva anche quando
 * qualcuno ferma la propagazione.
 */
export function useFineTrascinamento(spegni) {
  useEffect(() => {
    const fine = () => spegni()
    const fuori = (e) => { if (!e.relatedTarget) spegni() }   // uscito dalla finestra
    window.addEventListener('drop', fine, true)
    window.addEventListener('dragend', fine, true)
    window.addEventListener('dragleave', fuori, true)
    return () => {
      window.removeEventListener('drop', fine, true)
      window.removeEventListener('dragend', fine, true)
      window.removeEventListener('dragleave', fuori, true)
    }
  }, [spegni])
}

/**
 * File trascinati dal desktop, cartelle comprese.
 *
 * ``dataTransfer.files`` di una cartella trascinata contiene la cartella stessa
 * come un "file" senza estensione: il contenuto non c'e', e l'import diceva
 * "nessun file multimediale riconosciuto" davanti a una cartella piena di
 * effetti sonori e canzoni. Qui si scende nelle cartelle con le entry del
 * filesystem e ogni file porta con se' la sua sottocartella relativa, che
 * diventa la cartella del bin.
 *
 * Va chiamata dentro l'evento drop, prima di qualunque await: finito l'evento
 * il browser svuota ``dataTransfer`` e le entry non si leggono piu'.
 */
export function leggiTrascinati(dt) {
  const entries = [...(dt?.items || [])]
    .filter((it) => it.kind === 'file')
    .map((it) => it.webkitGetAsEntry?.())
  if (!entries.length || entries.some((e) => !e)) {
    // browser senza entry: si lavora coi soli file, come prima
    return Promise.resolve([...(dt?.files || [])].map((file) => ({ file, cartella: '' })))
  }
  return Promise.all(entries.map((e) => visita(e, ''))).then((liste) => liste.flat())
}

async function visita(entry, cartella) {
  if (entry.isFile) {
    const file = await new Promise((ok, ko) => entry.file(ok, ko))
    return [{ file, cartella }]
  }
  if (!entry.isDirectory) return []
  const dentro = cartella ? `${cartella}/${entry.name}` : entry.name
  const reader = entry.createReader()
  const figli = []
  // readEntries restituisce a blocchi (100 su Chrome): si legge finche' torna vuoto
  for (;;) {
    const blocco = await new Promise((ok, ko) => reader.readEntries(ok, ko))
    if (!blocco.length) break
    figli.push(...blocco)
  }
  const liste = await Promise.all(figli.map((f) => visita(f, dentro)))
  return liste.flat()
}
