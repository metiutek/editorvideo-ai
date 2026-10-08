/**
 * Verifiche delle funzioni pure della UI (niente DOM).
 *
 *   node test-util.mjs
 */
import assert from 'node:assert/strict'
import { dettaglioStrumento, impronta, rispostaEq, isKf, sampleKf, transformBox, natura } from './src/util.js'

let ok = 0
const test = (name, fn) => {
  try { fn(); ok++; console.log('ok   ' + name) }
  catch (e) { console.log('FAIL ' + name + ': ' + e.message); process.exitCode = 1 }
}

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

console.log(`\n${ok} verifiche superate`)
