// Copertura delle traduzioni e confine tra presentazione e dati del progetto.
import assert from 'node:assert/strict'
import fs from 'node:fs'
import { createRequire } from 'node:module'
const require = createRequire(import.meta.url)
const babel = createRequire(require.resolve('@vitejs/plugin-react'))('@babel/core')
const plugin = require('./localize.cjs')
const zh = JSON.parse(fs.readFileSync('src/locales/zh-CN.json', 'utf8'))

const data = { 'vedit.language': 'zh-CN' }
globalThis.localStorage = { getItem: (k) => data[k] ?? null, setItem: (k, v) => { data[k] = v } }
const { translate, translateMessage, setLanguage } = await import('./src/i18n.js')
assert.equal(translate('save'), '保存', 'la lingua salvata torna al caricamento')
assert.equal(translate(' save '), ' 保存 ', 'gli spazi fra nodi restano')
assert.equal(translate('  '), '  ')
assert.equal(translate('Move {0} up', ['活动 A / C0001.mp4']), '上移 活动 A / C0001.mp4')
assert.equal(translate('Unknown {0}', ['<script>']), 'Unknown <script>', 'testo, mai HTML eseguito')
assert.equal(translateMessage('Analyzing Wedding: C0001.mp4'), '正在分析 Wedding：C0001.mp4')
assert.equal(translate('C:\\活动\\save.mp4'), 'C:\\活动\\save.mp4')
assert.equal(translateMessage('A custom model reply about save'), 'A custom model reply about save')
setLanguage('en')
assert.equal(translate('save'), 'save')
assert.equal(translate('Move {0} up', ['Wedding']), 'Move Wedding up')
assert.equal(data['vedit.language'], 'en')
setLanguage('invalid')
assert.equal(data['vedit.language'], 'en')

// Tutti i testi JSX visibili devono avere una voce, incluse descrizioni lunghe.
plugin.chiavi.clear()
for (const f of fs.readdirSync('src').filter((f) => f.endsWith('.jsx'))) {
  const source = fs.readFileSync(`src/${f}`, 'utf8')
  babel.transformSync(source, {
    filename: f, parserOpts: { plugins: ['jsx'] }, plugins: [plugin], configFile: false, babelrc: false,
  })
  const ast = babel.parseSync(source, { parserOpts: { plugins: ['jsx'] }, configFile: false, babelrc: false })
  babel.traverse(ast, { JSXOpeningElement(path) {
    if (path.node.name.name === 'option') assert.ok(path.node.attributes.some((a) => a.name?.name === 'value'),
      `Option needs a stable API value independent of its translated label: ${f}:${path.node.loc.start.line}`)
  } })
}
for (const key of plugin.chiavi) assert.ok(Object.hasOwn(zh, key), `Missing Chinese UI text: ${key}`)
for (const [key, value] of Object.entries(zh)) {
  const placeholders = (s) => [...s.matchAll(/\{(\d+)\}/g)].map((m) => m[1]).sort()
  assert.deepEqual(placeholders(value), placeholders(key), `Placeholder mismatch: ${key}`)
}

// Lo stesso gesto continua a mandare gli stessi identificatori e parametri.
plugin.chiavi.clear()
const code = babel.transformSync(`const UI = ({name, run}) => <button className="save" data-kind="video" onClick={() => run('set_clip', {fit:'cover'})} title="Save">save {name}</button>`, {
  parserOpts: { plugins: ['jsx'] }, plugins: [plugin], configFile: false, babelrc: false,
}).code
assert.deepEqual([...plugin.chiavi].sort(), ['Save', 'save'])
assert.match(code, /className="save"/)
assert.match(code, /data-kind="video"/)
assert.match(code, /run\('set_clip',/)
assert.match(code, /fit: 'cover'/)
assert.match(code, /\{name\}/, 'il nome utente non viene tradotto')
console.log(`i18n: persisted language, interpolation, fallback, payload safety and ${Object.keys(zh).length} catalog entries passed`)
