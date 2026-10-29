/**
 * Verifiche delle funzioni pure della UI (niente DOM).
 *
 *   node test-util.mjs
 */
import assert from 'node:assert/strict'
import { leggiTrascinati } from './src/trascina.js'
import { BLOCCO, PEZZO, caricaTrascinati, importaPercorsi, mandaFile } from './src/caricamento.js'
import { IN_PARALLELO, _azzera, chiedi } from './src/mediaAssets.js'
import { dettaglioStrumento, impronta, rispostaEq, isKf, sampleKf, transformBox, natura, mostraEsatto,
  dimensioni, formatoDi, vociComando } from './src/util.js'

let ok = 0
const test = (name, fn) => {
  try { fn(); ok++; console.log('ok   ' + name) }
  catch (e) { console.log('FAIL ' + name + ': ' + e.message); process.exitCode = 1 }
}

test('menu "/": comandi dell\'editor, poi le skill', () => {
  const skill = [{ name: 'caveman:caveman', description: 'talk short' }, { name: 'titoli', description: 'big titles' }]
  assert.equal(vociComando('ciao', skill), null)
  // con lo spazio si stanno scrivendo gli argomenti: il menu si chiude
  assert.equal(vociComando('/titoli tre righe', skill), null)
  const tutte = vociComando('/', skill)
  assert.equal(tutte[0].name, 'clear')
  assert.ok(tutte[0].locale && tutte.some((v) => v.name === 'titoli' && !v.locale))
  // prima chi comincia cosi', poi chi lo contiene
  assert.deepEqual(vociComando('/ti', skill).map((v) => v.name), ['titoli', 'settings'])
  assert.deepEqual(vociComando('/st', skill).map((v) => v.name), ['stop', 'style'])
  assert.deepEqual(vociComando('/man', skill).map((v) => v.name), ['caveman:caveman'])
  assert.deepEqual(vociComando('/big', skill).map((v) => v.name), ['titoli'])
})

test('diretta: fotogramma esatto da fermi dove il browser non basta', () => {
  const base = { diretta: true, prova: null, approssimato: true, playing: false, url: 'f.jpg', pending: false }
  assert.equal(mostraEsatto(base), true)
  // in riproduzione resta la diretta: il fotogramma esatto sarebbe fermo
  assert.equal(mostraEsatto({ ...base, playing: true }), false)
  // mentre arriva quello nuovo non si mostra il vecchio, che e' di un altro istante
  assert.equal(mostraEsatto({ ...base, pending: true }), false)
  // il browser rifa' tutto: niente da sostituire
  assert.equal(mostraEsatto({ ...base, approssimato: false }), false)
  // in fedele e durante la prova di un effetto il monitor mostra gia' il fotogramma
  assert.equal(mostraEsatto({ ...base, diretta: false }), false)
  assert.equal(mostraEsatto({ ...base, prova: { label: 'glow' } }), false)
  assert.equal(mostraEsatto({ ...base, url: null }), false)
})

test('passi dell\'assistente: su cosa lavorano, in parole', () => {
  const project = {
    media: [{ id: 'm1', name: 'ripresa.mp4' }],
    tracks: [{ id: 'V1', clips: [{ id: 'c1', name: 'intro' }] }],
  }
  assert.equal(dettaglioStrumento('set_transform', { clip_id: 'c1', x: 10, scale: 2 }, project),
    'clip intro · x, scale')
  assert.equal(dettaglioStrumento('add_clip', { media_id: 'm1', start: 2, duration: 3 }, project),
    'ripresa.mp4 · 0:02.0 → 0:05.0')
  assert.equal(dettaglioStrumento('import_media', { paths: ['C:\\video\\a.mp4'] }, project), 'a.mp4')
  assert.equal(dettaglioStrumento('project_info', {}, project), '')
  assert.equal(dettaglioStrumento('x', null, project), '')
  assert.equal(dettaglioStrumento('ask_user', { domande: [{ titolo: 'Export', domanda: 'Esporto?' }] }, project),
    'Export')
})

test('curva dell\'equalizzatore: campane, scaffali e filtri al posto giusto', () => {
  const vicino = (a, b, tol = 0.6) => assert.ok(Math.abs(a - b) < tol, `${a} invece di ${b}`)
  vicino(rispostaEq([{ type: 'peak', freq: 1000, gain: -12, q: 2 }], 1000), -12)
  vicino(rispostaEq([{ type: 'peak', freq: 1000, gain: -12, q: 2 }], 100), 0)
  vicino(rispostaEq([{ type: 'lowshelf', freq: 200, gain: 6, q: 0.7 }], 30), 6, 1)
  vicino(rispostaEq([{ type: 'highshelf', freq: 8000, gain: -6, q: 0.7 }], 18000), -6, 1)
  assert.ok(rispostaEq([{ type: 'highpass', freq: 100, q: 0.7 }], 20) < -20)
  assert.ok(rispostaEq([{ type: 'lowpass', freq: 5000, q: 0.7 }], 15000) < -15)
  // banda spenta = piatto
  vicino(rispostaEq([{ type: 'peak', freq: 1000, gain: 12, q: 1, on: false }], 1000), 0)
})

test('impronta: stabile, e cambia col documento della clip html', () => {
  assert.equal(impronta('<p>a</p>'), impronta('<p>a</p>'))
  assert.notEqual(impronta('<p>a</p>'), impronta('<p>b</p>'))
  assert.equal(typeof impronta(undefined), 'string')
})

test('isKf torna sempre un booleano (uno 0 in JSX si stampa)', () => {
  assert.equal(isKf(0), false)
  assert.equal(isKf(null), false)
  assert.equal(isKf({ kf: [] }), true)
})

test('keyframe interpolati come nel backend', () => {
  const v = { kf: [{ t: 0, v: 0 }, { t: 2, v: 10 }] }
  assert.equal(isKf(v), true)
  assert.equal(sampleKf(v, -1), 0)
  assert.equal(sampleKf(v, 1), 5)
  assert.equal(sampleKf(v, 9), 10)
  assert.equal(sampleKf(3.5, 1), 3.5)
})

test('easing: ease_in_out passa da meta a meta strada', () => {
  const v = { kf: [{ t: 0, v: 0, ease: 'ease_in_out' }, { t: 1, v: 1 }] }
  assert.equal(sampleKf(v, 0.5), 0.5)
  assert.ok(sampleKf(v, 0.2) < 0.2)
})

test('riquadro: clip a schermo intero copre tutta l anteprima', () => {
  const r = transformBox({
    box: { left: 10, top: 4, w: 960, h: 540 },
    canvas: { width: 1920, height: 1080 },
    native: { width: 1920, height: 1080 },
  })
  assert.equal(r.k, 0.5)
  assert.equal(r.left, 10)
  assert.equal(r.top, 4)
  assert.equal(r.width, 960)
  assert.equal(r.height, 540)
})

test('riquadro: scala e offset in pixel di progetto', () => {
  const r = transformBox({
    box: { left: 0, top: 0, w: 960, h: 540 },
    canvas: { width: 1920, height: 1080 },
    native: { width: 1920, height: 1080 },
    x: 480, y: -270, scale: 0.5,
  })
  // meta' dimensione, spostata di un quarto canvas: a schermo vale la meta'
  assert.equal(r.width, 480)
  assert.equal(r.left, 960 / 2 - 240 + 240)
  assert.equal(r.top, 540 / 2 - 135 - 135)
})

test('riquadro: sorgente piu piccola del canvas (fit=none)', () => {
  const r = transformBox({
    box: { left: 0, top: 0, w: 640, h: 360 },
    canvas: { width: 1280, height: 720 },
    native: { width: 200, height: 120 },
    scale: 2,
  })
  assert.equal(r.width, 200)   // 200 * 2 * 0.5
  assert.equal(r.height, 120)
})

test('natura della clip: cosa produce davvero, quindi cosa mostrare', () => {
  const project = {
    media: [{ id: 'mv', audio: true }, { id: 'muto', audio: false }, { id: 'ma', audio: true }],
    tracks: [
      { id: 'V1', kind: 'video', clips: [
        { id: 'c1', type: 'media', media: 'mv' }, { id: 'c2', type: 'media', media: 'muto' },
        { id: 't1', type: 'text' }, { id: 'h1', type: 'html' }] },
      { id: 'A1', kind: 'audio', clips: [{ id: 'a1', type: 'media', media: 'ma' }] },
    ],
  }
  const n = (id) => natura(project.tracks.flatMap((t) => t.clips).find((c) => c.id === id), project)
  assert.deepEqual(n('c1'), { video: true, audio: true })
  assert.deepEqual(n('c2'), { video: true, audio: false })
  assert.deepEqual(n('t1'), { video: true, audio: false })
  assert.deepEqual(n('h1'), { video: true, audio: false })
  assert.deepEqual(n('a1'), { video: false, audio: true })
  assert.deepEqual(natura(null, project), { video: false, audio: false })
})


{
  // cartella trascinata dal desktop: il contenuto va letto dalle entry, a blocchi
  const f = (name) => ({ isFile: true, name, file: (ok) => ok({ name }) })
  const d = (name, figli, blocco = 2) => ({
    isDirectory: true, name,
    createReader: () => {
      let i = 0
      return { readEntries: (ok) => { ok(figli.slice(i, i + blocco)); i += blocco } }
    },
  })
  const sfx = d('SFX', [f('whoosh.wav'), f('boom.mp3'), d('Canzoni', [f('a.flac')]), f('note.txt')])
  const dt = { items: [{ kind: 'file', webkitGetAsEntry: () => sfx },
                       { kind: 'file', webkitGetAsEntry: () => f('clip.mp4') }] }
  const voci = await leggiTrascinati(dt)
  const nomi = voci.map((v) => `${v.cartella}|${v.file.name}`).sort()
  test('trascinare una cartella legge anche le sottocartelle', () => {
    assert.deepEqual(nomi, ['SFX/Canzoni|a.flac', 'SFX|boom.mp3', 'SFX|note.txt', 'SFX|whoosh.wav', '|clip.mp4'].sort())
  })

  const vecchio = await leggiTrascinati({ files: [{ name: 'x.mp4' }] })
  test('senza entry restano i file', () => assert.deepEqual(vecchio, [{ file: { name: 'x.mp4' }, cartella: '' }]))
}

{
  // upload a pezzi: riprende da dove il server si era fermato, ritenta i guasti
  const finto = (name, size, lastModified = 7) => ({ name, size, lastModified, slice: (a, b) => ({ a, b }) })
  const server = (opts = {}) => {
    const ricevuti = new Map(opts.gia || [])
    const chiamate = { pezzi: [], import: [] }
    let guasti = opts.guasti || 0
    return {
      chiamate,
      uploadStato: async (q) => {
        const r = ricevuti.get(q.nome) || 0
        return { ricevuti: r, completo: r === q.size, path: r === q.size ? `/m/${q.nome}` : undefined }
      },
      uploadPezzo: async (q, off, pezzo) => {
        if (opts.rifiuta === q.nome) throw Object.assign(new Error('no'), { status: 400 })
        if (guasti > 0) { guasti -= 1; throw Object.assign(new Error('guasto'), { status: 503 }) }
        assert.equal(off, ricevuti.get(q.nome) || 0)
        chiamate.pezzi.push([q.nome, pezzo.a, pezzo.b])
        ricevuti.set(q.nome, pezzo.b)
        return { ricevuti: pezzo.b, completo: pezzo.b === q.size, path: `/m/${q.nome}` }
      },
      importa: async (paths, cartella) => {
        chiamate.import.push([cartella, paths])
        return { scartati: paths.filter((p) => p.includes('rotto')).map((path) => ({ path, errore: 'x' })) }
      },
    }
  }

  const s1 = server({ gia: [['grande.mov', PEZZO]], guasti: 1 })
  let byte = 0
  const path = await mandaFile(s1, finto('grande.mov', 2 * PEZZO + 5), { onByte: (n) => { byte += n } })
  test('upload: riprende dal pezzo che mancava e ritenta un guasto', () => {
    assert.equal(path, '/m/grande.mov')
    assert.deepEqual(s1.chiamate.pezzi, [['grande.mov', PEZZO, 2 * PEZZO], ['grande.mov', 2 * PEZZO, 2 * PEZZO + 5]])
    assert.equal(byte, 2 * PEZZO + 5)
  })

  const s2 = server({ rifiuta: 'no.mp4', gia: [['fatto.mp4', 10]] })
  const voci = [
    { file: finto('a.mp4', 3), cartella: 'scheda/A001' },
    { file: finto('no.mp4', 3), cartella: '' },
    { file: finto('fatto.mp4', 10), cartella: 'scheda/A001' },
    { file: finto('rotto.mp4', 3), cartella: '' },
  ]
  const stati = []
  const fine = await caricaTrascinati(s2, voci, { onProgress: (s) => stati.push(s) })
  test('trascinati: i file buoni entrano, i rifiutati sono scartati, non bloccano', () => {
    assert.equal(fine.fatti, 4)
    assert.deepEqual(fine.scartati.map((s) => s.path).sort(), ['/m/rotto.mp4', 'no.mp4'])
    const importati = s2.chiamate.import.flatMap(([c, ps]) => ps.map((p) => `${c}|${p}`)).sort()
    assert.deepEqual(importati, ['scheda/A001|/m/a.mp4', 'scheda/A001|/m/fatto.mp4', '|/m/rotto.mp4'].sort())
    // il file gia' arrivato non si rimanda
    assert.ok(!s2.chiamate.pezzi.some(([n]) => n === 'fatto.mp4'))
    assert.equal(stati.at(-1).importati, 2)
  })

  const s3 = server()
  const tanti = Array.from({ length: 120 }, (_, i) => ({ path: `/d/c${i}.mp4`, cartella: i < 60 ? 'x' : 'y' }))
  const fine3 = await importaPercorsi(s3, tanti)
  test('dal disco: a blocchi per cartella, tutti contati', () => {
    assert.ok(s3.chiamate.import.every(([, ps]) => ps.length <= BLOCCO))
    assert.equal(s3.chiamate.import.flatMap(([, ps]) => ps).length, 120)
    assert.equal(fine3.fatti, 120)
    assert.equal(fine3.importati, 120)
  })

  const ctrl = new AbortController()
  ctrl.abort()
  const s4 = server()
  const fine4 = await importaPercorsi(s4, tanti, { signal: ctrl.signal })
  test('dal disco: fermato, non manda altro', () => {
    assert.ok(fine4.interrotto)
    assert.equal(s4.chiamate.import.length, 0)
  })
}

{
  // strisce e forme d'onda: poche alla volta, la timeline prima del pannello
  _azzera()
  const sblocca = []
  let attive = 0
  let picco = 0
  const ordine = []
  const lavoro = (nome) => () => new Promise((ok) => {
    attive += 1; picco = Math.max(picco, attive); ordine.push(nome)
    sblocca.push(() => { attive -= 1; ok(nome) })
  })
  for (let i = 0; i < 8; i += 1) chiedi(`bin${i}`, lavoro(`bin${i}`), 1)
  chiedi('timeline', lavoro('timeline'), 0)
  chiedi('bin7', lavoro('doppio'), 0)   // gia' in coda: sale di priorita', non si duplica
  while (sblocca.length) { sblocca.shift()(); await new Promise((r) => setTimeout(r, 0)) }
  test('coda anteprime: al massimo IN_PARALLELO, priorita\' rispettata, niente doppioni', () => {
    assert.ok(picco <= IN_PARALLELO)
    assert.deepEqual(ordine.slice(IN_PARALLELO, IN_PARALLELO + 2).sort(), ['bin7', 'timeline'])
    assert.equal(ordine.length, 9)
  })
}

test('formati: stesso conto del backend (store.risoluzione)', () => {
  assert.deepEqual(dimensioni('16:9', 1080), [1920, 1080])
  assert.deepEqual(dimensioni('9:16', 1080), [1080, 1920])
  assert.deepEqual(dimensioni('4:5', 1080), [1080, 1350])
  assert.deepEqual(dimensioni('21:9', 1080), [2520, 1080])
  assert.deepEqual(dimensioni('16:9', 2160), [3840, 2160])
  assert.equal(dimensioni('boh', 1080), null)
  assert.equal(formatoDi(1080, 1920), '9:16')
  assert.equal(formatoDi(1280, 720), '16:9')
  assert.equal(formatoDi(1000, 1234), null)
})

console.log(`\n${ok} verifiche superate`)
